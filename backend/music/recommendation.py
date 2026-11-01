import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict


class Evidence(TypedDict):
    tag_ids: list[int]
    neighbor_count: int


class RecommendationItem(TypedDict):
    song_id: int
    rank: int
    source: str
    content_score: float
    cf_score: float
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
class UserSignals:
    user_id: int
    origin: str
    interest_ids: tuple[int, ...] = ()
    favorites: tuple[TimedSong, ...] = ()
    completions: tuple[TimedSong, ...] = ()

    def __post_init__(self):
        require_integer(self.user_id)
        if self.origin not in {"REAL", "SIMULATED"}:
            raise ValueError("Invalid origin")
        for tag_id in self.interest_ids:
            require_integer(tag_id)
        if any(not isinstance(event, TimedSong) for event in (*self.favorites, *self.completions)):
            raise ValueError("Invalid positive feedback")


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


def content_weight(*, positive_song_count: int) -> float:
    require_integer(positive_song_count, minimum=0)
    return 0.30 + 0.60 * 10 / (10 + positive_song_count)


def normalize(vector: dict[int, float]) -> dict[int, float]:
    norm = math.sqrt(math.fsum(value * value for _, value in sorted(vector.items())))
    if norm == 0:
        return {}
    return {key: value / norm for key, value in sorted(vector.items()) if value > 0}


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
        matrix[user.user_id] = {
            song_id: float(5 * (song_id in favorites) + 3 * (song_id in completions))
            for song_id in sorted(favorites | completions)
        }
    return matrix


def compute_profile(
    *, interest_ids: tuple[int, ...], positive_scores: dict[int, float],
    song_vectors: dict[int, dict[int, float]],
) -> dict[int, float]:
    initial = normalize({tag_id: 1.0 for tag_id in sorted(set(interest_ids))})
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


def fuse_candidates(
    *, candidate_ids: tuple[int, ...], content_scores: dict[int, float], cf_scores: dict[int, float],
    evidence_tags: dict[int, tuple[int, ...]], neighbor_counts: dict[int, int],
    popularity: dict[int, int], active_tags: dict[int, str], positive_song_count: int, limit: int = 20,
) -> RecommendationResult:
    require_integer(limit, maximum=20)
    alpha_target = content_weight(positive_song_count=positive_song_count)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("Duplicate candidate IDs")
    for song_id in candidate_ids:
        require_integer(song_id)
        for score in (content_scores.get(song_id, 0), cf_scores.get(song_id, 0)):
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
                raise ValueError("Scores must be finite and nonnegative")
        require_integer(popularity.get(song_id, 0), minimum=0)
        require_integer(neighbor_counts.get(song_id, 0), minimum=0, maximum=20)
    content_max = max((content_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    cf_max = max((cf_scores.get(song_id, 0) for song_id in candidate_ids), default=0)
    alpha_effective = alpha_target if content_max and cf_max else 1.0 if content_max else 0.0 if cf_max else None
    personalized, popular = [], []
    for song_id in sorted(candidate_ids):
        content = content_scores.get(song_id, 0) / content_max if content_max else 0.0
        collaborative = cf_scores.get(song_id, 0) / cf_max if cf_max else 0.0
        tags = list(evidence_tags.get(song_id, ())) if content > 0 else []
        count = neighbor_counts.get(song_id, 0) if collaborative > 0 else 0
        if content > 0 and (not 1 <= len(tags) <= 2 or len(set(tags)) != len(tags) or any(tag not in active_tags for tag in tags)):
            raise ValueError("Positive content score requires active tag evidence")
        if collaborative > 0 and count == 0:
            raise ValueError("Positive CF score requires contributing neighbors")
        tag_names = "、".join(active_tags[tag_id] for tag_id in tags)
        if content > 0 and collaborative > 0:
            source, explanation = "HYBRID", f"匹配{tag_names}，相近偏好用户也喜欢"
        elif content > 0:
            source, explanation = "CONTENT", f"符合你的听歌偏好：{tag_names}"
        elif collaborative > 0:
            source, explanation = "CF", "与你偏好相近的用户也喜欢"
        else:
            source, explanation = "HOT", "热门歌曲，供你探索"
        score = alpha_effective * content + (1 - alpha_effective) * collaborative if alpha_effective is not None else 0.0
        item: RecommendationItem = {
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
    return RecommendationResult(selected, alpha_target, alpha_effective, None if candidate_ids else "NO_ELIGIBLE_SONGS")


def recommend(
    *, user_id: int, now: datetime, songs: tuple[SongFeatures, ...], users: tuple[UserSignals, ...],
    active_tags: dict[int, str], limit: int = 20,
) -> RecommendationResult:
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
    candidates = tuple(sorted(
        song.song_id for song in songs
        if song.active and song.playback_allowed and song.checked and song.file_exists and song.song_id not in excluded
    ))
    vectors = {
        song.song_id: normalize({tag_id: 1.0 for tag_id in set(song.tag_ids) if tag_id in active_tags})
        for song in songs
    }
    profile = compute_profile(
        interest_ids=tuple(tag_id for tag_id in target.interest_ids if tag_id in active_tags),
        positive_scores=positives, song_vectors=vectors,
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
    collaborative, counts = compute_cf(user_id=user_id, matrix=matrix, candidate_ids=candidates)
    popularity = {song_id: sum(row.get(song_id, 0) > 0 for row in matrix.values()) for song_id in candidates}
    return fuse_candidates(
        candidate_ids=candidates, content_scores=content, cf_scores=collaborative,
        evidence_tags=tags, neighbor_counts=counts, popularity=popularity, active_tags=active_tags,
        positive_song_count=len(positives), limit=limit,
    )
