import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError
from django.test import TestCase, override_settings
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from music import daily
from music.api.errors import ApiError
from music.api.serializers import SongSerializer
from music.media import playable_media_path
from music.models import Behavior, Favorite, RecommendationSnapshot, Song, SongTag, Tag, User, UserTag


class DailyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = datetime(2026, 10, 30, 4, tzinfo=timezone.utc)
        cls.past = cls.now - timedelta(days=2)
        cls.user = User.objects.create_user(username="daily_listener")
        cls.neighbor = User.objects.create_user(username="daily_neighbor")
        cls.simulated = User.objects.create_user(username="daily_simulated", origin="SIMULATED")
        cls.tag = Tag.objects.create(name="治愈", kind=Tag.MOOD)
        cls.other_tag = Tag.objects.create(name="通勤", kind=Tag.SCENE)
        cls.songs = [Song.objects.create(
            title=f"Metadata {number}", artist="SYNTHETIC_TEST_ONLY", duration_ms=100000,
            mime="audio/wav", file_path=f"songs/test-{number}.wav", active=True,
            source_name="SYNTHETIC_METADATA", source_url="https://example.org/source",
            license_name="TEST_ONLY_NOT_A_LICENSE", license_url="https://example.org/license",
            checked_at=cls.past, playback_allowed=True,
        ) for number in range(5)]
        Song.objects.update(created_at=cls.past)
        SongTag.objects.bulk_create([SongTag(song=song, tag=cls.tag) for song in cls.songs])
        UserTag.objects.create(user=cls.user, tag=cls.tag)
        cls.api = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.client.force_login(self.user)
        self.file_check = patch("pathlib.Path.is_file", return_value=True)
        self.file_check.start()
        self.addCleanup(self.file_check.stop)

    def get_daily(self, when=None):
        with patch("music.api.middleware.timezone.now", return_value=when or self.now):
            return self.client.get("/api/v1/recommendations/daily/")

    def refresh(self, when=None, body="", token=None):
        with patch("music.api.middleware.timezone.now", return_value=when or self.now):
            return self.client.post(
                "/api/v1/recommendations/daily/refresh/", body, content_type="application/json",
                HTTP_X_CSRFTOKEN=token or self.token,
            )

    def favorite(self, song, user=None, when=None):
        relation = Favorite.objects.create(user=user or self.user, song=song)
        Favorite.objects.filter(id=relation.id).update(created_at=when or self.past)
        return relation

    def behavior(self, song, *, user=None, when=None, kind=Behavior.COMPLETE, origin=None):
        owner = user or self.user
        return Behavior.objects.create(
            event_id=uuid4(), user=owner, song=song, listening_session_id=uuid4(), kind=kind,
            position_ms=90000 if kind == Behavior.COMPLETE else 0,
            listened_ms=90000 if kind == Behavior.COMPLETE else 0,
            effective_ms=90000 if kind == Behavior.COMPLETE else 0,
            occurred_at=when or self.past, origin=origin or owner.origin,
        )

    def assert_schema(self, response, name="Daily"):
        self.assertEqual(response["Cache-Control"], "private,no-store")
        self.assertEqual(response["X-Spec-Version"], "v0.1.0")
        UUID(response["X-Request-ID"])
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": self.api["components"]},
            format_checker=FormatChecker(),
        )
        validator.validate(response.json())

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error_code"], code)
        self.assertEqual(response.json()["request_id"], response["X-Request-ID"])
        self.assert_schema(response, "Error")

    def test_first_get_creates_private_daily_snapshot(self):
        response = self.get_daily()
        self.assertEqual(response.status_code, 200)
        self.assert_schema(response)
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(response.json()["day"], "2026-10-30")
        self.assertEqual(len(response.json()["items"]), 5)
        self.assertEqual(RecommendationSnapshot.objects.count(), 1)

    def test_repeated_get_does_not_recalculate_or_write(self):
        initial = self.get_daily().json()
        with patch("music.daily.recommend", side_effect=AssertionError("GET must not recalculate")):
            repeated = self.get_daily(self.now + timedelta(minutes=5)).json()
        self.assertEqual(initial, repeated)
        self.assertEqual(RecommendationSnapshot.objects.get().generated_at, self.now)

    def test_first_post_creates_revision_one(self):
        response = self.refresh()
        self.assertEqual(response.status_code, 200)
        self.assert_schema(response)
        self.assertEqual(response.json()["revision"], 1)

    def test_pt_m_008_refresh_boundaries_preserve_rejected_snapshot(self):
        self.get_daily()
        original = RecommendationSnapshot.objects.values().get()
        for seconds, expected in [(0, 60), (59, 1), (59.01, 1)]:
            response = self.refresh(self.now + timedelta(seconds=seconds))
            self.assert_error(response, 429, "RATE_LIMITED")
            self.assertEqual(response["Retry-After"], str(expected))
            self.assertEqual(original, RecommendationSnapshot.objects.values().get())
        response = self.refresh(self.now + timedelta(seconds=60))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 2)
        self.assertEqual(datetime.fromisoformat(response.json()["next_refresh_at"]), self.now + timedelta(seconds=120))
        response = self.refresh(self.now + timedelta(seconds=121))
        self.assertEqual(response.json()["revision"], 3)

    def test_midnight_cannot_bypass_per_user_refresh_limit(self):
        before = datetime(2026, 10, 30, 15, 59, 40, tzinfo=timezone.utc)
        after = before + timedelta(seconds=30)
        self.assertEqual(self.refresh(before).json()["day"], "2026-10-30")
        self.assert_error(self.refresh(after), 429, "RATE_LIMITED")
        self.assertEqual(RecommendationSnapshot.objects.count(), 1)
        response = self.refresh(before + timedelta(seconds=60))
        self.assertEqual(response.json()["day"], "2026-10-31")
        self.assertEqual(response.json()["revision"], 1)

    def test_new_day_get_creates_snapshot_and_updates_refresh_window(self):
        before = datetime(2026, 10, 30, 15, 59, 59, tzinfo=timezone.utc)
        after = before + timedelta(seconds=2)
        self.get_daily(before)
        response = self.get_daily(after)
        self.assertEqual(response.json()["day"], "2026-10-31")
        self.assertEqual(RecommendationSnapshot.objects.count(), 2)
        self.assertEqual(response.json()["revision"], 1)
        self.assert_error(self.refresh(after + timedelta(seconds=1)), 429, "RATE_LIMITED")

    def test_tc_m_016_csrf_precedes_auth_for_refresh(self):
        self.client.logout()
        response = self.client.post("/api/v1/recommendations/daily/refresh/", "", content_type="application/json")
        self.assert_error(response, 403, "CSRF_FAILED")
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assert_error(self.refresh(), 401, "AUTH_REQUIRED")
        self.assert_error(self.get_daily(), 401, "AUTH_REQUIRED")
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_unknown_query_or_body_does_not_generate(self):
        for path in ["/api/v1/recommendations/daily/?user_id=999", "/api/v1/recommendations/daily/?limit=1"]:
            self.assert_error(self.client.get(path), 400, "VALIDATION_ERROR")
        for body in ["{}", '{"alpha":0.5}', "null"]:
            self.assert_error(self.refresh(body=body), 400, "VALIDATION_ERROR")
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_refresh_content_type_and_method_errors_are_private(self):
        response = self.client.post(
            "/api/v1/recommendations/daily/refresh/", "", content_type="text/plain", HTTP_X_CSRFTOKEN=self.token,
        )
        self.assert_error(response, 415, "VALIDATION_ERROR")
        self.assert_error(self.client.get("/api/v1/recommendations/daily/refresh/"), 405, "VALIDATION_ERROR")

    def test_new_favorite_is_filtered_without_rewriting_snapshot(self):
        self.get_daily()
        original = RecommendationSnapshot.objects.values().get()
        self.favorite(self.songs[0], when=self.now + timedelta(seconds=1))
        response = self.get_daily(self.now + timedelta(seconds=2))
        self.assertNotIn(self.songs[0].id, [item["song_id"] for item in response.json()["items"]])
        self.assertEqual([item["rank"] for item in response.json()["items"]], [1, 2, 3, 4])
        self.assertEqual(original, RecommendationSnapshot.objects.values().get())

    def test_new_recent_complete_is_filtered_but_play_is_not(self):
        self.get_daily()
        self.behavior(self.songs[0], when=self.now + timedelta(seconds=1))
        self.behavior(self.songs[1], kind=Behavior.PLAY, when=self.now + timedelta(seconds=1))
        response = self.get_daily(self.now + timedelta(seconds=2))
        identifiers = {item["song_id"] for item in response.json()["items"]}
        self.assertNotIn(self.songs[0].id, identifiers)
        self.assertIn(self.songs[1].id, identifiers)

    def test_invalid_media_is_filtered_before_response(self):
        self.get_daily()
        Song.objects.filter(id=self.songs[0].id).update(active=False)
        Song.objects.filter(id=self.songs[1].id).update(playback_allowed=False)
        Song.objects.filter(id=self.songs[2].id).update(checked_at=None)
        Song.objects.filter(id=self.songs[3].id).update(file_path="../outside.wav")
        with patch("pathlib.Path.is_file", return_value=False):
            response = self.get_daily()
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["empty_reason"], "FILTERED_OUT")
        self.assertEqual(len(RecommendationSnapshot.objects.get().items), 5)

    def test_renamed_tag_invalidates_old_explanation(self):
        self.get_daily()
        Tag.objects.filter(id=self.tag.id).update(name="已改名")
        response = self.get_daily(self.now + timedelta(seconds=1))
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["empty_reason"], "FILTERED_OUT")
        response = self.refresh(self.now + timedelta(seconds=60))
        self.assertEqual(len(response.json()["items"]), 5)
        self.assertIn("已改名", response.json()["items"][0]["explanation"])

    def test_removed_song_tag_filters_only_affected_item(self):
        self.get_daily()
        SongTag.objects.filter(song=self.songs[0]).delete()
        response = self.get_daily()
        self.assertEqual(len(response.json()["items"]), 4)
        self.assertIsNone(response.json()["empty_reason"])

    def test_disabled_tag_filters_evidence_without_modifying_snapshot(self):
        self.get_daily()
        Tag.objects.filter(id=self.tag.id).update(active=False)
        self.assertEqual(self.get_daily().json()["items"], [])
        self.assertEqual(len(RecommendationSnapshot.objects.get().items), 5)

    def test_projection_does_not_backfill_or_implicitly_recalculate(self):
        self.get_daily()
        new_song = Song.objects.create(
            title="Later", artist="TEST", duration_ms=1000, mime="audio/wav", active=True,
            file_path="songs/later.wav", playback_allowed=True, checked_at=self.past,
        )
        Song.objects.filter(id=new_song.id).update(created_at=self.now + timedelta(seconds=1))
        SongTag.objects.create(song=new_song, tag=self.tag)
        Song.objects.filter(id=self.songs[0].id).update(active=False)
        response = self.get_daily(self.now + timedelta(seconds=2))
        self.assertEqual(len(response.json()["items"]), 4)
        self.assertNotIn(new_song.id, [item["song_id"] for item in response.json()["items"]])

    def test_tc_m_010_empty_library_snapshot_is_stable(self):
        Song.objects.update(active=False)
        response = self.get_daily()
        self.assert_schema(response)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["empty_reason"], "NO_ELIGIBLE_SONGS")
        Song.objects.update(active=True)
        self.assertEqual(self.get_daily().json()["items"], [])

    def test_tc_m_011_hot_api_has_honest_evidence(self):
        UserTag.objects.filter(user=self.user).delete()
        response = self.get_daily()
        self.assert_schema(response)
        self.assertIsNone(response.json()["alpha_effective"])
        for item in response.json()["items"]:
            self.assertEqual(item["source"], "HOT")
            self.assertEqual(item["evidence"], {"tag_ids": [], "neighbor_count": 0})
            self.assertEqual(item["explanation"], "热门歌曲，供你探索")

    def test_tc_m_009_content_only_api_without_neighbors(self):
        response = self.get_daily()
        self.assertEqual(response.json()["alpha_effective"], 1.0)
        for item in response.json()["items"]:
            self.assertEqual(item["source"], "CONTENT")
            self.assertEqual(item["evidence"]["neighbor_count"], 0)
        self.assert_schema(response)

    def test_cf_only_api_preserves_aggregate_evidence(self):
        UserTag.objects.filter(user=self.user).delete()
        SongTag.objects.all().delete()
        for song in self.songs[:2]:
            self.favorite(song)
            self.favorite(song, user=self.neighbor)
        self.favorite(self.songs[2], user=self.neighbor)
        response = self.get_daily()
        self.assertEqual(response.json()["alpha_effective"], 0.0)
        item = response.json()["items"][0]
        self.assertEqual(item["source"], "CF")
        self.assertEqual(item["evidence"], {"tag_ids": [], "neighbor_count": 1})
        self.assert_schema(response)

    def test_fabricated_hot_explanation_is_not_projected(self):
        UserTag.objects.filter(user=self.user).delete()
        self.get_daily()
        snapshot = RecommendationSnapshot.objects.get()
        snapshot.items[0]["explanation"] = "为你精挑细选"
        snapshot.items[1]["evidence"]["neighbor_count"] = 1
        snapshot.save(update_fields=["items"])
        response = self.get_daily()
        self.assertEqual(len(response.json()["items"]), 3)
        self.assertEqual(len(RecommendationSnapshot.objects.get().items), 5)

    def test_recent_complete_window_in_adapter_and_projection(self):
        self.behavior(self.songs[0], when=self.now - timedelta(hours=24))
        self.behavior(self.songs[1], when=self.now - timedelta(hours=24, microseconds=1))
        response = self.get_daily()
        identifiers = {item["song_id"] for item in response.json()["items"]}
        self.assertNotIn(self.songs[0].id, identifiers)
        self.assertIn(self.songs[1].id, identifiers)

    def test_inactive_user_cannot_create_or_refresh_snapshot(self):
        User.objects.filter(id=self.user.id).update(is_active=False)
        self.assert_error(self.get_daily(), 401, "AUTH_REQUIRED")
        self.assert_error(self.refresh(), 401, "AUTH_REQUIRED")
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_first_get_uses_request_time_across_midnight(self):
        before = datetime(2026, 10, 30, 15, 59, 59, tzinfo=timezone.utc)
        original = daily.recommend

        def delayed_calculation(**inputs):
            self.assertEqual(inputs["now"], before)
            return original(**inputs)

        with patch("music.daily.recommend", side_effect=delayed_calculation):
            response = self.get_daily(before)
        self.assertEqual(response.json()["day"], "2026-10-30")
        self.assertEqual(datetime.fromisoformat(response.json()["generated_at"]), before)

    def test_failed_initial_insert_rolls_back_written_row(self):
        save = RecommendationSnapshot.save

        def fail_after_insert(snapshot, *args, **kwargs):
            save(snapshot, *args, **kwargs)
            raise RuntimeError("INJECTED_AFTER_INSERT")

        with patch.object(RecommendationSnapshot, "save", fail_after_insert):
            with self.assertRaises(RuntimeError):
                daily.get_daily(user_id=self.user.id, now=self.now)
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_hybrid_adapter_reads_current_positive_feedback(self):
        for song in self.songs[:2]:
            self.favorite(song)
            self.favorite(song, user=self.neighbor)
        self.favorite(self.songs[2], user=self.neighbor)
        self.behavior(self.songs[2], user=self.neighbor)
        response = self.get_daily()
        item = next(item for item in response.json()["items"] if item["song_id"] == self.songs[2].id)
        self.assertEqual(item["source"], "HYBRID")
        self.assertEqual(item["evidence"]["neighbor_count"], 1)
        self.assertAlmostEqual(response.json()["alpha_target"], 0.8)
        self.assert_schema(response)

    def test_adapter_ignores_other_origins_future_feedback_and_inactive_neighbors(self):
        for song in self.songs[:2]:
            self.favorite(song)
            self.favorite(song, user=self.simulated)
            self.favorite(song, user=self.neighbor)
        self.favorite(self.songs[2], user=self.simulated)
        self.favorite(self.songs[2], user=self.neighbor, when=self.now)
        self.behavior(self.songs[3], kind=Behavior.COMPLETE, origin="SIMULATED")
        response = self.get_daily()
        self.assertEqual(response.json()["alpha_effective"], 1.0)
        self.assertIn(self.songs[3].id, [item["song_id"] for item in response.json()["items"]])
        self.favorite(self.songs[4], user=self.neighbor)
        User.objects.filter(id=self.neighbor.id).update(is_active=False)
        scores = daily.score_user_cf(user_id=self.user.id, candidate_ids=[self.songs[4].id], cutoff=self.now, origin="REAL")
        self.assertEqual(scores[self.songs[4].id], 0)

    def test_songs_created_at_cutoff_are_not_candidates(self):
        Song.objects.filter(id=self.songs[0].id).update(created_at=self.now)
        self.assertNotIn(self.songs[0].id, [item["song_id"] for item in self.get_daily().json()["items"]])

    def test_database_service_signatures_reuse_pure_engine(self):
        profile = daily.build_user_profile(user_id=self.user.id, cutoff=self.now, origin="REAL")
        self.assertEqual(profile, {self.tag.id: 1.0})
        items = daily.calculate_daily(user_id=self.user.id, now=self.now, limit=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)
        with self.assertRaises(ValueError):
            daily.calculate_daily(user_id=self.user.id, now=self.now, limit=True)
        with self.assertRaises(ValueError):
            daily.build_user_profile(user_id=self.user.id, cutoff=self.now, origin="SIMULATED")
        with self.assertRaises(ValueError):
            daily.get_daily(user_id=self.user.id, now=datetime(2026, 10, 30))

    def test_projection_denies_cross_user_snapshot_access(self):
        snapshot = daily.get_daily(user_id=self.user.id, now=self.now)
        with self.assertRaises(ApiError) as raised:
            daily.serialize_daily(snapshot=snapshot, user_id=self.neighbor.id, now=self.now)
        self.assertEqual(raised.exception.error_code, "NOT_FOUND")
        other = APIClient(enforce_csrf_checks=True)
        other.force_login(self.neighbor)
        with patch("music.api.middleware.timezone.now", return_value=self.now):
            response = other.get("/api/v1/recommendations/daily/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RecommendationSnapshot.objects.count(), 2)

    def test_failed_refresh_rolls_back_existing_snapshot(self):
        self.get_daily()
        original = RecommendationSnapshot.objects.values().get()
        save = RecommendationSnapshot.save

        def fail_after_write(snapshot, *args, **kwargs):
            save(snapshot, *args, **kwargs)
            raise RuntimeError("INJECTED_AFTER_WRITE")

        with patch.object(RecommendationSnapshot, "save", fail_after_write):
            with self.assertLogs("music.api.errors", level="ERROR"):
                response = self.refresh(self.now + timedelta(seconds=60))
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertNotIn("INJECTED_AFTER_WRITE", response.content.decode())
        self.assertEqual(original, RecommendationSnapshot.objects.values().get())

    def test_failed_initial_generation_leaves_no_snapshot(self):
        with patch("music.daily.recommend", side_effect=RuntimeError("INJECTED_COMPUTATION")):
            with self.assertLogs("music.api.errors", level="ERROR"):
                response = self.get_daily()
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_unrelated_integrity_error_is_not_swallowed(self):
        with patch("music.daily.RecommendationSnapshot.objects.create", side_effect=IntegrityError("INJECTED")):
            with self.assertRaises(IntegrityError):
                daily.get_daily(user_id=self.user.id, now=self.now)
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_unique_conflict_reloads_existing_snapshot(self):
        initial = daily.get_daily(user_id=self.user.id, now=self.now)
        with patch("music.daily.RecommendationSnapshot.objects.create", side_effect=IntegrityError("UNIQUE_CONFLICT")):
            recovered = daily.save_generation(user_id=self.user.id, now=self.now, snapshot=None)
        self.assertEqual(recovered.id, initial.id)
        self.assertEqual(RecommendationSnapshot.objects.count(), 1)

    def test_lost_file_between_generation_and_projection_is_hidden(self):
        snapshot = daily.get_daily(user_id=self.user.id, now=self.now)
        with patch("pathlib.Path.is_file", return_value=False):
            body = daily.serialize_daily(snapshot=snapshot, user_id=self.user.id, now=self.now)
        self.assertEqual(body["items"], [])
        self.assertEqual(body["empty_reason"], "FILTERED_OUT")

    @override_settings(MEDIA_ROOT=settings.BASE_DIR.parent / "media")
    def test_shared_media_guard_handles_paths_errors_and_serializer(self):
        song = self.songs[0]
        for file_path in ["../outside.wav", str(settings.BASE_DIR / "manage.py"), ".", ""]:
            song.file_path = file_path
            self.assertIsNone(playable_media_path(song))
        song.file_path = "songs/verified.wav"
        self.assertIsNotNone(playable_media_path(song))
        self.assertTrue(SongSerializer(song).data["playable"])
        with patch.object(Path, "resolve", side_effect=OSError("UNAVAILABLE")):
            self.assertIsNone(playable_media_path(song))
        media_root = Path(settings.MEDIA_ROOT).resolve()
        outside = media_root.parent / "outside.wav"
        with patch.object(Path, "resolve", side_effect=[media_root, outside]):
            self.assertIsNone(playable_media_path(song))

    def test_backwards_clock_is_limited_without_rewriting_newer_snapshot(self):
        self.get_daily()
        response = self.refresh(self.now - timedelta(seconds=1))
        self.assert_error(response, 429, "RATE_LIMITED")
        self.assertEqual(response["Retry-After"], "60")
        self.assertEqual(RecommendationSnapshot.objects.get().generated_at, self.now)
