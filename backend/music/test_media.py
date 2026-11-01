import io
import itertools
import json
import wave
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import RequestFactory, TestCase
from django.utils import timezone
from django.utils.datastructures import MultiValueDict
from rest_framework.test import APIClient

from music.admin import SongAdmin, TagAdmin
from music.api.errors import ApiError
from music.forms import SongAdminForm, TagAdminForm
from music.media import MAX_AUDIO_BYTES, inspect_audio, media_response, resolve_media, store_audio
from music.models import Song, Tag, User


def wav_bytes(frames=8000, channels=1, width=2, rate=8000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b"\x00" * frames * channels * width)
    return output.getvalue()


class MediaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="media_listener")
        cls.staff = User.objects.create_superuser(username="media_admin", password="Test!Only-7391")
        cls.song = Song.objects.create(
            title="Synthetic WAV", artist="TEST_ONLY", duration_ms=1000, mime="audio/wav",
            file_path="songs/synthetic.wav", active=True, playback_allowed=True,
            checked_at=timezone.now() - timedelta(minutes=1),
            source_name="IN_MEMORY_TEST", source_url="https://example.org/source",
            license_name="NOT_A_REAL_LICENSE", license_url="https://example.org/license",
        )

    def setUp(self):
        self.audio = wav_bytes()
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        self.admin = SongAdmin(Song, AdminSite())
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.staff

    def form_data(self, **changes):
        data = {
            "title": "Synthetic", "artist": "TEST_ONLY", "album": "", "duration_ms": 1000,
            "mime": "audio/wav", "active": True, "source_name": "IN_MEMORY_TEST",
            "source_url": "https://example.org/source", "license_name": "TEST_ONLY",
            "license_url": "https://example.org/license", "attribution_text": "",
            "checked_at": timezone.now() - timedelta(minutes=1), "playback_allowed": True,
            "redistribution_allowed": False, "rights_confirmed": True, "preview_confirmed": False,
        }
        return {**data, **changes}

    def upload_form(self, *, content=None, filename="test.wav", instance=None, **changes):
        upload = SimpleUploadedFile(filename, self.audio if content is None else content, content_type="application/octet-stream")
        return SongAdminForm(data=self.form_data(**changes), files={"upload": upload}, instance=instance)

    def stream(self, range_value=None):
        headers = {} if range_value is None else {"HTTP_RANGE": range_value}
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.stat", return_value=SimpleNamespace(st_size=len(self.audio))), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(self.audio)):
            response = self.client.get(f"/api/v1/songs/{self.song.id}/stream/", **headers)
            body = b"".join(response.streaming_content) if response.streaming else response.content
            response.close()
        return response, body

    def test_wav_inspection_computes_duration_from_actual_frames(self):
        self.assertEqual(inspect_audio(self.audio, "TRACK.WAV"), ("audio/wav", 1000))
        self.assertEqual(inspect_audio(wav_bytes(frames=1), "short.wav"), ("audio/wav", 1))

    def test_tc_m_017_rejects_empty_unknown_extension_and_type_conflict(self):
        for data, name in [(b"", "empty.wav"), (self.audio, "bad.exe"), (self.audio, "wrong.mp3"), (b"ID3", "bad.mp3")]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                inspect_audio(data, name)

    def test_tc_m_017_rejects_truncated_and_inconsistent_wav(self):
        truncated = self.audio[:-2]
        adjusted = truncated[:4] + (len(truncated) - 8).to_bytes(4, "little") + truncated[8:]
        for data in [self.audio[:-1], adjusted, b"RIFF" + b"\x00" * 20]:
            with self.assertRaises(ValidationError):
                inspect_audio(data, "bad.wav")

    def test_wav_parameter_limits_and_zero_frames(self):
        for data in [wav_bytes(frames=0), wav_bytes(channels=3), wav_bytes(rate=4000), wav_bytes(rate=200000)]:
            with self.assertRaises(ValidationError):
                inspect_audio(data, "unsupported.wav")

    def test_mp3_frame_header_structure_and_id3_boundary(self):
        header = b"\xff\xfb\x90\x00"
        self.assertEqual(inspect_audio(header, "header.mp3"), ("audio/mpeg", None))
        tagged = b"ID3\x04\x00\x00\x00\x00\x00\x03abc" + header
        self.assertEqual(inspect_audio(tagged, "tagged.mp3"), ("audio/mpeg", None))
        for data in [b"ID3\x04\x00\x00\x00\x00\x00\x7f" + header, b"ID3\x04\x00\x00\x80\x00\x00\x00" + header, b"\xff\xeb\x90\x00", b"\xff\xf9\x90\x00", b"\xff\xfb\x00\x00", b"\xff\xfb\xfc\x00", b"\xff\xfb\x9c\x00"]:
            with self.assertRaises(ValidationError):
                inspect_audio(data, "bad.mp3")

    def test_ogg_bos_version_and_page_bounds(self):
        page = b"OggS" + bytes([0, 2]) + b"\x00" * 20 + bytes([1, 3]) + b"abc"
        self.assertEqual(inspect_audio(page, "audio.ogg"), ("audio/ogg", None))
        for data in [page[:-1], page[:4] + bytes([1]) + page[5:], page[:5] + bytes([0]) + page[6:], b"OggS"]:
            with self.assertRaises(ValidationError):
                inspect_audio(data, "bad.ogg")

    def test_public_stream_full_and_range_payloads(self):
        for header, status, expected in [(None, 200, self.audio), ("bytes=0-99", 206, self.audio[:100]), ("bytes=100-", 206, self.audio[100:]), ("bytes=-25", 206, self.audio[-25:]), ("bytes=20-999999", 206, self.audio[20:])]:
            with self.subTest(header=header):
                response, body = self.stream(header)
                self.assertEqual(response.status_code, status)
                self.assertEqual(body, expected)
                self.assertEqual(response["Content-Length"], str(len(expected)))
                self.assertEqual(response["Accept-Ranges"], "bytes")
                self.assertEqual(response["Cache-Control"], "private,no-store")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertEqual(response["Content-Type"], "audio/wav")
                self.assertEqual(response["X-Spec-Version"], "v0.1.0")

    def test_416_has_no_json_or_audio_and_reports_total_size(self):
        for header in ["bytes=999999-", "bytes=10-1", "bytes=-0", "bytes=-", "bytes=0-1,3-4", "items=0-2", "bytes=+1-2", "bytes= 0-2", "x" * 101]:
            response, body = self.stream(header)
            self.assertEqual(response.status_code, 416, header)
            self.assertEqual(body, b"")
            self.assertEqual(response["Content-Length"], "0")
            self.assertEqual(response["Content-Range"], f"bytes */{len(self.audio)}")

    def test_stream_permission_precedes_range_parsing(self):
        Song.objects.filter(id=self.song.id).update(playback_allowed=False)
        response, body = self.stream("not-a-range")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(body)["error_code"], "PERMISSION_DENIED")
        Song.objects.filter(id=self.song.id).update(active=False)
        response, body = self.stream("not-a-range")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(body)["error_code"], "NOT_FOUND")

    def test_stream_requires_login_and_logout_blocks_new_requests(self):
        self.assertEqual(self.stream()[0].status_code, 200)
        self.client.logout()
        response, body = self.stream()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(body)["error_code"], "AUTH_REQUIRED")

    def test_missing_unchecked_or_unsafe_file_is_not_streamed(self):
        Song.objects.filter(id=self.song.id).update(checked_at=None)
        self.assertEqual(self.stream()[0].status_code, 403)
        Song.objects.filter(id=self.song.id).update(checked_at=timezone.now(), file_path="../outside.wav")
        self.assertEqual(self.stream()[0].status_code, 503)
        Song.objects.filter(id=self.song.id).update(file_path="songs/missing.wav")
        with patch("pathlib.Path.is_file", return_value=False):
            response = self.client.get(f"/api/v1/songs/{self.song.id}/stream/")
        self.assertEqual(response.status_code, 503)

    def test_stream_rejects_query_and_undefined_head_method(self):
        response = self.client.get(f"/api/v1/songs/{self.song.id}/stream/?file_path=outside")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.head(f"/api/v1/songs/{self.song.id}/stream/").status_code, 405)

    def test_open_failure_is_controlled_and_resource_closed_on_response_close(self):
        with patch("pathlib.Path.open", side_effect=OSError("INJECTED")):
            with self.assertRaises(Exception) as raised:
                media_response(path=Path("unused.wav"), mime="audio/wav", range_header=None)
        self.assertEqual(raised.exception.error_code, "MEDIA_UNAVAILABLE")
        audio = io.BytesIO(self.audio)
        with patch("pathlib.Path.open", return_value=audio):
            response = media_response(path=Path("unused.wav"), mime="audio/wav", range_header=None)
        response.close()
        self.assertTrue(audio.closed)

    def test_valid_wav_publish_form_requires_explicit_human_rights(self):
        form = self.upload_form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.audio_data, self.audio)
        form = self.upload_form(rights_confirmed=False)
        self.assertFalse(form.is_valid())
        self.assertIn("active", form.errors)

    def test_pt_m_009_all_publish_guard_combinations(self):
        for has_file, rights, playback, checked, duration in itertools.product([False, True], repeat=5):
            data = self.form_data(rights_confirmed=rights, playback_allowed=playback, checked_at=timezone.now() if checked else None, duration_ms=1000 if duration else 0)
            files = {"upload": SimpleUploadedFile("test.wav", self.audio)} if has_file else None
            form = SongAdminForm(data=data, files=files)
            self.assertEqual(form.is_valid(), all([has_file, rights, playback, checked, duration]), (has_file, rights, playback, checked, duration, form.errors))

    def test_draft_can_save_without_file_but_cannot_publish(self):
        form = SongAdminForm(data=self.form_data(active=False, checked_at=None, rights_confirmed=False, playback_allowed=False))
        self.assertTrue(form.is_valid(), form.errors)
        form = SongAdminForm(data=self.form_data())
        self.assertFalse(form.is_valid())
        self.assertIn("upload", form.errors)

    def test_form_rejects_zero_length_oversize_and_multiple_uploads(self):
        self.assertFalse(self.upload_form(content=b"").is_valid())
        upload = SimpleUploadedFile("test.wav", self.audio)
        upload.size = MAX_AUDIO_BYTES + 1
        form = SongAdminForm(data=self.form_data(), files={"upload": upload})
        self.assertFalse(form.is_valid())
        files = MultiValueDict({"upload": [SimpleUploadedFile("a.wav", self.audio), SimpleUploadedFile("b.wav", self.audio)]})
        form = SongAdminForm(data=self.form_data(), files=files)
        self.assertFalse(form.is_valid())

    def test_form_rejects_mime_mismatch_and_wav_duration_difference(self):
        self.assertFalse(self.upload_form(mime="audio/mpeg").is_valid())
        self.assertFalse(self.upload_form(duration_ms=2001).is_valid())
        self.assertTrue(self.upload_form(duration_ms=2000).is_valid())

    def test_tc_m_018_mp3_and_ogg_require_draft_then_preview(self):
        samples = [(b"\xff\xfb\x90\x00", "sample.mp3", "audio/mpeg"), (b"OggS" + bytes([0, 2]) + b"\x00" * 20 + bytes([1, 3]) + b"abc", "sample.ogg", "audio/ogg")]
        for content, name, mime in samples:
            self.assertFalse(self.upload_form(content=content, filename=name, mime=mime, preview_confirmed=True).is_valid())
            form = self.upload_form(content=content, filename=name, mime=mime, active=False)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertIsNone(form.cleaned_data["checked_at"])
            song = Song.objects.get(id=self.song.id)
            song.file_path = "songs/" + name
            song.mime = mime
            with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(content)):
                form = SongAdminForm(data=self.form_data(mime=mime), instance=song)
                self.assertFalse(form.is_valid())
                form = SongAdminForm(data=self.form_data(mime=mime, preview_confirmed=True), instance=song)
                self.assertTrue(form.is_valid(), form.errors)

    def test_form_rejects_future_verification_and_non_http_sources(self):
        self.assertFalse(self.upload_form(checked_at=timezone.now() + timedelta(hours=1)).is_valid())
        for field in ["source_url", "license_url"]:
            self.assertFalse(self.upload_form(**{field: "ftp://example.org/file"}).is_valid())

    def test_file_path_post_cannot_override_existing_storage(self):
        song = Song.objects.get(id=self.song.id)
        with patch("pathlib.Path.is_file", return_value=True):
            form = SongAdminForm(data=self.form_data(active=False, file_path="C:/outside.wav"), instance=song)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save(commit=False).file_path, "songs/synthetic.wav")
            self.assertNotIn("file_path", form.fields)

    def test_storage_uses_exclusive_uuid_path_and_never_user_filename(self):
        opened = []

        class RetainedBytes(io.BytesIO):
            def close(self):
                self.contents = self.getvalue()

        def capture(path, mode):
            handle = RetainedBytes()
            opened.append((path, mode, handle))
            return handle

        with patch.object(Path, "mkdir"), patch.object(Path, "open", capture):
            stored = store_audio(data=self.audio, extension=".wav")
        self.assertRegex(stored, r"^songs/[0-9a-f]{32}\.wav$")
        self.assertEqual(opened[0][1], "xb")
        self.assertEqual(opened[0][2].contents, self.audio)

    def test_storage_rejects_root_escape_without_writing(self):
        root = Path(settings.MEDIA_ROOT).resolve()
        with patch.object(Path, "resolve", side_effect=[root, root.parent / "escaped"]):
            with patch.object(Path, "open") as opened:
                with self.assertRaises(ValidationError):
                    store_audio(data=self.audio, extension=".wav")
                opened.assert_not_called()

    def test_admin_save_requires_staff_model_permission(self):
        form = self.upload_form()
        self.assertTrue(form.is_valid())
        self.request.user = self.user
        with patch("music.admin.store_audio") as store:
            with self.assertRaises(PermissionDenied):
                self.admin.save_model(self.request, form.save(commit=False), form, False)
            store.assert_not_called()

    def test_admin_save_persists_validated_new_path_and_preserves_old_file(self):
        form = self.upload_form(instance=Song.objects.get(id=self.song.id))
        self.assertTrue(form.is_valid(), form.errors)
        with patch("music.admin.store_audio", return_value="songs/new-uuid.wav") as store:
            self.admin.save_model(self.request, form.save(commit=False), form, True)
        store.assert_called_once()
        self.assertEqual(Song.objects.get(id=self.song.id).file_path, "songs/new-uuid.wav")
        self.assertFalse(self.admin.has_delete_permission(self.request, self.song))

    def test_database_failure_logs_orphan_without_deleting_media(self):
        form = self.upload_form()
        self.assertTrue(form.is_valid())
        with patch("music.admin.store_audio", return_value="songs/orphan.wav"), patch.object(Song, "save", side_effect=DatabaseError("INJECTED")):
            with self.assertLogs("music.admin", level="ERROR") as logs:
                with self.assertRaises(DatabaseError):
                    self.admin.save_model(self.request, form.save(commit=False), form, False)
        self.assertIn("songs/orphan.wav", "".join(logs.output))

    def test_admin_preview_permission_and_controlled_draft_playback(self):
        Song.objects.filter(id=self.song.id).update(active=False, checked_at=None, playback_allowed=False)
        self.request.user = self.user
        with self.assertRaises(PermissionDenied):
            self.admin.preview_audio(self.request, self.song.id)
        self.request.user = self.staff
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(self.audio)):
            response = self.admin.preview_audio(self.request, self.song.id)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), self.audio)
            response.close()
        self.assertIn("audio controls", str(self.admin.preview(self.song)))

    def test_tag_admin_trims_names_and_disallows_deletion(self):
        form = TagAdminForm(data={"name": " 治愈 ", "kind": "MOOD", "active": True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "治愈")
        self.assertFalse(TagAdminForm(data={"name": " ", "kind": "MOOD"}).is_valid())
        self.assertFalse(TagAdmin(Tag, AdminSite()).has_delete_permission(self.request))

    def test_admin_add_and_change_pages_render_safe_fields(self):
        self.client.force_login(self.staff)
        for url in ["/admin/music/song/add/", f"/admin/music/song/{self.song.id}/change/", "/admin/music/tag/add/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
        response = self.client.get(f"/admin/music/song/{self.song.id}/change/")
        self.assertContains(response, 'type="file"')
        self.assertContains(response, "rights_confirmed")
        self.assertContains(response, "preview_confirmed")
        self.assertNotContains(response, 'name="file_path"')

    def test_admin_preview_route_rejects_non_staff(self):
        response = self.client.get(f"/admin/music/song/{self.song.id}/preview/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/media/songs/synthetic.wav").status_code, 404)

    def test_staff_without_model_permission_cannot_preview_or_upload(self):
        User.objects.filter(id=self.user.id).update(is_staff=True)
        self.user.refresh_from_db()
        self.request.user = self.user
        with self.assertRaises(PermissionDenied):
            self.admin.preview_audio(self.request, self.song.id)
        form = self.upload_form()
        self.assertTrue(form.is_valid())
        with self.assertRaises(PermissionDenied):
            self.admin.save_model(self.request, form.save(commit=False), form, False)

    def test_existing_file_is_preserved_when_no_upload_is_submitted(self):
        instance = Song.objects.get(id=self.song.id)
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.open", side_effect=lambda *args, **kwargs: io.BytesIO(self.audio)):
            form = SongAdminForm(data=self.form_data(), instance=instance)
            self.assertTrue(form.is_valid(), form.errors)
        with patch("music.admin.store_audio") as store:
            self.admin.save_model(self.request, form.save(commit=False), form, True)
            store.assert_not_called()
        self.assertEqual(Song.objects.get(id=instance.id).file_path, "songs/synthetic.wav")

    def test_existing_unsafe_path_is_rejected_by_form(self):
        instance = Song.objects.get(id=self.song.id)
        instance.file_path = "../outside.wav"
        form = SongAdminForm(data=self.form_data(active=False), instance=instance)
        self.assertFalse(form.is_valid())
        with self.assertRaises(ValidationError):
            form.clean_file_path()

    def test_wav_altered_to_non_pcm_is_rejected(self):
        invalid = self.audio[:20] + b"\x06\x00" + self.audio[22:]
        with self.assertRaises(ValidationError):
            inspect_audio(invalid, "non-pcm.wav")

    def test_id3_footer_and_reserved_version_checks(self):
        frame = b"\xff\xfb\x90\x00"
        tagged = b"ID3\x04\x00\x10\x00\x00\x00\x00" + b"3DI\x04\x00\x10\x00\x00\x00\x00" + frame
        self.assertEqual(inspect_audio(tagged, "footer.mp3"), ("audio/mpeg", None))
        for version in [0, 1, 5, 255]:
            with self.assertRaises(ValidationError):
                inspect_audio(b"ID3" + bytes([version, 0, 0, 0, 0, 0, 0]) + frame, "invalid.mp3")

    def test_byte_limit_accepts_thirty_mib_and_rejects_one_extra_byte(self):
        data = b"\xff\xfb\x90\x00" + b"\x00" * (MAX_AUDIO_BYTES - 4)
        self.assertEqual(inspect_audio(data, "limit.mp3"), ("audio/mpeg", None))
        with self.assertRaises(ValidationError):
            inspect_audio(data + b"\x00", "too-big.mp3")

    def test_resolve_denies_inactive_user_and_invalid_mime_or_size(self):
        User.objects.filter(id=self.user.id).update(is_active=False)
        with self.assertRaises(ApiError) as raised:
            resolve_media(song_id=self.song.id, user_id=self.user.id)
        self.assertEqual(raised.exception.error_code, "AUTH_REQUIRED")
        User.objects.filter(id=self.user.id).update(is_active=True)
        for size in [0, MAX_AUDIO_BYTES + 1]:
            with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.stat", return_value=SimpleNamespace(st_size=size)):
                with self.assertRaises(ApiError) as raised:
                    resolve_media(song_id=self.song.id, user_id=self.user.id)
                self.assertEqual(raised.exception.error_code, "MEDIA_UNAVAILABLE")

    def test_range_exact_headers_and_oversized_suffix(self):
        response, body = self.stream("bytes=0-99")
        self.assertEqual(response["Content-Range"], f"bytes 0-99/{len(self.audio)}")
        response, body = self.stream("bytes=-999999")
        self.assertEqual(body, self.audio)
        self.assertEqual(response.status_code, 206)

    def test_stream_stops_at_requested_range_and_closes_on_iteration(self):
        audio = io.BytesIO(self.audio)
        with patch.object(Path, "open", return_value=audio):
            response = media_response(path=Path("unused.wav"), mime="audio/wav", range_header="bytes=5-12")
        self.assertEqual(b"".join(response.streaming_content), self.audio[5:13])
        self.assertTrue(audio.closed)

    def test_post_upload_content_type_is_not_trusted(self):
        upload = SimpleUploadedFile("test.wav", self.audio, content_type="text/html")
        form = SongAdminForm(data=self.form_data(), files={"upload": upload})
        self.assertTrue(form.is_valid(), form.errors)
