import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from clap_multilabel import VERSION, decide, texts
from clap_policy import MODEL_ID, REVISION
from clap_sampling_compare import internal_starts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--minimum-remaining", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / "local-ai/diagnostics") or output.exists():
        raise ValueError("Use a new ignored output")
    if not args.worker:
        log_path = output.with_suffix(".log")
        with log_path.open("xb") as log:
            command = [sys.executable, "-B", __file__, "--worker", "--output", str(output)]
            if args.minimum_remaining:
                command.append("--minimum-remaining")
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            started = progress = time.monotonic()
            size = 0
            try:
                while process.poll() is None:
                    time.sleep(2)
                    current = log_path.stat().st_size
                    if current != size:
                        size, progress = current, time.monotonic()
                    if time.monotonic() - started > 1200 or time.monotonic() - progress > 180:
                        raise TimeoutError("Bounded run timeout")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode:
                raise RuntimeError("Inspect multilabel log")
        return
    import torch
    import clap_batch

    baseline_path = root / "local-ai/diagnostics/catalog-v1.json"
    sampling_path = root / "local-ai/diagnostics/sampling-comparison-v1.json"
    baseline = json.loads(baseline_path.read_bytes())
    sampling = json.loads(sampling_path.read_bytes())
    from clap_prompt_compare import validate_baseline
    items = validate_baseline(baseline)
    if not sampling.get("completed") or not sampling.get("reproduction_passed"):
        raise ValueError("Incomplete sampling source")
    selected = sorted((row for row in sampling["results"] if row["variant"]["candidates"]), key=lambda row: row["input_sha256"])[:15]
    by_hash = {item["sha256"]: item for item in items}
    decision, version = decide, VERSION
    previous_digest = None
    if args.minimum_remaining:
        from clap_minimum import VERSION as minimum_version, decide_minimum, remaining_items
        previous_bytes = (root / "local-ai/diagnostics/multilabel-v1.json").read_bytes()
        previous = json.loads(previous_bytes)
        if previous["baseline_sha256"] != hashlib.sha256(baseline_path.read_bytes()).hexdigest():
            raise ValueError("Previous baseline fingerprint mismatch")
        selected = [dict(input_sha256=item["sha256"]) for item in remaining_items(items, previous)]
        decision, version = decide_minimum, minimum_version
        previous_digest = hashlib.sha256(previous_bytes).hexdigest()
    directory = root / "local-ai/models/clap-htsat-fused"
    manifest = clap_batch.verify_weights(directory)
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION:
        raise ValueError("Model mismatch")
    torch.set_num_threads(4)
    processor = clap_batch.ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = clap_batch.ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        inputs = processor(text=texts(), return_tensors="pt", padding=True)
        embeddings = torch.nn.functional.normalize(model.get_text_features(**inputs), dim=-1)
    report = dict(completed=False, policy_version=version, previous_report_sha256=previous_digest, model_id=MODEL_ID, revision=REVISION, prompts=texts(), baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(), sampling_sha256=hashlib.sha256(sampling_path.read_bytes()).hexdigest(), results=[])
    source_root = Path(baseline["scan"]["source_root"]).resolve(strict=True)
    old_starts, old_decide = clap_batch.segment_starts, clap_batch.decide_candidates
    try:
        clap_batch.segment_starts, clap_batch.decide_candidates = internal_starts, decision
        for row in selected:
            item = by_hash[row["input_sha256"]]
            path = source_root
            relative = Path(item["relative_path"])
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                raise ValueError("Unsafe source path")
            for part in relative.parts:
                path = path / part
                if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                    raise ValueError("Linked source")
            if not path.resolve(strict=True).is_relative_to(source_root) or path.stat().st_size != item["bytes"]:
                raise ValueError("Source changed")
            result = clap_batch.analyze_item(dict(path=str(path), sha256=item["sha256"], extension=item["extension"], duration_ms=item["duration_ms"]), model, processor, embeddings, "D:/ffmpeg/ffmpeg.exe")
            if result["status"] == "FAILED" or len(result["segments"]) != 3 or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Analysis failed or source changed")
            report["results"].append(dict(filename=item["relative_path"], analysis=result))
            temporary = output.with_name("temp_" + output.name)
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            os.replace(temporary, output)
            print(f"Completed {len(report['results'])}/{len(selected)}", flush=True)
    finally:
        clap_batch.segment_starts, clap_batch.decide_candidates = old_starts, old_decide
    report["completed"] = True
    report["distribution"] = dict(Counter(candidate["kind"] + ":" + candidate["name"] for row in report["results"] for candidate in row["analysis"]["candidates"]))
    temporary = output.with_name("temp_" + output.name)
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, output)


if __name__ == "__main__":
    main()
