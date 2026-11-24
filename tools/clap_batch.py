import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import numpy as np
import torch
from transformers import ClapModel, ClapProcessor

from clap_policy import MAPPING_VERSION, MODEL_ID, POLICY_VERSION, PROMPTS_VERSION, REVISION, decide_candidates, prompt_texts, segment_starts
from clap_probe import verify_weights


def signal_quality(signal, rate):
    if len(signal) < rate * 5:
        return "TOO_SHORT"
    rms = float(np.sqrt(np.mean(signal ** 2)))
    if not np.isfinite(signal).all() or rms < 0.001:
        return "SILENCE"
    window = min(4096, len(signal))
    frames = np.lib.stride_tricks.sliding_window_view(signal, window)[::window]
    energy = np.abs(np.fft.rfft(frames * np.hanning(window), axis=1)) ** 2
    total = energy.sum(axis=1)
    peaks = np.sort(energy, axis=1)[:, -5:].sum(axis=1)
    if float(np.mean(peaks / np.maximum(total, 1e-12))) > 0.97:
        return "TONAL_CONTROL"
    return "OK"


def analyze_item(item, model, processor, text_embeddings, ffmpeg):
    result = {"input_sha256": item["sha256"], "status": "FAILED", "segments": [], "candidates": [], "reasons": []}
    try:
        path = Path(item["path"])
        if path.is_symlink() or not 1 <= path.stat().st_size <= 31457280:
            raise ValueError("文件位置或大小无效")
        with path.open("rb") as source:
            data = source.read(31457281)
        if len(data) > 31457280 or hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("源文件指纹已改变，请重新扫描")
        starts = segment_starts(item["duration_ms"])
        if not starts:
            result.update(status="REJECTED", reasons=["时长不足20秒，缺少独立片段证据"])
            return result
        rate = processor.feature_extractor.sampling_rate
        for start in starts:
            process = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "pipe", "-f", item["extension"].lstrip("."), "-i", "pipe:0", "-ss", str(start), "-t", "10", "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"], input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if len(process.stdout) % 2 or len(process.stdout) > rate * 11 * 2:
                raise ValueError("解码输出大小异常")
            signal = np.frombuffer(process.stdout, dtype="<i2").astype(np.float32) / 32768
            quality = signal_quality(signal, rate)
            segment = {"start_seconds": start, "sample_seconds": round(len(signal) / rate, 3), "quality": quality, "scores": []}
            if quality == "OK":
                np.random.seed(42)
                inputs = processor(audio=signal, sampling_rate=rate, return_tensors="pt")
                with torch.inference_mode():
                    features = model.get_audio_features(**inputs)
                    features = torch.nn.functional.normalize(features, dim=-1)
                    scores = (features @ text_embeddings.T)[0].tolist()
                segment["scores"] = [round(value, 7) for value in scores]
            result["segments"].append(segment)
        candidates, reasons = decide_candidates(result["segments"])
        result.update(status="CANDIDATES" if candidates else "REJECTED", candidates=candidates, reasons=reasons)
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
        result.update(status="FAILED", candidates=[], reasons=["解码、指纹复验或模型推理失败；未生成标签"])
    return result


def main():
    request = json.loads(sys.stdin.buffer.read(65537).decode("utf-8"))
    items = request["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise ValueError("每次仅允许1至5首")
    directory = Path(request["home"]) / "models/clap-htsat-fused"
    manifest = verify_weights(directory)
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION:
        raise ValueError("模型版本不符")
    torch.set_num_threads(4)
    processor = ClapProcessor.from_pretrained(directory, local_files_only=True)
    model = ClapModel.from_pretrained(directory, local_files_only=True, use_safetensors=True).eval()
    with torch.inference_mode():
        texts = processor(text=prompt_texts(), return_tensors="pt", padding=True)
        text_embeddings = torch.nn.functional.normalize(model.get_text_features(**texts), dim=-1)
    results = [analyze_item(item, model, processor, text_embeddings, request["ffmpeg"]) for item in items]
    print(json.dumps({"model_id": MODEL_ID, "revision": REVISION, "policy_version": POLICY_VERSION, "prompts_version": PROMPTS_VERSION, "mapping_version": MAPPING_VERSION, "results": results}, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
