import json
import math
import sys
from pathlib import Path

from django.conf import settings


TOOLS_DIRECTORY = str(Path(__file__).resolve().parents[2] / "tools")
if TOOLS_DIRECTORY not in sys.path:
    sys.path.insert(0, TOOLS_DIRECTORY)

from clap_minimum import VERSION, decide_minimum
from clap_multilabel import texts
from clap_sampling_compare import internal_starts
from music.clap_candidates import MODEL_ID, REVISION


VERSIONS = dict(model_id=MODEL_ID, revision=REVISION, policy_version=VERSION, prompts_version="multilabel-neutral-v1", mapping_version="formal53-multilabel29-v1")


def validate_result(document, items):
    if not isinstance(document, dict) or any(document.get(key) != value for key, value in VERSIONS.items()):
        raise ValueError("多标签模型版本不符")
    results = document.get("results")
    if not isinstance(results, list) or len(results) != len(items):
        raise ValueError("多标签结果数量不符")
    for result, item in zip(results, items):
        if not isinstance(result, dict) or result.get("input_sha256") != item["sha256"] or result.get("status") not in {"CANDIDATES", "REJECTED", "FAILED"}:
            raise ValueError("多标签结果身份无效")
        segments = result.get("segments")
        if not isinstance(segments, list) or len(segments) > 3:
            raise ValueError("多标签片段数量无效")
        starts = internal_starts(item["duration_ms"])
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict) or segment.get("quality") not in {"OK", "TOO_SHORT", "SILENCE", "TONAL_CONTROL"} or segment.get("start_seconds") != starts[index]:
                raise ValueError("多标签取样无效")
            seconds = segment.get("sample_seconds")
            if type(seconds) not in (float, int) or not math.isfinite(seconds) or not 0 <= seconds <= 10.1 or segment["start_seconds"] + seconds > item["duration_ms"] / 1000 + 1:
                raise ValueError("多标签时长无效")
            if segment["quality"] == "OK" and seconds < 5:
                raise ValueError("有效片段不足5秒")
            scores = segment.get("scores")
            if not isinstance(scores, list) or len(scores) != (len(texts()) if segment["quality"] == "OK" else 0) or any(type(value) not in (int, float) or not math.isfinite(value) or not -1.001 <= value <= 1.001 for value in scores):
                raise ValueError("多标签分数无效")
        candidates, reasons = decide_minimum(segments)
        if result.get("status") == "FAILED":
            if result.get("candidates") != []:
                raise ValueError("失败不得输出标签")
        elif result.get("candidates") != candidates or result.get("reasons") != reasons or result["status"] != ("CANDIDATES" if candidates else "REJECTED"):
            raise ValueError("候选与原始分数复算不一致")
    return results


def confirmed_candidates(item):
    analysis = item.get("minimum_analysis", {})
    if analysis.get("status") != "CANDIDATES":
        raise ValueError("请先完成该歌曲多标签分析")
    validate_result({**analysis, "results": [analysis]}, [item])
    return analysis["candidates"]
