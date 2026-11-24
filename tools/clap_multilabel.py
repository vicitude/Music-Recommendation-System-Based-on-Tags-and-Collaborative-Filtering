import math

from clap_policy import CONTROLS, LABELS


VERSION = "multilabel-neutral-v1"
LIMITS = {"STYLE": 2, "MOOD": 3, "SCENE": 2}
MOODS = (("狂欢", "festive and celebratory"), ("热血励志", "rousing and triumphant"), ("活力", "energetic and vigorous"), ("欢快", "cheerful and happy"), ("甜蜜", "sweet and tender"), ("自信", "confident and assertive"), ("浪漫", "romantic and intimate"), ("放松", "relaxing and soothing"), ("治愈", "comforting and warm"), ("思念", "wistful and longing"), ("平静", "calm and peaceful"), ("孤独", "lonely and isolated"), ("悲伤", "sad and sorrowful"), ("苦情", "anguished and heartbroken"), ("抑郁", "gloomy and melancholic"))
EXPERIMENT_LABELS = tuple((kind, name, phrase) for kind, name, phrase, _ in LABELS if kind == "STYLE") + tuple(("MOOD", name, phrase) for name, phrase in MOODS)


def texts():
    prompts = []
    for kind, _, phrase in EXPERIMENT_LABELS:
        if kind == "STYLE":
            prompts.extend((f"This is {phrase}.", f"The musical style is {phrase}."))
        else:
            prompts.extend((f"This music sounds {phrase}.", f"The mood of this music is {phrase}."))
    return prompts + list(CONTROLS)


def decide(segments):
    valid = []
    for segment in segments:
        if segment.get("quality") != "OK":
            continue
        scores = segment.get("scores", [])
        if len(scores) != len(texts()) or any(type(score) not in (int, float) or not math.isfinite(score) or not -1.001 <= score <= 1.001 for score in scores):
            raise ValueError("Invalid multilabel score vector")
        if all(abs(segment["start_seconds"] - previous["start_seconds"]) >= 10 for previous in valid):
            valid.append(segment)
    if len(valid) < 2:
        return [], ["INSUFFICIENT_INDEPENDENT_SEGMENTS"]
    candidates, rejected = [], []
    for index, (kind, name, _) in enumerate(EXPERIMENT_LABELS):
        means = [sum(segment["scores"][index * 2 + offset] for segment in valid) / len(valid) for offset in (0, 1)]
        support = [segment["start_seconds"] for segment in valid if min(segment["scores"][index * 2:index * 2 + 2]) >= 0.30 and min(segment["scores"][index * 2:index * 2 + 2]) - max(segment["scores"][-3:]) >= 0.05]
        if min(means) < 0.30 or abs(means[0] - means[1]) > 0.12 or len(support) < 2:
            rejected.append(kind + ":" + name + ":INSUFFICIENT_DUAL_PROMPT_SUPPORT")
            continue
        candidates.append(dict(kind=kind, name=name, score=round(sum(means) / 2, 7), prompt_means=means, support_segments=support, needs_review=True, auto_apply=False, source=VERSION))
    selected = []
    for kind in ("STYLE", "MOOD"):
        selected.extend(sorted((candidate for candidate in candidates if candidate["kind"] == kind), key=lambda candidate: (-candidate["score"], candidate["name"]))[:LIMITS[kind]])
    supported_moods = {candidate["name"] for candidate in candidates if candidate["kind"] == "MOOD"}
    for scene, required in (("助眠", {"平静", "放松"}), ("运动", {"活力", "欢快"})):
        if required <= supported_moods:
            selected.append(dict(kind="SCENE", name=scene, basis=sorted(required), needs_review=True, auto_apply=False, source="RULE_SUGGESTION_NOT_AUDIO_FACT"))
    return selected, rejected
