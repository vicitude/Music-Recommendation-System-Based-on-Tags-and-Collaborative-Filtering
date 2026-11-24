import copy
import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from music import test_local_scanner as fixtures
from music.batch_import import create_batch, execute_batch, load_batch
from music.clap_candidates import MAPPING_VERSION, MODEL_ID, POLICY_VERSION, PROMPTS_VERSION, REVISION, analyze_batch, run_analysis, validate_result
from music.models import Song, SongTag


def rejected(item):
    return dict(input_sha256=item["sha256"], status="REJECTED", segments=[], candidates=[], reasons=["证据不足"])


def document(result):
    return dict(model_id=MODEL_ID, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION, results=[result])


class ResultValidationTests(SimpleTestCase):
    def test_subprocess_is_offline_bounded_and_validates_json(self):
        import json
        from types import SimpleNamespace

        item = dict(sha256="a" * 64, duration_ms=30000)
        payload = json.dumps(document(rejected(item))).encode()
        with patch("music.clap_candidates.Path.is_file", return_value=True), patch("music.clap_candidates.decoder_path", return_value="decoder"), patch("music.clap_candidates.subprocess.run", return_value=SimpleNamespace(stdout=payload)) as runner:
            self.assertEqual(run_analysis([item])[0]["status"], "REJECTED")
        options = runner.call_args.kwargs
        self.assertEqual(options["timeout"], 180)
        self.assertEqual(options["env"]["HF_HUB_OFFLINE"], "1")
        self.assertTrue(options["check"])
        with patch("music.clap_candidates.Path.is_file", return_value=True), patch("music.clap_candidates.decoder_path", return_value="decoder"), patch("music.clap_candidates.subprocess.run", return_value=SimpleNamespace(stdout=b"not-json")):
            with self.assertRaises(ValueError):
                run_analysis([item])

    def test_valid_rejection_and_invalid_versions_fingerprints_numbers(self):
        item = dict(sha256="a" * 64, duration_ms=30000)
        result = rejected(item)
        self.assertEqual(validate_result(document(result), [item]), [result])
        for changes in ({"revision": "wrong"}, {"results": []}, {"results": [dict(result, input_sha256="b" * 64)]}):
            with self.assertRaises(ValueError):
                validate_result({**document(result), **changes}, [item])
        broken = dict(result, segments=[dict(start_seconds=0, sample_seconds=10, quality="OK", scores=[float("nan")] * 41)])
        with self.assertRaises(ValueError):
            validate_result(document(broken), [item])

    def test_model_output_cannot_enable_writes_or_unknown_labels(self):
        item = dict(sha256="a" * 64, duration_ms=30000)
        segments = [dict(start_seconds=start, sample_seconds=10, quality="OK", scores=[0.1] * 41) for start in (0, 20)]
        candidate = dict(kind="STYLE", name="摇滚", score=0.5, gap=0.1, score_type="cosine_similarity", support_segments=[0, 20], needs_review=True, auto_apply=False)
        result = dict(input_sha256=item["sha256"], status="CANDIDATES", segments=segments, candidates=[candidate], reasons=[])
        validate_result(document(result), [item])
        for changes in ({"auto_apply": True}, {"name": "未支持"}, {"confidence": 0.99}, {"score": float("inf")}, {"support_segments": [0, 0]}):
            broken = copy.deepcopy(result)
            broken["candidates"][0].update(changes)
            with self.assertRaises(ValueError):
                validate_result(document(broken), [item])


class BatchModelTests(TestCase):
    setUp = fixtures.BatchImportTests.setUp

    def batch(self):
        return create_batch(self.admin.pk)

    def test_model_report_saved_without_song_writes_and_old_candidates_unchanged(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items: [rejected(item) for item in items]):
            result = analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint])
        self.assertEqual(result["items"][0]["model_analysis"]["status"], "REJECTED")
        self.assertEqual(result["items"][0]["tag_suggestions"], [])
        self.assertEqual(Song.objects.count(), 0)
        self.assertFalse(self.media.exists())
        self.assertEqual(load_batch(batch["batch_id"], self.admin.pk), result)

    def test_owner_unknown_selection_limits_and_file_changes_are_rejected(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        for owner, hashes in ((self.other.pk, [fingerprint]), (self.admin.pk, []), (self.admin.pk, ["x"]), (self.admin.pk, [str(index) for index in range(6)])):
            with self.assertRaises(ValueError):
                analyze_batch(batch["batch_id"], owner, hashes)
        (self.source / "Singer-Song.wav").write_bytes(b"changed")
        with patch("music.clap_candidates.run_analysis") as runner, self.assertRaises(ValueError):
            analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint])
        runner.assert_not_called()

    def test_model_timeout_degrades_without_blocking_import(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        with patch("music.clap_candidates.run_analysis", side_effect=subprocess.TimeoutExpired("model", 180)):
            result = analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint])
        self.assertEqual(result["items"][0]["model_analysis"]["status"], "UNAVAILABLE")
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(Song.objects.count(), 1)
        self.assertEqual(SongTag.objects.count(), 0)

    def test_during_analysis_file_change_discards_candidates(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        def change(items):
            (self.source / "Singer-Song.wav").write_bytes(b"changed")
            return [rejected(items[0])]
        with patch("music.clap_candidates.run_analysis", side_effect=change):
            result = analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint])
        self.assertEqual(result["items"][0]["model_analysis"]["status"], "FAILED")

    def test_admin_post_csrf_and_owner_bound_page(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        fields = dict(action="model_analyze", batch_id=batch["batch_id"], model_selected=[fingerprint])
        self.assertEqual(self.client.post(self.url, fields).status_code, 403)
        response = self.client.get(self.url, {"batch_id": batch["batch_id"]})
        self.assertContains(response, "分析所选歌曲（仅生成候选）")
        fields["csrfmiddlewaretoken"] = response.cookies["csrftoken"].value
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items: [rejected(item) for item in items]):
            response = self.client.post(self.url, fields)
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response["Location"]), "证据不足")
        self.assertEqual(SongTag.objects.count(), 0)

    def test_even_model_candidates_never_enter_formal_tag_write_route(self):
        batch = self.batch()
        fingerprint = batch["items"][0]["sha256"]
        result = dict(input_sha256=fingerprint, status="CANDIDATES", segments=[], candidates=[dict(kind="STYLE", name="摇滚", score=0.99, needs_review=True, auto_apply=False)], reasons=[])
        with patch("music.clap_candidates.run_analysis", return_value=[result]):
            analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint])
        execute_batch(batch["batch_id"], self.admin.pk, accept_high_tags=True)
        self.assertEqual(Song.objects.count(), 1)
        self.assertEqual(SongTag.objects.count(), 0)
