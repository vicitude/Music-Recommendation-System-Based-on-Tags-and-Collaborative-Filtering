from django.utils import timezone

from music.models import Tag, User


LIMITS = {Tag.STYLE: 2, Tag.MOOD: 3, Tag.SCENE: 2}


def checked_tags(tag_ids):
    if not isinstance(tag_ids, list) or not tag_ids or len(tag_ids) > 7 or any(type(value) is not int for value in tag_ids) or len(set(tag_ids)) != len(tag_ids):
        raise ValueError("标签选择无效，请勿重复选择。")
    tags = list(Tag.objects.filter(pk__in=tag_ids, active=True).order_by("kind", "id"))
    if len(tags) != len(tag_ids):
        raise ValueError("标签不存在或已停用，请刷新选项。")
    for kind, limit in LIMITS.items():
        if not 1 <= sum(tag.kind == kind for tag in tags) <= limit:
            raise ValueError("每类至少选择1项；曲风最多2项、情绪最多3项、场景最多2项。")
    return tags


def edited_candidates(item, owner_id):
    edit = item["candidate_edit"]
    if edit.get("input_sha256") != item["sha256"] or edit.get("owner_id") != owner_id:
        raise ValueError("人工候选身份不符，请重新保存。")
    return [dict(kind=tag.kind, name=tag.name, source="MANUAL", evidence_level="MANUAL_EDIT") for tag in checked_tags(edit.get("tag_ids"))]


def save_candidate_edit(batch_id, owner_id, fingerprint, values):
    from music.batch_import import _source_lock, load_batch, save_batch, source_root
    from music.minimum_candidates import confirmed_candidates

    owner = User.objects.get(pk=owner_id, is_active=True, is_staff=True)
    if not owner.has_perms(["music.add_song", "music.change_song", "music.add_tag", "music.add_songtag"]):
        raise ValueError("没有保存候选标签的权限。")
    if not isinstance(values, list) or any(not value.isascii() or not value.isdigit() or len(value) > 18 for value in values):
        raise ValueError("标签编号无效。")
    tags = checked_tags([int(value) for value in values])
    root = source_root()
    with _source_lock(root):
        batch = load_batch(batch_id, owner_id)
        if batch["source_root"] != str(root):
            raise ValueError("素材目录配置已改变，请重新扫描。")
        matches = [item for item in batch["items"] if item.get("sha256") == fingerprint and item.get("status") in {"READY", "NEEDS_METADATA"}]
        if len(matches) != 1:
            raise ValueError("所选歌曲不属于本批次或不可编辑。")
        item = matches[0]
        confirmed_candidates(item)
        item["candidate_edit"] = dict(input_sha256=fingerprint, owner_id=owner_id, tag_ids=[tag.pk for tag in tags], saved_at=timezone.now().isoformat())
        save_batch(batch)
    return batch
