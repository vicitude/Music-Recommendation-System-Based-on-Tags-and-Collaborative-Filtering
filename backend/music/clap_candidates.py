import json
import math
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from music.auto_tag import decoder_path
from music.local_scanner import _hash_file, safe_source


MODEL_ID = "laion/clap-htsat-fused"
REVISION = "365dea6ef167def6676140ed93bbc43f84dabb28"
POLICY_VERSION = "clap-conservative-v1"
PROMPTS_VERSION = "clap-prompts-v2"
MAPPING_VERSION = "formal53-clap19-v1"
SUPPORTED = {("STYLE", name) for name in ("流行", "摇滚", "电子", "民谣", "古典", "爵士", "嘻哈说唱", "R&B", "金属", "乡村", "蓝调", "雷鬼", "放克", "拉丁音乐")} | {("MOOD", name) for name in ("活力", "平静", "放松", "欢快", "悲伤")}


def validate_result(document, items):
    expected = dict(model_id=MODEL_ID, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION)
    if not isinstance(document, dict) or any(document.get(key) != value for key, value in expected.items()):
        raise ValueError("模型结果版本无效")
    results = document.get("results")
    if not isinstance(results, list) or len(results) != len(items):
        raise ValueError("模型结果数量无效")
    for result, item in zip(results, items):
        if not isinstance(result, dict) or result.get("input_sha256") != item["sha256"] or result.get("status") not in {"CANDIDATES", "REJECTED", "FAILED"}:
            raise ValueError("模型结果指纹或状态无效")
        segments = result.get("segments")
        if not isinstance(segments, list) or len(segments) > 3:
            raise ValueError("片段数量无效")
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("quality") not in {"OK", "TOO_SHORT", "SILENCE", "TONAL_CONTROL"}:
                raise ValueError("片段质量无效")
            for key in ("start_seconds", "sample_seconds"):
                value = segment.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= item["duration_ms"] / 1000 + 1:
                    raise ValueError("片段位置无效")
            scores = segment.get("scores")
            if not isinstance(scores, list) or len(scores) != (41 if segment["quality"] == "OK" else 0) or any(type(value) not in (int, float) or not math.isfinite(value) or not -1.001 <= value <= 1.001 for value in scores):
                raise ValueError("片段分数无效")
            if segment["sample_seconds"] > 10.1 or segment["start_seconds"] + segment["sample_seconds"] > item["duration_ms"] / 1000 + 1:
                raise ValueError("片段采样范围无效")
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) > 2 or (bool(candidates) != (result["status"] == "CANDIDATES")):
            raise ValueError("模型候选状态无效")
        kinds = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or (candidate.get("kind"), candidate.get("name")) not in SUPPORTED or candidate["kind"] in kinds:
                raise ValueError("模型候选标签无效")
            kinds.add(candidate["kind"])
            if candidate.get("needs_review") is not True or candidate.get("auto_apply") is not False or candidate.get("score_type") != "cosine_similarity" or "confidence" in candidate:
                raise ValueError("模型候选禁止自动写入")
            for key in ("score", "gap"):
                value = candidate.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("模型候选分数无效")
            support = candidate.get("support_segments")
            if not isinstance(support, list) or not 2 <= len(support) <= 3 or any(type(value) not in (int, float) or not math.isfinite(value) for value in support):
                raise ValueError("模型支持片段无效")
            valid_starts = {segment["start_seconds"] for segment in segments if segment["quality"] == "OK" and segment["sample_seconds"] >= 5}
            if len(set(support)) != len(support) or not set(support).issubset(valid_starts) or any(abs(first - second) < 10 for position, first in enumerate(support) for second in support[position + 1:]):
                raise ValueError("模型支持片段重复或不足")
            if candidate["score"] < 0.30 or candidate["gap"] < (0.04 if candidate["kind"] == "STYLE" else 0.05):
                raise ValueError("模型候选不足筛选阈值")
        reasons = result.get("reasons")
        if not isinstance(reasons, list) or len(reasons) > 5 or any(not isinstance(reason, str) or len(reason) > 500 for reason in reasons):
            raise ValueError("拒识原因无效")
    return results


def run_analysis(items, *, minimum=False):
    executable = Path(getattr(settings, "LOCAL_IMPORT_CLAP_PYTHON", Path.home() / "AppData/Local/MusicRecommenderAI/clap-venv/Scripts/python.exe"))
    home = Path(getattr(settings, "LOCAL_IMPORT_CLAP_HOME", settings.BASE_DIR.parent / "local-ai"))
    ffmpeg = decoder_path()
    if not executable.is_file() or not ffmpeg or not (home / "models/clap-htsat-fused/model.safetensors").is_file():
        raise ValueError("独立CLAP环境、模型或FFmpeg不可用")
    payload = json.dumps(dict(home=str(home), ffmpeg=ffmpeg, items=items)).encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("模型请求过大")
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
    worker = "clap_minimum_batch.py" if minimum else "clap_batch.py"
    process = subprocess.run([str(executable), "-B", str(settings.BASE_DIR.parent / "tools" / worker)], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=True, env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if len(process.stdout) > 1024 * 1024:
        raise ValueError("模型输出过大")
    validator = validate_result
    if minimum:
        from music.minimum_candidates import validate_result as validator
    return validator(json.loads(process.stdout.decode("utf-8")), items)


def analyze_batch(batch_id, owner_id, selected_hashes, *, minimum=False):
    from music.batch_import import _source_lock, load_batch, save_batch, source_root

    root = source_root()
    with _source_lock(root):
        batch = load_batch(batch_id, owner_id)
        if batch["source_root"] != str(root):
            raise ValueError("素材目录改变，请重新扫描")
        selected = list(dict.fromkeys(selected_hashes))
        if not 1 <= len(selected) <= 5:
            raise ValueError("请选择1至5首歌曲进行模型分析")
        indexed = {item.get("sha256"): item for item in batch["items"] if item.get("status") in {"READY", "NEEDS_METADATA"}}
        if any(fingerprint not in indexed for fingerprint in selected):
            raise ValueError("歌曲不可分析，请重新扫描")
        inputs = []
        for fingerprint in selected:
            item = indexed[fingerprint]
            path = safe_source(root, item["relative_path"])
            actual, size = _hash_file(path)
            if actual != fingerprint or size != item["bytes"]:
                raise ValueError("源文件已改变，请重新扫描")
            inputs.append(dict(path=str(path), sha256=fingerprint, duration_ms=item["duration_ms"], extension=item["extension"]))
        try:
            results = run_analysis(inputs, minimum=True) if minimum else run_analysis(inputs)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            results = [dict(input_sha256=item["sha256"], status="UNAVAILABLE", segments=[], candidates=[], reasons=["模型不可用、超时或结果校验失败；原有导入不受影响"]) for item in inputs]
        for request, result in zip(inputs, results):
            item = indexed[request["sha256"]]
            try:
                actual, size = _hash_file(safe_source(root, item["relative_path"]))
            except (OSError, ValueError, RuntimeError):
                actual, size = None, None
            if actual != item["sha256"] or size != item["bytes"]:
                result = dict(input_sha256=item["sha256"], status="FAILED", segments=[], candidates=[], reasons=["分析期间源文件改变，请重新扫描"])
            versions = dict(model_id=MODEL_ID, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION)
            if minimum:
                from music.minimum_candidates import VERSIONS
                versions = VERSIONS
            item["minimum_analysis" if minimum else "model_analysis"] = {**result, **versions, "analyzed_at": timezone.now().isoformat(), "auto_apply": False}
            if minimum:
                item.pop("candidate_edit", None)
        save_batch(batch)
        return batch
