import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from music.daily import calculate_daily
from music.evaluation import evaluate_methods, load_dataset, time_split
from music.models import Behavior, Favorite, Rating, Song, SongTag, Tag, User


class SeedSimulatedUsersTests(TestCase):
    def setUp(self):
        self.media_root = Path(tempfile.mkdtemp())
        for index in range(1, 25):
            (self.media_root / f"song{index}.mp3").write_bytes(b"ID3simulated")
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)

    @classmethod
    def setUpTestData(cls):
        now = datetime.now(timezone.utc)
        for index in range(1, 25):
            song = Song.objects.create(
                title=f"测试歌曲 {index}",
                artist=f"测试歌手 {index % 7 + 1}",
                album="模拟专辑",
                duration_ms=180000 + index * 1000,
                file_path=f"song{index}.mp3",
                mime="audio/mpeg",
                active=True,
                source_name="SIMULATED_TEST",
                source_url="https://example.com/simulated",
                license_name="synthetic test data",
                license_url="https://example.com/simulated-license",
                playback_allowed=True,
                redistribution_allowed=False,
                checked_at=now,
            )
            for kind, names in (
                (Tag.STYLE, ["流行", "摇滚", "电子", "民谣", "轻音乐", "国风", "爵士", "舞曲"]),
                (Tag.MOOD, ["愉悦", "激昂", "冷静", "温柔", "平静", "悠扬", "慵懒", "快乐"]),
                (Tag.SCENE, ["通勤", "运动", "夜晚", "散步", "学习", "放松", "咖啡", "聚会"]),
            ):
                tag, _ = Tag.objects.get_or_create(name=names[index % len(names)], kind=kind, defaults={"active": True})
                SongTag.objects.get_or_create(song=song, tag=tag)

    def test_seed_creates_two_hundred_distinct_simulated_users(self):
        call_command("seed_simulated_users", count=200, seed=42, verbosity=0)

        users = User.objects.filter(origin="SIMULATED")
        self.assertEqual(users.count(), 200)
        self.assertEqual(users.filter(onboarding_completed=True).count(), 200)
        self.assertGreater(Behavior.objects.filter(origin="SIMULATED").count(), 200)
        self.assertGreater(Favorite.objects.filter(user__origin="SIMULATED").count(), 0)
        self.assertGreater(Rating.objects.filter(user__origin="SIMULATED").count(), 0)

    def test_seed_is_idempotent_for_same_seed_and_prefix(self):
        call_command("seed_simulated_users", count=200, seed=42, verbosity=0)
        counts = {
            "users": User.objects.filter(origin="SIMULATED").count(),
            "behaviors": Behavior.objects.filter(origin="SIMULATED").count(),
            "favorites": Favorite.objects.filter(user__origin="SIMULATED").count(),
            "ratings": Rating.objects.filter(user__origin="SIMULATED").count(),
        }

        call_command("seed_simulated_users", count=200, seed=42, verbosity=0)

        self.assertEqual(User.objects.filter(origin="SIMULATED").count(), counts["users"])
        self.assertEqual(Behavior.objects.filter(origin="SIMULATED").count(), counts["behaviors"])
        self.assertEqual(Favorite.objects.filter(user__origin="SIMULATED").count(), counts["favorites"])
        self.assertEqual(Rating.objects.filter(user__origin="SIMULATED").count(), counts["ratings"])

    def test_simulated_users_receive_daily_recommendations_with_explanations(self):
        call_command("seed_simulated_users", count=200, seed=42, verbosity=0)
        user = User.objects.filter(origin="SIMULATED").order_by("id").first()

        items = calculate_daily(user_id=user.id, now=datetime.now(timezone.utc))

        self.assertGreater(len(items), 0)
        self.assertTrue(all(item["explanation"] for item in items))
        self.assertTrue(all(item["source"] in {"CONTENT", "USER_CF", "ITEM_CF", "HYBRID", "HOT"} for item in items))
        self.assertNotEqual(items[0]["source"], "HOT")

    def test_optional_login_password_allows_local_sign_in(self):
        call_command("seed_simulated_users", count=3, seed=42, login_password="Sim-Local-Only-2026", verbosity=0)

        user = User.objects.get(username="sim_user_001")

        self.assertTrue(user.check_password("Sim-Local-Only-2026"))

    def test_exported_dataset_can_be_scored_by_the_five_method_comparison(self):
        call_command("seed_simulated_users", count=200, seed=42, verbosity=0)
        output = Path(tempfile.mkdtemp())

        call_command("export_simulated_dataset", output=str(output), verbosity=0)

        dataset = load_dataset(output / "manifest.json")
        split = time_split(dataset)
        metrics = evaluate_methods(dataset, split, k=10)
        self.assertEqual(set(metrics), {"HOT", "CONTENT", "USER_CF", "FIXED", "ADAPTIVE"})
        for name in metrics:
            self.assertIsNotNone(metrics[name]["precision"])
            self.assertIsNotNone(metrics[name]["recall"])
