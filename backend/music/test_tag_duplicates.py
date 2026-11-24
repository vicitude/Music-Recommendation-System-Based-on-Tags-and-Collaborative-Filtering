from django.test import Client, TestCase

from music.models import Song, SongTag, Tag, User


class SongTagDuplicateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="duplicate_admin", password="test-only-password")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.song = Song.objects.create(title="Original", artist="TEST_ONLY", duration_ms=1000, mime="audio/mpeg")
        self.first = Tag.objects.create(name="流行", kind="STYLE")
        self.second = Tag.objects.create(name="温柔", kind="MOOD")
        self.url = f"/admin/music/song/{self.song.pk}/change/"

    def submit(self, rows, initial=0, **changes):
        token = self.client.get(self.url).cookies["csrftoken"].value
        data = {
            "csrfmiddlewaretoken": token, "title": "Changed", "artist": "TEST_ONLY", "album": "",
            "duration_ms": 1000, "mime": "audio/mpeg", "_save": "1",
            "songtag_set-TOTAL_FORMS": str(len(rows)), "songtag_set-INITIAL_FORMS": str(initial),
            "songtag_set-MIN_NUM_FORMS": "0", "songtag_set-MAX_NUM_FORMS": "1000", **changes,
        }
        for index, row in enumerate(rows):
            for key, value in row.items():
                data[f"songtag_set-{index}-{key}"] = str(value)
        return self.client.post(self.url, data)

    def row(self, tag, relation=None, delete=False):
        return {"tag": tag.pk, "song": self.song.pk, "id": relation.pk if relation else "", **({"DELETE": "on"} if delete else {})}

    def test_td_001_duplicate_new_rows_show_form_errors_without_writes(self):
        response = self.submit([self.row(self.first), self.row(self.first)])
        self.assertContains(response, "歌曲标签重复")
        self.assertContains(response, "风格｜流行")
        self.assertEqual(SongTag.objects.count(), 0)
        self.song.refresh_from_db()
        self.assertEqual(self.song.title, "Original")

    def test_scene_upper_limit_two(self):
        scenes = [Tag.objects.create(kind="SCENE", name=name) for name in ("学习", "工作", "夜晚")]
        response = self.submit([self.row(tag) for tag in scenes])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(SongTag.objects.count(), 0)
        response = self.submit([self.row(tag) for tag in scenes[:2]])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongTag.objects.count(), 2)

    def test_td_002_existing_plus_new_duplicate_is_rejected(self):
        relation = SongTag.objects.create(song=self.song, tag=self.first)
        response = self.submit([self.row(self.first, relation), self.row(self.first)], initial=1)
        self.assertContains(response, "歌曲标签重复")
        self.assertEqual(SongTag.objects.count(), 1)

    def test_td_003_changing_existing_row_to_occupied_tag_is_rejected(self):
        first = SongTag.objects.create(song=self.song, tag=self.first)
        second = SongTag.objects.create(song=self.song, tag=self.second)
        response = self.submit([self.row(self.second, first), self.row(self.second, second)], initial=2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(SongTag.objects.values_list("tag_id", flat=True)), {self.first.pk, self.second.pk})

    def test_td_004_swap_is_rejected_before_database_unique_conflict(self):
        first = SongTag.objects.create(song=self.song, tag=self.first)
        second = SongTag.objects.create(song=self.song, tag=self.second)
        response = self.submit([self.row(self.second, first), self.row(self.first, second)], initial=2)
        self.assertContains(response, "交换标签时请分两次保存")
        first.refresh_from_db()
        self.assertEqual(first.tag_id, self.first.pk)

    def test_td_005_delete_and_readd_same_tag_succeeds(self):
        relation = SongTag.objects.create(song=self.song, tag=self.first)
        response = self.submit([self.row(self.first, relation, delete=True), self.row(self.first)], initial=1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongTag.objects.count(), 1)
        self.assertEqual(SongTag.objects.get().tag_id, self.first.pk)

    def test_td_006_delete_occupied_row_before_updating_earlier_row(self):
        first = SongTag.objects.create(song=self.song, tag=self.first)
        second = SongTag.objects.create(song=self.song, tag=self.second)
        response = self.submit([self.row(self.second, first), self.row(self.second, second, delete=True)], initial=2)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongTag.objects.count(), 1)
        self.assertEqual(SongTag.objects.get().tag_id, self.second.pk)

    def test_td_007_nonduplicate_rows_save_normally(self):
        response = self.submit([self.row(self.first), self.row(self.second)])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SongTag.objects.count(), 2)

    def test_td_008_omitted_existing_relation_cannot_be_added_twice(self):
        SongTag.objects.create(song=self.song, tag=self.first)
        response = self.submit([self.row(self.first)])
        self.assertContains(response, "标签与已有记录冲突")
        self.assertEqual(SongTag.objects.count(), 1)
