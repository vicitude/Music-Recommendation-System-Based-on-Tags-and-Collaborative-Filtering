from django.core.exceptions import ValidationError
from django.db import transaction

from music.models import Tag


TAG_LIBRARY = (
    (Tag.STYLE, "曲风 / 一级分类", (
        ("流行", "旋律和主歌副歌易辨认的主流音乐。"),
        ("嘻哈说唱", "以说唱、节奏化语言表达或嘻哈制作风格为主。"),
        ("电子", "合成器、电子鼓或电子音色在编曲中明显。"),
        ("中国音乐", "以中国音乐传统、器乐或审美体系为主要特征。"),
        ("轻音乐", "整体听感舒缓、易作背景，不强调强烈冲突。"),
        ("慢摇DJ", "偏慢速或舞曲化的DJ编排与律动。"),
        ("民谣", "常以原声乐器、叙事演唱或民谣编配为主。"),
        ("摇滚", "电吉他、贝斯和鼓组等摇滚编制或律动突出。"),
        ("国风", "流行作品中明显使用中国传统音色、旋律或戏曲元素。"),
        ("另类/独立", "具有独立创作审美或非主流编曲取向。"),
        ("实验", "结构、音色或制作方式具有明显实验性。"),
        ("民族歌曲", "具有明确民族音乐旋律、演唱或器乐特征。"),
        ("原声带", "影视、游戏、舞台等作品的配乐或原声带曲目。"),
        ("世界音乐", "不属于单一主流分类的地域性或跨文化音乐。"),
        ("二次元", "动画、漫画、游戏或二次元文化相关音乐。"),
        ("R&B", "节奏布鲁斯、转音、律动和切分节奏明显。"),
        ("戏曲", "戏曲唱腔、曲牌或戏曲表演传统为主要表达。"),
        ("古典", "古典音乐传统中的作品、演奏或编曲。"),
        ("金属", "失真吉他、强烈鼓组和金属音乐编制突出。"),
        ("新世纪", "持续音色、氛围、冥想或新世纪音乐取向明显。"),
        ("儿童", "面向儿童创作或具有明确儿童音乐属性。"),
        ("爵士", "摇摆节奏、爵士和声或即兴演奏明显。"),
        ("蓝调", "蓝调式旋律、和声或演唱表达明显。"),
        ("乡村", "原声吉他、班卓琴或乡村音乐律动明显。"),
        ("雷鬼", "反拍节奏和雷鬼律动突出。"),
        ("拉丁音乐", "桑巴、探戈、拉丁流行等拉丁节奏明显。"),
        ("放克", "贝斯线条和切分节奏突出，整体律动鲜明。"),
    )),
    (Tag.MOOD, "情绪 / 听感", (
        ("狂欢", "整体具有庆祝、热闹和群体兴奋感。"),
        ("热血励志", "传递拼搏、振奋、向前或战斗感。"),
        ("活力", "节奏、能量或律动鲜明，容易带动身体。"),
        ("欢快", "整体轻快愉悦，容易产生开心感。"),
        ("甜蜜", "声音或表达具有轻松亲密的甜蜜感。"),
        ("自信", "表达坚定、从容、积极或自我肯定。"),
        ("浪漫", "整体具有亲密、爱意或浪漫氛围。"),
        ("放松", "声音和节奏舒缓，适合缓解紧绷感。"),
        ("治愈", "听感偏安慰、舒缓或温暖，不代表医疗效果。"),
        ("思念", "整体表达想念、牵挂或远方感。"),
        ("平静", "情绪起伏较小，听感安稳。"),
        ("孤独", "突出独处、疏离或寂寞感。"),
        ("悲伤", "有明显失落、难过或低落情绪。"),
        ("苦情", "长期压抑、纠结或悲苦表达明显。"),
        ("抑郁", "偏低沉、内敛或持续惆怅的听感。"),
    )),
    (Tag.SCENE, "后台标准场景 / 音乐适配", (
        ("清晨", "适合一天开始时的清新或舒缓氛围。"),
        ("夜晚", "适合夜间聆听的氛围，不代表歌曲只能夜间播放。"),
        ("助眠", "低刺激、舒缓或持续性较强的背景候选。"),
        ("学习", "适合作为学习背景，是否分心因人而异。"),
        ("工作", "适合作为工作背景，需结合人声和节奏判断。"),
        ("运动", "节奏、能量或律动适合活动身体。"),
        ("驾车", "适合驾驶背景，使用时仍需注意道路安全。"),
        ("约会", "适合亲密交流氛围，属于使用建议而非音频事实。"),
        ("小酒馆", "适合轻松社交或小型聚会氛围，属于使用建议。"),
        ("KTV", "适合演唱、跟唱或聚会互动，属于使用建议。"),
        ("游戏直播", "适合作为游戏或直播背景，属于使用建议。"),
    )),
)


EXTENDED_SCENES = {
    "通勤": ("驾车", "工作"),
    "图书馆": ("学习",),
    "咖啡厅": ("工作", "放松"),
    "散步": ("清晨", "夜晚"),
    "旅行": ("驾车", "工作"),
    "独处": ("夜晚", "助眠"),
    "聚会": ("KTV", "小酒馆", "游戏直播"),
    "跑步": ("运动",),
    "健身": ("运动",),
    "阅读": ("学习", "助眠"),
    "冥想": ("助眠",),
    "午后": ("工作", "清晨"),
}


LEGACY_TAG_ALIASES = {
    (Tag.STYLE, "说唱"): (Tag.STYLE, "嘻哈说唱"),
    (Tag.STYLE, "节奏布鲁斯"): (Tag.STYLE, "R&B"),
    (Tag.STYLE, "灵魂乐"): (Tag.STYLE, "R&B"),
    (Tag.STYLE, "电子舞曲"): (Tag.STYLE, "电子"),
    (Tag.STYLE, "迪斯科"): (Tag.STYLE, "慢摇DJ"),
    (Tag.STYLE, "拉丁"): (Tag.STYLE, "拉丁音乐"),
    (Tag.STYLE, "民族流行"): (Tag.STYLE, "民族歌曲"),
    (Tag.STYLE, "流行摇滚"): (Tag.STYLE, "流行"),
    (Tag.STYLE, "民谣流行"): (Tag.STYLE, "民谣"),
    (Tag.STYLE, "乡村流行"): (Tag.STYLE, "乡村"),
    (Tag.MOOD, "伤感"): (Tag.MOOD, "悲伤"),
    (Tag.MOOD, "忧郁"): (Tag.MOOD, "抑郁"),
    (Tag.MOOD, "激昂"): (Tag.MOOD, "热血励志"),
    (Tag.MOOD, "热血"): (Tag.MOOD, "热血励志"),
    (Tag.MOOD, "动感"): (Tag.MOOD, "活力"),
    (Tag.MOOD, "温柔"): (Tag.MOOD, "放松"),
    (Tag.STYLE, "钢琴"): (Tag.STYLE, "轻音乐"),
    (Tag.STYLE, "管弦乐"): (Tag.STYLE, "古典"),
    (Tag.STYLE, "纯音乐"): (Tag.STYLE, "轻音乐"),
    (Tag.STYLE, "伴奏"): (Tag.STYLE, "轻音乐"),
    (Tag.STYLE, "混音版"): (Tag.STYLE, "电子"),
}


def formal_tag_keys():
    return {f"{kind}:{name}" for kind, _, entries in TAG_LIBRARY for name, _ in entries}


def canonical_tag(kind, name):
    if kind == Tag.SCENE and name in EXTENDED_SCENES:
        return kind, EXTENDED_SCENES[name][0]
    legacy_fallbacks = {
        (Tag.MOOD, chr(0x91ca) + chr(0x7136)): (Tag.MOOD, chr(0x5e73) + chr(0x9759)),
        (Tag.MOOD, chr(0x60b2) + chr(0x58ee)): (Tag.MOOD, chr(0x60b2) + chr(0x4f24)),
        (Tag.SCENE, chr(0x653e) + chr(0x677e)): (Tag.SCENE, chr(0x52a9) + chr(0x7720)),
    }
    if (kind, name) in legacy_fallbacks:
        return legacy_fallbacks[(kind, name)]
    return LEGACY_TAG_ALIASES.get((kind, name), (kind, name))


def is_formal_tag(kind, name):
    target_kind, target_name = canonical_tag(kind, name)
    return f"{target_kind}:{target_name}" in formal_tag_keys()


def library_groups():
    existing = {(tag.kind, tag.name): tag for tag in Tag.objects.all().order_by("kind", "name", "id")}
    groups = []
    for kind, title, entries in TAG_LIBRARY:
        rows = []
        for name, description in entries:
            tag = existing.pop((kind, name), None)
            rows.append({"key": f"{kind}:{name}", "name": name, "description": description, "tag": tag})
        groups.append({"title": title, "items": rows})
    return groups, list(existing.values())


@transaction.atomic
def import_library(selected_keys):
    indexed = {f"{kind}:{name}": (kind, name) for kind, _, entries in TAG_LIBRARY for name, _ in entries}
    if not selected_keys or len(selected_keys) > len(indexed) or any(key not in indexed for key in selected_keys):
        raise ValidationError(f"请选择新词表中的有效标签，最多{len(indexed)}项")
    created, skipped = 0, 0
    for key in sorted(set(selected_keys)):
        kind, name = indexed[key]
        _, new = Tag.objects.get_or_create(kind=kind, name=name, defaults={"active": True})
        created += int(new)
        skipped += int(not new)
    return {"created": created, "skipped": skipped}
