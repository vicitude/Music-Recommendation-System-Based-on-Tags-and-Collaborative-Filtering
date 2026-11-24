import copy
import io
import wave
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase

from music.minimum_candidates import VERSIONS, confirmed_candidates, decide_minimum, internal_starts, texts, validate_result
from music.batch_import import create_batch, execute_batch, load_batch, save_batch
from music.clap_candidates import analyze_batch
from music.models import Song, SongTag, Tag, User
from music import test_local_scanner as fixtures


def analysis(item):
    scores = [0.1] * len(texts())
    scores[0:2] = [0.25, 0.26]
    scores[-3:] = [0, 0, 0]
    segments = [dict(start_seconds=start, sample_seconds=10.0, quality="OK", scores=list(scores)) for start in internal_starts(item["duration_ms"])]
    candidates, reasons = decide_minimum(segments)
    return dict(input_sha256=item["sha256"], status="CANDIDATES", segments=segments, candidates=candidates, reasons=reasons)


class MinimumValidationTests(SimpleTestCase):
    def test_recomputation_rejects_tampered_candidates_positions_or_version(self):
        item = dict(sha256="a" * 64, duration_ms=60000)
        result = analysis(item)
        self.assertEqual(validate_result(dict(VERSIONS, results=[result]), [item]), [result])
        for field in ("candidate", "position", "score", "version", "duration"):
            document = dict(VERSIONS, results=[copy.deepcopy(result)])
            if field == "candidate":
                document["results"][0]["candidates"][0]["name"] = "摇滚"
            elif field == "position":
                document["results"][0]["segments"][0]["start_seconds"] = 0
            elif field == "score":
                document["results"][0]["segments"][0]["scores"][0] = float("nan")
            elif field == "duration":
                document["results"][0]["segments"][0]["sample_seconds"] = 1
            else:
                document["policy_version"] = "old"
            with self.assertRaises(ValueError):
                validate_result(document, [item])


class MinimumBatchTests(TestCase):
    def setUp(self):
        fixtures.BatchImportTests.setUp(self)
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(bytes(8000 * 60 * 2))
        (self.source / "Singer-Song.wav").write_bytes(output.getvalue())

    def prepared(self):
        batch = create_batch(self.admin.pk)
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items, **kwargs: [analysis(item) for item in items]):
            return analyze_batch(batch["batch_id"], self.admin.pk, [batch["items"][0]["sha256"]], minimum=True)

    def test_confirmation_saves_three_kinds_and_sources_only_for_new_song(self):
        batch = self.prepared()
        self.assertEqual(Song.objects.count(), 0)
        page = self.client.get(self.url, {"batch_id": batch["batch_id"]})
        self.assertContains(page, "★低把握补位")
        self.assertContains(page, "使用建议")
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["created"], 1)
        self.assertEqual(set(SongTag.objects.values_list("tag__kind", flat=True)), {"STYLE", "MOOD", "SCENE"})
        self.assertTrue(all(candidate["evidence_level"] == "LOW_FALLBACK" for candidate in result["results"][0]["applied_tags"]))
        song = Song.objects.get()
        self.assertFalse(song.active)
        SongTag.objects.filter(song=song).delete()
        manual = Tag.objects.create(kind="STYLE", name="人工修改")
        SongTag.objects.create(song=song, tag=manual)
        second = create_batch(self.admin.pk)
        execute_batch(second["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(Song.objects.count(), 1)
        self.assertEqual(SongTag.objects.get(song=song).tag_id, manual.pk)

    def test_missing_analysis_fails_before_audio_copy_but_plain_draft_still_allowed(self):
        batch = create_batch(self.admin.pk)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)
        self.assertFalse(self.media.exists())
        execute_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(Song.objects.count(), 1)

    def test_direct_import_publish_and_recovery_without_overwriting_existing(self):
        from music.batch_import import recent_batches
        batch = self.prepared()
        self.assertEqual(recent_batches(self.admin.pk)[0]["analyzed"], 1)
        self.assertEqual(recent_batches(self.other.pk), [])
        page = self.client.get(self.url)
        self.assertContains(page, batch["batch_id"])
        token = page.cookies["csrftoken"].value
        response = self.client.post(self.url, {"csrfmiddlewaretoken": token, "action": "import_publish", "batch_id": batch["batch_id"], "confirm_import": "yes"})
        self.assertEqual(response.status_code, 302)
        song = Song.objects.get()
        self.assertTrue(song.active)
        self.assertTrue(song.playback_allowed)
        original = song.checked_at
        self.assertEqual(load_batch(batch["batch_id"], self.admin.pk)["results"][0]["message"], "已导入并发布到前台")
        execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True, publish=True)
        song.refresh_from_db()
        self.assertEqual(song.checked_at, original)
        self.assertEqual(Song.objects.count(), 1)

    def test_direct_publish_missing_analysis_and_invalid_audio_leave_no_song(self):
        batch = create_batch(self.admin.pk)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True, publish=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)
        batch = self.prepared()
        with patch("music.publishing.publish_song", side_effect=ValueError("发布校验失败")):
            result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True, publish=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)

    def test_tampered_or_disabled_candidate_fails_without_creation(self):
        batch = self.prepared()
        candidate = batch["items"][0]["minimum_analysis"]["candidates"][0]
        Tag.objects.create(kind=candidate["kind"], name=candidate["name"], active=False)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)
        self.assertFalse(self.media.exists())
        batch["items"][0]["minimum_analysis"]["candidates"][0]["name"] = "摇滚"
        save_batch(batch)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["failed"], 1)

    def test_model_action_csrf_owner_and_import_confirmation_permissions(self):
        batch = create_batch(self.admin.pk)
        fields = dict(action="minimum_analyze", batch_id=batch["batch_id"], model_selected=[batch["items"][0]["sha256"]])
        self.assertEqual(self.client.post(self.url, fields).status_code, 403)
        page = self.client.get(self.url)
        fields["csrfmiddlewaretoken"] = page.cookies["csrftoken"].value
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items, **kwargs: [analysis(item) for item in items]):
            self.assertEqual(self.client.post(self.url, fields).status_code, 302)
        with self.assertRaises(ValueError):
            analyze_batch(batch["batch_id"], self.other.pk, fields["model_selected"], minimum=True)
        staff = User.objects.create_user(username="minimum_limited", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="music", codename__in=["add_song", "change_song"]))
        with self.assertRaises(ValueError):
            execute_batch(batch["batch_id"], staff.pk, accept_model_tags=True)
        self.client.force_login(staff)
        token = self.client.get(self.url).cookies["csrftoken"].value
        self.assertEqual(self.client.post(self.url, dict(action="import", batch_id=batch["batch_id"], confirm_import="yes", accept_model_tags="yes", csrfmiddlewaretoken=token)).status_code, 403)
        self.assertEqual(Song.objects.count(), 0)

    def test_json_chunk_csrf_owner_and_explicit_failures(self):
        batch = create_batch(self.admin.pk)
        fields = dict(action="minimum_analyze_chunk", batch_id=batch["batch_id"], model_selected=[batch["items"][0]["sha256"]])
        self.assertEqual(self.client.post(self.url, fields).status_code, 403)
        page = self.client.get(self.url, {"batch_id": batch["batch_id"]})
        for text in ("全选可分析歌曲", "取消选择", "data-progress-status", "data-analysis-form", "batch-import.js"):
            self.assertContains(page, text)
        fields["csrfmiddlewaretoken"] = page.cookies["csrftoken"].value
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items, **kwargs: [analysis(item) for item in items]):
            response = self.client.post(self.url, fields)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["analysis"]["status"], "CANDIDATES")
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        response = self.client.post(self.url, {**fields, "model_selected": ["not-in-batch"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.client.force_login(self.other)
        token = self.client.get(self.url).cookies["csrftoken"].value
        response = self.client.post(self.url, {**fields, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Song.objects.count(), 0)

    def test_json_chunk_keeps_server_limit_five(self):
        batch = create_batch(self.admin.pk)
        token = self.client.get(self.url).cookies["csrftoken"].value
        response = self.client.post(self.url, dict(action="minimum_analyze_chunk", batch_id=batch["batch_id"], model_selected=[str(index) for index in range(6)], csrfmiddlewaretoken=token))
        self.assertEqual(response.status_code, 400)
        self.assertIn("1至5", response.json()["error"])

    def edit_values(self):
        return [str(Tag.objects.get_or_create(kind=kind, name=name)[0].pk) for kind, name in ((Tag.STYLE, "摇滚"), (Tag.MOOD, "欢快"), (Tag.SCENE, "运动"))]

    def test_manual_candidate_edit_persists_and_import_uses_it(self):
        from music.candidate_edits import save_candidate_edit
        batch = self.prepared()
        item = batch["items"][0]
        original = copy.deepcopy(item["minimum_analysis"])
        values = self.edit_values()
        page = self.client.get(self.url, {"batch_id": batch["batch_id"], "edit": item["sha256"]})
        self.assertContains(page, "保存候选标签修改")
        token = page.cookies["csrftoken"].value
        fields = dict(action="save_candidate_edit", batch_id=batch["batch_id"], fingerprint=item["sha256"], tag_ids=values)
        self.assertEqual(self.client.post(self.url, fields).status_code, 403)
        self.assertEqual(self.client.post(self.url, {**fields, "csrfmiddlewaretoken": token}).status_code, 302)
        saved = load_batch(batch["batch_id"], self.admin.pk)
        self.assertEqual(saved["items"][0]["minimum_analysis"], original)
        self.assertContains(self.client.get(self.url, {"batch_id": batch["batch_id"]}), "人工已调整")
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True, publish=True)
        self.assertEqual(result["result_summary"]["created"], 1)
        self.assertEqual(set(SongTag.objects.values_list("tag_id", flat=True)), set(map(int, values)))
        self.assertTrue(all(tag["evidence_level"] == "MANUAL_EDIT" for tag in result["results"][0]["applied_tags"]))
        self.assertTrue(Song.objects.get().active)
        relations = set(SongTag.objects.values_list("tag_id", flat=True))
        alternative = Tag.objects.create(kind=Tag.MOOD, name="平静")
        save_candidate_edit(batch["batch_id"], self.admin.pk, item["sha256"], [values[0], str(alternative.pk), values[2]])
        execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(set(SongTag.objects.values_list("tag_id", flat=True)), relations)
        with self.assertRaises(ValueError):
            save_candidate_edit(batch["batch_id"], self.other.pk, item["sha256"], values)
        staff = User.objects.create_user(username="candidate_limited", is_staff=True)
        staff.user_permissions.add(*Permission.objects.filter(content_type__app_label="music", codename__in=["add_song", "change_song"]))
        self.client.force_login(staff)
        token = self.client.get(self.url).cookies["csrftoken"].value
        self.assertEqual(self.client.post(self.url, {**fields, "csrfmiddlewaretoken": token}).status_code, 403)

    def test_manual_edit_invalid_selections_never_save_and_disabled_blocks_import(self):
        from music.candidate_edits import save_candidate_edit
        batch = self.prepared()
        fingerprint = batch["items"][0]["sha256"]
        values = self.edit_values()
        for invalid in ([], values[:2], values + [values[0]], ["999999999"], ["bad"], values + [str(Tag.objects.create(kind=Tag.STYLE, name="测试曲风").pk), str(Tag.objects.create(kind=Tag.STYLE, name="测试曲风2").pk)]):
            with self.assertRaises(ValueError):
                save_candidate_edit(batch["batch_id"], self.admin.pk, fingerprint, invalid)
            self.assertNotIn("candidate_edit", load_batch(batch["batch_id"], self.admin.pk)["items"][0])
        with self.assertRaises(ValueError):
            save_candidate_edit(batch["batch_id"], self.admin.pk, "unknown", values)
        save_candidate_edit(batch["batch_id"], self.admin.pk, fingerprint, values)
        Tag.objects.filter(pk=int(values[0])).update(active=False)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)

    def test_manual_edit_reanalysis_clears_edit_and_model_tamper_still_rejected(self):
        from music.candidate_edits import save_candidate_edit
        batch = self.prepared()
        fingerprint = batch["items"][0]["sha256"]
        values = self.edit_values()
        save_candidate_edit(batch["batch_id"], self.admin.pk, fingerprint, values)
        with patch("music.clap_candidates.run_analysis", side_effect=lambda items, **kwargs: [analysis(item) for item in items]):
            refreshed = analyze_batch(batch["batch_id"], self.admin.pk, [fingerprint], minimum=True)
        self.assertNotIn("candidate_edit", refreshed["items"][0])
        saved = save_candidate_edit(batch["batch_id"], self.admin.pk, fingerprint, values)
        saved["items"][0]["minimum_analysis"]["candidates"][0]["name"] = "伪造"
        save_batch(saved)
        result = execute_batch(batch["batch_id"], self.admin.pk, accept_model_tags=True)
        self.assertEqual(result["result_summary"]["failed"], 1)
        self.assertEqual(Song.objects.count(), 0)
