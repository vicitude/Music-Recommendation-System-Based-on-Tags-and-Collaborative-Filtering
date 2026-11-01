import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    workspace = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(workspace / "backend"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
    import django
    django.setup()
    from music.local_catalog import normalize_metadata, validate_catalog
    from music.media import inspect_audio, MAX_AUDIO_BYTES
    root = Path("D:/AAA素材库/song").resolve(strict=True)
    items, seen, duplicates = [], {}, []
    properties_list = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    for properties in properties_list:
        filename = properties["filename"]
        path = root / filename
        if path.is_symlink() or path.parent.resolve() != root or path.suffix.lower() != ".mp3":
            raise ValueError("Unexpected source")
        with path.open("rb") as audio:
            data = audio.read(MAX_AUDIO_BYTES + 1)
        inspect_audio(data, filename)
        fingerprint = hashlib.sha256(data).hexdigest()
        if fingerprint in seen:
            duplicates.append({"filename": filename, "same_as": seen[fingerprint], "sha256": fingerprint})
            continue
        seen[fingerprint] = filename
        items.append({"filename": filename, "sha256": fingerprint, "bytes": len(data), "rights_status": "UNVERIFIED", "draft_only": True, **normalize_metadata(filename, properties)})
    document = {"schema_version": 1, "prepared_on": "2026-10-30", "source_directory": str(root), "method": "WINDOWS_SHELL_PROPERTY_SYSTEM", "tag_method": "ASSISTED_CANDIDATES_NOT_AUDIO_ANALYSIS", "duplicates": duplicates, "items": items}
    validate_catalog(document)
    review = ["# 本地歌曲资料与候选标签核对表", "", "资料来源：Windows媒体属性，缺失字段才回退文件名；时长不是完整解码证明。标签为人工辅助候选，未试听、未联网核实；场景为使用建议，全部待核对。生成此表不等于已入库或发布。", "", "| 歌名 | 歌手 | 时长 | 专辑 | 候选标签 | 待核对 |", "|---|---|---|---|---|---|"]
    for item in items:
        duration = item["duration_ms"]
        formatted = str(duration // 60000) + ":" + str(duration // 1000 % 60).zfill(2) if duration else "未知"
        labels = "、".join(tag["name"] + "(" + tag["kind"] + "/" + tag["confidence"] + ")" for tag in item["tag_suggestions"]) or "无可靠候选，保留空白"
        values = [item["title"], item["artist"] or "未识别", formatted, item["album"] or "未识别", labels, "；".join(item["metadata_issues"]) or "候选标签仍需核对"]
        review.append("| " + " | ".join(value.replace("|", " / ").replace("\n", " ") for value in values) + " |")
    review += ["", f"合计{len(items)}首独立音频；资料完整{sum(item['eligible'] for item in items)}首；待核对{sum(not item['eligible'] for item in items)}首；重复内容{len(duplicates)}项。", "", "草稿不复制音频、不开启播放、不自动核验版权；后台导入页可明确确认应用候选标签。缺少歌手的曲目暂不入库，不按歌名猜创作者。"]
    patch = "*** Begin Patch\n"
    for name, content in [("local-catalog.json", json.dumps(document, ensure_ascii=False, indent=2)), ("local-catalog-review.md", "\n".join(review))]:
        path = "specs/music/system/" + name
        target = workspace / path
        if target.exists():
            raise ValueError("Output exists; use an explicit reviewed update patch")
        patch += "*** Add File: " + path + "\n" + "".join("+" + line + "\n" for line in content.splitlines())
    patch += "*** End Patch\n"
    sys.stdout.buffer.write(patch.encode("utf-8"))


if __name__ == "__main__":
    main()
