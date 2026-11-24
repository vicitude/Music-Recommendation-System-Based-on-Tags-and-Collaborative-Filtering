from clap_multilabel import EXPERIMENT_LABELS, decide, texts


VERSION = "multilabel-minimum-v2"
SCENES = {"狂欢": "KTV", "欢快": "KTV", "活力": "运动", "热血励志": "运动", "自信": "驾车", "甜蜜": "约会", "浪漫": "约会", "平静": "助眠", "放松": "助眠", "治愈": "助眠", "思念": "夜晚", "孤独": "夜晚", "悲伤": "夜晚", "苦情": "夜晚", "抑郁": "夜晚"}


def decide_minimum(segments):
    candidates, reasons = decide(segments)
    valid = []
    for segment in segments:
        if segment.get("quality") == "OK" and all(abs(segment["start_seconds"] - old["start_seconds"]) >= 10 for old in valid):
            valid.append(segment)
    if len(valid) != 3:
        return [], ["MINIMUM_REQUIRES_THREE_VALID_SEGMENTS"]
    if any(max(segment["scores"][:-3]) - max(segment["scores"][-3:]) < 0.05 for segment in valid):
        return [], ["NONMUSIC_COMPETITION_NO_FORCED_LABELS"]
    for candidate in candidates:
        candidate["evidence_level"] = "SUPPORTED_HEURISTIC" if candidate["kind"] != "SCENE" else "RULE_SUGGESTION"
    for kind in ("STYLE", "MOOD"):
        if any(candidate["kind"] == kind for candidate in candidates):
            continue
        indices = [index for index, label in enumerate(EXPERIMENT_LABELS) if label[0] == kind]
        means = {index: sum(sum(segment["scores"][index * 2:index * 2 + 2]) / 2 for segment in valid) / len(valid) for index in indices}
        best = max(indices, key=lambda index: (means[index], -index))
        candidates.append(dict(kind=kind, name=EXPERIMENT_LABELS[best][1], score=round(means[best], 7), evidence_level="LOW_FALLBACK", fallback_reason="NO_LABEL_PASSED_DUAL_PROMPT_RULE", needs_review=True, auto_apply=False, source=VERSION))
    if not any(candidate["kind"] == "SCENE" for candidate in candidates):
        mood = max((candidate for candidate in candidates if candidate["kind"] == "MOOD"), key=lambda candidate: candidate["score"])
        candidates.append(dict(kind="SCENE", name=SCENES[mood["name"]], evidence_level="LOW_FALLBACK", fallback_reason="NO_JOINT_SCENE_EVIDENCE", basis=[mood["name"]], needs_review=True, auto_apply=False, source="RULE_SUGGESTION_NOT_AUDIO_FACT"))
    return candidates, reasons


def remaining_items(items, previous):
    identities = {item["sha256"] for item in items}
    used = {row["analysis"]["input_sha256"] for row in previous["results"]}
    if not previous.get("completed") or previous.get("policy_version") != "multilabel-neutral-v1" or previous.get("prompts") != texts() or len(items) != 40 or len(identities) != 40 or len(previous["results"]) != 15 or len(used) != 15 or not used <= identities:
        raise ValueError("Invalid 40/15/25 sample partition or previous version")
    return sorted((item for item in items if item["sha256"] not in used), key=lambda item: item["sha256"])
