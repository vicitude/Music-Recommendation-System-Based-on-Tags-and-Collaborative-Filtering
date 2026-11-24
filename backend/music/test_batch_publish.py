import io
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Permission
from django.test import Client, TestCase

from music.models import Song, SongTag, Tag, User


class BatchPublishTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="batch_publisher", password="test-only-password")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/song/batch-publish/"
        self.song = self.create_song("可发布")

    def create_song(self, title):
        song = Song.objects.create(title=title, artist="测试", duration_ms=1000, mime="audio/mpeg", file_path="songs/test.mp3")
        for kind, name in ((Tag.STYLE, "流行"), (Tag.MOOD, "欢快"), (Tag.SCENE, "运动")):
            tag, _ = Tag.objects.get_or_create(kind=kind, name=name)
            SongTag.objects.create(song=song, tag=tag)
        return song

    def submit(self, songs, **changes):
        token = self.client.get(self.url).cookies["csrftoken"].value
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"\xff\xfb\x90\x00")):
            return self.client.post(self.url, {"csrfmiddlewaretoken": token, "selected": [str(song.pk) for song in songs], "confirm_publish": "yes", **changes})

    def test_mixed_results_preserve_invalid_and_repeated_publish(self):
        invalid = self.create_song("缺标签")
        SongTag.objects.filter(song=invalid, tag__kind=Tag.MOOD).delete()
        response = self.submit([self.song, invalid])
        self.assertContains(response, "发布成功")
        self.assertContains(response, "标签未达发布要求")
        self.song.refresh_from_db()
        invalid.refresh_from_db()
        self.assertTrue(self.song.active)
        self.assertTrue(self.song.playback_allowed)
        self.assertIsNotNone(self.song.checked_at)
        self.assertFalse(invalid.active)
        original_time = self.song.checked_at
        self.assertContains(self.submit([self.song]), "已发布，跳过")
        self.song.refresh_from_db()
        self.assertEqual(self.song.checked_at, original_time)
        self.assertEqual(LogEntry.objects.filter(object_id=str(self.song.pk)).count(), 1)
        self.assertEqual(SongTag.objects.filter(song=self.song).count(), 3)

    def test_disabled_and_excess_tags_block(self):
        Tag.objects.filter(kind=Tag.SCENE).update(active=False)
        self.assertContains(self.submit([self.song]), "标签未达发布要求")
        Tag.objects.filter(kind=Tag.SCENE).update(active=True)
        for name in ("摇滚", "电子"):
            SongTag.objects.create(song=self.song, tag=Tag.objects.create(kind=Tag.STYLE, name=name))
        self.assertContains(self.submit([self.song]), "标签未达发布要求")
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)

    def test_audio_and_metadata_validation(self):
        with patch("pathlib.Path.is_file", return_value=False):
            token = self.client.get(self.url).cookies["csrftoken"].value
            response = self.client.post(self.url, {"csrfmiddlewaretoken": token, "selected": [self.song.pk], "confirm_publish": "yes"})
        self.assertContains(response, "原媒体路径无效或文件不存在")
        self.song.mime = "audio/ogg"
        self.song.save()
        self.assertContains(self.submit([self.song]), "MIME与实际文件类型不一致")
        self.song.mime = "audio/mpeg"
        self.song.artist = ""
        self.song.save()
        self.assertContains(self.submit([self.song]), "未发布")
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)

    def test_csrf_confirmation_and_permissions(self):
        self.assertEqual(self.client.post(self.url, {"selected": [self.song.pk], "confirm_publish": "yes"}).status_code, 403)
        self.assertEqual(self.submit([self.song], confirm_publish="").status_code, 400)
        self.assertEqual(self.submit([]).status_code, 400)
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)
        staff = User.objects.create_user(username="no_publish", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="change_song", content_type__app_label="music"))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertContains(self.submit([self.song]), "发布成功")

    def test_visible_entry_points(self):
        for url in ("/admin/music/song/", "/admin/music/song/batch-import/"):
            self.assertContains(self.client.get(url), self.url)
        self.assertContains(self.client.get(self.url), "发布选中歌曲")
