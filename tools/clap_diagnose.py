import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from clap_policy import LABELS, MAPPING_VERSION, POLICY_VERSION, PROMPTS_VERSION, REVISION, prompt_texts


def diagnose_dimensions(result):
    valid = [segment for segment in result.get("segments", []) if segment["quality"] == "OK"]
    dimensions = {}
    for kind, margin in (("STYLE", 0.04), ("MOOD", 0.05)):
        indices = [index for index, label in enumerate(LABELS) if label[0] == kind]
        if len(valid) < 2:
            dimensions[kind] = dict(passed=False, failures=["INSUFFICIENT_SEGMENTS"])
            continue
        rows = [[(segment["scores"][index * 2] + segment["scores"][index * 2 + 1]) / 2 for index in range(len(LABELS))] for segment in valid]
        means = {index: sum(row[index] for row in rows) / len(rows) for index in indices}
        ranking = sorted(indices, key=lambda index: (-means[index], index))
        best, second = ranking[:2]
        controls = [max(segment["scores"][-3:]) for segment in valid]
        support, top_indices, prompt_agreement = 0, [], []
        for segment, row, control in zip(valid, rows, controls):
            order = sorted(indices, key=lambda index: (-row[index], index))
            top_indices.append(order[0])
            support += int(order[0] == best and row[best] - row[order[1]] >= 0.02 and row[best] - control >= 0.03)
            prompt_top = [max(indices, key=lambda index: segment["scores"][index * 2 + offset]) for offset in (0, 1)]
            prompt_agreement.append(prompt_top[0] == prompt_top[1])
        score, gap = means[best], means[best] - means[second]
        checks = dict(SCORE=score >= 0.30, GAP=gap >= margin, SUPPORT=support >= 2, CONTROL=score - sum(controls) / len(controls) >= 0.05)
        dimensions[kind] = dict(top_label=LABELS[best][1], score=score, gap=gap, control_gap=score - sum(controls) / len(controls), support_count=support, same_top_count=sum(index == best for index in top_indices), segment_tops=[LABELS[index][1] for index in top_indices], prompt_agreement=prompt_agreement, passed=all(checks.values()), failures=[key for key, passed in checks.items() if not passed], ranked=[dict(name=LABELS[index][1], score=means[index]) for index in ranking])
    return dimensions


def main():
    parser = argparse.ArgumentParser(description="Read-only full-catalog CLAP diagnosis; no database or tag writes")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    if not args.output.resolve().is_relative_to(workspace / "local-ai"):
        parser.error("Reports must stay in ignored local-ai directory")
    sys.path.insert(0, str(workspace / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
    import django
    django.setup()
    from music.clap_candidates import run_analysis
    from music.local_scanner import _hash_file, safe_source, scan_local_catalog

    root = args.source.resolve(strict=True)
    scan = scan_local_catalog(root)
    selected = [item for item in scan["items"] if item.get("status") in {"READY", "NEEDS_METADATA"}]
    report = dict(schema_version=1, purpose="COVERAGE_AND_REJECTION_DIAGNOSTIC_NOT_ACCURACY", policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION, revision=REVISION, prompts=prompt_texts(), scan=scan, results=[], completed=False, random_seed=42, sampling="ALL_STRUCTURALLY_VALID_FILES_SORTED_SCANNER_ORDER", started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        temporary = args.output.with_name("temp_" + args.output.name)
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, args.output)
    save()
    started = time.perf_counter()
    for offset in range(0, len(selected), 5):
        chunk = selected[offset:offset + 5]
        inputs = []
        for item in chunk:
            path = safe_source(root, item["relative_path"])
            actual, size = _hash_file(path)
            if actual != item["sha256"] or size != item["bytes"]:
                raise ValueError("Input changed before analysis")
            inputs.append(dict(path=str(path), sha256=item["sha256"], duration_ms=item["duration_ms"], extension=item["extension"]))
        try:
            results = run_analysis(inputs)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            results = [dict(input_sha256=item["sha256"], status="UNAVAILABLE", segments=[], candidates=[], reasons=[type(error).__name__]) for item in inputs]
        for item, result in zip(chunk, results):
            actual, size = _hash_file(safe_source(root, item["relative_path"]))
            if actual != item["sha256"] or size != item["bytes"]:
                result = dict(input_sha256=item["sha256"], status="FAILED", segments=[], candidates=[], reasons=["INPUT_CHANGED"])
            dimensions = diagnose_dimensions(result)
            if result["status"] in {"CANDIDATES", "REJECTED"}:
                expected = {kind for kind, evidence in dimensions.items() if evidence["passed"]}
                if expected != {candidate["kind"] for candidate in result["candidates"]}:
                    raise ValueError("Diagnostic gates differ from production policy")
            report["results"].append(dict(filename=item["relative_path"], metadata_status=item["status"], analysis=result, dimensions=dimensions))
        save()
        print("Processed",len(report["results"]),"/",len(selected),flush=True)
    report.update(completed=True, elapsed_seconds=round(time.perf_counter() - started, 3), status_counts=dict(Counter(entry["analysis"]["status"] for entry in report["results"])))
    save()
    print(json.dumps(dict(completed=True, songs=len(selected), status_counts=report["status_counts"], elapsed_seconds=report["elapsed_seconds"])),flush=True)


if __name__ == "__main__":
    main()
