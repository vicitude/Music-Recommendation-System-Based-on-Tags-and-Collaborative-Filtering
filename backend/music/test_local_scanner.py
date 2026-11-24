import hashlib
import io
import struct
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, SimpleTestCase, TestCase

from music.batch_import import create_batch, execute_batch, load_batch
from music.local_scanner import read_metadata, safe_source, scan_local_catalog
from music.models import Song, SongTag, User


def mp3_bytes():
    return b"\xff\xfb\x90\x00" + bytes(413) + b"\xff\xfb\xb0\x00" + bytes(622)


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(bytes(16000))
    return output.getvalue()


def ogg_bytes():
    identity = b"\x01vorbis" + struct.pack("<IBI", 0, 1, 48000) + bytes(14)
    comments = b"\x03vorbis" + struct.pack("<II", 0, 0) + b"\x01"
    def page(packet, sequence, flags, granule):
        return b"OggS" + bytes([0, flags]) + struct.pack("<QIII", granule, 1, sequence, 0) + bytes([1, len(packet)]) + packet
    return page(identity, 0, 2, 0) + page(comments, 1, 0, 0) + page(b"audio", 2, 4, 48000)


class LocalScannerTests(SimpleTestCase):
    def test_scan_three_formats_and_missing_metadata(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for extension, data in (("mp3", mp3_bytes()), ("wav", wav_bytes()), ("ogg", ogg_bytes())):
                (root / ("Artist-Track." + extension)).write_bytes(data)
            (root / "unknown.mp3").write_bytes(mp3_bytes() + bytes(1))
            result = scan_local_catalog(root)
            self.assertEqual(result["summary"]["eligible"], 3)
            unknown = next(item for item in result["items"] if item["filename"] == "unknown.mp3")
            self.assertEqual(unknown["status"], "NEEDS_METADATA")
            self.assertEqual(unknown["tag_suggestions"], [])
            for item in result["items"]:
                if item["eligible"]:
                    self.assertEqual((item["artist"], item["title"]), ("Artist", "Track"))

    def test_mp3_vbr_duration_counts_frames_not_first_bitrate(self):
        fields, duration, source, cover, mime = read_metadata(mp3_bytes(), ".mp3")
        self.assertEqual(duration, 52)
        self.assertEqual(source, "MPEG_FRAME_COUNT")
        self.assertEqual(mime, "audio/mpeg")
        self.assertFalse(cover)

    def test_id3_versions_encoding_and_cover(self):
        for version in (3, 4):
            title = bytes([3]) + "嵌入歌名".encode()
            size = len(title).to_bytes(4, "big")
            frame = b"TIT2" + size + bytes(2) + title
            cover = b"APIC" + (1).to_bytes(4, "big") + bytes(2) + b"x"
            artist = bytes([1]) + "歌手".encode("utf-16")
            frame += b"TPE1" + len(artist).to_bytes(4, "big") + bytes(2) + artist + cover
            tag_size = bytes([(len(frame) >> shift) & 127 for shift in (21, 14, 7, 0)])
            fields, duration, _, detected, _ = read_metadata(b"ID3" + bytes([version, 0, 0]) + tag_size + frame + mp3_bytes(), ".mp3")
            self.assertEqual(fields["title"], "嵌入歌名")
            self.assertEqual(fields["artist"], "歌手")
            self.assertTrue(detected)
            self.assertEqual(duration, 52)

    def test_reports_unsupported_corrupt_empty_and_ignores_lyrics(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in (("song.flac", b"flac"), ("empty.mp3", b""), ("bad.mp3", b"invalid"), ("song.lrc", b"lyrics")):
                (root / name).write_bytes(data)
            result = scan_local_catalog(root)
            self.assertEqual(result["summary"]["scanned"], 3)
            self.assertEqual(result["skipped"][0]["status"], "UNSUPPORTED_FORMAT")
            self.assertTrue(all(item["status"] == "FAILED" for item in result["items"]))

    def test_duplicates_and_existing_hashes_and_repeatability(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "A-One.mp3").write_bytes(mp3_bytes())
            nested = root / "nested"
            nested.mkdir()
            (nested / "B-Two.MP3").write_bytes(mp3_bytes())
            first = scan_local_catalog(root)
            self.assertEqual(first, scan_local_catalog(root))
            self.assertEqual(first["summary"]["duplicates"], 1)
            self.assertEqual(first["items"][1]["relative_path"], "nested/B-Two.MP3")
            fingerprint = hashlib.sha256(mp3_bytes()).hexdigest()
            result = scan_local_catalog(root, existing_hashes=[fingerprint])
            self.assertEqual(result["summary"]["eligible"], 0)

    def test_limits_and_invalid_roots(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("A-One.mp3", "B-Two.mp3"):
                (root / name).write_bytes(mp3_bytes())
            result = scan_local_catalog(root, max_items=1)
            self.assertTrue(result["truncated"])
            self.assertEqual(len(result["items"]), 1)
            for value in (0, 501, True):
                with self.assertRaises(ValueError):
                    scan_local_catalog(root, max_items=value)
            with self.assertRaises(ValueError):
                scan_local_catalog(root / "missing")

    def test_rejects_unsafe_relative_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for value in ("../outside.mp3", "D:/outside.mp3", "/outside.mp3", "file.mp3:stream"):
                with self.assertRaises((ValueError, OSError)):
                    safe_source(root, value)
            (root / "A-One.mp3").write_bytes(mp3_bytes())
            with patch("music.local_scanner._is_link", return_value=True):
                self.assertEqual(scan_local_catalog(root)["items"][0]["status"], "FAILED")

    def test_large_unreadable_and_truncated_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "A-One.mp3").write_bytes(mp3_bytes())
            with patch("music.local_scanner.MAX_AUDIO_BYTES", 10):
                self.assertEqual(scan_local_catalog(root)["items"][0]["status"], "FAILED")
            with patch("music.local_scanner._hash_file", side_effect=PermissionError):
                self.assertEqual(scan_local_catalog(root)["items"][0]["status"], "FAILED")
        for extension, data in ((".mp3", mp3_bytes()[:-12]), (".wav", wav_bytes()[:-2]), (".ogg", ogg_bytes()[:-2])):
            with self.assertRaises((ValueError, ValidationError)):
                read_metadata(data, extension)


class BatchImportTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.source = base / "source"
        self.source.mkdir()
        self.media = base / "media"
        self.reports = base / "reports"
        self.override = self.settings(LOCAL_IMPORT_SOURCE_ROOT=self.source, LOCAL_IMPORT_BATCH_ROOT=self.reports, MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.admin = User.objects.create_superuser(username="batch_admin", password="TestOnly!729183")
        self.other = User.objects.create_superuser(username="batch_other", password="TestOnly!729183")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.admin)
        self.url = "/admin/music/song/batch-import/"
        (self.source / "Singer-Song.wav").write_bytes(wav_bytes())

    def test_scan_no_song_or_media_and_owner_bound_report(self):
        batch = create_batch(self.admin.pk)
        self.assertEqual(Song.objects.count(), 0)
        self.assertFalse(self.media.exists())
        self.assertEqual(load_batch(batch["batch_id"], self.admin.pk), batch)
        with self.assertRaises(ValueError):
            load_batch(batch["batch_id"], self.other.pk)
        with self.assertRaises(ValueError):
            load_batch("../invalid", self.admin.pk)

    def test_confirmed_import_three_formats_preserves_source_and_idempotent(self):
        (self.source / "Artist-Mp3.mp3").write_bytes(mp3_bytes())
        (self.source / "Artist-Ogg.ogg").write_bytes(ogg_bytes())
        original = {path.name: path.read_bytes() for path in self.source.iterdir()}
        batch = create_batch(self.admin.pk)
        result = execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(result["result_summary"], {"created": 3, "skipped": 0, "failed": 0})
        execute_batch(batch["batch_id"], self.admin.pk)
        again = create_batch(self.admin.pk)
        self.assertEqual(execute_batch(again["batch_id"], self.admin.pk)["result_summary"]["skipped"], 3)
        self.assertEqual(Song.objects.count(), 3)
        self.assertEqual(len(list((self.media / "songs").iterdir())), 3)
        self.assertEqual(SongTag.objects.count(), 0)
        self.assertEqual(original, {path.name: path.read_bytes() for path in self.source.iterdir()})
        for song in Song.objects.all():
            self.assertFalse(song.active or song.playback_allowed or song.redistribution_allowed)
            self.assertIsNone(song.checked_at)
            self.assertEqual(song.license_name, "")

    def test_changed_file_fails_then_retry_succeeds(self):
        batch = create_batch(self.admin.pk)
        path = self.source / "Singer-Song.wav"
        original = path.read_bytes()
        path.write_bytes(original[:-2])
        result = execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)
        path.write_bytes(original)
        result = execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(result["result_summary"]["created"], 1)

    def test_per_song_failure_and_unassociated_copy_recorded(self):
        (self.source / "A-Mp3.mp3").write_bytes(mp3_bytes())
        batch = create_batch(self.admin.pk)
        create = Song.objects.create
        calls = []
        def failing_create(**fields):
            calls.append(fields)
            if len(calls) == 1:
                raise DatabaseError("private failure")
            return create(**fields)
        with patch("music.batch_import.Song.objects.create", side_effect=failing_create):
            result = execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(result["result_summary"], {"created": 1, "skipped": 0, "failed": 1})
        failed = next(entry for entry in result["results"] if entry["status"] == "failed")
        self.assertIn("unassociated_media", failed)
        self.assertNotIn("private failure", failed["message"])
        result = execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(result["result_summary"]["created"], 2)

    def test_admin_csrf_confirmation_permissions_and_owner(self):
        self.assertEqual(self.client.post(self.url, {"action": "scan"}).status_code, 403)
        page = self.client.get(self.url)
        self.assertContains(page, "扫描本地素材目录")
        token = page.cookies["csrftoken"].value
        response = self.client.post(self.url, {"action": "scan", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Song.objects.count(), 0)
        batch_id = response["Location"].split("batch_id=")[1]
        response = self.client.post(self.url, {"action": "import", "batch_id": batch_id, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url, {"action": "import", "batch_id": batch_id, "confirm_import": "yes", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Song.objects.count(), 1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url, {"batch_id": batch_id}).status_code, 400)
        staff = User.objects.create_user(username="batch_limited", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_overlapping_paths_rejected(self):
        with self.settings(MEDIA_ROOT=self.source / "media"):
            with self.assertRaises(ValueError):
                create_batch(self.admin.pk)
        with self.settings(LOCAL_IMPORT_BATCH_ROOT=self.source / "reports"):
            with self.assertRaises(ValueError):
                create_batch(self.admin.pk)
        self.assertFalse((self.source / "reports").exists())

    def test_source_lock_rejects_parallel_execution_without_changes(self):
        from music.batch_import import _source_lock

        batch = create_batch(self.admin.pk)
        with _source_lock(self.source.resolve()):
            with self.assertRaises(ValueError):
                execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(Song.objects.count(), 0)
        self.assertFalse(self.media.exists())

    def test_source_configuration_change_rejects_old_batch(self):
        batch = create_batch(self.admin.pk)
        another = self.source.parent / "another"
        another.mkdir()
        with self.settings(LOCAL_IMPORT_SOURCE_ROOT=another):
            with self.assertRaises(ValueError):
                execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(Song.objects.count(), 0)
