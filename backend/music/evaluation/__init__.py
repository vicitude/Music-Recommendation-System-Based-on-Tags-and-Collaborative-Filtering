import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from music.recommendation import (
    SongFeatures,
    TimedSong,
    UserSignals,
    build_tfidf_vectors,
    compute_cf,
    compute_item_cf,
    compute_profile,
    dot,
    normalize,
    positive_matrix,
    recommend,
)


class EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class Interaction:
    user_id: int
    song_id: int
    occurred_at: datetime
    positive: bool


@dataclass(frozen=True)
class EvaluationDataset:
    manifest: dict[str, Any]
    songs: tuple[dict[str, Any], ...]
    users: tuple[dict[str, Any], ...]
    interactions: tuple[Interaction, ...]


@dataclass(frozen=True)
class TimeSplit:
    train: tuple[Interaction, ...]
    validation: tuple[Interaction, ...]
    test: tuple[Interaction, ...]
    train_end: datetime
    validation_end: datetime


def _require_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise EvaluationError(f"{field} must be a positive integer")
    return value


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvaluationError(f"{field} must include a timezone")
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(f"Unable to read JSON: {path}") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"JSON root must be an object: {path}")
    return value


def load_dataset(manifest_path: str | Path) -> EvaluationDataset:
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_json(manifest_file)
    required = {"manifest_version", "source", "license_evidence", "origin", "timezone", "timestamps_are_real", "data_file"}
    missing = sorted(required - set(manifest))
    if missing:
        raise EvaluationError("Manifest missing: " + ", ".join(missing))
    if manifest["manifest_version"] != "v1":
        raise EvaluationError("Unsupported manifest_version")
    if not isinstance(manifest["source"], str) or not manifest["source"].strip():
        raise EvaluationError("source is required")
    if not isinstance(manifest["license_evidence"], str) or not manifest["license_evidence"].strip():
        raise EvaluationError("license_evidence is required")
    if manifest["origin"] not in {"REAL", "SIMULATED"}:
        raise EvaluationError("origin must be REAL or SIMULATED")
    if not isinstance(manifest["timezone"], str) or not manifest["timezone"].strip():
        raise EvaluationError("timezone is required")
    if manifest["timestamps_are_real"] is not True:
        raise EvaluationError("timestamps_are_real must be true; random split is not allowed")
    data_file = (manifest_file.parent / manifest["data_file"]).resolve()
    if manifest_file.parent not in data_file.parents:
        raise EvaluationError("data_file must stay below the manifest directory")
    data = _load_json(data_file)
    songs = data.get("songs")
    users = data.get("users")
    raw_interactions = data.get("interactions")
    if not isinstance(songs, list) or not isinstance(users, list) or not isinstance(raw_interactions, list):
        raise EvaluationError("data_file requires songs, users and interactions arrays")
    song_ids = {_require_int(song.get("song_id"), "song_id") for song in songs}
    user_ids = {_require_int(user.get("user_id"), "user_id") for user in users}
    if len(song_ids) != len(songs) or len(user_ids) != len(users):
        raise EvaluationError("song_id and user_id values must be unique")
    interactions = []
    seen = set()
    for index, raw in enumerate(raw_interactions):
        user_id = _require_int(raw.get("user_id"), f"interactions[{index}].user_id")
        song_id = _require_int(raw.get("song_id"), f"interactions[{index}].song_id")
        if user_id not in user_ids or song_id not in song_ids:
            raise EvaluationError(f"interactions[{index}] references an unknown entity")
        occurred_at = _parse_time(raw.get("occurred_at"), f"interactions[{index}].occurred_at")
        positive = raw.get("positive")
        if type(positive) is not bool:
            raise EvaluationError(f"interactions[{index}].positive must be boolean")
        key = (user_id, song_id, occurred_at, positive)
        if key in seen:
            raise EvaluationError("duplicate interactions are not allowed")
        seen.add(key)
        interactions.append(Interaction(user_id, song_id, occurred_at, positive))
    if not interactions:
        raise EvaluationError("at least one interaction is required")
    interactions.sort(key=lambda item: (item.occurred_at, item.user_id, item.song_id))
    return EvaluationDataset(manifest, tuple(songs), tuple(users), tuple(interactions))


def time_split(dataset: EvaluationDataset) -> TimeSplit:
    interactions = dataset.interactions
    total = len(interactions)
    train_count = math.floor(total * 0.70)
    validation_count = math.floor(total * 0.10)
    if train_count < 1 or validation_count < 1 or total - train_count - validation_count < 1:
        raise EvaluationError("time split requires at least 10 interactions")
    train_end = interactions[train_count - 1].occurred_at
    validation_end = interactions[train_count + validation_count - 1].occurred_at
    train_end_index = train_count
    while train_end_index < total and interactions[train_end_index].occurred_at == train_end:
        train_end_index += 1
    validation_end_index = train_count + validation_count
    while validation_end_index < total and interactions[validation_end_index].occurred_at == validation_end:
        validation_end_index += 1
    if train_end_index >= validation_end_index or validation_end_index >= total:
        raise EvaluationError("timestamp ties leave an empty time partition")
    train_end = interactions[train_end_index - 1].occurred_at
    validation_end = interactions[validation_end_index - 1].occurred_at
    return TimeSplit(
        interactions[:train_end_index],
        interactions[train_end_index:validation_end_index],
        interactions[validation_end_index:],
        train_end,
        validation_end,
    )


def ranking_metrics(*, recommendations: dict[int, list[int]], targets: dict[int, set[int]], candidate_ids: set[int], k: int = 10) -> dict[str, float | int | None]:
    if type(k) is not int or not 1 <= k <= 100:
        raise EvaluationError("k must be between 1 and 100")
    users_with_targets = [user_id for user_id, target in targets.items() if target]
    if not users_with_targets:
        return {"users": 0, "precision": None, "recall": None, "f1": None, "hit": None, "ndcg": None, "coverage": None}
    precision_values, recall_values, hit_values, ndcg_values = [], [], [], []
    recommended_union = set()
    for user_id in users_with_targets:
        ranked = list(dict.fromkeys(recommendations.get(user_id, [])))[:k]
        recommended_union.update(ranked)
        relevant = targets[user_id]
        hits = [index for index, song_id in enumerate(ranked) if song_id in relevant]
        precision_values.append(len(hits) / k)
        recall_values.append(len(hits) / len(relevant))
        hit_values.append(1.0 if hits else 0.0)
        dcg = sum(1 / math.log2(index + 2) for index in hits)
        ideal_count = min(k, len(relevant))
        idcg = sum(1 / math.log2(index + 2) for index in range(ideal_count))
        ndcg_values.append(dcg / idcg if idcg else 0.0)
    coverage = len(recommended_union) / len(candidate_ids) if candidate_ids else None
    precision = sum(precision_values) / len(precision_values)
    recall = sum(recall_values) / len(recall_values)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "users": len(users_with_targets),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "hit": sum(hit_values) / len(hit_values),
        "ndcg": sum(ndcg_values) / len(ndcg_values),
        "coverage": coverage,
    }


def user_groups(*, dataset: EvaluationDataset, train: tuple[Interaction, ...]) -> dict[str, set[int]]:
    counts = {user["user_id"]: 0 for user in dataset.users}
    for event in train:
        if event.positive:
            counts[event.user_id] = counts.get(event.user_id, 0) + 1
    groups = {"cold_start_0": set(), "light_1_9": set(), "regular_10_29": set(), "heavy_30_plus": set()}
    for user_id, count in counts.items():
        group = "cold_start_0" if count == 0 else "light_1_9" if count < 10 else "regular_10_29" if count < 30 else "heavy_30_plus"
        groups[group].add(user_id)
    return groups


def catalog_metrics(*, recommendations: dict[int, list[int]], dataset: EvaluationDataset, train: tuple[Interaction, ...], k: int = 10) -> dict[str, float | None]:
    song_tags = {song["song_id"]: set(song.get("tag_ids", [])) for song in dataset.songs}
    train_seen = {(event.user_id, event.song_id) for event in train if event.positive}
    lists = [list(dict.fromkeys(items))[:k] for items in recommendations.values() if items]
    if not lists:
        return {"diversity": None, "novelty": None}
    pair_scores = []
    novelty_scores = []
    for ranked in lists:
        for index, song_id in enumerate(ranked):
            novelty_scores.append(sum(1 for user_id in recommendations if (user_id, song_id) not in train_seen) / max(1, len(recommendations)))
            for other_id in ranked[index + 1:]:
                left, right = song_tags.get(song_id, set()), song_tags.get(other_id, set())
                union = left | right
                pair_scores.append(1 - len(left & right) / len(union) if union else 0.0)
    return {
        "diversity": sum(pair_scores) / len(pair_scores) if pair_scores else 0.0,
        "novelty": sum(novelty_scores) / len(novelty_scores) if novelty_scores else 0.0,
    }


def _signals(*, dataset: EvaluationDataset, train: tuple[Interaction, ...]) -> tuple[UserSignals, ...]:
    positive = {}
    for event in train:
        if event.positive:
            positive.setdefault(event.user_id, []).append(TimedSong(event.song_id, event.occurred_at))
    return tuple(
        UserSignals(
            user_id=user["user_id"],
            origin=dataset.manifest["origin"],
            interest_ids=tuple(user.get("interest_tag_ids", [])),
            favorites=tuple(positive.get(user["user_id"], ())),
        )
        for user in sorted(dataset.users, key=lambda item: item["user_id"])
    )


def _features(dataset: EvaluationDataset) -> tuple[tuple[SongFeatures, ...], dict[int, str]]:
    tags = sorted({tag_id for song in dataset.songs for tag_id in song.get("tag_ids", [])})
    active_tags = {tag_id: str(tag_id) for tag_id in tags}
    songs = tuple(
        SongFeatures(song_id=song["song_id"], tag_ids=tuple(song.get("tag_ids", [])), active=True, playback_allowed=True, checked=True, file_exists=True)
        for song in sorted(dataset.songs, key=lambda item: item["song_id"])
    )
    return songs, active_tags


def _candidate_ids(*, dataset: EvaluationDataset, train: tuple[Interaction, ...], user_id: int) -> tuple[int, ...]:
    seen = {event.song_id for event in train if event.user_id == user_id and event.positive}
    return tuple(sorted(song["song_id"] for song in dataset.songs if song["song_id"] not in seen))


def _rank_hot(*, candidate_ids: tuple[int, ...], train: tuple[Interaction, ...]) -> list[int]:
    popularity = {}
    for event in train:
        if event.positive:
            popularity[event.song_id] = popularity.get(event.song_id, 0) + 1
    return sorted(candidate_ids, key=lambda song_id: (-popularity.get(song_id, 0), song_id))


def _rank_content(*, user_id: int, candidate_ids: tuple[int, ...], songs: tuple[SongFeatures, ...], users: tuple[UserSignals, ...], active_tags: dict[int, str], train: tuple[Interaction, ...]) -> list[int]:
    matrix = positive_matrix(users=users, cutoff=max(event.occurred_at for event in train) + timedelta(microseconds=1), origin=users[0].origin)
    vectors, idf = build_tfidf_vectors(songs=songs, active_tags=active_tags)
    target = next(user for user in users if user.user_id == user_id)
    profile = compute_profile(interest_ids=target.interest_ids, positive_scores=matrix.get(user_id, {}), song_vectors=vectors, tag_idf=idf)
    return sorted(candidate_ids, key=lambda song_id: (-dot(profile, vectors[song_id]), song_id))


def _rank_user_cf(*, user_id: int, candidate_ids: tuple[int, ...], users: tuple[UserSignals, ...], train: tuple[Interaction, ...]) -> list[int]:
    cutoff = max(event.occurred_at for event in train) + timedelta(microseconds=1)
    matrix = positive_matrix(users=users, cutoff=cutoff, origin=users[0].origin)
    scores, _ = compute_cf(user_id=user_id, matrix=matrix, candidate_ids=candidate_ids)
    return sorted(candidate_ids, key=lambda song_id: (-scores.get(song_id, 0), song_id))


def _rank_fixed(*, user_id: int, candidate_ids: tuple[int, ...], songs: tuple[SongFeatures, ...], users: tuple[UserSignals, ...], active_tags: dict[int, str], train: tuple[Interaction, ...], three_route=False) -> list[int]:
    cutoff = max(event.occurred_at for event in train) + timedelta(microseconds=1)
    matrix = positive_matrix(users=users, cutoff=cutoff, origin=users[0].origin)
    vectors, idf = build_tfidf_vectors(songs=songs, active_tags=active_tags)
    target = next(user for user in users if user.user_id == user_id)
    profile = compute_profile(interest_ids=target.interest_ids, positive_scores=matrix.get(user_id, {}), song_vectors=vectors, tag_idf=idf)
    content = {song_id: dot(profile, vectors[song_id]) for song_id in candidate_ids}
    collaborative, _ = compute_cf(user_id=user_id, matrix=matrix, candidate_ids=candidate_ids)
    content_max = max(content.values(), default=0)
    cf_max = max(collaborative.values(), default=0)
    if three_route:
        item_scores, _ = compute_item_cf(user_id=user_id, matrix=matrix, candidate_ids=candidate_ids)
        routes = [scores for scores in (content, collaborative, item_scores) if max(scores.values(), default=0) > 0]
        return sorted(candidate_ids, key=lambda song_id: (-sum(scores.get(song_id, 0) / max(scores.values()) for scores in routes) / max(1, len(routes)), song_id))
    return sorted(
        candidate_ids,
        key=lambda song_id: (
            -(0.5 * (content[song_id] / content_max if content_max else 0) + 0.5 * (collaborative.get(song_id, 0) / cf_max if cf_max else 0)),
            song_id,
        ),
    )


def evaluate_methods(dataset: EvaluationDataset, split: TimeSplit, *, k: int = 10, c2=False, context_now=None, fixed_scene_id=None, enable_rerank: bool = True) -> dict[str, dict[str, float | int | None]]:
    if not isinstance(enable_rerank, bool):
        raise ValueError('Invalid reranking switch')
    songs, active_tags = _features(dataset)
    users = _signals(dataset=dataset, train=split.train)
    cutoff = split.train[-1].occurred_at + timedelta(microseconds=1)
    targets = {}
    for event in split.test:
        if event.positive and not any(previous.user_id == event.user_id and previous.song_id == event.song_id and previous.positive for previous in split.train):
            targets.setdefault(event.user_id, set()).add(event.song_id)
    recommendations = {name: {} for name in (("HOT", "CONTENT", "USER_CF", "ITEM_CF", "FIXED", "ADAPTIVE") if c2 else ("HOT", "CONTENT", "USER_CF", "FIXED", "ADAPTIVE"))}
    scenes = {tag["name"]: tag["id"] for tag in dataset.manifest.get("tags", []) if tag["kind"] == "SCENE"} if c2 else {}
    if context_now is not None and context_now < cutoff:
        raise EvaluationError("context time must not precede training cutoff")
    for user in users:
        candidates = _candidate_ids(dataset=dataset, train=split.train, user_id=user.user_id)
        recommendations["HOT"][user.user_id] = _rank_hot(candidate_ids=candidates, train=split.train)
        recommendations["CONTENT"][user.user_id] = _rank_content(user_id=user.user_id, candidate_ids=candidates, songs=songs, users=users, active_tags=active_tags, train=split.train)
        recommendations["USER_CF"][user.user_id] = _rank_user_cf(user_id=user.user_id, candidate_ids=candidates, users=users, train=split.train)
        if c2:
            matrix = positive_matrix(users=users, cutoff=cutoff, origin=users[0].origin)
            scores, _ = compute_item_cf(user_id=user.user_id, matrix=matrix, candidate_ids=candidates)
            recommendations["ITEM_CF"][user.user_id] = sorted(candidates, key=lambda song_id: (-scores.get(song_id, 0), song_id))
        recommendations["FIXED"][user.user_id] = _rank_fixed(user_id=user.user_id, candidate_ids=candidates, songs=songs, users=users, active_tags=active_tags, train=split.train, three_route=c2)
        if candidates:
            result = recommend(user_id=user.user_id, now=context_now or cutoff, songs=songs, users=users, active_tags=active_tags, limit=min(20, len(candidates)), scene_ids_by_name=scenes, selected_scene_id=fixed_scene_id, enable_rerank=enable_rerank)
            recommendations["ADAPTIVE"][user.user_id] = [item["song_id"] for item in result.items]
        else:
            recommendations["ADAPTIVE"][user.user_id] = []
    candidate_ids = {song["song_id"] for song in dataset.songs}
    groups = user_groups(dataset=dataset, train=split.train)
    result = {}
    for name, values in recommendations.items():
        metrics = ranking_metrics(recommendations=values, targets=targets, candidate_ids=candidate_ids, k=k)
        metrics.update(catalog_metrics(recommendations=values, dataset=dataset, train=split.train, k=k))
        metrics["groups"] = {
            group: ranking_metrics(
                recommendations={user_id: values.get(user_id, []) for user_id in user_ids},
                targets={user_id: targets.get(user_id, set()) for user_id in user_ids},
                candidate_ids=candidate_ids,
                k=k,
            )
            for group, user_ids in groups.items()
        }
        result[name] = metrics
    return result
