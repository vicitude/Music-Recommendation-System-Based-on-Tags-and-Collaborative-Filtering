from music.models import Tag
from music.tag_library import TAG_LIBRARY


VERSION = "formal-v1"
ARCHETYPES = (
    ("流行探索者", ("流行", "R&B"), ("欢快", "治愈", "甜蜜"), ("驾车", "清晨")),
    ("摇滚能量派", ("摇滚", "金属"), ("热血励志", "活力", "自信"), ("运动", "夜晚")),
    ("电子夜行者", ("电子", "慢摇DJ"), ("狂欢", "活力", "孤独"), ("夜晚", "游戏直播")),
    ("民谣故事党", ("民谣", "乡村"), ("思念", "悲伤", "平静"), ("清晨", "驾车")),
    ("轻音乐专注者", ("轻音乐", "古典"), ("平静", "放松", "治愈"), ("学习", "工作")),
    ("国风爱好者", ("国风", "中国音乐", "戏曲"), ("思念", "浪漫", "悲伤"), ("夜晚", "学习")),
    ("爵士慢生活", ("爵士", "蓝调", "放克"), ("放松", "浪漫", "平静"), ("小酒馆", "约会")),
    ("节奏舞曲派", ("电子", "嘻哈说唱", "R&B"), ("欢快", "活力", "狂欢"), ("运动", "游戏直播")),
)
HOURS = (2, 6, 9, 12, 15, 18, 21, 23)
PREFERRED_BUCKETS = (1, 5, 6, 1, 2, 6, 6, 5)


def formal_tags():
    allowed = {(kind, name) for kind, _, entries in TAG_LIBRARY for name, _ in entries}
    tags = {kind: {} for kind, _ in Tag.KIND_CHOICES}
    for tag in Tag.objects.filter(active=True).order_by("id"):
        if (tag.kind, tag.name) in allowed:
            tags[tag.kind][tag.name] = tag
    return tags
