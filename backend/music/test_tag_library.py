from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.staticfiles import finders
from django.db import DatabaseError
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase
from django.utils.html import escape

from music.forms import SongTagAdminForm
from music.local_catalog import load_catalog
from music.models import Song, SongTag, Tag, User, UserTag
from music.tag_library import TAG_LIBRARY, canonical_tag, import_library, library_groups


class TagVocabularyTests(SimpleTestCase):
    def test_tl_001_new_vocabulary_has_27_15_11_formal_choices(self):
        self.assertEqual([len(entries) for _, _, entries in TAG_LIBRARY], [27, 15, 11])
        keys = [(kind, name) for kind, _, entries in TAG_LIBRARY for name, _ in entries]
        self.assertEqual(len(keys), len(set(keys)))
        for _, _, entries in TAG_LIBRARY:
            for name, explanation in entries:
                self.assertTrue(1 <= len(name) <= 30)
                self.assertTrue(explanation.strip())
        for item in load_catalog():
            for tag in item["tag_suggestions"]:
                self.assertIn((tag["kind"], tag["name"]), keys)

    def test_tl_020_legacy_names_map_to_formal_names(self):
        self.assertEqual(canonical_tag(Tag.MOOD, "伤感"), (Tag.MOOD, "悲伤"))
        self.assertEqual(canonical_tag(Tag.MOOD, "激昂"), (Tag.MOOD, "热血励志"))
        self.assertEqual(canonical_tag(Tag.STYLE, "流行摇滚"), (Tag.STYLE, "流行"))
        self.assertEqual(canonical_tag(Tag.STYLE, "钢琴"), (Tag.STYLE, "轻音乐"))

    def test_tl_002_readable_tag_labels_and_disabled_marker(self):
        self.assertEqual(str(Tag(name="流行", kind=Tag.STYLE)), "风格｜流行")
        self.assertEqual(str(Tag(name="悲伤", kind=Tag.MOOD)), "情绪｜悲伤")
        self.assertEqual(str(Tag(name="通勤", kind=Tag.SCENE, active=False)), "场景｜通勤（已停用）")

    def test_tl_017_client_script_exists_and_only_changes_selected_checkboxes(self):
        from pathlib import Path

        script = Path(finders.find("music/tag-library.js")).read_text(encoding="utf-8")
        self.assertIn('input[name="selected"]:not(:disabled)', script)
        self.assertNotIn("fetch(", script)
        self.assertNotIn(".submit(", script)


class TagLibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="tag_admin", password="test-only-password")
        cls.staff = User.objects.create_user(username="tag_staff", is_staff=True)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/tag/library/"

    def post(self, **changes):
        token = self.client.get(self.url).cookies["csrftoken"].value
        return self.client.post(self.url, {"csrfmiddlewaretoken": token, "confirm_library": "yes", "selected": ["STYLE:流行", "MOOD:放松"], **changes})

    def test_tl_003_get_displays_all_choices_without_writing_or_preselection(self):
        response = self.client.get(self.url)
        self.assertContains(response, "53个正式选项")
        self.assertContains(response, "不自动修改歌曲标签")
        for _, _, entries in TAG_LIBRARY:
            for name, description in entries:
                self.assertContains(response, escape(name))
                self.assertContains(response, escape(description))
        self.assertNotRegex(response.content.decode(), r'<input\b[^>]*name="selected"[^>]*\bchecked\b')
        self.assertContains(response, "/static/music/tag-library.js")
        self.assertEqual(Tag.objects.count(), 0)

    def test_tl_004_import_creates_only_tags_and_repeated_values_deduplicate(self):
        result = import_library(["STYLE:流行", "STYLE:流行", "MOOD:放松"])
        self.assertEqual(result, {"created": 2, "skipped": 0})
        self.assertEqual(import_library(["STYLE:流行"]), {"created": 0, "skipped": 1})
        self.assertEqual(Song.objects.count(), 0)
        self.assertEqual(SongTag.objects.count(), 0)
        self.assertEqual(UserTag.objects.count(), 0)

    def test_tl_005_existing_disabled_and_custom_tags_unchanged(self):
        disabled = Tag.objects.create(kind=Tag.STYLE, name="流行", active=False)
        custom = Tag.objects.create(kind=Tag.MOOD, name="自定义听感")
        self.assertEqual(import_library(["STYLE:流行"])["skipped"], 1)
        disabled.refresh_from_db()
        self.assertFalse(disabled.active)
        groups, other = library_groups()
        self.assertEqual(other, [custom])
        self.assertEqual(groups[0]["items"][0]["tag"], disabled)
        response = self.client.get(self.url)
        self.assertContains(response, "已停用（不会自动启用）")
        self.assertContains(response, "情绪｜自定义听感")

    def test_tl_006_unknown_empty_and_excessive_selection_are_atomic(self):
        for selected in ([], ["STYLE:流行", "MOOD:invented"], ["STYLE:流行"] * 71):
            with self.assertRaises(ValidationError):
                import_library(selected)
        self.assertEqual(Tag.objects.count(), 0)

    def test_tl_007_failure_rolls_back_prior_creation(self):
        create = Tag.objects.get_or_create
        calls = []

        def failing_create(**fields):
            calls.append(fields)
            if len(calls) == 2:
                raise DatabaseError("private details")
            return create(**fields)

        with patch("music.tag_library.Tag.objects.get_or_create", side_effect=failing_create), self.assertRaises(DatabaseError):
            import_library(["STYLE:流行", "MOOD:放松"])
        self.assertEqual(Tag.objects.count(), 0)

    def test_tl_008_csrf_and_confirmation_required(self):
        self.assertEqual(self.client.post(self.url, {"confirm_library": "yes"}).status_code, 403)
        self.assertEqual(self.post(confirm_library="").status_code, 400)
        self.assertEqual(Tag.objects.count(), 0)

    def test_tl_009_confirmed_post_redirects_and_adds_selected_only(self):
        self.assertRedirects(self.post(), self.url)
        self.assertEqual(Tag.objects.count(), 2)
        self.assertRedirects(self.post(), self.url)
        self.assertEqual(Tag.objects.count(), 2)

    def test_tl_010_permissions_allow_readonly_song_editor_not_import(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="music", codename="change_song"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="selected"')
        self.assertEqual(self.post().status_code, 403)
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="music", codename="add_tag"))
        self.assertEqual(self.post().status_code, 302)

    def test_tl_011_inactive_and_listener_cannot_view(self):
        self.staff.is_staff = False
        self.staff.save()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.admin.is_active = False
        self.admin.save()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_tl_012_method_and_error_messages_are_safe(self):
        client = Client()
        client.force_login(self.admin)
        self.assertEqual(client.put(self.url).status_code, 405)
        with patch("music.admin.import_library", side_effect=DatabaseError("private error")):
            response = self.post()
        self.assertContains(response, "已回滚", status_code=400)
        self.assertNotContains(response, "private error", status_code=400)
        self.assertEqual(self.post(selected=["BAD:label"]).status_code, 400)

    def test_tl_013_dropdown_groups_display_names_instead_of_object_ids(self):
        Tag.objects.create(kind=Tag.SCENE, name="通勤")
        Tag.objects.create(kind=Tag.STYLE, name="流行")
        Tag.objects.create(kind=Tag.MOOD, name="温柔", active=False)
        form = SongTagAdminForm()
        html = str(form["tag"])
        for label in ("风格", "情绪", "场景"):
            self.assertIn(f'<optgroup label="{label}">', html)
        self.assertIn("风格｜流行", html)
        self.assertIn("情绪｜温柔（已停用）", html)
        self.assertNotIn("Tag object", html)

    def test_tl_014_change_page_and_tag_list_have_guide_entry(self):
        song = Song.objects.create(title="合成测试", artist="测试", duration_ms=1000, mime="audio/mpeg", source_name="test", source_url="", license_name="", license_url="")
        tag = Tag.objects.create(kind=Tag.STYLE, name="流行")
        SongTag.objects.create(song=song, tag=tag)
        response = self.client.get(f"/admin/music/song/{song.pk}/change/")
        self.assertContains(response, "风格｜流行")
        self.assertContains(response, self.url)
        self.assertNotContains(response, "Tag object")
        self.assertContains(self.client.get("/admin/music/tag/"), self.url)

    def test_tl_015_import_all_formal_choices_is_repeatable(self):
        keys = [f"{kind}:{name}" for kind, _, entries in TAG_LIBRARY for name, _ in entries]
        self.assertEqual(import_library(keys), {"created": 53, "skipped": 0})
        self.assertEqual(import_library(keys), {"created": 0, "skipped": 53})

    def test_tl_016_grouped_field_rejects_unknown_id_and_saves_valid_relationship(self):
        tag = Tag.objects.create(kind=Tag.STYLE, name="流行")
        form = SongTagAdminForm(data={"tag": str(tag.pk)})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tag"], tag)
        self.assertFalse(SongTagAdminForm(data={"tag": "999999"}).is_valid())

    def test_tl_018_saved_song_tag_uses_readable_label(self):
        tag = Tag.objects.create(kind=Tag.STYLE, name="流行")
        self.assertEqual(str(SongTag(tag=tag)), "风格｜流行")
        self.assertEqual(str(SongTag()), "未选择标签")

    def test_tl_019_draft_editor_saves_tags_without_invented_license(self):
        song = Song.objects.create(title="合成测试", artist="测试", duration_ms=1000, mime="audio/mpeg", source_name="LOCAL_DRAFT_SHA256:" + "a" * 64, source_url="", license_name="", license_url="")
        tag = Tag.objects.create(kind=Tag.STYLE, name="流行")
        url = f"/admin/music/song/{song.pk}/change/"
        token = self.client.get(url).cookies["csrftoken"].value
        data = {
            "csrfmiddlewaretoken": token, "title": song.title, "artist": song.artist, "album": "",
            "duration_ms": song.duration_ms, "mime": song.mime, "source_name": song.source_name,
            "source_url": "", "license_name": "", "license_url": "", "attribution_text": "",
            "songtag_set-TOTAL_FORMS": "1", "songtag_set-INITIAL_FORMS": "0",
            "songtag_set-MIN_NUM_FORMS": "0", "songtag_set-MAX_NUM_FORMS": "1000",
            "songtag_set-0-tag": str(tag.pk), "songtag_set-0-song": str(song.pk), "_save": "保存",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SongTag.objects.filter(song=song, tag=tag, weight=1).exists())
        song.refresh_from_db()
        self.assertFalse(song.active)
        self.assertFalse(song.playback_allowed)
        self.assertEqual(song.license_url, "")
        self.assertEqual(song.source_name, data["source_name"])
        response = self.client.post(url, {**data, "_publish": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "发布必须有有效音频")
        song.refresh_from_db()
        self.assertFalse(song.active)
