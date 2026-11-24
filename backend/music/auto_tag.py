import io
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from django.conf import settings
from scipy.signal import resample_poly

from music.tag_library import canonical_tag, is_formal_tag


RULE_VERSION = "audio-rules-v1"
VOCABULARY_VERSION = "formal-53-v46"
SAMPLE_RATE = 11025
SAMPLE_SECONDS = 30
LIMITS = {"STYLE": 2, "MOOD": 3, "SCENE": 2}


def decoder_path():
    configured = getattr(settings, "LOCAL_IMPORT_FFMPEG", "")
    if configured:
        return str(Path(configured)) if Path(configured).is_file() else None
    return shutil.which("ffmpeg")


def decode_sample(data, extension):
    if extension == ".wav":
        with wave.open(io.BytesIO(data), "rb") as audio:
            rate, width, channels = audio.getframerate(), audio.getsampwidth(), audio.getnchannels()
            raw = audio.readframes(min(audio.getnframes(), rate * SAMPLE_SECONDS))
        if width == 1:
            signal = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128
        elif width in (2, 4):
            signal = np.frombuffer(raw, dtype="<i" + str(width)).astype(np.float64) / (2 ** (8 * width - 1))
        elif width == 3:
            octets = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
            values = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
            signal = ((values ^ 0x800000) - 0x800000).astype(np.float64) / 8388608
        else:
            raise ValueError("不支持的PCM位宽")
        signal = signal.reshape(-1, channels).mean(axis=1)
        divisor = math.gcd(rate, SAMPLE_RATE)
        return resample_poly(signal, SAMPLE_RATE // divisor, rate // divisor), "WAV_PCM"
    decoder = decoder_path()
    if not decoder:
        raise ValueError("未配置FFmpeg，MP3/OGG声学分析不可用；未安装新软件")
    process = subprocess.run(
        [decoder, "-hide_banner", "-loglevel", "error", "-nostdin", "-protocol_whitelist", "pipe", "-f", "mp3" if extension == ".mp3" else "ogg", "-i", "pipe:0", "-t", str(SAMPLE_SECONDS), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1"],
        input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.returncode or not process.stdout or len(process.stdout) > SAMPLE_RATE * SAMPLE_SECONDS * 2 + 8192 or len(process.stdout) % 2:
        raise ValueError("音频解码失败或输出异常")
    return np.frombuffer(process.stdout, dtype="<i2").astype(np.float64) / 32768, "FFMPEG_PCM"


def extract_features(signal):
    signal = np.asarray(signal, dtype=np.float64)
    if signal.ndim != 1 or not np.isfinite(signal).all() or not len(signal):
        raise ValueError("采样数据无效")
    signal = signal[:SAMPLE_RATE * SAMPLE_SECONDS]
    rms = float(np.sqrt(np.mean(signal ** 2)))
    result = {"sample_seconds": round(len(signal) / SAMPLE_RATE, 3), "sample_rate": SAMPLE_RATE, "rms": round(rms, 6), "dbfs": round(20 * math.log10(max(rms, 1e-8)), 3), "bpm": None, "bpm_strength": 0.0, "vocal_tendency": None}
    if len(signal) < SAMPLE_RATE * 5 or rms < 0.001:
        result["quality"] = "TOO_SHORT" if len(signal) < SAMPLE_RATE * 5 else "SILENCE"
        return result
    window, hop = 1024, 256
    frames = np.lib.stride_tricks.sliding_window_view(signal, window)[::hop]
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(window), axis=1))
    frequencies = np.fft.rfftfreq(window, 1 / SAMPLE_RATE)
    centroid = (spectrum @ frequencies) / np.maximum(spectrum.sum(axis=1), 1e-12)
    envelope = np.sqrt(np.mean(frames ** 2, axis=1))
    result.update(quality="OK", spectral_centroid_hz=round(float(np.mean(centroid)), 2), zero_crossing_rate=round(float(np.mean(signal[:-1] * signal[1:] < 0)), 5), energy_variation=round(float(np.std(envelope) / max(np.mean(envelope), 1e-8)), 4))
    onset = np.maximum(np.diff(envelope), 0)
    onset -= onset.mean()
    correlation = np.correlate(onset, onset, mode="full")[len(onset) - 1:]
    minimum = int(60 * SAMPLE_RATE / (180 * hop))
    maximum = min(len(correlation) - 1, int(60 * SAMPLE_RATE / (60 * hop)))
    if maximum > minimum and correlation[0] > 1e-10 and result["energy_variation"] >= 0.05:
        lag = minimum + int(np.argmax(correlation[minimum:maximum + 1]))
        strength = float(correlation[lag] / correlation[0])
        result["bpm_strength"] = round(max(0, strength), 4)
        if strength >= 0.25:
            result["bpm"] = round(60 * SAMPLE_RATE / (hop * lag), 1)
    return result


def select_candidates(candidates):
    indexed = {}
    for candidate in candidates:
        kind, name = candidate["kind"], candidate["name"]
        score = candidate["confidence"]
        if kind not in LIMITS or not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0.55 <= score <= 1 or not is_formal_tag(kind, name):
            continue
        kind, name = canonical_tag(kind, name)
        key = kind, name
        value = {**candidate, "kind": kind, "name": name, "rule_version": RULE_VERSION, "needs_review": score < 0.75}
        if key not in indexed or indexed[key]["confidence"] < score:
            indexed[key] = value
    result, counts = [], dict.fromkeys(LIMITS, 0)
    for key in sorted(indexed, key=lambda key: (-indexed[key]["confidence"], key)):
        candidate = indexed[key]
        if counts[candidate["kind"]] < LIMITS[candidate["kind"]]:
            result.append(candidate)
            counts[candidate["kind"]] += 1
    return result


def generate_candidates(filename, metadata, features):
    candidates = []
    def add(kind, name, confidence, source, basis):
        candidates.append(dict(kind=kind, name=name, confidence=confidence, source=source, basis=basis))
    genre = str(metadata.get("genre") or "").strip()
    aliases = {"pop": "流行", "rock": "摇滚", "jazz": "爵士", "classical": "古典", "electronic": "电子", "hip-hop": "嘻哈说唱", "hip hop": "嘻哈说唱", "folk": "民谣", "country": "乡村", "r&b": "R&B", "blues": "蓝调", "metal": "金属"}
    for token in re.split(r"[;,；，]+", genre):
        name = aliases.get(token.strip().casefold(), token.strip())
        if is_formal_tag("STYLE", name):
            add("STYLE", name, 0.85, "EMBEDDED_GENRE", "嵌入曲风字段：" + genre + "；未声学确认")
    for token, name in (("remix", "电子"), ("orchestral", "古典"), ("交响乐版", "古典"), ("钢琴版", "轻音乐"), ("纯音乐", "轻音乐"), ("伴奏", "轻音乐")):
        if token in Path(filename).stem.casefold():
            add("STYLE", name, 0.60, "FILENAME_VERSION", "文件名版本词：" + token + "；不是声音识别")
    if features.get("quality") == "OK":
        evidence = "前30秒信号规则：" + str({key: features.get(key) for key in ("dbfs", "bpm", "energy_variation", "spectral_centroid_hz")})
        if features["dbfs"] < -22 and features["energy_variation"] < 0.45 and features["spectral_centroid_hz"] < 1800:
            add("MOOD", "平静", 0.65, "AUDIO_RULE", evidence)
            add("MOOD", "放松", 0.60, "AUDIO_RULE", evidence)
            add("SCENE", "助眠", 0.60, "AUDIO_RULE", evidence + "；仅适配建议")
        elif features.get("bpm") and features["bpm"] >= 110 and features["dbfs"] > -22 and features["bpm_strength"] >= 0.35:
            add("MOOD", "活力", 0.65, "AUDIO_RULE", evidence)
            add("SCENE", "运动", 0.65, "AUDIO_RULE", evidence + "；仅适配建议")
    return select_candidates(candidates)


def analyze_tags(data, extension, filename, metadata):
    result = dict(rule_version=RULE_VERSION, vocabulary_version=VOCABULARY_VERSION, status="UNAVAILABLE", features={}, decoder=None, issues=[])
    try:
        signal, decoder = decode_sample(data, extension)
        result.update(status="ANALYZED", features=extract_features(signal), decoder=decoder)
    except (OSError, ValueError, EOFError, wave.Error, subprocess.SubprocessError) as error:
        result["issues"] = [str(error) if isinstance(error, ValueError) else "解码或采样失败，未生成声学标签"]
    result["candidates"] = generate_candidates(filename, metadata, result["features"])
    return result
