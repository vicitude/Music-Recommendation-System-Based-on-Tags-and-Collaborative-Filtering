import hashlib
import logging
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from music.local_catalog import validate_catalog
from music.media import MAX_AUDIO_BYTES, inspect_audio, store_audio
from music.models import Song


logger = logging.getLogger(__name__)
SOURCE_ROOT = Path("D:/AAA素材库/song")


def catalog_audio_rows(items):
    markers = ["LOCAL_DRAFT_SHA256:" + item["sha256"] for item in items]
    indexed = {}
    for song in Song.objects.filter(source_name__in=markers).order_by("id"):
        indexed.setdefault(song.source_name, []).append(song)
    rows = []
    for item in items:
        songs = indexed.get("LOCAL_DRAFT_SHA256:" + item["sha256"], [])
        song = songs[0] if len(songs) == 1 else None
        selectable = False
        if not songs:
            state = "尚未导入资料"
        elif len(songs) != 1:
            state = "存在重复资料，需核对"
        elif song.file_path:
            state = "已关联，不覆盖"
        elif song.active or song.playback_allowed or song.checked_at is not None:
            state = "不是未核验草稿，需核对"
        else:
            state = "可关联音频"
            selectable = True
        rows.append({"item": item, "song": song, "state": state, "selectable": selectable})
    return rows


def read_local_audio(item, source_root):
    root = Path(source_root).resolve(strict=True)
    source = root / item["filename"]
    resolved = source.resolve(strict=True)
    if source.is_symlink() or resolved.parent != root or not resolved.is_file():
        raise ValidationError("文件位置不安全，未复制")
    expected_size = item.get("bytes")
    if type(expected_size) is not int or not 1 <= expected_size <= MAX_AUDIO_BYTES:
        raise ValidationError("清单大小无效或超过30MiB，未复制")
    if resolved.stat().st_size != expected_size:
        raise ValidationError("源文件大小与清单不一致，请重新核对资料")
    with resolved.open("rb") as audio:
        data = audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) != expected_size or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValidationError("源文件与清单不一致，请重新核对资料")
    inspect_audio(data, item["filename"])
    return data


def bind_local_audio(*, items, selected_hashes, source_root=None):
    validate_catalog({"schema_version": 1, "items": items})
    indexed = {item["sha256"]: item for item in items}
    selected = sorted(set(selected_hashes))
    if not selected or any(fingerprint not in indexed for fingerprint in selected):
        raise ValidationError("请从清单选择需要关联的歌曲")
    result = {"linked": 0, "skipped": 0, "failed": 0, "entries": []}
    for fingerprint in selected:
        item = indexed[fingerprint]
        stored = None
        status = "linked"
        message = "已关联，可进入歌曲编辑页试听"
        try:
            with transaction.atomic():
                songs = list(Song.objects.select_for_update().filter(source_name="LOCAL_DRAFT_SHA256:" + fingerprint).order_by("id"))
                if len(songs) != 1:
                    raise ValidationError("资料不存在或重复，请先核对资料草稿")
                song = songs[0]
                if song.file_path:
                    status, message = "skipped", "已有音频关联，未覆盖"
                else:
                    if song.active or song.playback_allowed or song.checked_at is not None:
                        raise ValidationError("仅允许关联未发布、未核验的资料草稿")
                    data = read_local_audio(item, SOURCE_ROOT if source_root is None else source_root)
                    stored = store_audio(data=data, extension=".mp3")
                    song.file_path, song.mime = stored, "audio/mpeg"
                    song.save(update_fields=["file_path", "mime"])
        except (ValidationError, OSError, ValueError, RuntimeError, DatabaseError) as error:
            status = "failed"
            if stored:
                logger.error("Unassociated local audio retained: %s", stored)
            if isinstance(error, ValidationError):
                message = "；".join(error.messages)
            else:
                message = "文件读取、复制或数据库保存失败；成功项保留，可能有未关联副本，请检查本机服务"
        result[status] += 1
        result["entries"].append({"filename": item["filename"], "status": status, "message": message})
    return result
