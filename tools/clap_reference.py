import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from clap_policy import LABELS
from clap_prompt_compare import validate_baseline


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path, report):
    root = Path(__file__).resolve().parents[1] / "local-ai/diagnostics"
    if not path.resolve().is_relative_to(root):
        raise ValueError("Output must stay in ignored diagnostics directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)


def select_samples(items):
    if len({item["sha256"] for item in items}) != len(items):
        raise ValueError("Duplicate audio identity")
    return sorted(items, key=lambda item: item["sha256"])[:12]


def verify_dimension(kind, value):
    if value["status"] == "PENDING":
        if value.get("labels") or value.get("evidence"):
            raise ValueError("Pending reference must not contain asserted labels/evidence")
        return False
    if value["status"] != "VERIFIED" or type(value.get("exhaustive")) is not bool:
        raise ValueError("Invalid reference status/completeness")
    allowed = {label[1] for label in LABELS if label[0] == kind}
    labels = value.get("labels")
    if not isinstance(labels, list) or not labels or len(set(labels)) != len(labels) or not set(labels) <= allowed:
        raise ValueError("Invalid reference labels")
    evidence = value.get("evidence", {})
    if evidence.get("source_type") not in {"RELEASE_METADATA", "EXPERT_DATABASE", "INDEPENDENT_REVIEW"}:
        raise ValueError("Weak, model or synthetic evidence cannot be a reference")
    if evidence.get("identity_match") is not True or evidence.get("independent_of_model") is not True:
        raise ValueError("Unmatched or non-independent evidence")
    for field in ("locator", "quote", "mapping_reason", "reviewer", "reviewed_at"):
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise ValueError("Missing evidence provenance")
    return True


def evaluate(reference, baseline):
    items = validate_baseline(baseline)
    selected = select_samples(items)
    if reference.get("schema_version") != 1 or reference.get("selection") != "SHA256_ASC_FIRST12" or [row["sha256"] for row in reference["samples"]] != [item["sha256"] for item in selected]:
        raise ValueError("Reference identity/selection mismatch")
    predictions = {row["analysis"]["input_sha256"]: row["analysis"]["candidates"] for row in baseline["results"]}
    counts = Counter()
    covered = set()
    for sample in reference["samples"]:
        for kind in ("STYLE", "MOOD"):
            value = sample["dimensions"][kind]
            if not verify_dimension(kind, value):
                continue
            counts["verified_dimensions"] += 1
            covered.add(sample["sha256"])
            truth = set(value["labels"])
            predicted = {candidate["name"] for candidate in predictions[sample["sha256"]] if candidate["kind"] == kind}
            counts["emitted_labels"] += len(predicted)
            if value["exhaustive"]:
                counts["complete_dimensions"] += 1
                counts["tp"] += len(truth & predicted)
                counts["fp"] += len(predicted - truth)
                counts["fn"] += len(truth - predicted)
                counts["abstained_complete_dimensions"] += int(not predicted)
            else:
                counts["partial_confirmed_hits"] += len(truth & predicted)
                counts["partial_unknown_predictions"] += len(predicted - truth)
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else 0.0 if precision == 0 and recall == 0 else None
    return dict(status="REFERENCE_AVAILABLE" if counts["verified_dimensions"] else "INSUFFICIENT_REFERENCE", scope="DEVELOPMENT_REFERENCE_NOT_INDEPENDENT_TEST", counts=dict(counts), selected_songs=12, covered_songs=len(covered), precision=precision, recall=recall, f1=f1)


def prepare(args):
    baseline = read_json(args.baseline)
    items = validate_baseline(baseline)
    root = Path(baseline["scan"]["source_root"]).resolve(strict=True)
    audit = []
    started = time.monotonic()
    for item in items:
        if time.monotonic() - started > 660:
            raise TimeoutError("Metadata audit limit")
        path = root
        relative = Path(item["relative_path"])
        if relative.is_absolute() or relative.drive or ".." in relative.parts:
            raise ValueError("Unsafe relative path")
        for part in relative.parts:
            path = path / part
            if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                raise ValueError("Linked source rejected")
        if not path.resolve(strict=True).is_relative_to(root) or not 0 < path.stat().st_size <= 31457280 or path.stat().st_size != item["bytes"]:
            raise ValueError("Source size/location changed")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Source fingerprint changed")
        result = subprocess.run([args.ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_entries", "format_tags=genre,mood", "-of", "json", str(path)], capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tags = json.loads(result.stdout).get("format", {}).get("tags", {})
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Source changed after extraction")
        audit.append(dict(sha256=item["sha256"], filename=item["relative_path"], raw_tags=tags, evidence_grade="WEAK_EMBEDDED_METADATA_NOT_TRUTH"))
    by_hash = {row["sha256"]: row for row in audit}
    samples = [dict(sha256=item["sha256"], filename=item["relative_path"], title=item["title"], artist=item["artist"], embedded_evidence=by_hash[item["sha256"]], dimensions={kind: dict(status="PENDING", labels=[], exhaustive=False, evidence={}) for kind in ("STYLE", "MOOD")}) for item in select_samples(items)]
    reference = dict(schema_version=1, selection="SHA256_ASC_FIRST12", baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(), extractor=str(Path(args.ffprobe).resolve()), samples=samples, metadata_audit=audit)
    write_new(args.output, reference)
    print(json.dumps(dict(selected=len(samples), audited=len(audit), with_embedded_tags=sum(bool(row["raw_tags"]) for row in audit), evaluation=evaluate(reference, baseline)), ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description="Blind reference preparation and evidence-gated development evaluation")
    parser.add_argument("action", choices=("prepare", "evaluate"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--ffprobe")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.ffprobe:
            parser.error("prepare requires existing local ffprobe")
        prepare(args)
    else:
        if not args.reference:
            parser.error("evaluate requires reference")
        reference = read_json(args.reference)
        if reference.get("baseline_sha256") != hashlib.sha256(args.baseline.read_bytes()).hexdigest():
            raise ValueError("Baseline report fingerprint mismatch")
        report = evaluate(reference, read_json(args.baseline))
        write_new(args.output, report)
        print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
