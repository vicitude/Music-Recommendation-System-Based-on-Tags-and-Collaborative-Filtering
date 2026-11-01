from datetime import datetime, timedelta

from django.db import IntegrityError, transaction

from music.api.errors import ApiError
from music.api.serializers import BehaviorRequestSerializer
from music.models import Behavior, Song, User
from music.recommendation import require_aware


def existing_event(*, event_id, user_id: int, payload: dict) -> Behavior | None:
    event = Behavior.objects.filter(event_id=event_id).first()
    if event is None:
        return None
    if event.user_id != user_id or any(getattr(event, field) != value for field, value in payload.items()):
        raise ApiError("EVENT_CONFLICT", ["event_id"])
    return event


def check_session(*, user_id: int, payload: dict) -> Behavior | None:
    events = list(Behavior.objects.filter(user_id=user_id, listening_session_id=payload["listening_session_id"]).order_by("id"))
    if any(event.song_id != payload["song_id"] for event in events):
        raise ApiError("INVALID_TRANSITION", ["listening_session_id"])
    terminal = any(event.kind in {Behavior.COMPLETE, Behavior.SKIP} for event in events)
    if terminal and payload["kind"] != Behavior.PLAY:
        raise ApiError("INVALID_TRANSITION", ["kind"])
    if any(event.kind == payload["kind"] for event in events):
        raise ApiError("EVENT_CONFLICT", ["listening_session_id", "kind"])
    play = next((event for event in events if event.kind == Behavior.PLAY), None)
    if payload["kind"] != Behavior.PLAY and play is None:
        raise ApiError("INVALID_TRANSITION", ["listening_session_id"])
    return play


@transaction.atomic
def record_behavior(
    *, user_id: int, event_id: str, song_id: int, listening_session_id: str,
    kind: str, position_ms: int, listened_ms: int, now: datetime,
) -> tuple[Behavior, bool]:
    require_aware(now)
    serializer = BehaviorRequestSerializer(data={
        "event_id": event_id, "song_id": song_id, "listening_session_id": listening_session_id,
        "kind": kind, "position_ms": position_ms, "listened_ms": listened_ms,
    })
    if not serializer.is_valid():
        raise ApiError("VALIDATION_ERROR", list(serializer.errors))
    values = serializer.validated_data
    event_uuid = values.pop("event_id")
    try:
        user = User.objects.select_for_update().get(id=user_id, is_active=True)
    except User.DoesNotExist:
        raise ApiError("AUTH_REQUIRED") from None
    prior = existing_event(event_id=event_uuid, user_id=user_id, payload=values)
    if prior is not None:
        return prior, False
    try:
        song = Song.objects.get(id=values["song_id"], active=True)
    except Song.DoesNotExist:
        raise ApiError("NOT_FOUND", ["song_id"]) from None
    play = check_session(user_id=user_id, payload=values)
    if values["kind"] == Behavior.PLAY:
        invalid = [field for field in ("position_ms", "listened_ms") if values[field] != 0]
        if invalid:
            raise ApiError("VALIDATION_ERROR", invalid)
        effective_ms = 0
    else:
        if values["position_ms"] > song.duration_ms:
            raise ApiError("VALIDATION_ERROR", ["position_ms"])
        elapsed_ms = (now - play.occurred_at) // timedelta(milliseconds=1)
        if elapsed_ms < 0:
            raise ApiError("INVALID_TRANSITION", ["listening_session_id"])
        effective_ms = min(values["listened_ms"], elapsed_ms, song.duration_ms)
        threshold = (4 * song.duration_ms + 4) // 5
        if values["kind"] == Behavior.COMPLETE and (effective_ms < threshold or values["position_ms"] < threshold):
            raise ApiError("INVALID_TRANSITION", ["listened_ms", "position_ms"])
    try:
        with transaction.atomic():
            event = Behavior.objects.create(
                event_id=event_uuid, user=user, **values, effective_ms=effective_ms,
                occurred_at=now, origin=user.origin,
            )
    except IntegrityError:
        prior = existing_event(event_id=event_uuid, user_id=user_id, payload=values)
        if prior is not None:
            return prior, False
        check_session(user_id=user_id, payload=values)
        raise
    return event, True
