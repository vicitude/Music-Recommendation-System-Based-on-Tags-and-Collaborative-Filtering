import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from clap_policy import MAPPING_VERSION, MODEL_ID, POLICY_VERSION, PROMPTS_VERSION, REVISION, prompt_texts
from clap_prompt_compare import TOLERANCE, score_delta, summarize, validate_baseline


def internal_starts(duration_ms):
    if type(duration_ms) is not int or not 20000 <= duration_ms <= 86400000:
        raise ValueError("Invalid duration")
    last = duration_ms / 1000 - 10
    starts = [round(last * fraction, 3) for fraction in (0.2, 0.5, 0.8)]
    if any(after - before < 10 for before, after in zip(starts, starts[1:])):
        raise ValueError("Internal segments would overlap")
    return starts


def supervise(args):
    log_path = args.output.with_suffix(".log")
    if args.output.exists() or log_path.exists():
        raise ValueError("Use new report and log filenames")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", "--baseline", str(args.baseline), "--output", str(args.output), "--ffmpeg", args.ffmpeg]
    with log_path.open("xb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = last_progress = time.monotonic()
        size = 0
        try:
            while process.poll() is None:
                time.sleep(2)
                current = log_path.stat().st_size
                if current != size:
                    size, last_progress = current, time.monotonic()
                if time.monotonic() - started > 1200 or time.monotonic() - last_progress > 180:
                    raise TimeoutError("Total or no-progress timeout")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode:
            raise RuntimeError(f"Comparison failed; inspect {log_path}")


def run(args, workspace):
    baseline_bytes = args.baseline.read_bytes()
    baseline = json.loads(baseline_bytes)
    selected = validate_baseline(baseline)
    for item in selected:
        internal_starts(item["duration_ms"])
    import numpy as np
    import torch
    import clap_batch

    directory = workspace / "local-ai/models/clap-htsat-fused"
    manifest = clap_batch.verify_weights(directory)
    if manifest["revision"] != REVISION or manifest["model_id"] != MODEL_ID:
        raise ValueError("Model mismatch")
    torch.set_num_threads(4)
    processor = clap_batch.ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = clap_batch.ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        inputs = processor(text=prompt_texts(), return_tensors="pt", padding=True)
        embeddings = torch.nn.functional.normalize(model.get_text_features(**inputs), dim=-1)
    controls = dict(silence=clap_batch.signal_quality(np.zeros(480000, dtype=np.float32), 48000), tone=clap_batch.signal_quality(np.sin(2 * np.pi * 440 * np.arange(480000) / 48000).astype(np.float32), 48000))
    if controls != dict(silence="SILENCE", tone="TONAL_CONTROL"):
        raise ValueError("Signal controls failed")
    report = dict(completed=False, purpose="SAMPLING_SENSITIVITY_NOT_ACCURACY", model_id=MODEL_ID, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION, prompts=prompt_texts(), baseline_sha256=hashlib.sha256(baseline_bytes).hexdigest(), random_seed=42, cpu_threads=4, tolerance=TOLERANCE, sampling_version="internal20-50-80-v1", controls=controls, results=[])

    def save():
        temporary = args.output.with_name("temp_" + args.output.name)
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, args.output)

    save()
    root = Path(baseline["scan"]["source_root"]).resolve(strict=True)
    started = time.monotonic()
    production_starts = clap_batch.segment_starts
    for item, previous in zip(selected, baseline["results"]):
        path = root / item["relative_path"]
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root) or path.stat().st_size != item["bytes"]:
            raise ValueError("Source path or size changed")
        inputs = dict(path=str(path), sha256=item["sha256"], duration_ms=item["duration_ms"], extension=item["extension"])
        original = clap_batch.analyze_item(inputs, model, processor, embeddings, args.ffmpeg)
        try:
            clap_batch.segment_starts = internal_starts
            variant = clap_batch.analyze_item(inputs, model, processor, embeddings, args.ffmpeg)
        finally:
            clap_batch.segment_starts = production_starts
        for result in (original, variant):
            if result["status"] not in {"CANDIDATES", "REJECTED"} or len(result["segments"]) != 3 or any(segment["quality"] != "OK" for segment in result["segments"]):
                raise ValueError("Analysis or segment quality failed; no sample substitution")
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Source changed after analysis")
        delta = score_delta(previous["analysis"]["segments"], original["segments"])
        middle_delta = score_delta([original["segments"][1]], [variant["segments"][1]])
        report["results"].append(dict(filename=item["relative_path"], input_sha256=item["sha256"], original=original, variant=variant, baseline_max_abs_delta=delta, middle_max_abs_delta=middle_delta))
        save()
        print(f"Completed {len(report['results'])}/40; baseline delta {delta:.7f}; middle delta {middle_delta:.7f}", flush=True)
        if max(delta, middle_delta) > TOLERANCE:
            raise ValueError("Reproduction control failed")
    report.update(completed=True, elapsed_seconds=round(time.monotonic() - started, 3), original_summary=summarize(report["results"], "original"), variant_summary=summarize(report["results"], "variant"), baseline_max_abs_delta=max(row["baseline_max_abs_delta"] for row in report["results"]), middle_max_abs_delta=max(row["middle_max_abs_delta"] for row in report["results"]), reproduction_passed=True)
    save()


def main():
    parser = argparse.ArgumentParser(description="Read-only paired sampling comparison with bounded supervisor")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    args.output = args.output.resolve()
    if not args.output.is_relative_to(workspace / "local-ai/diagnostics") or args.output.exists():
        parser.error("Use a new output in ignored local-ai/diagnostics")
    if args.worker:
        run(args, workspace)
    else:
        supervise(args)


if __name__ == "__main__":
    main()
