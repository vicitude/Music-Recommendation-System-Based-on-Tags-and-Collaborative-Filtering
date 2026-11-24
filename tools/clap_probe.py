import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from transformers import ClapModel, ClapProcessor


PROMPTS = (
    ("pop", "This is a recording of pop music."),
    ("rock", "This is a recording of rock music with electric guitars and drums."),
    ("electronic", "This is a recording of electronic dance music."),
    ("folk", "This is a recording of folk music with acoustic instruments."),
    ("classical", "This is a recording of classical orchestral music."),
    ("jazz", "This is a recording of jazz music."),
    ("hip_hop", "This is a recording of hip hop music with rapping."),
    ("ambient", "This is a recording of calm ambient instrumental music."),
    ("speech", "This is a recording of a person speaking, not music."),
)


def verify_weights(directory):
    manifest = json.loads((directory / "installation-manifest.json").read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["name"] == "model.safetensors")
    with (directory / entry["name"]).open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != entry["sha256"] or actual != "3f648de6d030e17494be455d323b8d191233fbae0c7ce0ba745fd21a926a63a6":
        raise ValueError("Weight checksum mismatch")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Offline CLAP load and inference probe; never writes song tags")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("MUSIC_AI_HOME", Path(__file__).resolve().parents[1] / "local-ai")))
    parser.add_argument("--ffmpeg", type=Path, default=Path("D:/ffmpeg/ffmpeg.exe"))
    parser.add_argument("--audio", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if len(args.audio) > 5:
        parser.error("At most five songs per probe")
    torch.set_num_threads(4)
    np.random.seed(42)
    directory = args.home / "models/clap-htsat-fused"
    manifest = verify_weights(directory)
    started = time.perf_counter()
    processor = ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    report = {"model": manifest["model_id"], "revision": manifest["revision"], "device": "cpu", "load_seconds": round(time.perf_counter() - started, 3), "score_type": "cosine_similarity_not_probability", "prompts_version": "probe-v1", "automatic_tag_writes": False, "results": []}
    rate = processor.feature_extractor.sampling_rate
    sources = [("synthetic_440hz_control", 0.1 * np.sin(2 * np.pi * 440 * np.arange(rate * 10) / rate))]
    for path in args.audio:
        process = subprocess.run([str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-i", str(path.resolve(strict=True)), "-t", "10", "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        signal = np.frombuffer(process.stdout, dtype="<i2").astype(np.float32) / 32768
        if len(signal) == 0 or len(signal) > rate * 11:
            raise ValueError("Unexpected decoded signal size")
        sources.append((path.name, signal))
    for name, signal in sources:
        started = time.perf_counter()
        inputs = processor(text=[prompt for _, prompt in PROMPTS], audio=signal, sampling_rate=rate, return_tensors="pt", padding=True)
        with torch.inference_mode():
            outputs = model(**inputs)
            scores = (outputs.audio_embeds @ outputs.text_embeds.T)[0].tolist()
        ranked = sorted([{"label": label, "cosine_similarity": round(score, 5)} for (label, _), score in zip(PROMPTS, scores)], key=lambda item: -item["cosine_similarity"])
        report["results"].append({"filename": name, "sample_seconds": round(len(signal) / rate, 3), "inference_seconds": round(time.perf_counter() - started, 3), "ranking": ranked})
        print(json.dumps(report["results"][-1], ensure_ascii=True), flush=True)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PROBE_COMPLETE", flush=True)


if __name__ == "__main__":
    main()
