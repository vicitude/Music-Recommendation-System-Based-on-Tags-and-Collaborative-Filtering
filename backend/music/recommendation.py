import math
from functools import lru_cache

from music.ncf import NCFModel, fit_ncf, predict_ncf, validate_inputs
from music.diversity import rerank_diverse
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo


class Evidence(TypedDict):
    tag_ids: list[int]
    neighbor_count: int


class RecommendationItem(TypedDict):
    song_id: int
    rank: int
    source: str
    content_score: float
    cf_score: float
    user_cf_score: float
    item_cf_score: float
    ncf_score: float
    score: float
    explanation: str
    evidence: Evidence


def require_integer(value: int, *, minimum: int = 1, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        raise ValueError("Integer outside allowed range")


def require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")


@dataclass(frozen=True)
class TimedSong:
    song_id: int
    occurred_at: datetime

    def __post_init__(self):
        require_integer(self.song_id)
        require_aware(self.occurred_at)


@dataclass(frozen=True)
class TimedRating:
    song_id: int
    score: int
    occurred_at: datetime

    def __post_init__(self):
        require_integer(self.song_id)
        require_integer(self.score, minimum=1, maximum=5)
        require_aware(self.occurred_at)


@dataclass(frozen=True)
class UserSignals:
    user_id: int
    origin: str
    interest_ids: tuple[int, ...] = ()
    favorites: tuple[TimedSong, ...] = ()
    completions: tuple[TimedSong, ...] = ()
    ratings: tuple[TimedRating, ...] = ()
    scene_ids: tuple[int, ...] = ()

    def __post_init__(self):
        require_integer(self.user_id)
        if self.origin not in {"REAL", "SIMULATED"}:
            raise ValueError("Invalid origin")
        for tag_id in self.interest_ids:
            require_integer(tag_id)
        if any(not isinstance(event, TimedSong) for event in (*self.favorites, *self.completions)):
            raise ValueError("Invalid positive feedback")
        if any(not isinstance(event, TimedRating) for event in self.ratings):
            raise ValueError("Invalid ratings")
        for scene_id in self.scene_ids:
            require_integer(scene_id)


@dataclass(frozen=True)
class SongFeatures:
    song_id: int
    tag_ids: tuple[int, ...] = ()
    active: bool = False
    playback_allowed: bool = False
    checked: bool = False
    file_exists: bool = False

    def __post_init__(self):
        require_integer(self.song_id)
        for tag_id in self.tag_ids:
            require_integer(tag_id)
        if any(type(value) is not bool for value in (self.active, self.playback_allowed, self.checked, self.file_exists)):
            raise ValueError("Eligibility flags must be boolean")


@dataclass(frozen=True)
class RecommendationResult:
    items: list[RecommendationItem]
    alpha_target: float
    alpha_effective: float | None
    empty_reason: str | None
    route_weights: dict[str, float] = None
    scene_id: int | None = None
    scene_source: str | None = None
    scene_match_rate: float = 0.0
    time_context: str | None = None


def content_weight(*, positive_song_count: int) -> float:
    require_integer(positive_song_count, minimum=0)
    return 0.30 + 0.60 * 10 / (10 + positive_song_count)

def time_context(*, hour: int) -> str:
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("Invalid hour")
    return ("凌晨" if hour < 5 else "清晨" if hour < 8 else "上午" if hour < 11 else "午间" if hour < 14 else "下午" if hour < 17 else "傍晚" if hour < 20 else "夜晚" if hour < 23 else "深夜")


def time_context_scene_names(context: str) -> tuple[str, ...]:
    names = {"凌晨": ("助眠", "夜晚"), "清晨": ("清晨", "放松"), "上午": ("工作", "学习"), "午间": ("工作", "放松", "运动"), "下午": ("工作", "学习"), "傍晚": ("驾车", "运动"), "夜晚": ("夜晚", "约会"), "深夜": ("夜晚", "助眠")}
    if context not in names:
        raise ValueError("Invalid time context")
    return names[context]


def default_scene_id(*, hour: int, scene_ids_by_name: dict[str, int]) -> int | None:
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("Invalid hour")
    context = time_context(hour=hour)
    if "工作" not in scene_ids_by_name and "运动" in scene_ids_by_name:
        legacy = {"清晨": ("通勤",), "上午": ("通勤",), "午间": ("运动",), "下午": ("运动",), "傍晚": ("通勤",), "夜晚": ("放松",), "深夜": ("夜晚",), "凌晨": ("夜晚",)}
        return next((scene_ids_by_name[name] for name in legacy[context] if name in scene_ids_by_name), None)
    for name in time_context_scene_names(context):
        if name in scene_ids_by_name:
            return scene_ids_by_name[name]
    legacy = {"清晨": ("通勤",), "上午": ("通勤",), "午间": ("运动",), "下午": ("运动",), "傍晚": ("通勤",), "夜晚": ("放松",), "深夜": ("夜晚",), "凌晨": ("夜晚",)}
    return next((scene_ids_by_name[name] for name in legacy[context] if name in scene_ids_by_name), None)

def scene_route_adjustment(*, route_weights: dict[str, float], scene_match_rate: float) -> dict[str, float]:
    if not isinstance(scene_match_rate, (int, float)) or isinstance(scene_match_rate, bool) or not math.isfinite(scene_match_rate) or not 0 <= scene_match_rate <= 1 or any(name not in route_weights for name in ("content", "user_cf", "item_cf")):
        raise ValueError("Invalid scene adjustment")
    if scene_match_rate == 0:
        return dict(route_weights)
    adjusted = {**route_weights, "ncf": route_weights.get("ncf", 0.0)}
    shift = min(0.15, 0.15 * scene_match_rate)
    adjusted["content"] += shift * 0.67
    adjusted["item_cf"] += shift * 0.33
    adjusted["user_cf"] = max(0.0, adjusted["user_cf"] - shift)
    total = math.fsum(adjusted.values())
    return {name: value / total for name, value in adjusted.items()} if total else adjusted


def resolve_scene(*, now: datetime, selected_scene_id: int | None, scene_ids_by_name: dict[str, int]) -> tuple[int | None, str | None]:
    require_aware(now)
    if selected_scene_id is not None:
        require_integer(selected_scene_id)
        if selected_scene_id not in scene_ids_by_name.values():
            raise ValueError('Invalid selected scene')
        return selected_scene_id, 'USER'
    scene_id = default_scene_id(hour=now.astimezone(ZoneInfo("Asia/Shanghai")).hour, scene_ids_by_name=scene_ids_by_name)
    return scene_id, 'TIME' if scene_id is not None else None


def calculate_scene_match_rate(*, candidate_ids: tuple[int, ...], songs: tuple[SongFeatures, ...], scene_id: int | None) -> float:
    if scene_id is None:
        return 0.0
    require_integer(scene_id)
    song_map = {song.song_id: song for song in songs}
    eligible = [song_map[song_id] for song_id in candidate_ids if song_id in song_map]
    if not eligible:
        return 0.0
    return sum(scene_id in song.tag_ids for song in eligible) / len(eligible)

def normalize(vector: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(math.fsum(value * value for _, value in sorted(vector.items())))
    if norm == 0:
        return {}
    return {key: value / norm for key, value in sorted(vector.items()) if value > 0}


def build_tfidf_vectors(*, songs: tuple[SongFeatures, ...], active_tags: dict[int, str], idf: dict[int, float] | None = None) -> tuple[dict[int, dict[int, float]], dict[int, float]]:
    if len({song.song_id for song in songs}) != len(songs):
        raise ValueError("Duplicate song IDs")
    if any(type(tag_id) is not int or tag_id < 1 for tag_id in active_tags):
        raise ValueError("Invalid active tag IDs")
    tokens = {song.song_id: tuple(sorted(set(song.tag_ids) & active_tags.keys())) for song in songs}
    document_count = len(songs)
    if idf is None:
        document_frequency = {tag_id: sum(tag_id in song_tokens for song_tokens in tokens.values()) for tag_id in active_tags}
        idf = {tag_id: math.log((1 + document_count) / (1 + document_frequency[tag_id])) + 1 for tag_id in sorted(active_tags)}
    else:
        idf = {tag_id: float(value) for tag_id, value in sorted(idf.items())}
        if any(not math.isfinite(value) or value <= 0 for value in idf.values()):
            raise ValueError("Invalid IDF")
    vectors = {}
    for song_id, song_tokens in sorted(tokens.items()):
        if not song_tokens:
            vectors[song_id] = {}
            continue
        vectors[song_id] = normalize({tag_id: (1 / len(song_tokens)) * idf.get(tag_id, 0.0) for tag_id in song_tokens})
    return vectors, idf


def dot(left: dict[int, float], right: dict[int, float]) -> float:
    return math.fsum(left[key] * right.get(key, 0.0) for key in sorted(left))


def positive_matrix(
    *, users: tuple[UserSignals, ...], cutoff: datetime, origin: str,
) -> dict[int, dict[int, float]]:
    require_aware(cutoff)
    if origin not in {"REAL", "SIMULATED"} or len({user.user_id for user in users}) != len(users):
        raise ValueError("Invalid origin or duplicate user IDs")
    matrix = {}
    for user in sorted(users, key=lambda item: item.user_id):
        if user.origin != origin:
            continue
        favorites = {event.song_id for event in user.favorites if event.occurred_at < cutoff}
        completions = {event.song_id for event in user.completions if event.occurred_at < cutoff}
        ratings = {event.song_id: event.score for event in user.ratings if event.occurred_at < cutoff}
        positive_ratings = {song_id: score for song_id, score in ratings.items() if score >= 4}
        matrix[user.user_id] = {
            song_id: float(
                (5 if song_id in favorites else 0)
                + (3 if song_id in completions else 0)
                + positive_ratings.get(song_id, 0)
            )
            for song_id in sorted(favorites | completions | positive_ratings.keys())
            if (5 if song_id in favorites else 0)
            + (3 if song_id in completions else 0)
            + positive_ratings.get(song_id, 0) > 0
        }
    return matrix


def compute_profile(
    *, interest_ids: tuple[int, ...], positive_scores: dict[int, float],
    song_vectors: dict[int, dict[int, float]], tag_idf: dict[int, float] | None = None,
) -> dict[int, float]:
    weights = tag_idf or {tag_id: 1.0 for tag_id in set(interest_ids)}
    initial = normalize({tag_id: weights.get(tag_id, 0.0) for tag_id in sorted(set(interest_ids))})
    contributions = {}
    for song_id, score in sorted(positive_scores.items()):
        if score <= 0:
            continue
        for tag_id, value in sorted(song_vectors.get(song_id, {}).items()):
            contributions.setdefault(tag_id, []).append(score * value)
    behavior = normalize({tag_id: math.fsum(values) for tag_id, values in sorted(contributions.items())})
    if not initial:
        return behavior
    if not behavior:
        return initial
    count = sum(score > 0 for score in positive_scores.values())
    blend = count / (count + 10)
    return normalize({
        tag_id: (1 - blend) * initial.get(tag_id, 0.0) + blend * behavior.get(tag_id, 0.0)
        for tag_id in sorted(initial.keys() | behavior.keys())
    })


def compute_cf(
    *, user_id: int, matrix: dict[int, dict[int, float]], candidate_ids: tuple[int, ...],
    neighbor_limit: int = 20,
) -> tuple[dict[int, float], dict[int, int]]:
    require_integer(neighbor_limit, maximum=20)
    target = {song_id: score for song_id, score in matrix.get(user_id, {}).items() if score > 0}
    target_vector = normalize(target)
    neighbors = []
    for other_id, row in sorted(matrix.items()):
        if other_id == user_id:
            continue
        positive = {song_id: score for song_id, score in row.items() if score > 0}
        if len(target.keys() & positive.keys()) < 2:
            continue
        similarity = min(1.0, max(0.0, dot(target_vector, normalize(positive))))
        if similarity > 0:
            neighbors.append((other_id, similarity))
    neighbors.sort(key=lambda item: (-item[1], item[0]))
    neighbors = neighbors[:neighbor_limit]
    scores, counts = {}, {}
    for song_id in sorted(set(candidate_ids)):
        contributions = [
            (similarity, matrix[other_id][song_id])
            for other_id, similarity in neighbors if matrix[other_id].get(song_id, 0) > 0
        ]
        denominator = math.fsum(similarity for similarity, _ in contributions)
        scores[song_id] = (
            math.fsum(similarity * score for similarity, score in contributions) / denominator
            if denominator else 0.0
        )
        counts[song_id] = len(contributions)
    return scores, counts


def compute_item_cf(*, user_id: int, matrix: dict[int, dict[int, float]], candidate_ids: tuple[int, ...], neighbor_limit: int = 20) -> tuple[dict[int, float], dict[int, int]]:
    require_integer(user_id)
    require_integer(neighbor_limit, maximum=20)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError('Duplicate candidate IDs')
    for song_id in candidate_ids:
        require_integer(song_id)
    if user_id not in matrix:
        raise ValueError('Target user is missing')
    rows = {}
    for owner_id, row in sorted(matrix.items()):
        if not isinstance(row, dict):
            raise ValueError('Invalid matrix row')
        positive = {}
        for song_id, score in row.items():
            require_integer(song_id)
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
                raise ValueError('Matrix scores must be finite and nonnegative')
            if score > 0:
                positive[song_id] = float(score)
        rows[owner_id] = positive
    target = rows[user_id]
    target_total = math.fsum(target.values())
    item_users = {}
    for owner_id, row in rows.items():
        for song_id, score in row.items():
            item_users.setdefault(song_id, {})[owner_id] = score
    def item_similarity(left_song_id: int, right_song_id: int) -> float:
        left = item_users.get(left_song_id, {})
        right = item_users.get(right_song_id, {})
        shared = sorted(left.keys() & right.keys())
        if not shared:
            return 0.0
        numerator = math.fsum(left[owner_id] * right[owner_id] for owner_id in shared)
        left_norm = math.sqrt(math.fsum(value * value for value in left.values()))
        right_norm = math.sqrt(math.fsum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return min(1.0, max(0.0, numerator / (left_norm * right_norm)))
    scores, counts = {}, {}
    for song_id in sorted(candidate_ids):
        if song_id in target or target_total == 0:
            scores[song_id], counts[song_id] = 0.0, 0
            continue
        contributions = []
        for source_song_id, target_score in sorted(target.items()):
            similarity = item_similarity(song_id, source_song_id)
            if similarity > 0:
                contributions.append((similarity, target_score, source_song_id))
        contributions.sort(key=lambda item: (-item[0], item[2]))
        contributions = contributions[:neighbor_limit]
        scores[song_id] = min(1.0, max(0.0, math.fsum(similarity * target_score for similarity, target_score, _ in contributions) / target_total))
        counts[song_id] = len(contributions)
    return scores, counts


@lru_cache(maxsize=8)
def _cached_model(rows: tuple, items: tuple, factors: int, epochs: int) -> NCFModel:
    return fit_ncf(matrix={uid: dict(row) for uid, row in rows}, item_ids=items, factors=factors, epochs=epochs)


def compute_ncf(*, user_id: int, matrix: dict[int, dict[int, float]], candidate_ids: tuple[int, ...], factors: int = 8, epochs: int = 30) -> dict[int, float]:
    require_integer(user_id)
    rows, items = validate_inputs(matrix, candidate_ids, factors, epochs, 42, 0.01)
    if not candidate_ids or user_id not in matrix or not any(value > 0 for value in matrix[user_id].values()):
        return {}
    model = _cached_model(rows, items, factors, epochs)
    return predict_ncf(model, user_id=user_id, candidate_ids=candidate_ids)


def fuse_candidates(
    *, candidate_ids: tuple[int, ...], content_scores: dict[int, float], cf_scores: dict[int, float] | None = None,
    user_cf_scores: dict[int, float] | None = None, item_cf_scores: dict[int, float] | None = None, ncf_scores: dict[int, float] | None = None,
    evidence_tags: dict[int, tuple[int, ...]], neighbor_counts: dict[int, int] | None = None,
    user_neighbor_counts: dict[int, int] | None = None, item_neighbor_counts: dict[int, int] | None = None,
    popularity: dict[int, int], active_tags: dict[int, str], positive_song_count: int, limit: int = 20,
    scene_match_rate: float = 0.0, scene_id: int | None = None, scene_source: str | None = None,
) -> RecommendationResult:
    require_integer(limit, maximum=20)
    alpha_target = content_weight(positive_song_count=positive_song_count)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Duplicate candidate IDs")
    if cf_scores is not None and user_cf_scores is not None:
        raise ValueError('Use either cf_scores or user_cf_scores')
    user_cf_scores = user_cf_scores if user_cf_scores is not None else cf_scores or {}
    item_cf_scores = item_cf_scores or {}
    ncf_scores = ncf_scores or {}
    if neighbor_counts is not None and user_neighbor_counts is not None:
        raise ValueError('Use either neighbor_counts or user_neighbor_counts')
    user_neighbor_counts = user_neighbor_counts if user_neighbor_counts is not None else neighbor_counts or {}
    item_neighbor_counts = item_neighbor_counts or {}
    for song_id in candidate_ids:
        require_integer(song_id)
        for score in (content_scores.get(song_id, 0), user_cf_scores.get(song_id, 0), item_cf_scores.get(song_id, 0), ncf_scores.get(song_id, 0)):
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
                raise ValueError("Scores must be finite and nonnegative")
        require_integer(popularity.get(song_id, 0), minimum=0)
        require_integer(user_neighbor_counts.get(song_id, 0), minimum=0, maximum=20)
        require_integer(item_neighbor_counts.get(song_id, 0), minimum=0, maximum=20)
    content_max = max((content_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    user_cf_max = max((user_cf_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    item_cf_max = max((item_cf_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    ncf_max = max((ncf_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    collaborative_routes = [name for name, maximum in (("user_cf", user_cf_max), ("item_cf", item_cf_max), ("ncf", ncf_max)) if maximum]
    available = {"content": alpha_target if content_max else 0.0, "user_cf": (1 - alpha_target) / len(collaborative_routes) if user_cf_max else 0.0, "item_cf": (1 - alpha_target) / len(collaborative_routes) if item_cf_max else 0.0, "ncf": (1 - alpha_target) / len(collaborative_routes) if ncf_max else 0.0}
    if content_max and not collaborative_routes:
        available = {"content": 1.0, "user_cf": 0.0, "item_cf": 0.0, "ncf": 0.0}
    weight_total = math.fsum(available.values())
    route_weights = {name: value / weight_total for name, value in available.items()} if weight_total else {name: 0.0 for name in available}
    route_weights = scene_route_adjustment(route_weights=route_weights, scene_match_rate=scene_match_rate)
    alpha_effective = route_weights["content"] if weight_total else None
    personalized, popular = [], []
    for song_id in sorted(candidate_ids):
        content = content_scores.get(song_id, 0) / content_max if content_max else 0.0
        user_collaborative = user_cf_scores.get(song_id, 0) / user_cf_max if user_cf_max else 0.0
        ncf = ncf_scores.get(song_id, 0) / ncf_max if ncf_max else 0.0
        item_collaborative = item_cf_scores.get(song_id, 0) / item_cf_max if item_cf_max else 0.0
        collaborative = (route_weights["user_cf"] * user_collaborative + route_weights["item_cf"] * item_collaborative + route_weights.get("ncf", 0.0) * ncf) / max(route_weights["user_cf"] + route_weights["item_cf"] + route_weights.get("ncf", 0.0), 1e-12) if route_weights["user_cf"] + route_weights["item_cf"] + route_weights.get("ncf", 0.0) else 0.0
        tags = list(evidence_tags.get(song_id, ())) if content > 0 else []
        user_count = user_neighbor_counts.get(song_id, 0) if user_collaborative > 0 else 0
        item_count = item_neighbor_counts.get(song_id, 0) if item_collaborative > 0 else 0
        count = user_count if user_collaborative > 0 else item_count
        if content > 0 and (not 1 <= len(tags) <= 2 or len(set(tags)) != len(tags) or any(tag not in active_tags for tag in tags)):
            raise ValueError("Positive content score requires active tag evidence")
        if (user_collaborative > 0 and user_count == 0) or (item_collaborative > 0 and item_count == 0):
            raise ValueError("Positive CF score requires contributing neighbors")
        tag_names = "、".join(active_tags[tag_id] for tag_id in tags)
        if content > 0 and (user_collaborative > 0 or item_collaborative > 0):
            source, explanation = "HYBRID", f"匹配{tag_names}，相近偏好用户也喜欢"
        elif content > 0:
            source, explanation = "CONTENT", f"符合你的听歌偏好：{tag_names}"
        elif user_collaborative > 0:
            source, explanation = "USER_CF", "与你偏好相近的用户也喜欢"
        elif item_collaborative > 0:
            source, explanation = "ITEM_CF", "与你喜欢的歌曲相似"
        elif ncf > 0:
            source, explanation = "NCF", "神经协同模型发现的潜在偏好"
        else:
            source, explanation = "HOT", "热门歌曲，供你探索"
        score = (route_weights["content"] * content + route_weights["user_cf"] * user_collaborative + route_weights["item_cf"] * item_collaborative + route_weights.get("ncf", 0.0) * ncf) if weight_total else 0.0
        item: RecommendationItem = {
            "user_cf_score": round(user_collaborative, 6),
            "item_cf_score": round(item_collaborative, 6),
            "ncf_score": round(ncf, 6),
            "song_id": song_id, "rank": 1, "source": source,
            "content_score": round(content, 6), "cf_score": round(collaborative, 6), "score": round(score, 6),
            "explanation": explanation, "evidence": {"tag_ids": tags, "neighbor_count": count},
        }
        if source == "HOT":
            popular.append(item)
        else:
            personalized.append((score, item))
    personalized.sort(key=lambda pair: (-pair[0], pair[1]["song_id"]))
    popular.sort(key=lambda item: (-popularity.get(item["song_id"], 0), item["song_id"]))
    selected = ([item for _, item in personalized] + popular)[:limit]
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
    return RecommendationResult(
        selected, alpha_target, alpha_effective, None if candidate_ids else "NO_ELIGIBLE_SONGS",
        route_weights, scene_id, scene_source, scene_match_rate,
    )


def recommend(
    *, user_id: int, now: datetime, songs: tuple[SongFeatures, ...], users: tuple[UserSignals, ...],
    active_tags: dict[int, str], limit: int = 20, selected_scene_id: int | None = None,
    scene_ids_by_name: dict[str, int] | None = None, enable_rerank: bool = True,
) -> RecommendationResult:
    if not isinstance(enable_rerank, bool):
        raise ValueError('Invalid reranking switch')
    require_integer(user_id)
    require_integer(limit, maximum=20)
    require_aware(now)
    if len({song.song_id for song in songs}) != len(songs) or len({user.user_id for user in users}) != len(users):
        raise ValueError("Duplicate song or user IDs")
    for tag_id, name in active_tags.items():
        require_integer(tag_id)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 30 or name != name.strip():
            raise ValueError("Invalid active tag name")
    target = next((user for user in users if user.user_id == user_id), None)
    if target is None:
        raise ValueError("Target user is missing")
    matrix = positive_matrix(users=users, cutoff=now, origin=target.origin)
    positives = matrix[user_id]
    excluded = {event.song_id for event in target.favorites if event.occurred_at < now}
    excluded.update(event.song_id for event in target.completions if now - timedelta(hours=24) <= event.occurred_at < now)
    excluded.update(event.song_id for event in target.ratings if event.occurred_at < now and event.score <= 2)
    candidates = tuple(sorted(
        song.song_id for song in songs
        if song.active and song.playback_allowed and song.checked and song.file_exists and song.song_id not in excluded
    ))
    scene_ids_by_name = scene_ids_by_name or {}
    default_selected_scene = selected_scene_id
    if default_selected_scene is None and len(target.scene_ids) == 1:
        default_selected_scene = target.scene_ids[0]
    scene_id, scene_source = resolve_scene(
        now=now, selected_scene_id=default_selected_scene, scene_ids_by_name=scene_ids_by_name,
    ) if scene_ids_by_name else (None, None)
    vectors, idf = build_tfidf_vectors(songs=songs, active_tags=active_tags)
    profile = compute_profile(
        interest_ids=tuple(tag_id for tag_id in target.interest_ids if tag_id in active_tags),
        positive_scores=positives, song_vectors=vectors, tag_idf=idf,
    )
    content, tags = {}, {}
    for song_id in candidates:
        vector = vectors[song_id]
        content[song_id] = min(1.0, max(0.0, dot(profile, vector)))
        contributions = sorted(
            ((tag_id, profile.get(tag_id, 0) * value) for tag_id, value in vector.items() if profile.get(tag_id, 0) > 0),
            key=lambda pair: (-pair[1], pair[0]),
        )
        tags[song_id] = tuple(tag_id for tag_id, _ in contributions[:2])
    user_collaborative, user_counts = compute_cf(user_id=user_id, matrix=matrix, candidate_ids=candidates)
    item_collaborative, item_counts = compute_item_cf(user_id=user_id, matrix=matrix, candidate_ids=candidates)
    ncf = compute_ncf(user_id=user_id, matrix=matrix, candidate_ids=candidates)
    popularity = {song_id: sum(row.get(song_id, 0) > 0 for row in matrix.values()) for song_id in candidates}
    result = fuse_candidates(
        candidate_ids=candidates, content_scores=content, user_cf_scores=user_collaborative, item_cf_scores=item_collaborative, ncf_scores=ncf,
        evidence_tags=tags, user_neighbor_counts=user_counts, item_neighbor_counts=item_counts,
        popularity=popularity, active_tags=active_tags, positive_song_count=len(positives), limit=limit,
        scene_match_rate=calculate_scene_match_rate(candidate_ids=candidates, songs=songs, scene_id=scene_id),
        scene_id=scene_id, scene_source=scene_source,
    )
    items = result.items
    if enable_rerank:
        song_tags = {song.song_id: tuple(sorted(set(song.tag_ids) & active_tags.keys())) for song in songs}
        history_tags = {tag for sid in positives for tag in song_tags.get(sid, ())}
        items = rerank_diverse(items=items, song_tags=song_tags, popularity=popularity, user_history_tags=history_tags, limit=limit)
    return RecommendationResult(items, result.alpha_target, result.alpha_effective, result.empty_reason, result.route_weights, result.scene_id, result.scene_source, result.scene_match_rate, time_context=time_context(hour=now.astimezone(ZoneInfo("Asia/Shanghai")).hour))
