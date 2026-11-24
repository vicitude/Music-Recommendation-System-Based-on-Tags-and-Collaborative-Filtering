import math


MODEL_ID = "laion/clap-htsat-fused"
REVISION = "365dea6ef167def6676140ed93bbc43f84dabb28"
POLICY_VERSION = "clap-conservative-v1"
PROMPTS_VERSION = "clap-prompts-v2"
MAPPING_VERSION = "formal53-clap19-v1"
LABELS = (
    ("STYLE", "流行", "pop music", "mainstream pop song with melodic vocals"),
    ("STYLE", "摇滚", "rock music", "rock song with electric guitars bass and drums"),
    ("STYLE", "电子", "electronic dance music", "electronic music with synthesizers and programmed beats"),
    ("STYLE", "民谣", "folk music", "acoustic folk song with acoustic guitar"),
    ("STYLE", "古典", "classical music", "classical orchestral instrumental music"),
    ("STYLE", "爵士", "jazz music", "jazz music with swing rhythms and improvisation"),
    ("STYLE", "嘻哈说唱", "hip hop music", "rap music with rhythmic rapping vocals and beats"),
    ("STYLE", "R&B", "rhythm and blues music", "R and B song with soulful singing and syncopated rhythms"),
    ("STYLE", "金属", "heavy metal music", "metal music with distorted electric guitars and heavy drums"),
    ("STYLE", "乡村", "country music", "country song with acoustic guitar and country singing"),
    ("STYLE", "蓝调", "blues music", "blues music with blues guitar and soulful vocals"),
    ("STYLE", "雷鬼", "reggae music", "reggae song with offbeat guitar and reggae rhythms"),
    ("STYLE", "放克", "funk music", "funk music with groovy bass and syncopated rhythms"),
    ("STYLE", "拉丁音乐", "Latin music", "music with Latin percussion and Latin dance rhythms"),
    ("MOOD", "活力", "energetic music", "music that sounds energetic and powerful"),
    ("MOOD", "平静", "calm music", "music that sounds peaceful and calm"),
    ("MOOD", "放松", "relaxing music", "music that sounds soothing and relaxed"),
    ("MOOD", "欢快", "happy upbeat music", "music that sounds cheerful and happy"),
    ("MOOD", "悲伤", "sad music", "music that sounds sad and melancholy"),
)
CONTROLS = (
    "This is a recording of a person speaking, not music.",
    "This is a recording of noise without music.",
    "This is a recording of a single steady electronic tone, not a song.",
)


def prompt_texts():
    return ["This is a recording of " + phrase + "." for _, _, *phrases in LABELS for phrase in phrases] + list(CONTROLS)


def segment_starts(duration_ms):
    if type(duration_ms) is not int or not 20000 <= duration_ms <= 86400000:
        return []
    last = duration_ms / 1000 - 10
    starts = []
    for value in (0.0, last / 2, last):
        if all(abs(value - previous) >= 10 for previous in starts):
            starts.append(round(value, 3))
    return starts


def decide_candidates(segments):
    valid = []
    for segment in segments:
        if segment.get("quality") != "OK":
            continue
        scores = segment.get("scores", [])
        if len(scores) != len(prompt_texts()) or any(type(score) not in (int, float) or not math.isfinite(score) or not -1.001 <= score <= 1.001 for score in scores):
            raise ValueError("模型原始分数无效")
        if any(abs(segment["start_seconds"] - previous["start_seconds"]) < 10 for previous in valid):
            continue
        valid.append(segment)
    if len(valid) < 2:
        return [], ["至少需要两个互不重叠的有效片段；静音、短音频或单音不贴标签"]
    matrix = [[(segment["scores"][index * 2] + segment["scores"][index * 2 + 1]) / 2 for index in range(len(LABELS))] for segment in valid]
    controls = [max(segment["scores"][-len(CONTROLS):]) for segment in valid]
    candidates, reasons = [], []
    for kind, margin in (("STYLE", 0.04), ("MOOD", 0.05)):
        indices = [index for index, label in enumerate(LABELS) if label[0] == kind]
        means = {index: sum(row[index] for row in matrix) / len(matrix) for index in indices}
        ranking = sorted(indices, key=lambda index: (-means[index], index))
        best, second = ranking[:2]
        support = []
        for segment, row, control in zip(valid, matrix, controls):
            order = sorted(indices, key=lambda index: (-row[index], index))
            if order[0] == best and row[best] - row[order[1]] >= 0.02 and row[best] - control >= 0.03:
                support.append(segment["start_seconds"])
        score = means[best]
        gap = score - means[second]
        if score < 0.30 or gap < margin or len(support) < 2 or score - sum(controls) / len(controls) < 0.05:
            reasons.append(kind + "：原始相似度、领先差距、片段一致性或非音乐对照证据不足")
            continue
        candidates.append(dict(kind=kind, name=LABELS[best][1], score=round(score, 6), gap=round(gap, 6), score_type="cosine_similarity", support_segments=support, needs_review=True, auto_apply=False, source="CLAP_MULTISEGMENT"))
    return candidates, reasons
