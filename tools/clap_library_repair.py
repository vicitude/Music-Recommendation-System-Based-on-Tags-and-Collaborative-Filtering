import hashlib
import json
import subprocess
import sys
from pathlib import Path

from clap_minimum import VERSION, decide_minimum
from clap_multilabel import texts
from clap_policy import MODEL_ID, REVISION
from clap_sampling_compare import internal_starts


def combine_plan(old_plan, diagnosis, additions):
    if diagnosis.get("matched_unique") != 36 or len(diagnosis.get("missing", [])) != 4 or diagnosis.get("duplicates") or len(diagnosis.get("non_target_songs", [])) != 4:
        raise ValueError("Unexpected database diagnosis; no plan changes")
    missing = {row["sha256"] for row in diagnosis["missing"]}
    old_ids = {row["sha256"] for row in old_plan["items"]}
    new_ids = {row["sha256"] for row in additions}
    if len(old_ids) != 40 or len(missing) != 4 or not missing <= old_ids or len(additions) != 4 or len(new_ids) != 4 or new_ids & old_ids:
        raise ValueError("Invalid 36+4 identity partition")
    return dict(old_plan, items=sorted([row for row in old_plan["items"] if row["sha256"] not in missing] + additions, key=lambda row: row["sha256"]), selection="DATABASE_DIAGNOSIS_36_PLUS4", supersedes="retag40-v2.json")


def run():
    root = Path(__file__).resolve().parents[1]
    home = root / "local-ai/diagnostics"
    output = home / "retag40-library-v3.json"
    evidence_path = home / "retag-library4-analysis-v3.json"
    if output.exists() or evidence_path.exists():
        raise ValueError("Refuse overwrite")
    diagnosis_path = home / "retag-match-20261109-193110-ab1802ad.json"
    diagnosis = json.loads(diagnosis_path.read_bytes())
    baseline = json.loads((home / "catalog-v1.json").read_bytes())
    old = json.loads((home / "retag40-v2.json").read_bytes())
    extras = [item for item in baseline["scan"]["items"] if item.get("status") == "FAILED"]
    if len(extras) != 4:
        raise ValueError("Expected original four excluded files")
    matches = {item["sha256"]: [] for item in extras}
    media_root = root / "media"
    count = 0
    for directory, directories, files in __import__("os").walk(media_root):
        for entry in list(directories) + files:
            path = Path(directory) / entry
            if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                raise ValueError("Reparse media rejected")
        for name in files:
            path = Path(directory) / name
            count += 1
            if count > 500:
                raise ValueError("Media scan bound")
            if path.suffix.lower() != ".mp3":
                continue
            if not 0 < path.stat().st_size <= 31457280:
                raise ValueError("Invalid media size")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in matches:
                matches[digest].append(path)
    if any(len(paths) != 1 for paths in matches.values()):
        raise ValueError("Four extra media fingerprints not uniquely present")
    import torch
    import clap_batch
    model_path = root / "local-ai/models/clap-htsat-fused"
    manifest = clap_batch.verify_weights(model_path)
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION:
        raise ValueError("Model mismatch")
    torch.set_num_threads(4)
    processor = clap_batch.ClapProcessor.from_pretrained(model_path, local_files_only=True)
    model = clap_batch.ClapModel.from_pretrained(model_path, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        inputs = processor(text=texts(), return_tensors="pt", padding=True)
        embeddings = torch.nn.functional.normalize(model.get_text_features(**inputs), dim=-1)
    results, additions = [], []
    old_starts, old_decide = clap_batch.segment_starts, clap_batch.decide_candidates
    try:
        clap_batch.segment_starts, clap_batch.decide_candidates = internal_starts, decide_minimum
        for item in extras:
            path = matches[item["sha256"]][0]
            probe = subprocess.run(["D:/ffmpeg/ffprobe.exe", "-v", "error", "-protocol_whitelist", "file", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, check=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            duration_ms = round(float(json.loads(probe.stdout)["format"]["duration"]) * 1000)
            result = clap_batch.analyze_item(dict(path=str(path), sha256=item["sha256"], extension=".mp3", duration_ms=duration_ms), model, processor, embeddings, "D:/ffmpeg/ffmpeg.exe")
            if result["status"] != "CANDIDATES" or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Additional audio analysis failed; no replacement plan")
            for kind, maximum in (("STYLE", 2), ("MOOD", 3), ("SCENE", 2)):
                if not 1 <= sum(candidate["kind"] == kind for candidate in result["candidates"]) <= maximum:
                    raise ValueError("Additional analysis failed count gates")
            results.append(dict(filename=item["filename"], duration_ms=duration_ms, strict_scan_status="FAILED", analysis=result))
            additions.append(dict(sha256=item["sha256"], filename=item["filename"], candidates=result["candidates"], reasons=result["reasons"]))
            print("Completed additional " + str(len(results)) + "/4", flush=True)
    finally:
        clap_batch.segment_starts, clap_batch.decide_candidates = old_starts, old_decide
    repaired = combine_plan(old, diagnosis, additions)
    repaired["diagnosis_sha256"] = hashlib.sha256(diagnosis_path.read_bytes()).hexdigest()
    repaired["additional_audio_sha256"] = sorted(matches)
    evidence = dict(completed=True, model_id=MODEL_ID, revision=REVISION, policy_version=VERSION, prompts=texts(), results=results)
    with evidence_path.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(repaired, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print("Repaired exact40 plan saved; database unchanged", flush=True)


if __name__ == "__main__":
    if "--worker" in sys.argv:
        run()
    else:
        log_path = Path(__file__).resolve().parents[1] / "local-ai/diagnostics/retag-library4-v3.log"
        with log_path.open("xb") as log:
            subprocess.run([sys.executable, "-B", __file__, "--worker"], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
