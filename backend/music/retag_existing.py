import hashlib
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from music.media import MAX_AUDIO_BYTES
from music.models import Song, SongTag, Tag
from music.tag_library import TAG_LIBRARY


def validate_plan(plan):
    if plan.get("schema_version") != 1 or plan.get("policy_version") != "multilabel-minimum-v2" or plan.get("operation") != "REPLACE_EXISTING_40_SONG_TAGS_ONLY" or len(plan.get("items", [])) != 40:
        raise ValueError("只允许已批准的40首统一重标清单")
    allowed = {(kind, name) for kind, _, entries in TAG_LIBRARY for name, _ in entries}
    seen = set()
    for item in plan["items"]:
        fingerprint = item.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or fingerprint in seen:
            raise ValueError("清单音频指纹无效或重复")
        seen.add(fingerprint)
        candidates = item.get("candidates", [])
        pairs = [(candidate.get("kind"), candidate.get("name")) for candidate in candidates]
        if len(set(pairs)) != len(pairs) or any(pair not in allowed for pair in pairs):
            raise ValueError("清单包含重复或非正式标签")
        if any(candidate.get("needs_review") is not True or candidate.get("auto_apply") is not False or candidate.get("evidence_level") not in {"LOW_FALLBACK", "SUPPORTED_HEURISTIC", "RULE_SUGGESTION"} for candidate in candidates):
            raise ValueError("清单缺少候选与补位来源标记")
        for kind, maximum in (("STYLE", 2), ("MOOD", 3), ("SCENE", 2)):
            if not 1 <= sum(pair[0] == kind for pair in pairs) <= maximum:
                raise ValueError("每首须曲风1—2、情绪1—3、场景1—2")


def verify_media(song, expected):
    relative = Path(song.file_path)
    if not song.file_path or relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("目标歌曲音频路径无效")
    root = Path(settings.MEDIA_ROOT).resolve(strict=True)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("目标音频不允许链接/重解析路径")
    if not path.resolve(strict=True).is_relative_to(root) or not 0 < path.stat().st_size <= MAX_AUDIO_BYTES:
        raise ValueError("目标音频位置或大小无效")
    with path.open("rb") as stream:
        data = stream.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("目标歌曲音频指纹不匹配，整批停止")


def save_backup(path, payload):
    root = Path(settings.BASE_DIR).parent / "local-ai/retag-backups"
    if not path.resolve().is_relative_to(root):
        raise ValueError("备份必须保存在项目私有local-ai/retag-backups")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, cls=DjangoJSONEncoder, allow_nan=False)
        stream.flush()
        import os
        os.fsync(stream.fileno())


def diagnose_matches(plan):
    validate_plan(plan)
    grouped = {}
    unmatched = []
    markers = {"LOCAL_DRAFT_SHA256:" + item["sha256"]: item for item in plan["items"]}
    for song in Song.objects.order_by("pk").values("id", "title", "artist", "active", "source_name"):
        marker = song.pop("source_name")
        if marker in markers:
            grouped.setdefault(marker, []).append(song)
        else:
            song["has_import_fingerprint"] = bool(re.fullmatch(r"LOCAL_DRAFT_SHA256:[0-9a-f]{64}", marker))
            unmatched.append(song)
    missing = []
    duplicates = []
    for marker, item in markers.items():
        rows = grouped.get(marker, [])
        detail = dict(filename=item.get("filename", item["sha256"][:12]), sha256=item["sha256"], songs=rows)
        if not rows:
            missing.append(detail)
        elif len(rows) > 1:
            duplicates.append(detail)
    return dict(status="READ_ONLY_MATCH_DIAGNOSIS", expected=40, matched_unique=sum(len(rows) == 1 for rows in grouped.values()), missing=missing, duplicates=duplicates, non_target_songs=unmatched)


@transaction.atomic
def retag_existing(plan, *, apply=False, backup_path=None):
    validate_plan(plan)
    markers = {"LOCAL_DRAFT_SHA256:" + item["sha256"]: item for item in plan["items"]}
    songs = list(Song.objects.select_for_update().filter(source_name__in=markers).order_by("pk"))
    if len(songs) != 40 or {song.source_name for song in songs} != set(markers):
        diagnosis = diagnose_matches(plan)
        examples = "、".join(item["filename"] for item in (diagnosis["missing"] + diagnosis["duplicates"])[:5])
        raise ValueError(f"40首精确指纹匹配失败：唯一匹配{diagnosis['matched_unique']}首，缺失{len(diagnosis['missing'])}首，重复{len(diagnosis['duplicates'])}组。示例：{examples}。请运行--diagnose生成只读明细；未改标签，未按歌名替代")
    original_fields = list(Song.objects.filter(pk__in=[song.pk for song in songs]).order_by("pk").values())
    song_ids = [song.pk for song in songs]
    old_relations = list(SongTag.objects.select_for_update().filter(song_id__in=song_ids).order_by("song_id", "tag_id").values("song_id", "tag_id", "weight"))
    pairs = {(candidate["kind"], candidate["name"]) for item in plan["items"] for candidate in item["candidates"]}
    existing = {(tag.kind, tag.name): tag for tag in Tag.objects.select_for_update().all() if (tag.kind, tag.name) in pairs}
    if any(not tag.active for tag in existing.values()):
        raise ValueError("目标标签中有停用项，未自动复活")
    for song in songs:
        verify_media(song, markers[song.source_name]["sha256"])
    planned_pairs = {(song.pk, candidate["kind"], candidate["name"], 1) for song in songs for candidate in markers[song.source_name]["candidates"]}
    current_pairs = set(SongTag.objects.filter(song_id__in=song_ids).values_list("song_id", "tag__kind", "tag__name", "weight"))
    if not apply:
        return dict(status="PREVIEW_ONLY", songs=40, old_relations=len(old_relations), new_relations=sum(len(item["candidates"]) for item in plan["items"]), missing_dictionary_tags=len(pairs - set(existing)), matches_plan=current_pairs == planned_pairs)
    if backup_path is None:
        raise ValueError("写入前必须提供新备份文件")
    plan_digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    save_backup(backup_path, dict(status="PRE_WRITE_BACKUP_NOT_COMMIT_RECEIPT", canonical_plan_sha256=plan_digest, plan=plan, songs=original_fields, song_tags=old_relations, existing_target_tags=[dict(id=tag.pk, kind=tag.kind, name=tag.name, active=tag.active) for tag in existing.values()]))
    for kind, name in sorted(pairs - set(existing)):
        tag, _ = Tag.objects.get_or_create(kind=kind, name=name, defaults={"active": True})
        if not tag.active:
            raise ValueError("目标标签已停用")
        existing[(kind, name)] = tag
    expected = []
    for song in songs:
        for candidate in markers[song.source_name]["candidates"]:
            expected.append((song.pk, existing[(candidate["kind"], candidate["name"])].pk, 1))
    SongTag.objects.filter(song_id__in=song_ids).delete()
    SongTag.objects.bulk_create([SongTag(song_id=song_id, tag_id=tag_id, weight=weight) for song_id, tag_id, weight in expected])
    actual = list(SongTag.objects.filter(song_id__in=song_ids).values_list("song_id", "tag_id", "weight"))
    if sorted(actual) != sorted(expected) or list(Song.objects.filter(pk__in=song_ids).order_by("pk").values()) != original_fields:
        raise ValueError("写入核验不符，整批回滚")
    return dict(status="VERIFIED_IN_TRANSACTION", songs=40, new_relations=len(expected), backup=str(backup_path))
