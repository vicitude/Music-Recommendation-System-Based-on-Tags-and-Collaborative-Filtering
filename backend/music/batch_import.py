import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from music.local_scanner import safe_source, scan_local_catalog
from music.media import MAX_AUDIO_BYTES, inspect_audio, store_audio
from music.models import Song, SongTag, Tag, User


def source_root():
    root = Path(getattr(settings, "LOCAL_IMPORT_SOURCE_ROOT", "D:/AAA素材库/song")).resolve(strict=True)
    media = Path(settings.MEDIA_ROOT).resolve()
    if not root.is_dir() or root.is_relative_to(media) or media.is_relative_to(root):
        raise ValueError("素材目录必须与项目媒体目录分离")
    return root


def batch_root():
    root = Path(getattr(settings, "LOCAL_IMPORT_BATCH_ROOT", settings.BASE_DIR.parent / "local-import-batches")).resolve()
    media = Path(settings.MEDIA_ROOT).resolve()
    source = Path(getattr(settings, "LOCAL_IMPORT_SOURCE_ROOT", "D:/AAA素材库/song")).resolve()
    if root.is_relative_to(media) or media.is_relative_to(root) or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("批次报告、素材目录和公开媒体目录必须分离")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _batch_path(batch_id):
    if str(UUID(batch_id)) != batch_id:
        raise ValueError("批次编号无效")
    return batch_root() / (batch_id + ".json")


def save_batch(batch):
    target = _batch_path(batch["batch_id"])
    temporary = target.with_name("temp_" + uuid4().hex + ".json")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(batch, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)


def load_batch(batch_id, owner_id):
    target = _batch_path(batch_id)
    if target.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("批次报告过大")
    batch = json.loads(target.read_text(encoding="utf-8"))
    if batch.get("batch_id") != batch_id or batch.get("owner_id") != owner_id:
        raise ValueError("批次不存在或不属于当前账号")
    return batch


@contextmanager
def _source_lock(root):
    name = hashlib.sha256(str(root).casefold().encode()).hexdigest()
    with (batch_root() / (name + ".lock")).open("a+b") as lock:
        lock.seek(0, 2)
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("已有本目录导入正在运行，请稍后重试") from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def create_batch(owner_id, *, analyze=False):
    root = source_root()
    report_root = batch_root()
    if root.is_relative_to(report_root) or report_root.is_relative_to(root):
        raise ValueError("素材目录与私有报告目录必须分离")
    batch = scan_local_catalog(root, analyze=analyze)
    batch.update(batch_id=str(uuid4()), owner_id=owner_id, created_at=timezone.now().isoformat(), results=[])
    save_batch(batch)
    return batch


def recent_batches(owner_id):
    batches = []
    for path in batch_root().glob("*.json"):
        try:
            batch = load_batch(path.stem, owner_id)
            batches.append({"batch_id": batch["batch_id"], "created_at": batch.get("created_at", ""), "analyzed": sum(item.get("minimum_analysis", {}).get("status") == "CANDIDATES" for item in batch.get("items", []))})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(batches, key=lambda batch: batch["created_at"], reverse=True)[:10]


def execute_batch(batch_id, owner_id, *, accept_high_tags=False, accept_model_tags=False, publish=False):
    if publish and not accept_model_tags:
        raise ValueError("直接发布必须采用已确认的多标签候选")
    if publish:
        owner = User.objects.get(pk=owner_id, is_active=True, is_staff=True)
        if not owner.has_perms(["music.add_song", "music.change_song"]):
            raise ValueError("没有导入并发布歌曲的权限")
    if accept_high_tags and accept_model_tags:
        raise ValueError("旧规则与多标签确认不可混用")
    if accept_high_tags or accept_model_tags:
        owner = User.objects.get(pk=owner_id, is_active=True, is_staff=True)
        if not owner.has_perms(["music.add_tag", "music.add_songtag"]):
            raise ValueError("没有写入标签的权限")
    root = source_root()
    with _source_lock(root):
        batch = load_batch(batch_id, owner_id)
        if batch["source_root"] != str(root):
            raise ValueError("素材目录配置已改变，请重新扫描")
        previous = {entry["relative_path"]: entry for entry in batch["results"]}
        results = []
        for item in batch["items"]:
            relative = item["relative_path"]
            old = previous.get(relative)
            entry = {"relative_path": relative, "status": "skipped", "message": "资料不完整、文件异常或批内重复，未导入"}
            if old and old["status"] == "created":
                entry = old
            elif item["eligible"]:
                stored = None
                try:
                    marker = "LOCAL_DRAFT_SHA256:" + item["sha256"]
                    with transaction.atomic():
                        existing = Song.objects.filter(source_name=marker).first()
                        if existing:
                            entry.update(message="指纹已存在，不覆盖", song_id=existing.pk)
                        else:
                            model_tags = []
                            if accept_model_tags:
                                from music.minimum_candidates import confirmed_candidates
                                model_tags = confirmed_candidates(item)
                                if item.get("candidate_edit"):
                                    from music.candidate_edits import edited_candidates
                                    model_tags = edited_candidates(item, owner_id)
                                for candidate in model_tags:
                                    if Tag.objects.filter(kind=candidate["kind"], name=candidate["name"], active=False).exists():
                                        raise ValueError("候选包含停用标签，请先调整标签字典")
                            path = safe_source(root, relative)
                            if path.stat().st_size != item["bytes"] or not 1 <= item["bytes"] <= MAX_AUDIO_BYTES:
                                raise ValueError("源文件大小已改变，请重新扫描")
                            with path.open("rb") as source:
                                data = source.read(MAX_AUDIO_BYTES + 1)
                            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                                raise ValueError("源文件内容已改变，请重新扫描")
                            mime, _ = inspect_audio(data, relative)
                            stored = store_audio(data=data, extension=item["extension"])
                            song = Song.objects.create(title=item["title"], artist=item["artist"], album=item["album"], duration_ms=item["duration_ms"], file_path=stored, mime=mime, active=False, playback_allowed=False, redistribution_allowed=False, checked_at=None, source_name=marker, source_url="", license_name="", license_url="", attribution_text="本地学习项目草稿；批次：" + batch_id + "；音频结构已检查，未试听；标签证据见私有批次报告，不含许可声明。")
                            applied = []
                            for candidate in model_tags:
                                tag, _ = Tag.objects.get_or_create(kind=candidate["kind"], name=candidate["name"], defaults={"active": True})
                                if not tag.active:
                                    raise ValueError("目标标签停用，未写入")
                                SongTag.objects.create(song=song, tag=tag)
                                applied.append(candidate)
                            analysis = item.get("tag_analysis", {})
                            if accept_high_tags and analysis.get("input_sha256") == item["sha256"]:
                                from music.auto_tag import RULE_VERSION, select_candidates

                                if analysis.get("rule_version") == RULE_VERSION:
                                    for candidate in select_candidates(analysis.get("candidates", [])):
                                        if candidate["confidence"] < 0.75:
                                            continue
                                        tag, _ = Tag.objects.get_or_create(kind=candidate["kind"], name=candidate["name"], defaults={"active": True})
                                        if tag.active:
                                            SongTag.objects.get_or_create(song=song, tag=tag)
                                            applied.append(candidate)
                            entry.update(status="created", message="已复制音频并创建草稿，未发布", song_id=song.pk, applied_tags=applied)
                            if publish:
                                from music.publishing import publish_song
                                publish_song(song)
                                entry["message"] = "已导入并发布到前台"
                    if publish and entry.get("song_id") and entry["status"] != "created":
                        entry["message"] = "歌曲已入库，本次不覆盖；如未发布，请使用批量发布入口"
                except (OSError, ValueError, RuntimeError, ValidationError, DatabaseError) as error:
                    message = "；".join(error.messages) if isinstance(error, ValidationError) else str(error) if isinstance(error, ValueError) else "文件操作或数据库保存失败，可重试"
                    entry.update(status="failed", message=message)
                    if stored:
                        entry["unassociated_media"] = stored
                if old:
                    history = list(old.get("previous_unassociated_media", []))
                    if old.get("unassociated_media"):
                        history.append(old["unassociated_media"])
                    if history:
                        entry["previous_unassociated_media"] = history
            results.append(entry)
            batch["results"] = results + [pending for pending in batch["results"] if pending["relative_path"] not in {result["relative_path"] for result in results}]
            batch["updated_at"] = timezone.now().isoformat()
            save_batch(batch)
        batch["results"] = results
        batch["result_summary"] = {status: sum(entry["status"] == status for entry in results) for status in ("created", "skipped", "failed")}
        save_batch(batch)
        return batch
