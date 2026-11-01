import io
import re
import wave
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse

from music.api.errors import ApiError
from music.models import Song, User


MAX_AUDIO_BYTES = 31457280
MIME_BY_EXTENSION = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg"}


def controlled_media_path(file_path: str) -> Path | None:
    if not file_path:
        return None
    relative_path = Path(file_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None
    try:
        media_root = Path(settings.MEDIA_ROOT).resolve()
        media_path = (media_root / relative_path).resolve()
        if media_root in media_path.parents and media_path.is_file():
            return media_path
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def playable_media_path(song: Song) -> Path | None:
    if not song.active or not song.playback_allowed or song.checked_at is None or not song.file_path:
        return None
    return controlled_media_path(song.file_path)


def inspect_audio(data: bytes, filename: str) -> tuple[str, int | None]:
    extension = Path(filename).suffix.lower()
    if extension not in MIME_BY_EXTENSION or not 1 <= len(data) <= MAX_AUDIO_BYTES:
        raise ValidationError("音频为空、超过30MiB或扩展名不支持")
    duration = None
    if extension == ".wav":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE" or int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValidationError("WAV结构或长度不合法")
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
                if audio.getcomptype() != "NONE" or channels not in {1, 2} or not 1 <= width <= 4 or not 8000 <= rate <= 192000 or frames == 0:
                    raise ValidationError("WAV参数不支持")
                remaining = frames
                while remaining:
                    count = min(remaining, 65536)
                    if len(audio.readframes(count)) != count * channels * width:
                        raise ValidationError("WAV数据被截断")
                    remaining -= count
                duration = (1000 * frames + rate - 1) // rate
        except (wave.Error, EOFError, OSError, ValueError):
            raise ValidationError("无法解析WAV") from None
    elif extension == ".ogg":
        if len(data) < 27 or data[:4] != b"OggS" or data[4] != 0 or not data[5] & 2:
            raise ValidationError("OGG首页面不合法")
        segments = data[26]
        if not segments or len(data) < 27 + segments or len(data) < 27 + segments + sum(data[27:27 + segments]):
            raise ValidationError("OGG首页面被截断")
    else:
        offset = 0
        if data[:3] == b"ID3":
            if len(data) < 10 or data[3] not in {2, 3, 4} or data[4] == 255 or any(byte & 128 for byte in data[6:10]):
                raise ValidationError("ID3头不合法")
            tag_size = sum(byte << shift for byte, shift in zip(data[6:10], (21, 14, 7, 0)))
            offset = 10 + tag_size + (10 if data[3] == 4 and data[5] & 16 else 0)
        header = data[offset:offset + 4]
        if len(header) != 4 or header[0] != 255 or header[1] & 224 != 224 or (header[1] >> 3) & 3 == 1 or (header[1] >> 1) & 3 == 0 or header[2] >> 4 in {0, 15} or (header[2] >> 2) & 3 == 3:
            raise ValidationError("未找到合法MPEG音频帧头")
    return MIME_BY_EXTENSION[extension], duration


def store_audio(*, data: bytes, extension: str) -> str:
    inspect_audio(data, "audio" + extension)
    root = Path(settings.MEDIA_ROOT).resolve()
    directory = root / "songs"
    if not directory.resolve().is_relative_to(root):
        raise ValidationError("媒体目录不安全")
    directory.mkdir(parents=True, exist_ok=True)
    relative = f"songs/{uuid4().hex}{extension.lower()}"
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValidationError("媒体路径越界")
    with target.open("xb") as output:
        output.write(data)
    return relative


def resolve_media(*, song_id: int, user_id: int) -> tuple[Path, str, int]:
    if not User.objects.filter(id=user_id, is_active=True).exists():
        raise ApiError("AUTH_REQUIRED")
    try:
        song = Song.objects.get(id=song_id, active=True)
    except Song.DoesNotExist:
        raise ApiError("NOT_FOUND", ["song_id"]) from None
    if not song.playback_allowed or song.checked_at is None:
        raise ApiError("PERMISSION_DENIED")
    path = playable_media_path(song)
    if path is None or song.mime not in MIME_BY_EXTENSION.values():
        raise ApiError("MEDIA_UNAVAILABLE")
    try:
        size = path.stat().st_size
    except OSError:
        raise ApiError("MEDIA_UNAVAILABLE") from None
    if not 1 <= size <= MAX_AUDIO_BYTES:
        raise ApiError("MEDIA_UNAVAILABLE")
    return path, song.mime, size


def media_response(*, path: Path, mime: str, range_header: str | None) -> StreamingHttpResponse:
    audio = None
    try:
        audio = path.open("rb")
        audio.seek(0, 2)
        size = audio.tell()
        audio.seek(0)
    except OSError:
        if audio is not None:
            audio.close()
        raise ApiError("MEDIA_UNAVAILABLE") from None
    if not 1 <= size <= MAX_AUDIO_BYTES:
        audio.close()
        raise ApiError("MEDIA_UNAVAILABLE")
    start, end, response_status = 0, size - 1, 200
    if range_header is not None:
        match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", range_header) if len(range_header) <= 100 else None
        valid = match is not None and bool(match[1] or match[2])
        if valid:
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
                valid = start <= end and start < size
            else:
                suffix = int(match[2])
                valid = suffix > 0
                start = max(0, size - suffix)
        if not valid:
            audio.close()
            response = StreamingHttpResponse(iter(()), status=416, content_type=mime)
            response["Content-Range"] = f"bytes */{size}"
            response["Content-Length"] = "0"
            response["Accept-Ranges"] = "bytes"
            response["Cache-Control"] = "private,no-store"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        response_status = 206
    try:
        audio.seek(start)
    except OSError:
        audio.close()
        raise ApiError("MEDIA_UNAVAILABLE") from None

    def chunks():
        remaining = end - start + 1
        try:
            while remaining:
                chunk = audio.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            audio.close()

    response = StreamingHttpResponse(chunks(), status=response_status, content_type=mime)
    response["Content-Length"] = str(end - start + 1)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private,no-store"
    response["X-Content-Type-Options"] = "nosniff"
    if response_status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response._resource_closers.append(audio.close)
    return response
