import json
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from music.models import Song, SongTag, Tag, User


def suggest_tags(filename):
    candidates = {
        "A-Lin-天若有情": ("流行", "伤感", "夜晚"),
        "Capper&罗言RollFlash-雪 Distance": ("说唱", None, "通勤"),
        "DJ Dark&Mentol-Mood(Radio Edit)": ("电子", "动感", "运动"),
        "G.E.M.邓紫棋-句号": ("流行", "释然", "通勤"),
        "HITA-赤伶": ("国风", "悲壮", None),
        "Kirsty刘瑾睿-若把你(Live)": ("流行", "温柔", "放松"),
        "Lana Del Rey-Young And Beautiful": ("流行", "忧郁", "夜晚"),
        "Taylor Swift-Love Story": ("乡村流行", "浪漫", "通勤"),
        "草东没有派对-山海": ("摇滚", "激昂", None),
        "陈粒-虚拟": ("流行", None, None),
        "凤凰传奇-奢香夫人": ("民族流行", "动感", "运动"),
        "告五人-爱人错过": ("流行摇滚", None, "通勤"),
        "告五人-唯一": ("流行", "伤感", "夜晚"),
        "葛东琪-悬溺": ("流行", "忧郁", "夜晚"),
        "葛东琪-悬溺(伴奏)": ("流行", None, None),
        "郭顶-凄美地": ("流行摇滚", "忧郁", "夜晚"),
        "萧亚轩-遗失的心跳": ("流行", "伤感", "通勤"),
        "李玉刚&国风新语-赤伶(2021交响乐版)": ("国风", None, None),
    }
    stem = Path(filename).stem
    result = []
    for kind, name in zip(("STYLE", "MOOD", "SCENE"), candidates.get(stem, ())):
        if name:
            result.append({"kind": kind, "name": name, "confidence": "LOW" if kind == "SCENE" else "MEDIUM", "basis": "歌曲身份常识候选，未对当前文件试听；场景为使用建议", "needs_review": True})
    for word, label in (("钢琴版", "钢琴"), ("Orchestral", "管弦乐"), ("纯音乐", "纯音乐"), ("伴奏", "伴奏"), ("交响乐版", "管弦乐"), ("Remix", "混音版")):
        if word.casefold() in stem.casefold() and not any(item["name"] == label for item in result):
            result.append({"kind": "STYLE", "name": label, "confidence": "LOW", "basis": f"文件名版本词：{word}，未声学验证", "needs_review": True})
    return result


def normalize_metadata(filename, properties):
    stem = Path(filename).stem
    split = stem.split("-", 1)
    embedded_title = str(properties.get("title") or "").strip()
    embedded_artist = str(properties.get("artist") or "").strip()
    title = embedded_title or (split[1].strip() if len(split) == 2 else stem)
    artist = embedded_artist or (split[0].strip() if len(split) == 2 else "")
    duration = properties.get("duration_100ns")
    duration_ms = int(duration) // 10000 if type(duration) is int and duration > 0 else None
    if duration_ms is not None and not 1 <= duration_ms <= 86400000:
        duration_ms = None
    issues = []
    if not artist:
        issues.append("歌手缺失，不能从文件名确认")
    if duration_ms is None:
        issues.append("未取得有效媒体时长")
    if any(len(value) > 120 for value in (title, artist, str(properties.get("album") or ""))):
        issues.append("字段超过120字符")
    return {
        "title": title, "artist": artist, "album": str(properties.get("album") or "").strip(), "duration_ms": duration_ms,
        "metadata_sources": {"title": "WINDOWS_MEDIA_PROPERTY" if embedded_title else "FILENAME", "artist": "WINDOWS_MEDIA_PROPERTY" if embedded_artist else "FILENAME" if artist else "UNKNOWN", "album": "WINDOWS_MEDIA_PROPERTY" if properties.get("album") else "UNKNOWN", "duration_ms": "WINDOWS_MEDIA_PROPERTY" if duration_ms else "UNKNOWN"},
        "metadata_issues": issues, "tag_suggestions": suggest_tags(filename),
    }


def validate_catalog(document):
    if not isinstance(document, dict) or document.get("schema_version") != 1 or not isinstance(document.get("items"), list) or len(document["items"]) > 100:
        raise ValidationError("歌曲清单格式或数量无效")
    hashes = set()
    for item in document["items"]:
        if not isinstance(item, dict):
            raise ValidationError("歌曲条目无效")
        fingerprint = item.get("sha256", "")
        filename = item.get("filename", "")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint) or fingerprint in hashes:
            raise ValidationError("歌曲指纹无效或重复")
        hashes.add(fingerprint)
        if not isinstance(filename, str) or any(part in filename for part in ("/", "\\", "..")) or not filename.lower().endswith(".mp3"):
            raise ValidationError("文件名无效")
        for field in ("title", "artist", "album"):
            if not isinstance(item.get(field), str) or len(item[field]) > 120:
                raise ValidationError("歌曲字段无效")
        duration = item.get("duration_ms")
        if duration is not None and (type(duration) is not int or not 1 <= duration <= 86400000):
            raise ValidationError("歌曲时长无效")
        tags = item.get("tag_suggestions")
        if not isinstance(tags, list) or len(tags) > 10:
            raise ValidationError("候选标签无效")
        for tag in tags:
            if not isinstance(tag, dict) or tag.get("kind") not in {"STYLE", "MOOD", "SCENE"} or not isinstance(tag.get("name"), str) or not 1 <= len(tag["name"].strip()) <= 30 or tag.get("confidence") not in {"LOW", "MEDIUM"} or tag.get("needs_review") is not True or not isinstance(tag.get("basis"), str):
                raise ValidationError("候选标签字段无效")
        item["eligible"] = bool(item["title"].strip() and item["artist"].strip() and duration)
    return document["items"]


def load_catalog():
    path = settings.BASE_DIR.parent / "specs/music/system/local-catalog.json"
    if path.stat().st_size > 1024 * 1024:
        raise ValidationError("清单超过允许大小")
    return validate_catalog(json.loads(path.read_text(encoding="utf-8")))


@transaction.atomic
def import_drafts(*, items, selected_hashes, owner_id, accept_tags=False):
    validate_catalog({"schema_version": 1, "items": items})
    indexed = {item["sha256"]: item for item in items}
    selected = sorted(set(selected_hashes))
    if not selected or any(fingerprint not in indexed or not indexed[fingerprint]["eligible"] for fingerprint in selected):
        raise ValidationError("所选歌曲无效或资料不完整")
    User.objects.select_for_update().get(id=owner_id, is_active=True, is_staff=True)
    created, skipped = 0, 0
    for fingerprint in selected:
        item = indexed[fingerprint]
        marker = "LOCAL_DRAFT_SHA256:" + fingerprint
        if Song.objects.filter(source_name=marker).exists():
            skipped += 1
            continue
        candidates = item["tag_suggestions"]
        note = "本机学习项目资料草稿；音频未复制、未发布；时长来源为Windows媒体属性。原文件：" + item["filename"]
        if candidates:
            note += "\n人工辅助候选（未音频验证）：" + "、".join(tag["name"] + "[" + tag["confidence"] + "]" for tag in candidates)
        song = Song.objects.create(title=item["title"].strip(), artist=item["artist"].strip(), album=item["album"].strip(), duration_ms=item["duration_ms"], mime="audio/mpeg", active=False, playback_allowed=False, redistribution_allowed=False, checked_at=None, file_path="", source_name=marker, source_url="", license_name="", license_url="", attribution_text=note)
        if accept_tags:
            for candidate in candidates:
                tag, _ = Tag.objects.get_or_create(kind=candidate["kind"], name=candidate["name"].strip(), defaults={"active": True})
                SongTag.objects.get_or_create(song=song, tag=tag)
        created += 1
    return {"created": created, "skipped": skipped}
