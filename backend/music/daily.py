import math
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction

from music.api.errors import ApiError
from music.media import playable_media_path
from music.models import Behavior, Favorite, Rating, RecommendationSnapshot, Song, SongTag, Tag, User, UserTag
from music.recommendation import (
    RecommendationItem,
    SongFeatures,
    TimedSong,
    TimedRating,
    UserSignals,
    compute_cf,
    compute_profile,
    build_tfidf_vectors,
    normalize,
    positive_matrix,
    recommend,
    require_aware,
    time_context,
    require_integer,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
REFRESH_INTERVAL = timedelta(seconds=60)
DAILY_LIMIT = 10


class RefreshLimited(ApiError):
    def __init__(self, seconds: float):
        super().__init__("RATE_LIMITED", ["refresh"])
        self.retry_after = min(60, max(1, math.ceil(seconds)))


def active_user(user_id: int, *, lock: bool = False) -> User:
    users = User.objects.select_for_update() if lock else User.objects
    try:
        return users.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        raise ApiError("AUTH_REQUIRED") from None


def load_inputs(*, user_id: int, cutoff: datetime, origin: str | None = None) -> dict:
    require_aware(cutoff)
    user = active_user(user_id)
    if origin is not None and origin != user.origin:
        raise ValueError("Origin does not match target user")
    users = list(User.objects.filter(origin=user.origin, is_active=True).order_by("id"))
    user_ids = [member.id for member in users]
    tags = dict(Tag.objects.filter(active=True).order_by("id").values_list("id", "name"))
    scene_tags = dict(Tag.objects.filter(active=True, kind=Tag.SCENE).order_by("id").values_list("id", "name"))
    song_tags = defaultdict(list)
    for song_id, tag_id in SongTag.objects.filter(tag_id__in=tags).order_by("song_id", "tag_id").values_list("song_id", "tag_id"):
        song_tags[song_id].append(tag_id)
    songs = tuple(
        SongFeatures(
            song_id=song.id, tag_ids=tuple(song_tags[song.id]), active=song.active,
            playback_allowed=song.playback_allowed, checked=song.checked_at is not None,
            file_exists=playable_media_path(song) is not None,
        )
        for song in Song.objects.filter(created_at__lt=cutoff).order_by("id")
    )
    favorites, completions, ratings, interests, scenes = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for owner_id, song_id, created_at in Favorite.objects.filter(user_id__in=user_ids, created_at__lt=cutoff).order_by("id").values_list("user_id", "song_id", "created_at"):
        favorites[owner_id].append(TimedSong(song_id, created_at))
    for owner_id, song_id, occurred_at in Behavior.objects.filter(
        user_id__in=user_ids, origin=user.origin, kind=Behavior.COMPLETE, occurred_at__lt=cutoff,
    ).order_by("id").values_list("user_id", "song_id", "occurred_at"):
        completions[owner_id].append(TimedSong(song_id, occurred_at))
    for owner_id, song_id, score, created_at in Rating.objects.filter(
        user_id__in=user_ids, created_at__lt=cutoff,
    ).order_by("id").values_list("user_id", "song_id", "score", "created_at"):
        ratings[owner_id].append(TimedRating(song_id, score, created_at))
    for owner_id, tag_id in UserTag.objects.filter(user_id__in=user_ids, tag_id__in=tags).order_by("user_id", "tag_id").values_list("user_id", "tag_id"):
        interests[owner_id].append(tag_id)
        if tag_id in scene_tags:
            scenes[owner_id].append(tag_id)
    signals = tuple(
        UserSignals(member.id, member.origin, tuple(interests[member.id]), tuple(favorites[member.id]), tuple(completions[member.id]), tuple(ratings[member.id]), tuple(scenes[member.id]))
        for member in users
    )
    return {"user_id": user_id, "now": cutoff, "songs": songs, "users": signals, "active_tags": tags, "scene_ids_by_name": {name: tag_id for tag_id, name in scene_tags.items()}}


def build_user_profile(*, user_id: int, cutoff: datetime, origin: str) -> dict[int, float]:
    inputs = load_inputs(user_id=user_id, cutoff=cutoff, origin=origin)
    target = next(user for user in inputs["users"] if user.user_id == user_id)
    matrix = positive_matrix(users=inputs["users"], cutoff=cutoff, origin=origin)
    vectors, idf = build_tfidf_vectors(songs=inputs["songs"], active_tags=inputs["active_tags"])
    return compute_profile(interest_ids=target.interest_ids, positive_scores=matrix[user_id], song_vectors=vectors, tag_idf=idf)


def score_user_cf(
    *, user_id: int, candidate_ids: list[int], cutoff: datetime, origin: str, neighbor_limit: int = 20,
) -> dict[int, float]:
    require_integer(neighbor_limit, maximum=20)
    inputs = load_inputs(user_id=user_id, cutoff=cutoff, origin=origin)
    matrix = positive_matrix(users=inputs["users"], cutoff=cutoff, origin=origin)
    scores, _ = compute_cf(user_id=user_id, matrix=matrix, candidate_ids=tuple(candidate_ids), neighbor_limit=neighbor_limit)
    return scores


def calculate_daily(*, user_id: int, now: datetime, limit: int = DAILY_LIMIT) -> list[RecommendationItem]:
    require_integer(limit, maximum=20)
    return recommend(**load_inputs(user_id=user_id, cutoff=now), limit=limit).items


def latest_generation(user_id: int) -> datetime | None:
    return RecommendationSnapshot.objects.filter(user_id=user_id).order_by("-generated_at", "-id").values_list("generated_at", flat=True).first()


def save_generation(*, user_id: int, now: datetime, snapshot: RecommendationSnapshot | None, selected_scene_id: int | None = None) -> RecommendationSnapshot:
    result = recommend(**load_inputs(user_id=user_id, cutoff=now), limit=DAILY_LIMIT, selected_scene_id=selected_scene_id)
    values = {
        "algorithm_version": "adaptive-v0.1.0", "items": result.items,
        "alpha_target": result.alpha_target, "alpha_effective": result.alpha_effective, "generated_at": now,
        "route_weights": result.route_weights, "scene_id": result.scene_id,
        "scene_source": result.scene_source or "", "scene_match_rate": result.scene_match_rate,
    }
    if snapshot is not None:
        for name, value in values.items():
            setattr(snapshot, name, value)
        snapshot.revision += 1
        snapshot.save(update_fields=[*values, "revision"])
        return snapshot
    day = now.astimezone(SHANGHAI).date()
    try:
        with transaction.atomic():
            return RecommendationSnapshot.objects.create(user_id=user_id, day=day, revision=1, **values)
    except IntegrityError:
        existing = RecommendationSnapshot.objects.select_for_update().filter(user_id=user_id, day=day).first()
        if existing is None:
            raise
        return existing


@transaction.atomic
def get_daily(*, user_id: int, now: datetime, selected_scene_id: int | None = None) -> RecommendationSnapshot:
    require_aware(now)
    active_user(user_id, lock=True)
    snapshot = RecommendationSnapshot.objects.select_for_update().filter(user_id=user_id, day=now.astimezone(SHANGHAI).date()).first()
    if snapshot is not None and (selected_scene_id is None or snapshot.scene_id == selected_scene_id):
        return snapshot
    return save_generation(user_id=user_id, now=now, snapshot=snapshot, selected_scene_id=selected_scene_id)


@transaction.atomic
def refresh_daily(*, user_id: int, now: datetime, selected_scene_id: int | None = None) -> RecommendationSnapshot:
    require_aware(now)
    active_user(user_id, lock=True)
    snapshot = RecommendationSnapshot.objects.select_for_update().filter(user_id=user_id, day=now.astimezone(SHANGHAI).date()).first()
    latest = latest_generation(user_id)
    if latest is not None and now < latest + REFRESH_INTERVAL:
        raise RefreshLimited((latest + REFRESH_INTERVAL - now).total_seconds())
    return save_generation(user_id=user_id, now=now, snapshot=snapshot, selected_scene_id=selected_scene_id)


def valid_evidence(item: RecommendationItem, *, tags: dict[int, str], song_tags: set[int]) -> bool:
    evidence = item["evidence"]
    tag_ids, count = evidence["tag_ids"], evidence["neighbor_count"]
    source = item["source"]
    if source in {"CONTENT", "HYBRID"}:
        if not 1 <= len(tag_ids) <= 2 or len(set(tag_ids)) != len(tag_ids) or not set(tag_ids) <= song_tags & tags.keys():
            return False
        names = "、".join(tags[tag_id] for tag_id in tag_ids)
        if source == "CONTENT":
            return count == 0 and item["explanation"] == f"符合你的听歌偏好：{names}"
        return 1 <= count <= 20 and item["explanation"] == f"匹配{names}，相近偏好用户也喜欢"
    if source in {"CF", "USER_CF"}:
        return not tag_ids and 1 <= count <= 20 and item["explanation"] == "与你偏好相近的用户也喜欢"
    if source == "ITEM_CF":
        return not tag_ids and 1 <= count <= 20 and item["explanation"] == "与你喜欢的歌曲相似"
        return not tag_ids and 1 <= count <= 20 and item["explanation"] == "与你偏好相近的用户也喜欢"
    return source == "HOT" and not tag_ids and count == 0 and item["explanation"] == "热门歌曲，供你探索"


def serialize_daily(*, snapshot: RecommendationSnapshot, user_id: int, now: datetime) -> dict:
    require_aware(now)
    if snapshot.user_id != user_id:
        raise ApiError("NOT_FOUND")
    user = active_user(user_id)
    song_ids = [item["song_id"] for item in snapshot.items]
    songs = {song.id: song for song in Song.objects.filter(id__in=song_ids)}
    excluded = set(Behavior.objects.filter(
        user_id=user_id, song_id__in=song_ids, origin=user.origin, kind=Behavior.COMPLETE,
        occurred_at__gte=now - timedelta(hours=24), occurred_at__lt=now,
    ).values_list("song_id", flat=True))
    tags = dict(Tag.objects.filter(active=True).values_list("id", "name"))
    song_tags = defaultdict(set)
    for song_id, tag_id in SongTag.objects.filter(song_id__in=song_ids, tag_id__in=tags).values_list("song_id", "tag_id"):
        song_tags[song_id].add(tag_id)
    items = []
    for item in snapshot.items:
        song_id = item["song_id"]
        song = songs.get(song_id)
        if song is None or song_id in excluded or playable_media_path(song) is None:
            continue
        if not valid_evidence(item, tags=tags, song_tags=song_tags[song_id]):
            continue
        items.append({**item, "rank": len(items) + 1})
        if len(items) == DAILY_LIMIT:
            break
    latest = latest_generation(user_id) or snapshot.generated_at
    scene_name = Tag.objects.filter(id=snapshot.scene_id, kind=Tag.SCENE).values_list("name", flat=True).first() if snapshot.scene_id else None
    return {
        "day": snapshot.day.isoformat(), "revision": snapshot.revision,
        "algorithm_version": snapshot.algorithm_version, "generated_at": snapshot.generated_at.isoformat(),
        "alpha_target": snapshot.alpha_target, "alpha_effective": snapshot.alpha_effective,
        "next_refresh_at": (latest + REFRESH_INTERVAL).isoformat(), "items": items,
        "route_weights": snapshot.route_weights or {}, "scene_id": snapshot.scene_id,
        "time_context": time_context(hour=snapshot.generated_at.astimezone(SHANGHAI).hour),
        "scene_name": scene_name, "scene_source": snapshot.scene_source or None,
        "scene_match_rate": snapshot.scene_match_rate,
        "empty_reason": None if items else "FILTERED_OUT" if snapshot.items else "NO_ELIGIBLE_SONGS",
    }
