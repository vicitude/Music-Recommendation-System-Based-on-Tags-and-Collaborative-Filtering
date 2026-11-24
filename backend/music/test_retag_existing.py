import copy
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from music.models import Song, SongTag, Tag
from music.retag_existing import diagnose_matches, retag_existing, validate_plan, verify_media


class RetagExistingTests(TestCase):
    def setUp(self):
        self.plan = dict(schema_version=1, policy_version="multilabel-minimum-v2", operation="REPLACE_EXISTING_40_SONG_TAGS_ONLY", items=[])
        self.old_tag = Tag.objects.create(kind="STYLE", name="摇滚")
        for index in range(40):
            identity = f"{index:064x}"
            song = Song.objects.create(title=f"song-{index}", artist="artist", duration_ms=60000, mime="audio/mpeg", source_name="LOCAL_DRAFT_SHA256:" + identity, active=index % 2 == 0, file_path="music/example.mp3")
            SongTag.objects.create(song=song, tag=self.old_tag, weight=3)
            candidates = [dict(kind=kind, name=name, evidence_level="LOW_FALLBACK", needs_review=True, auto_apply=False) for kind, name in (("STYLE", "流行"), ("MOOD", "悲伤"), ("SCENE", "夜晚"))]
            self.plan["items"].append(dict(sha256=identity, candidates=candidates))
        self.unrelated = Song.objects.create(title="other", artist="other", duration_ms=30000, mime="audio/mpeg")
        SongTag.objects.create(song=self.unrelated, tag=self.old_tag, weight=5)

    def test_preview_does_not_write_and_apply_preserves_other_state(self):
        before = list(Song.objects.order_by("pk").values())
        with patch("music.retag_existing.verify_media"), patch("music.retag_existing.save_backup") as backup:
            preview = retag_existing(self.plan)
            self.assertEqual(preview["songs"], 40)
            self.assertFalse(preview["matches_plan"])
            backup.assert_not_called()
            self.assertEqual(Tag.objects.count(), 1)
            result = retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
            payload = backup.call_args.args[1]
            self.assertEqual(len(payload["song_tags"]), 40)
            self.assertEqual({row["weight"] for row in payload["song_tags"]}, {3})
            self.assertEqual(result["new_relations"], 120)
            self.assertTrue(retag_existing(self.plan)["matches_plan"])
        self.assertEqual(list(Song.objects.order_by("pk").values()), before)
        self.assertEqual(SongTag.objects.get(song=self.unrelated).weight, 5)

    def test_missing_duplicate_or_invalid_counts_rejected(self):
        changed = copy.deepcopy(self.plan)
        changed["items"][0]["candidates"] = changed["items"][0]["candidates"][:1]
        with self.assertRaises(ValueError):
            validate_plan(changed)
        changed = copy.deepcopy(self.plan)
        changed["items"][0]["sha256"] = changed["items"][1]["sha256"]
        with self.assertRaises(ValueError):
            validate_plan(changed)
        Song.objects.filter(title="song-0").update(source_name="wrong")
        with patch("music.retag_existing.verify_media"), self.assertRaises(ValueError):
            retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
        self.assertEqual(SongTag.objects.count(), 41)

    def test_backup_failure_rolls_back(self):
        with patch("music.retag_existing.verify_media"), patch("music.retag_existing.save_backup", side_effect=OSError("disk full")), self.assertRaises(OSError):
            retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
        self.assertEqual(SongTag.objects.count(), 41)
        self.assertEqual(Tag.objects.count(), 1)

    def test_disabled_tag_not_revived(self):
        Tag.objects.create(kind="MOOD", name="悲伤", active=False)
        with patch("music.retag_existing.verify_media"), self.assertRaises(ValueError):
            retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
        self.assertFalse(Tag.objects.get(name="悲伤").active)
        self.assertEqual(SongTag.objects.count(), 41)

    def test_insert_failure_restores_deleted_relations(self):
        with patch("music.retag_existing.verify_media"), patch("music.retag_existing.save_backup"), patch("music.retag_existing.SongTag.objects.bulk_create", side_effect=RuntimeError("insert failed")), self.assertRaises(RuntimeError):
            retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
        self.assertEqual(SongTag.objects.count(), 41)
        self.assertEqual(Tag.objects.count(), 1)

    def test_actual_media_fingerprint_mismatch_is_not_ignored(self):
        song = Song.objects.get(title="song-0")
        fake_root = Path("D:/media")
        fake_file = fake_root / "music/example.mp3"
        with patch("music.retag_existing.Path.resolve", side_effect=[fake_root, fake_file]), patch("music.retag_existing.Path.is_symlink", return_value=False), patch("music.retag_existing.Path.lstat", return_value=SimpleNamespace(st_file_attributes=0)), patch("music.retag_existing.Path.stat", return_value=SimpleNamespace(st_size=4)), patch("music.retag_existing.Path.open", return_value=io.BytesIO(b"data")):
            with self.assertRaisesRegex(ValueError, "指纹不匹配"):
                verify_media(song, "0" * 64)

    def test_diagnosis_missing_and_duplicate_without_changes(self):
        before = list(SongTag.objects.order_by("pk").values())
        Song.objects.filter(title="song-0").update(source_name="legacy-source")
        Song.objects.filter(title="song-1").update(source_name="LOCAL_DRAFT_SHA256:" + f"{2:064x}")
        diagnosis = diagnose_matches(self.plan)
        self.assertEqual(diagnosis["matched_unique"], 37)
        self.assertEqual(len(diagnosis["missing"]), 2)
        self.assertEqual(len(diagnosis["duplicates"]), 1)
        self.assertEqual(len(diagnosis["duplicates"][0]["songs"]), 2)
        self.assertEqual(len(diagnosis["non_target_songs"]), 2)
        self.assertNotIn("source_name", str(diagnosis))
        self.assertEqual(list(SongTag.objects.order_by("pk").values()), before)
        with patch("music.retag_existing.save_backup") as backup, self.assertRaisesRegex(ValueError, "唯一匹配37首"):
            retag_existing(self.plan, apply=True, backup_path=Path("backup.json"))
        backup.assert_not_called()

    def test_diagnosis_complete_does_not_verify_media_or_write(self):
        with patch("music.retag_existing.verify_media") as media:
            diagnosis = diagnose_matches(self.plan)
        media.assert_not_called()
        self.assertEqual(diagnosis["matched_unique"], 40)
        self.assertEqual(diagnosis["missing"], [])
        self.assertEqual(diagnosis["duplicates"], [])
        self.assertEqual(Tag.objects.count(), 1)
