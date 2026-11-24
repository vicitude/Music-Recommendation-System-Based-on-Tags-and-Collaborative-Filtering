from django.test import Client, TestCase

from music.models import Song, SongTag, Tag, User


class PublishedPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="published_page_admin", password="test-only-password")
        self.client = Client()
        self.client.force_login(self.admin)
        tag = Tag.objects.create(kind=Tag.STYLE, name="流行")
        self.published = Song.objects.create(title="已发布歌曲", artist="测试歌手", duration_ms=1000, mime="audio/mpeg", active=True, playback_allowed=True, checked_at="2026-11-10T10:00:00Z", file_path="songs/a.mp3")
        SongTag.objects.create(song=self.published, tag=tag)
        Song.objects.create(title="草稿歌曲", artist="测试歌手", duration_ms=1000, mime="audio/mpeg", active=False, playback_allowed=False, file_path="songs/b.mp3")

    def test_page_only_lists_published_songs_with_tags(self):
        response = self.client.get("/admin/music/song/published/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "共 1 首已发布歌曲")
        self.assertContains(response, "已发布歌曲")
        self.assertContains(response, "流行")
        self.assertNotContains(response, "草稿歌曲")

    def test_entry_points_are_visible(self):
        self.assertContains(self.client.get("/admin/music/song/"), "查看已发布歌曲")
        self.assertContains(self.client.get("/admin/music/song/batch-import/"), "查看已发布歌曲")
        self.assertContains(self.client.get("/admin/music/song/batch-publish/"), "查看已发布歌曲")
