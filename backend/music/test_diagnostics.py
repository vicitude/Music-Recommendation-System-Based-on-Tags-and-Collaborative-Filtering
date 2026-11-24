from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.db import DatabaseError
from django.test import Client, TestCase
from django.utils import timezone

from music.daily import load_inputs
from music.diagnostics import build_diagnostics
from music.models import Favorite, RecommendationSnapshot, Song, SongTag, Tag, User, UserTag
from music.recommendation import recommend


class DiagnosticsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="diagnostic_admin", password="test-only-password")
        self.target = User.objects.create_user(username="target")
        self.peer = User.objects.create_user(username="peer")
        self.tag = Tag.objects.create(name="流行", kind="STYLE")
        self.now = timezone.now()
        self.past = self.now - timedelta(days=1)
        self.songs = [Song.objects.create(title=f"Synthetic {number}", artist="TEST_ONLY", duration_ms=1000, mime="audio/mpeg", active=True, playback_allowed=True, checked_at=self.past, file_path=f"songs/{number}.mp3") for number in range(4)]
        Song.objects.update(created_at=self.past)
        SongTag.objects.bulk_create([SongTag(song=song, tag=self.tag) for song in self.songs])
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/user/recommendation-diagnostics/"
        self.files = patch("pathlib.Path.is_file", return_value=True)
        self.files.start()
        self.addCleanup(self.files.stop)

    def test_diag_001_initial_page_is_readonly_no_automatic_trial(self):
        with patch("music.admin.build_diagnostics") as calculate:
            response = self.client.get(self.url)
        self.assertContains(response, "请选择账号")
        calculate.assert_not_called()
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_diag_002_cold_start_uses_tags_and_matches_engine(self):
        UserTag.objects.create(user=self.target, tag=self.tag)
        report = build_diagnostics(user_id=self.target.pk, now=self.now)
        expected = recommend(**load_inputs(user_id=self.target.pk, cutoff=self.now), limit=10)
        self.assertEqual(report["alpha_effective"], 1)
        self.assertEqual(report["positive_count"], 0)
        self.assertEqual([row["score"] for row in report["rows"]], [item["score"] for item in expected.items])
        self.assertTrue(all(row["source"] == "CONTENT" for row in report["rows"]))
        self.assertEqual(RecommendationSnapshot.objects.count(), 0)

    def test_diag_003_hybrid_has_contributing_neighbors(self):
        for owner, songs in ((self.target, self.songs[:2]), (self.peer, self.songs[:3])):
            for song in songs:
                favorite = Favorite.objects.create(user=owner, song=song)
                Favorite.objects.filter(pk=favorite.pk).update(created_at=self.past)
        report = build_diagnostics(user_id=self.target.pk, now=self.now)
        self.assertEqual(report["positive_count"], 2)
        self.assertTrue(0 < report["alpha_effective"] < 1)
        row = next(row for row in report["rows"] if row["song_id"] == self.songs[2].pk)
        self.assertEqual(row["source"], "HYBRID")
        self.assertEqual(row["evidence"]["neighbor_count"], 1)
        self.assertEqual(Favorite.objects.count(), 5)

    def test_diag_004_no_signals_hot_and_no_candidates_empty(self):
        report = build_diagnostics(user_id=self.target.pk, now=self.now)
        self.assertIsNone(report["alpha_effective"])
        self.assertTrue(all(row["source"] == "HOT" for row in report["rows"]))
        Song.objects.update(active=False)
        self.assertEqual(build_diagnostics(user_id=self.target.pk, now=self.now)["rows"], [])

    def test_diag_005_simulated_users_are_isolated(self):
        self.peer.origin = "SIMULATED"
        self.peer.save()
        report = build_diagnostics(user_id=self.target.pk, now=self.now)
        self.assertEqual(report["peer_count"], 1)
        self.assertEqual(report["origin"], "REAL")

    def test_diag_006_permissions_methods_and_bad_ids(self):
        self.assertEqual(self.client.get(self.url + "?user_id=invalid").status_code, 400)
        self.assertEqual(self.client.get(self.url + "?user_id=999999").status_code, 400)
        client = Client()
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url).status_code, 405)
        self.client.force_login(self.target)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.peer.is_staff = True
        self.peer.save()
        self.client.force_login(self.peer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.peer.user_permissions.add(*Permission.objects.filter(content_type__app_label="music", codename__in=["view_user", "view_song"]))
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_diag_007_rendered_report_and_exception_are_safe(self):
        response = self.client.get(self.url, {"user_id": self.target.pk})
        for text in ("当前计算依据", "标签分", "协同分", "贡献邻居", "尚无每日快照"):
            self.assertContains(response, text)
        with patch("music.admin.build_diagnostics", side_effect=DatabaseError("private details")):
            response = self.client.get(self.url, {"user_id": self.target.pk})
        self.assertContains(response, "诊断暂时不可用", status_code=503)
        self.assertNotContains(response, "private details", status_code=503)

    def test_diag_008_existing_snapshot_is_not_replaced(self):
        snapshot = RecommendationSnapshot.objects.create(user=self.target, day=self.now.date(), revision=7, alpha_target=0.9, items=[], generated_at=self.past)
        before = RecommendationSnapshot.objects.values().get(pk=snapshot.pk)
        report = build_diagnostics(user_id=self.target.pk, now=self.now)
        self.assertEqual(report["snapshot"].revision, 7)
        self.assertEqual(RecommendationSnapshot.objects.values().get(pk=snapshot.pk), before)
