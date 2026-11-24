import io
import wave
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase

from music.auto_tag import SAMPLE_RATE, analyze_tags, decode_sample, extract_features, generate_candidates, select_candidates
from music.batch_import import create_batch, execute_batch
from music.local_scanner import read_metadata
from music.models import SongTag, Tag
from music import test_local_scanner as fixtures
from music.test_local_scanner import mp3_bytes


def genre_mp3(genre="Rock"):
    payload = bytes([3]) + genre.encode()
    frame = b"TCON" + len(payload).to_bytes(4, "big") + bytes(2) + payload
    size = bytes([(len(frame) >> shift) & 127 for shift in (21, 14, 7, 0)])
    return b"ID3" + bytes([3, 0, 0]) + size + frame + mp3_bytes()


class AutoTagTests(SimpleTestCase):
    def test_configured_decoder_precedes_path_and_invalid_setting_does_not_fallback(self):
        from music.auto_tag import decoder_path

        with self.settings(LOCAL_IMPORT_FFMPEG="configured.exe"), patch("music.auto_tag.Path.is_file", return_value=True), patch("music.auto_tag.shutil.which") as lookup:
            self.assertEqual(decoder_path(), "configured.exe")
            lookup.assert_not_called()
        with self.settings(LOCAL_IMPORT_FFMPEG="missing.exe"), patch("music.auto_tag.Path.is_file", return_value=False), patch("music.auto_tag.shutil.which") as lookup:
            self.assertIsNone(decoder_path())
            lookup.assert_not_called()
        with self.settings(LOCAL_IMPORT_FFMPEG=""), patch("music.auto_tag.shutil.which", return_value="path-decoder.exe"):
            self.assertEqual(decoder_path(), "path-decoder.exe")

    def test_silence_short_and_invalid_samples_do_not_create_acoustic_tags(self):
        for signal in (np.zeros(SAMPLE_RATE * 6), np.ones(SAMPLE_RATE) * 0.1):
            features = extract_features(signal)
            self.assertNotEqual(features["quality"], "OK")
            self.assertEqual(generate_candidates("歌手-悲伤的约会.mp3", {}, features), [])
        for signal in ([], [float("nan")], [[1, 2]]):
            with self.assertRaises(ValueError):
                extract_features(signal)

    def test_pcm_sample_and_features_are_measured(self):
        times = np.arange(SAMPLE_RATE * 6) / SAMPLE_RATE
        signal = 0.04 * np.sin(2 * np.pi * 440 * times)
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(SAMPLE_RATE)
            audio.writeframes((signal * 32767).astype("<i2").tobytes())
        decoded, source = decode_sample(output.getvalue(), ".wav")
        self.assertEqual(source, "WAV_PCM")
        features = extract_features(decoded)
        self.assertEqual(features["quality"], "OK")
        self.assertAlmostEqual(features["spectral_centroid_hz"], 440, delta=10)
        self.assertLess(features["dbfs"], -22)
        self.assertIsNone(features["vocal_tendency"])
        self.assertIsNone(features["bpm"])
        candidates = generate_candidates("unknown.wav", {}, features)
        self.assertTrue(any(tag["name"] == "助眠" for tag in candidates))
        self.assertTrue(all(tag["confidence"] < 0.75 for tag in candidates))

    def test_periodic_pulses_produce_bounded_bpm_estimate(self):
        signal = np.zeros(SAMPLE_RATE * 12)
        for position in range(0, len(signal) - 300, SAMPLE_RATE // 2):
            signal[position:position + 300] = np.hanning(300) * 0.8
        features = extract_features(signal)
        self.assertIsNotNone(features["bpm"])
        self.assertTrue(60 <= features["bpm"] <= 185)
        self.assertGreater(features["bpm_strength"], 0.25)

    def test_metadata_is_high_filename_is_medium_not_identity_guess(self):
        fields, *_ = read_metadata(genre_mp3(), ".mp3")
        self.assertEqual(fields["genre"], "Rock")
        tags = generate_candidates("歌手-版本Remix.mp3", fields, {})
        self.assertEqual(next(tag["confidence"] for tag in tags if tag["name"] == "摇滚"), 0.85)
        self.assertEqual(next(tag["confidence"] for tag in tags if tag["name"] == "电子"), 0.60)
        self.assertEqual(generate_candidates("A-Lin-天若有情.mp3", {}, {}), [])

    def test_thresholds_formal_vocabulary_deduplication_and_limits(self):
        tags = [dict(kind="STYLE", name=name, confidence=score, source="TEST", basis="测试") for name, score in (("摇滚", 0.55), ("流行", 0.75), ("电子", 0.85), ("爵士", 0.54), ("未知", 0.99), ("电子", 0.6))]
        selected = select_candidates(tags)
        self.assertEqual({tag["name"] for tag in selected}, {"电子", "流行"})
        self.assertTrue(all(not tag["needs_review"] for tag in selected))
        self.assertEqual(len(select_candidates([dict(kind="SCENE", name=name, confidence=0.6) for name in ("清晨", "夜晚", "学习", "工作")])), 2)

    def test_decoder_unavailable_and_timeout_keep_metadata_candidates(self):
        with patch("music.auto_tag.decoder_path", return_value=None):
            result = analyze_tags(genre_mp3(), ".mp3", "Track.mp3", {"genre": "Rock"})
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["features"], {})
        self.assertEqual(result["candidates"][0]["name"], "摇滚")
        import subprocess
        with patch("music.auto_tag.decoder_path", return_value="decoder"), patch("music.auto_tag.subprocess.run", side_effect=subprocess.TimeoutExpired("decoder", 20)):
            self.assertEqual(analyze_tags(b"x", ".mp3", "x.mp3", {})["status"], "UNAVAILABLE")

    def test_genre_unknown_and_emotional_conflicts_not_inferred(self):
        for genre in ("unknown", "(17)", "", "not rock"):
            self.assertEqual(generate_candidates("歌手-夜晚伤感.mp3", {"genre": genre}, {}), [])
        self.assertEqual(generate_candidates("x.mp3", {"genre": "另类/独立"}, {})[0]["name"], "另类/独立")


class AutoTagImportTests(TestCase):
    setUp = fixtures.BatchImportTests.setUp

    def test_candidates_persist_and_only_high_apply_when_enabled(self):
        (self.source / "Singer-Remix.mp3").write_bytes(genre_mp3())
        with patch("music.auto_tag.decoder_path", return_value=None):
            batch = create_batch(self.admin.pk, analyze=True)
        item = next(item for item in batch["items"] if item["extension"] == ".mp3")
        self.assertEqual(item["tag_analysis"]["input_sha256"], item["sha256"])
        self.assertEqual(item["tag_analysis"]["status"], "UNAVAILABLE")
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(list(SongTag.objects.values_list("tag__name", flat=True)), ["摇滚"])
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(SongTag.objects.count(), 1)

    def test_opt_out_and_existing_manual_tags_are_not_changed(self):
        (self.source / "Singer-Track.mp3").write_bytes(genre_mp3())
        batch = create_batch(self.admin.pk, analyze=True)
        execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(SongTag.objects.count(), 0)
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(SongTag.objects.count(), 0)

    def test_inactive_tags_are_not_reactivated(self):
        Tag.objects.create(kind="STYLE", name="摇滚", active=False)
        (self.source / "Singer-Track.mp3").write_bytes(genre_mp3())
        batch = create_batch(self.admin.pk, analyze=True)
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(SongTag.objects.count(), 0)
        self.assertFalse(Tag.objects.get(name="摇滚").active)

    def test_page_displays_analysis_and_explicit_toggle(self):
        (self.source / "Singer-Track.mp3").write_bytes(genre_mp3())
        with patch("music.auto_tag.decoder_path", return_value=None):
            batch = create_batch(self.admin.pk, analyze=True)
        response = self.client.get(self.url, {"batch_id": batch["batch_id"]})
        self.assertContains(response, "摇滚")
        self.assertContains(response, "UNAVAILABLE")
        self.assertContains(response, 'name="accept_high_tags"')

    def test_song_only_staff_cannot_enable_tag_writes(self):
        from django.contrib.auth.models import Permission
        from music.models import User

        staff = User.objects.create_user(username="song_only", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="music", codename__in=["add_song", "change_song"]))
        self.client.force_login(staff)
        batch = create_batch(staff.pk)
        response = self.client.get(self.url, {"batch_id": batch["batch_id"]})
        self.assertNotContains(response, 'name="accept_high_tags"')
        token = response.cookies["csrftoken"].value
        response = self.client.post(self.url, dict(action="import", batch_id=batch["batch_id"], confirm_import="yes", accept_high_tags="yes", csrfmiddlewaretoken=token))
        self.assertEqual(response.status_code, 403)
        with self.assertRaises(ValueError):
            execute_batch(batch["batch_id"], staff.pk, accept_high_tags=True)
