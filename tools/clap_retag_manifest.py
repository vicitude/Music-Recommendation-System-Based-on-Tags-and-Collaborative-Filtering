import hashlib
import json
from pathlib import Path

from clap_minimum import VERSION, decide_minimum
from clap_multilabel import texts
from clap_policy import MODEL_ID, REVISION
from clap_prompt_compare import validate_baseline
from clap_sampling_compare import internal_starts


def build_manifest(baseline_bytes, first_bytes, remaining_bytes):
    baseline = json.loads(baseline_bytes)
    items = validate_baseline(baseline)
    indexed = {item["sha256"]: item for item in items}
    outputs = []
    seen = set()
    for data, expected_version, count in ((first_bytes, "multilabel-neutral-v1", 15), (remaining_bytes, VERSION, 25)):
        report = json.loads(data)
        if not report.get("completed") or report.get("policy_version") != expected_version or report.get("model_id") != MODEL_ID or report.get("revision") != REVISION or report.get("prompts") != texts() or report.get("baseline_sha256") != hashlib.sha256(baseline_bytes).hexdigest() or len(report["results"]) != count:
            raise ValueError("Source report version or baseline mismatch")
        for row in report["results"]:
            analysis = row["analysis"]
            identity = analysis["input_sha256"]
            if identity in seen or identity not in indexed or analysis["status"] != "CANDIDATES":
                raise ValueError("Duplicate, unknown or failed input")
            item = indexed[identity]
            segments = analysis["segments"]
            if row["filename"] != item["relative_path"] or [segment["start_seconds"] for segment in segments] != internal_starts(item["duration_ms"]):
                raise ValueError("Sample identity or positions changed")
            candidates, reasons = decide_minimum(segments)
            for kind, maximum in (("STYLE", 2), ("MOOD", 3), ("SCENE", 2)):
                if not 1 <= sum(candidate["kind"] == kind for candidate in candidates) <= maximum:
                    raise ValueError("No valid minimum-label analysis")
            outputs.append(dict(sha256=identity, filename=item["relative_path"], candidates=candidates, reasons=reasons))
            seen.add(identity)
    if seen != set(indexed):
        raise ValueError("Expected exact 40-song identity set")
    return dict(schema_version=1, policy_version=VERSION, model_id=MODEL_ID, revision=REVISION, baseline_sha256=hashlib.sha256(baseline_bytes).hexdigest(), source_reports_sha256=[hashlib.sha256(data).hexdigest() for data in (first_bytes, remaining_bytes)], operation="REPLACE_EXISTING_40_SONG_TAGS_ONLY", items=sorted(outputs, key=lambda item: item["sha256"]))


def main():
    root = Path(__file__).resolve().parents[1] / "local-ai/diagnostics"
    manifest = build_manifest((root / "catalog-v1.json").read_bytes(), (root / "multilabel-v1.json").read_bytes(), (root / "minimum-remaining25-v2.json").read_bytes())
    with (root / "retag40-v2.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("Unified 40-song plan generated; database unchanged")


if __name__ == "__main__":
    main()
