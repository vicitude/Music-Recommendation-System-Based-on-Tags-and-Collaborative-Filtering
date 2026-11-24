import hashlib
import os
import re
import struct
import wave
from pathlib import Path

from django.core.exceptions import ValidationError

from music.media import MAX_AUDIO_BYTES, MIME_BY_EXTENSION, inspect_audio


SUPPORTED_EXTENSIONS = frozenset(MIME_BY_EXTENSION)
KNOWN_AUDIO_EXTENSIONS = SUPPORTED_EXTENSIONS | {".flac", ".m4a", ".mp4", ".aac", ".wma"}
MAX_SCAN_ITEMS = 500
HASH_CHUNK_SIZE = 1024 * 1024


def _is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def safe_source(root, relative_path):
    relative = Path(relative_path)
    if relative.is_absolute() or relative.drive or not relative.parts or any(part in {".", ".."} or ":" in part for part in relative.parts):
        raise ValueError("文件相对路径无效")
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise ValueError("不允许链接或重解析路径")
    resolved = current.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("文件位置不安全")
    return resolved


def _hash_file(path):
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_SIZE):
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                raise ValueError("文件超过30MiB限制")
            digest.update(chunk)
    if not total:
        raise ValueError("空文件")
    return digest.hexdigest(), total


def _synchsafe(value):
    if len(value) != 4 or any(byte & 128 for byte in value):
        raise ValueError("ID3长度无效")
    return sum(byte << shift for byte, shift in zip(value, (21, 14, 7, 0)))


def _text(payload):
    if not payload:
        return ""
    encodings = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}
    if payload[0] not in encodings:
        raise ValueError("ID3文本编码无效")
    return payload[1:].decode(encodings[payload[0]], errors="replace").split("\x00", 1)[0].strip()


def _frame_header(data, offset):
    if offset + 4 > len(data):
        raise ValueError("MP3帧被截断")
    first, second, third, _ = data[offset:offset + 4]
    version, layer = (second >> 3) & 3, (second >> 1) & 3
    bitrate_index, rate_index = third >> 4, (third >> 2) & 3
    if first != 255 or second & 224 != 224 or version == 1 or layer != 1 or bitrate_index in {0, 15} or rate_index == 3:
        raise ValueError("未找到连续的MPEG Layer III帧")
    if version == 3:
        bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
        rate, samples, coefficient = (44100, 48000, 32000)[rate_index], 1152, 144
    else:
        bitrates = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        rate = (22050, 24000, 16000)[rate_index] // (2 if version == 0 else 1)
        samples, coefficient = 576, 72
    size = coefficient * bitrates[bitrate_index] * 1000 // rate + ((third >> 1) & 1)
    if offset + size > len(data):
        raise ValueError("MP3音频帧被截断")
    return size, samples, rate


def _mp3_metadata(data):
    fields, offset, cover = {}, 0, False
    if data[:3] == b"ID3":
        version, flags = data[3], data[5]
        if version not in {3, 4}:
            raise ValueError("当前自动扫描支持ID3v2.3/v2.4/v1；其他版本待处理")
        end = 10 + _synchsafe(data[6:10])
        if end > len(data) or flags & 0x80:
            raise ValueError("ID3标签被截断或使用不支持的不同步编码")
        position = 10
        if flags & 0x40:
            extension_size = _synchsafe(data[10:14]) if version == 4 else int.from_bytes(data[10:14], "big") + 4
            if extension_size < 4 or 10 + extension_size > end:
                raise ValueError("ID3扩展头无效")
            position += extension_size
        while position + 10 <= end and data[position] != 0:
            frame_id = data[position:position + 4]
            frame_size = _synchsafe(data[position + 4:position + 8]) if version == 4 else int.from_bytes(data[position + 4:position + 8], "big")
            frame_end = position + 10 + frame_size
            if frame_size < 1 or frame_end > end:
                raise ValueError("ID3帧长度无效")
            payload = data[position + 10:frame_end]
            frame_flags = data[position + 9]
            if not frame_flags:
                key = {b"TIT2": "title", b"TPE1": "artist", b"TALB": "album", b"TCON": "genre"}.get(frame_id)
                if key:
                    fields[key] = _text(payload)
                if frame_id == b"APIC":
                    cover = True
            position = frame_end
        offset = end + (10 if version == 4 and flags & 0x10 else 0)
    end = len(data)
    if len(data) >= 128 and data[-128:-125] == b"TAG":
        tail = data[-128:]
        for key, start in (("title", 3), ("artist", 33), ("album", 63)):
            if not fields.get(key):
                raw = tail[start:start + 30].split(b"\x00", 1)[0]
                try:
                    fields[key] = raw.decode("gb18030").strip()
                except UnicodeDecodeError:
                    fields[key] = raw.decode("latin-1").strip()
        end -= 128
    seconds, frames = 0, 0
    audio_data = data[:end]
    while offset < end:
        if data[offset] == 0 and not any(data[offset:end]):
            break
        size, samples, rate = _frame_header(audio_data, offset)
        seconds += samples / rate
        frames += 1
        offset += size
    if frames < 2:
        raise ValueError("MP3缺少足够的连续音频帧")
    return fields, round(seconds * 1000), "MPEG_FRAME_COUNT", cover


def _comments(packet, signature):
    if not packet.startswith(signature):
        raise ValueError("OGG缺少注释头")
    position = len(signature)
    def number():
        nonlocal position
        if position + 4 > len(packet):
            raise ValueError("OGG注释长度无效")
        value = struct.unpack_from("<I", packet, position)[0]
        position += 4
        return value
    vendor_size = number()
    position += vendor_size
    count = number()
    fields, cover = {}, False
    if count > 10000:
        raise ValueError("OGG注释数量异常")
    for _ in range(count):
        size = number()
        if position + size > len(packet):
            raise ValueError("OGG注释被截断")
        value = packet[position:position + size].decode("utf-8", errors="replace")
        position += size
        key, separator, text = value.partition("=")
        if separator and key.upper() in {"TITLE", "ARTIST", "ALBUM", "GENRE"}:
            fields[key.lower()] = text.strip()
        if key.upper() in {"METADATA_BLOCK_PICTURE", "COVERART"}:
            cover = True
    return fields, cover


def _ogg_metadata(data):
    position, sequence, serial = 0, 0, None
    packet, packets, granule, ended = bytearray(), [], None, False
    while position < len(data):
        if ended or data[position:position + 4] != b"OggS" or position + 27 > len(data) or data[position + 4] != 0:
            raise ValueError("OGG页面无效或包含多音轨链")
        flags = data[position + 5]
        page_serial, page_sequence = struct.unpack_from("<II", data, position + 14)
        if serial is None:
            serial = page_serial
        if page_serial != serial or page_sequence != sequence or bool(flags & 1) != bool(packet) or (sequence == 0 and not flags & 2):
            raise ValueError("OGG页面不连续")
        sequence += 1
        page_granule = struct.unpack_from("<Q", data, position + 6)[0]
        if page_granule != 0xFFFFFFFFFFFFFFFF:
            granule = page_granule
        count = data[position + 26]
        sizes = data[position + 27:position + 27 + count]
        payload_start = position + 27 + count
        page_end = payload_start + sum(sizes)
        if len(sizes) != count or page_end > len(data):
            raise ValueError("OGG页面被截断")
        cursor = payload_start
        for size in sizes:
            packet.extend(data[cursor:cursor + size])
            cursor += size
            if size < 255:
                if len(packets) < 2:
                    packets.append(bytes(packet))
                packet.clear()
        ended = bool(flags & 4)
        position = page_end
    if not ended or packet or len(packets) < 2 or granule is None:
        raise ValueError("OGG结束页或头信息缺失")
    if packets[0].startswith(b"\x01vorbis") and len(packets[0]) >= 30:
        rate = struct.unpack_from("<I", packets[0], 12)[0]
        fields, cover = _comments(packets[1], b"\x03vorbis")
        samples = granule
    elif packets[0].startswith(b"OpusHead") and len(packets[0]) >= 19:
        rate = 48000
        samples = granule - struct.unpack_from("<H", packets[0], 10)[0]
        fields, cover = _comments(packets[1], b"OpusTags")
    else:
        raise ValueError("仅支持Vorbis/Opus OGG音频")
    if rate <= 0 or samples <= 0:
        raise ValueError("OGG时长无效")
    return fields, round(samples * 1000 / rate), "OGG_GRANULE", cover


def read_metadata(data, extension):
    mime, duration = inspect_audio(data, "audio" + extension)
    if extension == ".mp3":
        fields, duration, duration_source, cover = _mp3_metadata(data)
    elif extension == ".ogg":
        fields, duration, duration_source, cover = _ogg_metadata(data)
    else:
        fields, duration_source, cover = {}, "WAV_FRAME_COUNT", False
        position = 12
        while position + 8 <= len(data):
            kind, size = data[position:position + 4], int.from_bytes(data[position + 4:position + 8], "little")
            chunk = data[position + 8:position + 8 + size]
            if kind == b"LIST" and chunk[:4] == b"INFO":
                cursor = 4
                while cursor + 8 <= len(chunk):
                    key = {b"INAM": "title", b"IART": "artist", b"IPRD": "album", b"IGNR": "genre"}.get(chunk[cursor:cursor + 4])
                    length = int.from_bytes(chunk[cursor + 4:cursor + 8], "little")
                    if cursor + 8 + length > len(chunk):
                        raise ValueError("WAV元数据被截断")
                    if key:
                        raw = chunk[cursor + 8:cursor + 8 + length].rstrip(b"\x00")
                        try:
                            fields[key] = raw.decode("utf-8").strip()
                        except UnicodeDecodeError:
                            fields[key] = raw.decode("gb18030", errors="replace").strip()
                    cursor += 8 + length + length % 2
            position += 8 + size + size % 2
    if type(duration) is not int or not 1 <= duration <= 86400000:
        raise ValueError("音频时长超出有效范围")
    return fields, duration, duration_source, cover, mime


def _scan_file(root, path, seen, analyze=False):
    relative = path.relative_to(root).as_posix()
    item = {"filename": path.name, "relative_path": relative, "extension": path.suffix.lower(), "eligible": False, "status": "FAILED", "metadata_issues": [], "tag_suggestions": [], "duplicate_of": None}
    try:
        path = safe_source(root, relative)
        fingerprint, size = _hash_file(path)
        item.update(sha256=fingerprint, bytes=size)
        if fingerprint in seen:
            item.update(status="DUPLICATE", duplicate_of=seen[fingerprint])
            item["metadata_issues"].append("重复音频指纹，跳过")
            return item
        seen[fingerprint] = relative
        with path.open("rb") as source:
            data = source.read(MAX_AUDIO_BYTES + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != fingerprint:
            raise ValueError("扫描期间源文件发生变化")
        fields, duration, source, cover, mime = read_metadata(data, item["extension"])
        stem = path.stem.strip()
        parts = re.split(r"\s+-\s+", stem, maxsplit=1)
        if len(parts) == 1:
            parts = stem.split("-", 1)
        fallback_artist, fallback_title = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", stem)
        item.update(title=fields.get("title") or fallback_title, artist=fields.get("artist") or fallback_artist, album=fields.get("album") or "", duration_ms=duration, mime=mime, cover_detected=cover)
        item["metadata_sources"] = {key: "EMBEDDED" if fields.get(key) else "FILENAME" if item[key] else "UNKNOWN" for key in ("title", "artist", "album")}
        item["metadata_sources"]["duration_ms"] = source
        for key, label in (("title", "歌名"), ("artist", "歌手")):
            if not item[key].strip():
                item["metadata_issues"].append(label + "缺失")
        if any(len(item[key]) > 120 for key in ("title", "artist", "album")):
            item["metadata_issues"].append("字段超过120字符")
        item["eligible"] = not item["metadata_issues"]
        item["status"] = "READY" if item["eligible"] else "NEEDS_METADATA"
        if analyze:
            from music.auto_tag import analyze_tags

            analysis = analyze_tags(data, item["extension"], path.name, fields)
            analysis["input_sha256"] = fingerprint
            item["tag_analysis"] = analysis
            item["tag_suggestions"] = analysis["candidates"]
    except (OSError, ValueError, RuntimeError, ValidationError, struct.error, wave.Error) as error:
        item["metadata_issues"] = error.messages if isinstance(error, ValidationError) else [str(error)]
    return item


def scan_local_catalog(source_root, *, max_items=500, existing_hashes=(), analyze=False):
    if type(max_items) is not int or not 1 <= max_items <= MAX_SCAN_ITEMS:
        raise ValueError("每次扫描数量必须为1至500首")
    try:
        root = Path(source_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("素材目录不是文件夹")
    except OSError as error:
        raise ValueError("素材目录不存在或不可读") from error
    items, skipped = [], []
    seen = {value: "EXISTING:" + value for value in existing_hashes if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)}
    visited, truncated = 0, False
    def walk_error(error):
        skipped.append({"relative_path": "", "status": "READ_ERROR", "reason": "子目录不可读"})
    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(directories, key=str.casefold):
            path = Path(directory) / name
            if _is_link(path):
                directories.remove(name)
                skipped.append({"relative_path": path.relative_to(root).as_posix(), "status": "UNSAFE_PATH", "reason": "跳过链接目录"})
        directories.sort(key=str.casefold)
        for name in sorted(filenames, key=str.casefold):
            path = Path(directory) / name
            extension = path.suffix.lower()
            if extension not in KNOWN_AUDIO_EXTENSIONS:
                continue
            if visited >= max_items:
                truncated = True
                break
            visited += 1
            if extension not in SUPPORTED_EXTENSIONS:
                skipped.append({"relative_path": path.relative_to(root).as_posix(), "status": "UNSUPPORTED_FORMAT", "reason": "暂不支持该格式，请使用MP3/WAV/OGG"})
                continue
            items.append(_scan_file(root, path, seen, analyze=analyze))
        if truncated:
            break
    eligible = sum(item["eligible"] for item in items)
    return {"schema_version": 2, "source_root": str(root), "items": items, "skipped": skipped, "truncated": truncated, "summary": {"scanned": visited, "supported": len(items), "duplicates": sum(item["status"] == "DUPLICATE" for item in items), "eligible": eligible, "rejected": visited - eligible}}
