import io
from datetime import timedelta, timezone

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from music.models import Behavior, Favorite, Rating, Song, SongTag, Tag, User, UserTag
from music.simulation_profiles import ARCHETYPES


class C1SimulationTests(TestCase):
    def setUp(self):
        self.real = User.objects.create_user(username="real_keep")
        for archetype in ARCHETYPES:
            for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), archetype[1:]):
                for name in names:
                    Tag.objects.get_or_create(kind=kind, name=name)
        for index in range(24):
            song = Song.objects.create(title=f"Song {index}", artist="Test", duration_ms=180000, mime="audio/mpeg", active=True)
            for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), ARCHETYPES[index % 8][1:]):
                SongTag.objects.create(song=song, tag=Tag.objects.get(kind=kind, name=names[0]))

    def generate(self, count=200):
        call_command("seed_simulated_users", count=count, seed=42, profile_version="formal-v1", stdout=io.StringIO())

    def test_formal_profiles_preserve_dictionary_real_data_and_cover_eight_times(self):
        dictionary = set(Tag.objects.values_list("id", "name", "active"))
        songs = list(Song.objects.values())
        self.generate()
        self.assertEqual(User.objects.filter(origin="SIMULATED").count(), 200)
        self.assertEqual(set(Tag.objects.values_list("id", "name", "active")), dictionary)
        self.assertEqual(list(Song.objects.values()), songs)
        self.real.refresh_from_db()
        self.assertEqual(self.real.origin, "REAL")
        self.assertEqual(UserTag.objects.filter(user=self.real).count(), 0)
        interests = {tuple(UserTag.objects.filter(user=user).order_by("tag_id").values_list("tag_id", flat=True)) for user in User.objects.filter(origin="SIMULATED")}
        self.assertGreater(len(interests), 8)
        from music.recommendation import time_context
        contexts = {time_context(hour=value.astimezone(timezone(timedelta(hours=8))).hour) for value in Behavior.objects.filter(kind=Behavior.PLAY).values_list("occurred_at", flat=True)}
        self.assertEqual(len(contexts), 8)
        for favorite in Favorite.objects.select_related("user", "song"):
            self.assertTrue(Behavior.objects.filter(user=favorite.user, song=favorite.song, occurred_at__lte=favorite.created_at).exists())
        self.assertTrue(Rating.objects.exists())
        before = Behavior.objects.count()
        with self.assertRaises(CommandError):
            self.generate()
        self.assertEqual(Behavior.objects.count(), before)

    def test_missing_or_disabled_formal_tags_do_not_create_data(self):
        Tag.objects.filter(kind=Tag.MOOD).update(active=False)
        count = Tag.objects.count()
        with self.assertRaises(CommandError):
            self.generate(3)
        self.assertEqual(User.objects.filter(origin="SIMULATED").count(), 0)
        self.assertEqual(Tag.objects.count(), count)

    def test_approved_preparation_adds_only_missing_tags_and_preserves_disabled(self):
        disabled = Tag.objects.create(kind=Tag.STYLE, name="实验", active=False)
        output = io.StringIO()
        call_command("prepare_c1_simulation", confirm="C1 ADD 200", stdout=output)
        self.assertIn("VERIFIED_IN_TRANSACTION", output.getvalue())
        self.assertEqual(User.objects.filter(origin="SIMULATED").count(), 200)
        disabled.refresh_from_db()
        self.assertFalse(disabled.active)
        self.assertEqual(Song.objects.count(), 24)
        with self.assertRaises(CommandError):
            call_command("prepare_c1_simulation", confirm="C1 ADD 200", stdout=output)

    def test_preparation_failure_rolls_back_new_tags_and_accounts(self):
        from unittest.mock import patch
        count = Tag.objects.count()
        with patch("music.management.commands.prepare_c1_simulation.call_command", side_effect=CommandError("test failure")):
            with self.assertRaises(CommandError):
                call_command("prepare_c1_simulation", confirm="C1 ADD 200", stdout=io.StringIO())
        self.assertEqual(Tag.objects.count(), count)
        self.assertEqual(User.objects.filter(origin="SIMULATED").count(), 0)
