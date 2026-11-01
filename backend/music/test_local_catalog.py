import copy
import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, SimpleTestCase, TestCase

from music.local_catalog import import_drafts, load_catalog, normalize_metadata, suggest_tags, validate_catalog
from music.models import Song, SongTag, Tag, User


def catalog_item(**changes):
    return {"filename": "Test Artist-Test Song.mp3", "sha256": "a" * 64, "title": "Test Song", "artist": "Test Artist", "album": "", "duration_ms": 180000, "tag_suggestions": [{"kind": "STYLE", "name": "流行", "confidence": "MEDIUM", "basis": "测试候选非真实歌曲", "needs_review": True}], **changes}


class CatalogPreparationTests(SimpleTestCase):
    def test_lc_m_001_metadata_prefers_embedded_fields_and_measured_duration(self):
        result = normalize_metadata("Other-File.mp3", {"title": " Embedded ", "artist": "Artist", "album": "Album", "duration_100ns": 2573322000})
        self.assertEqual((result["title"], result["artist"], result["album"], result["duration_ms"]), ("Embedded", "Artist", "Album", 257332))
        self.assertEqual(result["metadata_sources"]["duration_ms"], "WINDOWS_MEDIA_PROPERTY")

    def test_lc_m_002_missing_artist_and_duration_are_not_fabricated(self):
        result = normalize_metadata("unknown.mp3", {})
        self.assertEqual(result["artist"], "")
        self.assertIsNone(result["duration_ms"])
        self.assertEqual(len(result["metadata_issues"]), 2)
        fallback = normalize_metadata("Singer-Track-Live.mp3", {"duration_100ns": 10000000})
        self.assertEqual((fallback["artist"], fallback["title"]), ("Singer", "Track-Live"))
        self.assertEqual(fallback["duration_ms"], 1000)

    def test_lc_m_003_tag_suggestions_are_reviewable_not_audio_claims(self):
        for filename in ("Taylor Swift-Love Story.mp3", "忠于你-Fake love(钢琴版).mp3", "unknown.mp3"):
            for tag in suggest_tags(filename):
                self.assertTrue(tag["needs_review"])
                self.assertIn(tag["confidence"], {"LOW", "MEDIUM"})
                self.assertTrue(tag["basis"])
        self.assertEqual(suggest_tags("unknown.mp3"), [])

    def test_lc_m_004_manifest_rejects_traversal_hash_duration_and_unknown_tag(self):
        for changes in ({"filename": "../other.mp3"}, {"filename": "D:\\a.mp3"}, {"sha256": "invalid"}, {"duration_ms": True}, {"duration_ms": -1}, {"tag_suggestions": [{"kind": "BAD", "name": "x"}]}, {"title": "x" * 121}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_catalog({"schema_version": 1, "items": [catalog_item(**changes)]})
        with self.assertRaises(ValidationError):
            validate_catalog({"schema_version": 1, "items": [catalog_item(), catalog_item()]})

    def test_lc_m_005_real_prepared_catalog_matches_audited_fingerprints(self):
        items = load_catalog()
        audit = json.loads((settings.BASE_DIR.parent / "specs/music/system/material-audit.json").read_text(encoding="utf-8"))
        checked = {item["sha256"]: item for item in audit["items"] if "sha256" in item}
        self.assertEqual(len(items), 44)
        self.assertEqual(sum(item["eligible"] for item in items), 40)
        for item in items:
            self.assertEqual(checked[item["sha256"]]["filename"], item["filename"])
            self.assertTrue(1 <= item["duration_ms"] <= 86400000)
            self.assertEqual(item["rights_status"], "UNVERIFIED")


class CatalogImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="catalog_admin", password="TestOnly!73919")
        cls.listener = User.objects.create_user(username="catalog_listener")
        cls.staff = User.objects.create_user(username="catalog_limited", is_staff=True)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/song/local-import/"
        self.items = [catalog_item()]

    def apply(self, *, tags=False, items=None, hashes=None):
        return import_drafts(items=items or self.items, selected_hashes=hashes or ["a" * 64], owner_id=self.admin.id, accept_tags=tags)

    def test_lc_m_006_only_creates_unpublished_metadata_without_media(self):
        with patch("music.media.store_audio") as store:
            result = self.apply()
        self.assertEqual(result, {"created": 1, "skipped": 0})
        song = Song.objects.get()
        for field in ("active", "playback_allowed", "redistribution_allowed"):
            self.assertFalse(getattr(song, field))
        for field in ("file_path", "source_url", "license_name", "license_url"):
            self.assertEqual(getattr(song, field), "")
        self.assertIsNone(song.checked_at)
        self.assertIn("LOCAL_DRAFT_SHA256:", song.source_name)
        self.assertEqual(SongTag.objects.count(), 0)
        self.assertEqual(Tag.objects.count(), 0)
        store.assert_not_called()

    def test_lc_m_007_explicit_candidate_acceptance_creates_links(self):
        self.apply(tags=True)
        self.assertEqual(Tag.objects.get().name, "流行")
        self.assertEqual(SongTag.objects.get().weight, 1)
        self.assertIn("人工辅助候选", Song.objects.get().attribution_text)

    def test_lc_m_008_repeat_deduplicates_without_overwriting_manual_edits(self):
        self.apply(tags=True)
        Song.objects.update(title="Manually edited")
        result = self.apply(tags=True, hashes=["a" * 64, "a" * 64])
        self.assertEqual(result, {"created": 0, "skipped": 1})
        self.assertEqual(Song.objects.get().title, "Manually edited")
        self.assertEqual(SongTag.objects.count(), 1)

    def test_lc_m_009_invalid_selection_or_incomplete_metadata_writes_nothing(self):
        with self.assertRaises(ValidationError):
            self.apply(hashes=["b" * 64])
        with self.assertRaises(ValidationError):
            self.apply(items=[catalog_item(artist="")])
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_010_failure_rolls_back_song_tag_and_membership(self):
        with patch("music.local_catalog.SongTag.objects.get_or_create", side_effect=DatabaseError("injected")):
            with self.assertRaises(DatabaseError):
                self.apply(tags=True)
        self.assertEqual(Song.objects.count(), 0)
        self.assertEqual(Tag.objects.count(), 0)

    def test_lc_m_011_admin_get_displays_preview_but_never_writes(self):
        with patch("music.admin.load_catalog", return_value=validate_catalog({"schema_version": 1, "items": copy.deepcopy(self.items)})):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Song")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "不复制音频")
        self.assertNotContains(response, 'name="accept_tags" value="yes" checked')
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_012_post_requires_csrf_and_explicit_confirmation(self):
        denied = self.client.post(self.url, {"selected": ["a" * 64], "confirm_drafts": "yes"})
        self.assertEqual(denied.status_code, 403)
        with patch("music.admin.load_catalog", return_value=validate_catalog({"schema_version": 1, "items": self.items})):
            response = self.client.get(self.url)
            token = response.cookies["csrftoken"].value
            response = self.client.post(self.url, {"selected": ["a" * 64], "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_013_confirmed_post_imports_and_redirects(self):
        with patch("music.admin.load_catalog", return_value=validate_catalog({"schema_version": 1, "items": self.items})):
            token = self.client.get(self.url).cookies["csrftoken"].value
            response = self.client.post(self.url, {"selected": ["a" * 64], "csrfmiddlewaretoken": token, "confirm_drafts": "yes", "accept_tags": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/music/song/")
        self.assertEqual(Song.objects.count(), 1)
        self.assertEqual(SongTag.objects.count(), 1)

    def test_lc_m_014_nonadmin_or_unprivileged_staff_cannot_import(self):
        for user in (self.listener, self.staff):
            self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertIn(response.status_code, (302, 403))
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_015_unavailable_manifest_and_unknown_selection_are_safe(self):
        with patch("music.admin.load_catalog", side_effect=ValueError("private error")):
            response = self.client.get(self.url)
        self.assertContains(response, "清单不可用")
        self.assertNotContains(response, "private error")
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_016_imported_drafts_never_leak_to_public_catalog(self):
        self.apply(tags=True)
        response = self.client.get("/api/v1/songs/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    def test_lc_m_017_full_prepared_catalog_imports_forty_drafts_and_deduplicates(self):
        items = load_catalog()
        selected = [item["sha256"] for item in items if item["eligible"]]
        result = import_drafts(items=items, selected_hashes=selected, owner_id=self.admin.id, accept_tags=True)
        self.assertEqual(result, {"created": 40, "skipped": 0})
        repeated = import_drafts(items=items, selected_hashes=selected, owner_id=self.admin.id, accept_tags=True)
        self.assertEqual(repeated, {"created": 0, "skipped": 40})
        self.assertEqual(Song.objects.count(), 40)
        self.assertEqual(Song.objects.filter(active=True).count(), 0)
        self.assertEqual(Song.objects.exclude(file_path="").count(), 0)
        self.assertEqual(SongTag.objects.count(), sum(len(item["tag_suggestions"]) for item in items if item["eligible"]))

    def test_lc_m_018_song_editor_cannot_apply_tags_without_tag_permissions(self):
        permissions = Permission.objects.filter(content_type__app_label="music", codename__in=["add_song", "change_song"])
        self.staff.user_permissions.add(*permissions)
        self.client.force_login(self.staff)
        with patch("music.admin.load_catalog", return_value=validate_catalog({"schema_version": 1, "items": self.items})):
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'name="accept_tags"')
            token = response.cookies["csrftoken"].value
            response = self.client.post(self.url, {"selected": ["a" * 64], "csrfmiddlewaretoken": token, "confirm_drafts": "yes", "accept_tags": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Song.objects.count(), 0)

    def test_lc_m_019_later_batch_failure_rolls_back_earlier_song(self):
        items = [catalog_item(), catalog_item(sha256="b" * 64, title="Other")]
        original_create = Song.objects.create
        calls = []

        def create(**fields):
            calls.append(fields)
            if len(calls) == 2:
                raise DatabaseError("injected second row failure")
            return original_create(**fields)

        with patch("music.local_catalog.Song.objects.create", side_effect=create), self.assertRaises(DatabaseError):
            import_drafts(items=items, selected_hashes=["a" * 64, "b" * 64], owner_id=self.admin.id, accept_tags=True)
        self.assertEqual(Song.objects.count(), 0)
        self.assertEqual(Tag.objects.count(), 0)
        self.assertEqual(SongTag.objects.count(), 0)
