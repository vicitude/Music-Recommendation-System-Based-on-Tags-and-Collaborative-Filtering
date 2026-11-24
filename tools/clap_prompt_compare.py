import argparse
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path

from clap_diagnose import diagnose_dimensions
from clap_policy import LABELS, MAPPING_VERSION, POLICY_VERSION, PROMPTS_VERSION, REVISION, decide_candidates, prompt_texts, segment_starts


GENRES = ("pop", "rock", "electronic dance", "folk", "classical", "jazz", "hip hop", "rhythm and blues", "heavy metal", "country", "blues", "reggae", "funk", "Latin")
TOLERANCE = 0.0001


def comparison_prompts():
    texts = prompt_texts()
    for index, genre in enumerate(GENRES):
        texts[index * 2:index * 2 + 2] = [f"This is a recording of {genre} music.", f"The music genre is {genre}."]
    return texts


def validate_baseline(report):
    expected = dict(completed=True, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION, prompts=prompt_texts(), random_seed=42)
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("Baseline version or completion mismatch")
    selected = [item for item in report["scan"]["items"] if item.get("status") in {"READY", "NEEDS_METADATA"}]
    if len(selected) != 40 or len(report["results"]) != 40:
        raise ValueError("Expected the fixed 40-song baseline")
    for item, record in zip(selected, report["results"]):
        result = record["analysis"]
        if record["filename"] != item["relative_path"] or result["input_sha256"] != item["sha256"] or result["status"] not in {"CANDIDATES", "REJECTED"}:
            raise ValueError("Baseline identity mismatch")
        segments = result["segments"]
        if [segment["start_seconds"] for segment in segments] != segment_starts(item["duration_ms"]) or len(segments) != 3 or any(segment["quality"] != "OK" or len(segment["scores"]) != 41 for segment in segments):
            raise ValueError("Baseline segment mismatch")
    return selected


def score_delta(left, right):
    if len(left) != len(right):
        raise ValueError("Segment count mismatch")
    differences = []
    for before, after in zip(left, right):
        if any(before[key] != after[key] for key in ("start_seconds", "sample_seconds", "quality")) or len(before["scores"]) != len(after["scores"]):
            raise ValueError("Segment metadata or score count mismatch")
        differences.extend(abs(first - second) for first, second in zip(before["scores"], after["scores"]))
    return max(differences, default=0)


def summarize(records, key):
    results = [record[key] for record in records]
    summary = dict(songs=len(results), songs_with_candidates=sum(bool(result["candidates"]) for result in results), dimensions={})
    for kind in ("STYLE", "MOOD"):
        dimensions = [diagnose_dimensions(result)[kind] for result in results]
        counts = Counter(candidate["name"] for result in results for candidate in result["candidates"] if candidate["kind"] == kind)
        summary["dimensions"][kind] = dict(candidates=dict(counts), prompt_agreement=sum(sum(dimension["prompt_agreement"]) for dimension in dimensions), segment_count=sum(len(dimension["prompt_agreement"]) for dimension in dimensions), unanimous_songs=sum(dimension["same_top_count"] == 3 for dimension in dimensions), failures=dict(Counter(failure for dimension in dimensions for failure in dimension["failures"])))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Offline paired prompt comparison; no database or tag writes")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    if not args.output.resolve().is_relative_to(workspace / "local-ai" / "diagnostics") or args.output.exists():
        parser.error("Use a new report inside ignored local-ai/diagnostics")
    baseline_bytes = args.baseline.read_bytes()
    baseline = json.loads(baseline_bytes)
    selected = validate_baseline(baseline)
    import numpy as np
    import torch
    from clap_batch import ClapModel, ClapProcessor, analyze_item, signal_quality, verify_weights

    directory = workspace / "local-ai" / "models" / "clap-htsat-fused"
    manifest = verify_weights(directory)
    if manifest["revision"] != REVISION or manifest["model_id"] != "laion/clap-htsat-fused":
        raise ValueError("Model mismatch")
    torch.set_num_threads(4)
    processor = ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        embeddings = []
        for prompts in (prompt_texts(), comparison_prompts()):
            inputs = processor(text=prompts, return_tensors="pt", padding=True)
            embeddings.append(torch.nn.functional.normalize(model.get_text_features(**inputs), dim=-1))
        embeddings[1][28:] = embeddings[0][28:]

    class CaptureAudio:
        def __init__(self):
            self.features = []

        def get_audio_features(self, **inputs):
            features = model.get_audio_features(**inputs)
            self.features.append(torch.nn.functional.normalize(features, dim=-1))
            return features

    controls = dict(silence=signal_quality(np.zeros(480000, dtype=np.float32), 48000), tone=signal_quality(np.sin(2 * np.pi * 440 * np.arange(480000) / 48000).astype(np.float32), 48000))
    if controls != dict(silence="SILENCE", tone="TONAL_CONTROL"):
        raise ValueError("Signal control failed")
    report = dict(completed=False, purpose="PROMPT_SENSITIVITY_NOT_ACCURACY", revision=REVISION, policy_version=POLICY_VERSION, mapping_version=MAPPING_VERSION, baseline_prompts_version=PROMPTS_VERSION, experiment_prompts_version="style-symmetric-v1", baseline_sha256=hashlib.sha256(baseline_bytes).hexdigest(), original_prompts=prompt_texts(), experiment_prompts=comparison_prompts(), tolerance=TOLERANCE, random_seed=42, cpu_threads=4, controls=controls, results=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temporary = args.output.with_name("temp_" + args.output.name)
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, args.output)

    save()
    started = time.monotonic()
    root = Path(baseline["scan"]["source_root"]).resolve(strict=True)
    for item, previous in zip(selected, baseline["results"]):
        if time.monotonic() - started > 1200:
            raise TimeoutError("Comparison time limit")
        path = root / item["relative_path"]
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or path.stat().st_size != item["bytes"]:
            raise ValueError("Source location or size changed")
        capture = CaptureAudio()
        original = analyze_item(dict(path=str(path), sha256=item["sha256"], duration_ms=item["duration_ms"], extension=item["extension"]), capture, processor, embeddings[0], args.ffmpeg)
        if original["status"] not in {"CANDIDATES", "REJECTED"} or len(capture.features) != 3:
            raise ValueError("Audio analysis failed or changed quality")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Source changed after analysis")
        delta = score_delta(previous["analysis"]["segments"], original["segments"])
        variant = dict(input_sha256=item["sha256"], segments=[])
        for segment, features in zip(original["segments"], capture.features):
            with torch.inference_mode():
                scores = [round(value, 7) for value in (features @ embeddings[1].T)[0].tolist()]
            if scores[28:] != segment["scores"][28:]:
                raise ValueError("Unchanged mood/control scores differ")
            variant["segments"].append(dict(segment, scores=scores))
        candidates, reasons = decide_candidates(variant["segments"])
        variant.update(status="CANDIDATES" if candidates else "REJECTED", candidates=candidates, reasons=reasons)
        report["results"].append(dict(filename=item["relative_path"], input_sha256=item["sha256"], original=original, variant=variant, baseline_max_abs_delta=delta))
        save()
        print(f"Completed {len(report['results'])}/40; baseline delta {delta:.7f}", flush=True)
    report.update(completed=True, elapsed_seconds=round(time.monotonic() - started, 3), original_summary=summarize(report["results"], "original"), variant_summary=summarize(report["results"], "variant"))
    report["baseline_max_abs_delta"] = max(record["baseline_max_abs_delta"] for record in report["results"])
    report["reproduction_passed"] = report["baseline_max_abs_delta"] <= TOLERANCE
    save()
    if not report["reproduction_passed"]:
        raise ValueError("Historical baseline reproduction gate failed; inspect report")


if __name__ == "__main__":
    main()
