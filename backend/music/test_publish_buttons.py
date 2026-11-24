import io
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import Client, TestCase

from music.forms import SongAdminForm
from music.models import Song, SongTag, Tag, User, UserTag


class PublishButtonTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="publish_admin", password="test-only-password")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.song = Song.objects.create(title="合成歌曲", artist="测试", duration_ms=1000, mime="audio/mpeg", file_path="songs/synthetic.mp3")
        self.url = f"/admin/music/song/{self.song.pk}/change/"

    def payload(self, **changes):
        token = self.client.get(self.url).cookies["csrftoken"].value
        return {
            "csrfmiddlewaretoken": token, "title": self.song.title, "artist": self.song.artist,
            "album": "", "duration_ms": 1000, "mime": "audio/mpeg",
            "songtag_set-TOTAL_FORMS": "0", "songtag_set-INITIAL_FORMS": "0",
            "songtag_set-MIN_NUM_FORMS": "0", "songtag_set-MAX_NUM_FORMS": "1000", **changes,
        }

    def submit(self, **changes):
        data = self.payload(**changes)
        if "songtag_set-TOTAL_FORMS" not in changes:
            for index, (kind, name) in enumerate((("STYLE", "流行"), ("MOOD", "悲伤"), ("SCENE", "夜晚"))):
                tag, _ = Tag.objects.get_or_create(kind=kind, name=name)
                relation = SongTag.objects.filter(song=self.song, tag=tag).first()
                data[f"songtag_set-{index}-tag"] = str(tag.pk)
                data[f"songtag_set-{index}-song"] = str(self.song.pk)
                if relation:
                    data[f"songtag_set-{index}-id"] = str(relation.pk)
            data["songtag_set-TOTAL_FORMS"] = "3"
            data["songtag_set-INITIAL_FORMS"] = str(SongTag.objects.filter(song=self.song).count())
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(b"\xff\xfb\x90\x00")):
            return self.client.post(self.url, data)

    def test_pb_001_button_publishes_and_catalog_is_playable(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'name="_publish"')
        for field in ("active", "playback_allowed", "checked_at", "preview_confirmed"):
            self.assertNotContains(page, f'name="{field}"')
        response = self.submit(_publish="1")
        self.assertEqual(response.status_code, 302)
        self.song.refresh_from_db()
        self.assertTrue(self.song.active)
        self.assertTrue(self.song.playback_allowed)
        self.assertIsNotNone(self.song.checked_at)
        with patch("pathlib.Path.is_file", return_value=True):
            response = self.client.get("/api/v1/songs/")
        self.assertEqual(response.json()["count"], 1)
        self.assertTrue(response.json()["results"][0]["playable"])

    def test_pb_002_normal_save_keeps_draft_and_forged_switches_ignored(self):
        self.assertEqual(self.submit(_save="1", active="on", playback_allowed="on", checked_at="2099-01-01").status_code, 302)
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)
        self.assertFalse(self.song.playback_allowed)
        self.assertIsNone(self.song.checked_at)

    def test_pb_003_edit_published_song_and_unpublish(self):
        self.submit(_publish="1")
        self.song.refresh_from_db()
        published_at = self.song.checked_at
        self.assertEqual(self.submit(_save="1", title="改名").status_code, 302)
        self.song.refresh_from_db()
        self.assertTrue(self.song.active)
        self.assertEqual(self.song.checked_at, published_at)
        self.assertEqual(self.song.title, "改名")
        self.assertEqual(self.submit(_unpublish="1").status_code, 302)
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)
        self.assertFalse(self.song.playback_allowed)
        self.assertEqual(self.client.get("/api/v1/songs/").json()["count"], 0)

    def test_pb_004_missing_file_or_bad_structure_prevents_publishing(self):
        for missing in (True, False):
            data = self.payload(_publish="1")
            with patch("pathlib.Path.is_file", return_value=not missing), patch("pathlib.Path.open", return_value=io.BytesIO(b"bad")):
                response = self.client.post(self.url, data)
            self.assertEqual(response.status_code, 200)
            self.song.refresh_from_db()
            self.assertFalse(self.song.active)

    def test_pb_005_csrf_and_change_permission_enforced(self):
        self.assertEqual(self.client.post(self.url, {"_publish": "1"}).status_code, 403)
        staff = User.objects.create_user(username="readonly", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="music", codename="view_song"))
        self.client.force_login(staff)
        page = self.client.get(self.url)
        self.assertNotContains(page, 'name="_publish"')
        token = page.cookies["csrftoken"].value
        self.assertEqual(self.client.post(self.url, {"_publish": "1", "csrfmiddlewaretoken": token}).status_code, 403)

    def test_pb_006_conflicting_actions_fail(self):
        form = SongAdminForm(data={"_publish": "1", "_unpublish": "1"}, instance=self.song)
        self.assertFalse(form.is_valid())
        self.assertIn("不能同时发布和下架", str(form.errors))

    def test_publish_requires_all_three_active_kinds_but_draft_can_be_empty(self):
        self.assertEqual(self.submit(_publish="1", **{"songtag_set-TOTAL_FORMS": "0"}).status_code, 200)
        self.song.refresh_from_db()
        self.assertFalse(self.song.active)
        self.assertEqual(self.submit(_save="1", **{"songtag_set-TOTAL_FORMS": "0"}).status_code, 302)
        self.assertFalse(SongTag.objects.filter(song=self.song).exists())

    def test_pb_007_tag_crud_search_and_confirmed_delete_preserve_song(self):
        add_url = "/admin/music/tag/add/"
        token = self.client.get(add_url).cookies["csrftoken"].value
        self.assertEqual(self.client.post(add_url, {"csrfmiddlewaretoken": token, "name": "测试标签", "kind": "STYLE", "active": "on", "_save": "1"}).status_code, 302)
        tag = Tag.objects.get(name="测试标签")
        edit_url = f"/admin/music/tag/{tag.pk}/change/"
        self.assertEqual(self.client.post(edit_url, {"csrfmiddlewaretoken": token, "name": "更新标签", "kind": "MOOD", "active": "on", "_save": "1"}).status_code, 302)
        self.assertContains(self.client.get("/admin/music/tag/?q=更新标签"), "更新标签")
        SongTag.objects.create(song=self.song, tag=tag)
        UserTag.objects.create(user=self.admin, tag=tag)
        delete_url = f"/admin/music/tag/{tag.pk}/delete/"
        self.assertEqual(self.client.get(delete_url).status_code, 200)
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(self.client.post(delete_url, {"post": "yes"}).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {"post": "yes", "csrfmiddlewaretoken": token}).status_code, 302)
        self.assertFalse(Tag.objects.filter(pk=tag.pk).exists())
        self.assertEqual(SongTag.objects.count(), 0)
        self.assertEqual(UserTag.objects.count(), 0)
        self.assertTrue(Song.objects.filter(pk=self.song.pk).exists())

    def test_pb_008_delete_requires_permission(self):
        tag = Tag.objects.create(name="保留", kind="STYLE")
        staff = User.objects.create_user(username="tag_editor", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="music", codename="change_tag"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(f"/admin/music/tag/{tag.pk}/delete/").status_code, 403)
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())

    def test_pb_009_inline_delete_removes_only_song_relationship(self):
        tag = Tag.objects.create(name="保留全局", kind="STYLE")
        relation = SongTag.objects.create(song=self.song, tag=tag)
        response = self.submit(_save="1", **{
            "songtag_set-TOTAL_FORMS": "1", "songtag_set-INITIAL_FORMS": "1",
            "songtag_set-0-id": str(relation.pk), "songtag_set-0-song": str(self.song.pk),
            "songtag_set-0-tag": str(tag.pk), "songtag_set-0-DELETE": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SongTag.objects.filter(pk=relation.pk).exists())
        self.assertTrue(Tag.objects.filter(pk=tag.pk).exists())
