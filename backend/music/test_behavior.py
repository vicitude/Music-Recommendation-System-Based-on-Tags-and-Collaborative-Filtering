import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError
from django.test import TestCase
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from music import behavior, daily
from music.api.errors import ApiError
from music.models import Behavior, Song, SongTag, Tag, User


class BehaviorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.now = datetime(2026, 10, 30, 4, tzinfo=timezone.utc)
        cls.user = User.objects.create_user(username="event_listener")
        cls.other = User.objects.create_user(username="event_other")
        cls.song = Song.objects.create(
            title="Synthetic event metadata", artist="TEST_ONLY", duration_ms=100000,
            mime="audio/wav", active=True, file_path="songs/synthetic.wav",
            source_name="SYNTHETIC_TEST", source_url="https://example.org/source",
            license_name="TEST_NOT_A_LICENSE", license_url="https://example.org/license",
        )
        cls.other_song = Song.objects.create(
            title="Other synthetic metadata", artist="TEST_ONLY", duration_ms=100000,
            mime="audio/wav", active=True,
        )
        Song.objects.update(created_at=cls.now - timedelta(days=1))
        cls.api = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.client.force_login(self.user)
        self.session = str(uuid4())

    def payload(self, *, kind="PLAY", position=0, listened=0, session=None, song=None):
        return {
            "event_id": str(uuid4()), "song_id": (song or self.song).id,
            "listening_session_id": session or self.session, "kind": kind,
            "position_ms": position, "listened_ms": listened,
        }

    def post(self, data, when=None, client=None, token=None, path="/api/v1/behaviors/"):
        with patch("music.api.middleware.timezone.now", return_value=when or self.now):
            return (client or self.client).post(
                path, json.dumps(data), content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token,
            )

    def assert_schema(self, response, name):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": self.api["components"]},
            format_checker=FormatChecker(),
        )
        validator.validate(response.json())
        self.assertEqual(response["X-Spec-Version"], "v0.1.0")
        UUID(response["X-Request-ID"])

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error_code"], code)
        self.assertEqual(response.json()["request_id"], response["X-Request-ID"])
        self.assert_schema(response, "Error")

    def start(self):
        response = self.post(self.payload())
        self.assertEqual(response.status_code, 201, response.content)
        return response

    def test_first_play_has_server_time_origin_and_zero_effective_ms(self):
        response = self.start()
        self.assert_schema(response, "BehaviorResponse")
        self.assertEqual(set(response.json()), {"id", "event_id", "effective_ms"})
        self.assertEqual(response.json()["effective_ms"], 0)
        event = Behavior.objects.get()
        self.assertEqual(event.occurred_at, self.now)
        self.assertEqual(event.origin, "REAL")
        self.assertEqual(event.user_id, self.user.id)

    def test_tc_m_006_pt_m_001_hundred_retries_preserve_single_event(self):
        data = self.payload()
        original = self.post(data)
        self.assertEqual(original.status_code, 201)
        for retry in range(100):
            response = self.post(data, self.now + timedelta(seconds=retry + 1))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), original.json())
        self.assertEqual(Behavior.objects.count(), 1)
        self.assertEqual(Behavior.objects.get().occurred_at, self.now)
        altered = {**data, "position_ms": 1}
        self.assert_error(self.post(altered), 409, "EVENT_CONFLICT")

    def test_every_payload_change_conflicts_before_other_rules(self):
        data = self.payload()
        self.post(data)
        changes = {
            "song_id": self.other_song.id, "listening_session_id": str(uuid4()),
            "kind": "SKIP", "position_ms": 1, "listened_ms": 1,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assert_error(self.post({**data, field: value}), 409, "EVENT_CONFLICT")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_cross_user_event_id_conflict_does_not_disclose_old_event(self):
        data = self.payload()
        original = self.post(data).json()
        self.client.force_login(self.other)
        response = self.post(data)
        self.assert_error(response, 409, "EVENT_CONFLICT")
        self.assertNotIn("effective_ms", response.json())
        self.assertNotIn(str(original["id"]), response.json()["message"])
        self.assertEqual(Behavior.objects.count(), 1)

    def test_uuid_and_kind_normalization_preserve_idempotency(self):
        data = self.payload()
        data["event_id"] = "  " + data["event_id"].upper() + "  "
        data["listening_session_id"] = data["listening_session_id"].upper()
        data["kind"] = " PLAY "
        response = self.post(data)
        self.assertEqual(response.status_code, 201)
        normalized = {**data, "event_id": str(UUID(data["event_id"].strip())), "listening_session_id": str(UUID(self.session)), "kind": "PLAY"}
        self.assertEqual(self.post(normalized).status_code, 200)

    def test_exact_replay_survives_song_unpublish_and_origin_change(self):
        data = self.payload()
        response = self.post(data)
        Song.objects.filter(id=self.song.id).update(active=False)
        User.objects.filter(id=self.user.id).update(origin="SIMULATED")
        repeated = self.post(data)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), response.json())
        self.assertEqual(Behavior.objects.get().origin, "REAL")

    def test_new_event_requires_active_song(self):
        Song.objects.filter(id=self.song.id).update(active=False)
        self.assert_error(self.post(self.payload()), 404, "NOT_FOUND")
        self.assert_error(self.post({**self.payload(), "song_id": 999999}), 404, "NOT_FOUND")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_tc_m_007_seek_cannot_instantly_count_as_completion(self):
        self.start()
        response = self.post(self.payload(kind="COMPLETE", position=90000, listened=90000), self.now + timedelta(seconds=1))
        self.assert_error(response, 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.filter(kind=Behavior.COMPLETE).count(), 0)

    def test_tc_m_013_long_pause_cannot_inflate_listening(self):
        self.start()
        response = self.post(self.payload(kind="COMPLETE", position=90000, listened=1000), self.now + timedelta(minutes=10))
        self.assert_error(response, 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_completion_exact_eighty_percent_is_accepted(self):
        self.start()
        response = self.post(self.payload(kind="COMPLETE", position=80000, listened=80000), self.now + timedelta(seconds=80))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["effective_ms"], 80000)
        self.assert_schema(response, "BehaviorResponse")

    def test_completion_requires_both_position_and_effective_duration(self):
        self.start()
        for position, listened in [(79999, 90000), (90000, 79999)]:
            response = self.post(self.payload(kind="COMPLETE", position=position, listened=listened), self.now + timedelta(seconds=90))
            self.assert_error(response, 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_elapsed_milliseconds_are_floored_without_float_rounding(self):
        self.start()
        data = self.payload(kind="COMPLETE", position=80000, listened=80000)
        self.assert_error(self.post(data, self.now + timedelta(microseconds=79999999)), 409, "INVALID_TRANSITION")
        self.assertEqual(self.post(data, self.now + timedelta(microseconds=80000000)).status_code, 201)

    def test_short_song_uses_integer_ceiling(self):
        Song.objects.filter(id=self.song.id).update(duration_ms=7)
        self.start()
        data = self.payload(kind="COMPLETE", position=6, listened=6)
        self.assert_error(self.post(data, self.now + timedelta(milliseconds=5)), 409, "INVALID_TRANSITION")
        self.assertEqual(self.post(data, self.now + timedelta(milliseconds=6)).json()["effective_ms"], 6)

    def test_one_millisecond_song_requires_one_millisecond(self):
        Song.objects.filter(id=self.song.id).update(duration_ms=1)
        self.start()
        data = self.payload(kind="COMPLETE", position=1, listened=1)
        self.assert_error(self.post(data, self.now), 409, "INVALID_TRANSITION")
        self.assertEqual(self.post(data, self.now + timedelta(milliseconds=1)).status_code, 201)

    def test_listened_duration_is_clamped_to_song_duration(self):
        self.start()
        response = self.post(self.payload(kind="COMPLETE", position=100000, listened=86400000), self.now + timedelta(days=1))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["effective_ms"], 100000)

    def test_skip_accepts_partial_feedback_and_terminates(self):
        self.start()
        response = self.post(self.payload(kind="SKIP", position=4000, listened=1000), self.now + timedelta(seconds=2))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["effective_ms"], 1000)
        self.assertEqual(Behavior.objects.filter(kind=Behavior.COMPLETE).count(), 0)

    def test_missing_play_cannot_terminate_session(self):
        for kind in ["SKIP", "COMPLETE"]:
            self.assert_error(self.post(self.payload(kind=kind, position=90000, listened=90000)), 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_song_switch_cannot_reuse_session(self):
        self.start()
        for kind in ["PLAY", "SKIP", "COMPLETE"]:
            data = self.payload(kind=kind, song=self.other_song)
            self.assert_error(self.post(data), 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_second_play_with_new_event_cannot_reset_clock(self):
        self.start()
        self.assert_error(self.post(self.payload(), self.now + timedelta(seconds=70)), 409, "EVENT_CONFLICT")
        self.assertEqual(Behavior.objects.get().occurred_at, self.now)

    def test_pt_m_011_terminal_states_reject_all_new_terminators(self):
        for terminal in ["COMPLETE", "SKIP"]:
            session = str(uuid4())
            self.assertEqual(self.post(self.payload(session=session)).status_code, 201)
            data = self.payload(kind=terminal, position=90000, listened=90000, session=session)
            accepted = self.post(data, self.now + timedelta(seconds=90))
            self.assertEqual(accepted.status_code, 201)
            for retry in range(5):
                repeated = self.post(data, self.now + timedelta(seconds=91 + retry))
                self.assertEqual(repeated.status_code, 200)
                self.assertEqual(repeated.json(), accepted.json())
            for next_kind in ["COMPLETE", "SKIP"]:
                response = self.post(self.payload(kind=next_kind, position=90000, listened=90000, session=session), self.now + timedelta(seconds=100))
                self.assert_error(response, 409, "INVALID_TRANSITION")
            self.assert_error(self.post(self.payload(session=session)), 409, "EVENT_CONFLICT")
        self.assertEqual(Behavior.objects.count(), 4)

    def test_new_session_can_replay_same_song_without_extra_matrix_credit(self):
        for session in [str(uuid4()), str(uuid4())]:
            self.post(self.payload(session=session))
            self.assertEqual(self.post(self.payload(kind="COMPLETE", position=90000, listened=90000, session=session), self.now + timedelta(seconds=90)).status_code, 201)
        inputs = daily.load_inputs(user_id=self.user.id, cutoff=self.now + timedelta(seconds=91))
        from music.recommendation import positive_matrix

        matrix = positive_matrix(users=inputs["users"], cutoff=inputs["now"], origin="REAL")
        self.assertEqual(matrix[self.user.id][self.song.id], 3.0)

    def test_backwards_clock_rejects_new_terminal_but_allows_exact_retry(self):
        data = self.payload()
        self.post(data)
        self.assertEqual(self.post(data, self.now - timedelta(seconds=1)).status_code, 200)
        self.assert_error(self.post(self.payload(kind="SKIP"), self.now - timedelta(microseconds=1)), 409, "INVALID_TRANSITION")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_position_over_duration_and_nonzero_play_are_validation_errors(self):
        for position, listened in [(1, 0), (0, 1), (1, 1)]:
            self.assert_error(self.post(self.payload(position=position, listened=listened)), 400, "VALIDATION_ERROR")
        self.start()
        for kind in ["COMPLETE", "SKIP"]:
            self.assert_error(self.post(self.payload(kind=kind, position=100001)), 400, "VALIDATION_ERROR")
        self.assertEqual(Behavior.objects.count(), 1)

    def test_strict_fields_reject_invalid_types_and_outside_ranges(self):
        invalid_fields = {
            "event_id": [None, 42, True, "invalid", str(uuid4()).replace("-", "")],
            "listening_session_id": [None, 42, "invalid"],
            "song_id": [True, 1.0, "1", 0, -1, None],
            "position_ms": [True, 1.0, "0", -1, 86400001, None],
            "listened_ms": [False, 1.0, "0", -1, 86400001, None],
            "kind": [True, 1, None, "play", "PAUSE"],
        }
        for field, values in invalid_fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_error(self.post({**self.payload(), field: value}), 400, "VALIDATION_ERROR")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_missing_extra_and_client_server_fields_are_rejected(self):
        data = self.payload()
        for field in data:
            missing = {key: value for key, value in data.items() if key != field}
            self.assert_error(self.post(missing), 400, "VALIDATION_ERROR")
        for field, value in [("user_id", self.other.id), ("origin", "SIMULATED"), ("occurred_at", self.now.isoformat()), ("effective_ms", 100000)]:
            self.assert_error(self.post({**data, field: value}), 400, "VALIDATION_ERROR")
        for value in [None, [], 7]:
            self.assert_error(self.post(value), 400, "VALIDATION_ERROR")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_body_query_content_type_and_method_validation(self):
        self.assert_error(self.post(self.payload(), path="/api/v1/behaviors/?user_id=1"), 400, "VALIDATION_ERROR")
        for raw in ["", "{", "a" * 65537]:
            response = self.client.post("/api/v1/behaviors/", raw, content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
            self.assert_error(response, 400, "VALIDATION_ERROR")
        response = self.client.post("/api/v1/behaviors/", "", content_type="text/plain", HTTP_X_CSRFTOKEN=self.token)
        self.assert_error(response, 415, "VALIDATION_ERROR")
        self.assert_error(self.client.get("/api/v1/behaviors/"), 405, "VALIDATION_ERROR")

    def test_csrf_precedes_auth_and_inactive_user_is_denied(self):
        self.client.logout()
        response = self.client.post("/api/v1/behaviors/", self.payload(), format="json")
        self.assert_error(response, 403, "CSRF_FAILED")
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assert_error(self.post(self.payload()), 401, "AUTH_REQUIRED")
        self.client.force_login(self.user)
        User.objects.filter(id=self.user.id).update(is_active=False)
        self.assert_error(self.post(self.payload()), 401, "AUTH_REQUIRED")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_authenticated_writes_still_require_csrf(self):
        response = self.client.post("/api/v1/behaviors/", self.payload(), format="json")
        self.assert_error(response, 403, "CSRF_FAILED")

    def test_service_direct_calls_validate_time_types_and_account(self):
        data = self.payload()
        with self.assertRaises(ValueError):
            behavior.record_behavior(user_id=self.user.id, now=datetime(2026, 10, 30), **data)
        with self.assertRaises(ApiError) as raised:
            behavior.record_behavior(user_id=self.user.id, now=self.now, **{**data, "song_id": True})
        self.assertEqual(raised.exception.error_code, "VALIDATION_ERROR")
        with self.assertRaises(ApiError) as raised:
            behavior.record_behavior(user_id=999999, now=self.now, **data)
        self.assertEqual(raised.exception.error_code, "AUTH_REQUIRED")

    def test_transaction_failure_after_insert_rolls_back_event(self):
        save = Behavior.save

        def fail_after_insert(event, *args, **kwargs):
            save(event, *args, **kwargs)
            raise RuntimeError("PRIVATE_INJECTED_FAILURE")

        with patch.object(Behavior, "save", fail_after_insert):
            with self.assertLogs("music.api.errors", level="ERROR"):
                response = self.post(self.payload())
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertNotIn("PRIVATE_INJECTED_FAILURE", response.content.decode())
        self.assertEqual(Behavior.objects.count(), 0)

    def test_terminal_failure_keeps_play_and_does_not_advance_state(self):
        self.start()
        data = self.payload(kind="COMPLETE", position=90000, listened=90000)
        with patch("music.behavior.Behavior.objects.create", side_effect=RuntimeError("INJECTED_TERMINAL")):
            with self.assertLogs("music.api.errors", level="ERROR"):
                response = self.post(data, self.now + timedelta(seconds=90))
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertEqual(Behavior.objects.count(), 1)
        self.assertEqual(self.post(data, self.now + timedelta(seconds=90)).status_code, 201)

    def test_unrelated_integrity_error_is_not_swallowed(self):
        with patch("music.behavior.Behavior.objects.create", side_effect=IntegrityError("INJECTED_UNKNOWN")):
            with self.assertRaises(IntegrityError):
                behavior.record_behavior(user_id=self.user.id, now=self.now, **self.payload())
        self.assertEqual(Behavior.objects.count(), 0)

    def test_global_unique_race_recovers_exact_prior_event(self):
        data = self.payload()
        first = self.post(data).json()
        prior = Behavior.objects.get()
        with patch("music.behavior.existing_event", side_effect=[None, prior]):
            with patch("music.behavior.check_session", return_value=None):
                with patch("music.behavior.Behavior.objects.create", side_effect=IntegrityError("UNIQUE")):
                    event, created = behavior.record_behavior(user_id=self.user.id, now=self.now, **data)
        self.assertFalse(created)
        self.assertEqual(event.id, first["id"])
        self.assertEqual(Behavior.objects.count(), 1)

    def test_session_race_maps_to_conflict_without_partial_insert(self):
        data = self.payload()
        with patch("music.behavior.check_session", side_effect=[None, ApiError("EVENT_CONFLICT")]):
            with patch("music.behavior.Behavior.objects.create", side_effect=IntegrityError("SESSION_UNIQUE")):
                with self.assertRaises(ApiError) as raised:
                    behavior.record_behavior(user_id=self.user.id, now=self.now, **data)
        self.assertEqual(raised.exception.error_code, "EVENT_CONFLICT")
        self.assertEqual(Behavior.objects.count(), 0)

    def test_api_events_feed_profile_and_filter_daily_candidate(self):
        tag = Tag.objects.create(name="治愈", kind=Tag.MOOD)
        SongTag.objects.create(song=self.song, tag=tag)
        SongTag.objects.create(song=self.other_song, tag=tag)
        self.start()
        before = daily.build_user_profile(user_id=self.user.id, cutoff=self.now + timedelta(seconds=1), origin="REAL")
        self.assertEqual(before, {})
        data = self.payload(kind="COMPLETE", position=90000, listened=90000)
        self.assertEqual(self.post(data, self.now + timedelta(seconds=90)).status_code, 201)
        cutoff = self.now + timedelta(seconds=91)
        self.assertEqual(daily.build_user_profile(user_id=self.user.id, cutoff=cutoff, origin="REAL"), {tag.id: 1.0})
        Song.objects.update(checked_at=self.now, playback_allowed=True, file_path="songs/synthetic.wav")
        with patch("pathlib.Path.is_file", return_value=True):
            items = daily.calculate_daily(user_id=self.user.id, now=cutoff)
        self.assertEqual([item["song_id"] for item in items], [self.other_song.id])
        self.assertEqual(items[0]["source"], "CONTENT")

    def test_simulated_user_events_remain_in_simulated_group(self):
        User.objects.filter(id=self.user.id).update(origin="SIMULATED")
        self.start()
        self.assertEqual(Behavior.objects.get().origin, "SIMULATED")
        inputs = daily.load_inputs(user_id=self.other.id, cutoff=self.now + timedelta(seconds=1))
        self.assertNotIn(self.user.id, [member.user_id for member in inputs["users"]])

    def test_completion_replay_preserves_original_effective_ms_after_unpublish(self):
        self.start()
        data = self.payload(kind="COMPLETE", position=90000, listened=90000)
        initial = self.post(data, self.now + timedelta(seconds=85))
        self.assertEqual(initial.json()["effective_ms"], 85000)
        Song.objects.filter(id=self.song.id).update(active=False)
        repeated = self.post(data, self.now + timedelta(hours=2))
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), initial.json())
        self.assertEqual(Behavior.objects.count(), 2)

    def test_session_uuid_is_scoped_to_user(self):
        self.start()
        self.client.force_login(self.other)
        self.assertEqual(self.post(self.payload()).status_code, 201)
        self.assertEqual(self.post(self.payload(kind="SKIP"), self.now + timedelta(seconds=1)).status_code, 201)
        self.client.force_login(self.user)
        self.assertEqual(self.post(self.payload(kind="COMPLETE", position=90000, listened=90000), self.now + timedelta(seconds=90)).status_code, 201)
        self.assertEqual(Behavior.objects.count(), 4)

    def test_skip_effective_ms_is_limited_by_server_elapsed(self):
        self.start()
        response = self.post(self.payload(kind="SKIP", position=90000, listened=90000), self.now + timedelta(milliseconds=1200))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["effective_ms"], 1200)

    def test_completion_thresholds_for_varied_durations(self):
        for duration in [2, 3, 6, 11, 999, 30000, 86400000]:
            Song.objects.filter(id=self.song.id).update(duration_ms=duration)
            session = str(uuid4())
            self.assertEqual(self.post(self.payload(session=session)).status_code, 201)
            threshold = (4 * duration + 4) // 5
            data = self.payload(kind="COMPLETE", position=threshold, listened=threshold, session=session)
            self.assert_error(self.post(data, self.now + timedelta(milliseconds=threshold - 1)), 409, "INVALID_TRANSITION")
            response = self.post(data, self.now + timedelta(milliseconds=threshold))
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["effective_ms"], threshold)
