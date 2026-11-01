import copy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, TestCase
from django.utils import timezone

from music.local_catalog import import_drafts
from music.local_media import bind_local_audio, catalog_audio_rows, read_local_audio
from music.media import MAX_AUDIO_BYTES
from music.models import Song, User
from music.test_local_catalog import catalog_item


class LocalMediaTests(TestCase):
    def setUp(self):
        self.source_directory = TemporaryDirectory()
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.source_directory.cleanup)
        self.addCleanup(self.media_directory.cleanup)
        self.source = Path(self.source_directory.name)
        self.media = Path(self.media_directory.name)
        self.settings_override = self.settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.data = b"\xff\xfb\x90\x00" + bytes(256)
        self.item = catalog_item(sha256=hashlib.sha256(self.data).hexdigest(), bytes=len(self.data))
        (self.source / self.item["filename"]).write_bytes(self.data)
        self.admin = User.objects.create_superuser(username="media_admin", password="test-password")
        import_drafts(items=[self.item], selected_hashes=[self.item["sha256"]], owner_id=self.admin.pk)
        self.song = Song.objects.get()
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/song/local-audio/"

    def apply(self, items=None, selected=None):
        return bind_local_audio(items=items or [self.item], selected_hashes=selected or [self.item["sha256"]], source_root=self.source)

    def test_lm_001_copy_preserves_source_and_all_draft_fields(self):
        before = Song.objects.values().get()
        result = self.apply()
        self.assertEqual((result["linked"], result["failed"]), (1, 0))
        self.song.refresh_from_db()
        self.assertEqual((self.media / self.song.file_path).read_bytes(), self.data)
        self.assertEqual((self.source / self.item["filename"]).read_bytes(), self.data)
        after = Song.objects.values().get()
        for key in before.keys() - {"file_path", "mime"}:
            self.assertEqual(before[key], after[key], key)

    def test_lm_002_repeat_skips_without_reading_source(self):
        self.apply()
        with patch("music.local_media.read_local_audio", side_effect=AssertionError("must not read")):
            result = self.apply()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(list(self.media.rglob("*.mp3"))), 1)

    def test_lm_003_unknown_and_empty_selection_write_nothing(self):
        for selected in ([], ["b" * 64]):
            with self.assertRaises(ValidationError):
                bind_local_audio(items=[self.item], selected_hashes=selected, source_root=self.source)
        self.assertEqual(list(self.media.iterdir()), [])

    def test_lm_004_missing_source_is_reported_without_link(self):
        result = bind_local_audio(items=[self.item], selected_hashes=[self.item["sha256"]], source_root=self.source / "missing")
        self.assertEqual(result["failed"], 1)
        self.song.refresh_from_db()
        self.assertEqual(self.song.file_path, "")

    def test_lm_005_same_size_tampered_source_is_rejected(self):
        (self.source / self.item["filename"]).write_bytes(b"x" * len(self.data))
        result = self.apply()
        self.assertEqual(result["failed"], 1)
        self.assertIn("不一致", result["entries"][0]["message"])

    def test_lm_006_size_bounds_are_checked(self):
        for size in (0, True, MAX_AUDIO_BYTES + 1, len(self.data) + 1):
            item = {**self.item, "bytes": size}
            self.assertEqual(self.apply(items=[item])["failed"], 1)
        self.assertEqual(list(self.media.iterdir()), [])

    def test_lm_007_invalid_mp3_structure_rejected_even_with_matching_hash(self):
        data = b"not audio"
        item = {**self.item, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        (self.source / item["filename"]).write_bytes(data)
        with self.assertRaises(ValidationError):
            read_local_audio(item, self.source)

    def test_lm_008_path_traversal_and_symlink_are_rejected(self):
        with self.assertRaises(ValidationError):
            self.apply(items=[{**self.item, "filename": "../outside.mp3"}])
        with patch("music.local_media.Path.is_symlink", return_value=True):
            self.assertEqual(self.apply()["failed"], 1)
        with patch("music.local_media.Path.resolve", side_effect=[self.source, self.media / "outside.mp3"]):
            with self.assertRaises(ValidationError):
                read_local_audio(self.item, self.source)

    def test_lm_009_published_or_checked_drafts_cannot_bind(self):
        for fields in ({"active": True}, {"playback_allowed": True}, {"checked_at": timezone.now()}):
            Song.objects.filter(pk=self.song.pk).update(active=False, playback_allowed=False, checked_at=None)
            Song.objects.filter(pk=self.song.pk).update(**fields)
            self.assertEqual(self.apply()["failed"], 1)
        self.assertEqual(list(self.media.iterdir()), [])

    def test_lm_010_duplicate_marker_is_not_guessed(self):
        self.song.pk = None
        self.song.save()
        self.assertEqual(self.apply()["failed"], 1)
        self.assertFalse(catalog_audio_rows([self.item])[0]["selectable"])

    def test_lm_011_database_failure_retains_and_logs_copy(self):
        with patch("music.local_media.Song.save", side_effect=DatabaseError("private secret")), self.assertLogs("music.local_media", level="ERROR") as logs:
            result = self.apply()
        self.assertEqual(result["failed"], 1)
        self.assertNotIn("private secret", str(result))
        self.assertIn("retained", logs.output[0])
        self.song.refresh_from_db()
        self.assertEqual(self.song.file_path, "")
        self.assertEqual(len(list(self.media.rglob("*.mp3"))), 1)

    def test_lm_012_partial_batch_retains_success(self):
        missing = catalog_item(filename="Missing.mp3", sha256="b" * 64, bytes=20)
        import_drafts(items=[missing], selected_hashes=[missing["sha256"]], owner_id=self.admin.pk)
        result = self.apply(items=[self.item, missing], selected=[self.item["sha256"], missing["sha256"]])
        self.assertEqual((result["linked"], result["failed"]), (1, 1))
        self.assertEqual(Song.objects.exclude(file_path="").count(), 1)

    def test_lm_013_get_only_lists_states_and_edit_link(self):
        with patch("music.admin.load_catalog", return_value=[self.item]), patch("music.local_media.read_local_audio", side_effect=AssertionError("no reads")):
            response = self.client.get(self.url)
        self.assertContains(response, "可关联音频")
        self.assertContains(response, f"/admin/music/song/{self.song.pk}/change/")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertEqual(list(self.media.iterdir()), [])

    def test_lm_014_csrf_and_confirmation_required(self):
        self.assertEqual(self.client.post(self.url, {"confirm_audio": "yes"}).status_code, 403)
        with patch("music.admin.load_catalog", return_value=[self.item]):
            token = self.client.get(self.url).cookies["csrftoken"].value
            response = self.client.post(self.url, {"csrfmiddlewaretoken": token, "selected": self.item["sha256"]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.media.iterdir()), [])

    def test_lm_015_confirmed_post_copies_and_shows_preview_entry(self):
        with patch("music.admin.load_catalog", return_value=[self.item]), patch("music.local_media.SOURCE_ROOT", self.source):
            token = self.client.get(self.url).cookies["csrftoken"].value
            response = self.client.post(self.url, {"csrfmiddlewaretoken": token, "selected": self.item["sha256"], "confirm_audio": "yes", "source_root": "untrusted"})
        self.assertContains(response, "本次处理结果：关联 1")
        self.assertContains(response, "已关联，不覆盖")
        preview = self.client.get(f"/admin/music/song/{self.song.pk}/preview/", HTTP_RANGE="bytes=0-3")
        self.assertEqual(preview.status_code, 206)
        self.assertEqual(b"".join(preview.streaming_content), self.data[:4])
        public = self.client.get("/api/v1/songs/")
        self.assertEqual(public.json()["count"], 0)

    def test_lm_016_only_song_editor_or_admin_has_access(self):
        user = User.objects.create_user(username="staff", password="test", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="music", codename="change_song"))
        with patch("music.admin.load_catalog", return_value=[self.item]):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        user.is_active = False
        user.save()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lm_017_unavailable_catalog_and_method_are_safe(self):
        with patch("music.admin.load_catalog", side_effect=ValueError("private detail")):
            response = self.client.get(self.url)
        self.assertContains(response, "暂不可用")
        self.assertNotContains(response, "private detail")
        client = Client()
        client.force_login(self.admin)
        self.assertEqual(client.put(self.url).status_code, 405)

    def test_lm_018_unimported_and_existing_broken_link_states(self):
        item = copy.deepcopy(self.item)
        item["sha256"] = "c" * 64
        self.assertIn("尚未导入", catalog_audio_rows([item])[0]["state"])
        self.song.file_path = "songs/missing.mp3"
        self.song.save()
        self.assertEqual(self.apply()["skipped"], 1)
        self.assertFalse(catalog_audio_rows([self.item])[0]["selectable"])
