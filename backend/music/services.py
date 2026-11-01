from datetime import datetime

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.request import Request

from music.api.errors import ApiError
from music.models import Favorite, Playlist, PlaylistSong, Song, Tag, User, UserTag


def require_aware(now: datetime) -> None:
    if timezone.is_naive(now):
        raise ValueError("A timezone-aware datetime is required")


def register_user(*, username: str, password: str, now: datetime) -> User:
    require_aware(now)
    if User.objects.filter(username=username).exists():
        raise ApiError("USERNAME_TAKEN", ["username"])
    user = User(username=username, origin="REAL", date_joined=now)
    try:
        validate_password(password, user=user)
    except ValidationError:
        raise ApiError("VALIDATION_ERROR", ["password"]) from None
    user.set_password(password)
    try:
        with transaction.atomic():
            user.save()
    except IntegrityError:
        if User.objects.filter(username=username).exists():
            raise ApiError("USERNAME_TAKEN", ["username"]) from None
        raise
    return user


def authenticate_user(*, request: Request, username: str, password: str) -> User:
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise ApiError("AUTH_FAILED")
    login(request, user)
    return user


def logout_user(*, request: Request) -> None:
    logout(request)


@transaction.atomic
def set_interests(*, user_id: int, tag_ids: list[int]) -> list[int]:
    user = User.objects.select_for_update().get(id=user_id)
    if len(tag_ids) != len(set(tag_ids)) or len(tag_ids) not in {0, 3, 4, 5}:
        raise ApiError("VALIDATION_ERROR", ["tag_ids"])
    active_ids = set(Tag.objects.filter(id__in=tag_ids, active=True).values_list("id", flat=True))
    if active_ids != set(tag_ids):
        raise ApiError("VALIDATION_ERROR", ["tag_ids"])
    UserTag.objects.filter(user=user).delete()
    UserTag.objects.bulk_create([UserTag(user=user, tag_id=tag_id) for tag_id in sorted(tag_ids)])
    user.onboarding_completed = True
    user.save(update_fields=["onboarding_completed"])
    return sorted(tag_ids)


@transaction.atomic
def set_favorite(*, user_id: int, song_id: int, present: bool) -> None:
    User.objects.select_for_update().get(id=user_id)
    if present:
        if not Song.objects.filter(id=song_id, active=True).exists():
            raise ApiError("NOT_FOUND", ["song_id"])
        Favorite.objects.get_or_create(user_id=user_id, song_id=song_id)
    else:
        Favorite.objects.filter(user_id=user_id, song_id=song_id).delete()


@transaction.atomic
def create_playlist(*, user_id: int, name: str, now: datetime) -> Playlist:
    require_aware(now)
    User.objects.select_for_update().get(id=user_id)
    if Playlist.objects.filter(user_id=user_id).count() >= 100:
        raise ApiError("LIMIT_REACHED", ["playlist_id"])
    playlist = Playlist.objects.create(user_id=user_id, name=name)
    Playlist.objects.filter(id=playlist.id).update(created_at=now)
    playlist.created_at = now
    return playlist


def owned_playlist(*, user_id: int, playlist_id: int, lock: bool = False) -> Playlist:
    playlists = Playlist.objects.select_for_update() if lock else Playlist.objects
    try:
        return playlists.get(id=playlist_id, user_id=user_id)
    except Playlist.DoesNotExist:
        raise ApiError("NOT_FOUND", ["playlist_id"]) from None


@transaction.atomic
def rename_playlist(*, user_id: int, playlist_id: int, name: str) -> Playlist:
    User.objects.select_for_update().get(id=user_id)
    playlist = owned_playlist(user_id=user_id, playlist_id=playlist_id, lock=True)
    playlist.name = name
    playlist.save(update_fields=["name"])
    return playlist


@transaction.atomic
def delete_playlist(*, user_id: int, playlist_id: int) -> None:
    User.objects.select_for_update().get(id=user_id)
    playlist = owned_playlist(user_id=user_id, playlist_id=playlist_id, lock=True)
    playlist.delete()


@transaction.atomic
def set_playlist_song(*, user_id: int, playlist_id: int, song_id: int, present: bool) -> None:
    User.objects.select_for_update().get(id=user_id)
    playlist = owned_playlist(user_id=user_id, playlist_id=playlist_id, lock=True)
    memberships = PlaylistSong.objects.filter(playlist=playlist)
    if present:
        if not Song.objects.filter(id=song_id, active=True).exists():
            raise ApiError("NOT_FOUND", ["song_id"])
        if memberships.filter(song_id=song_id).exists():
            return
        if memberships.count() >= 500:
            raise ApiError("LIMIT_REACHED", ["song_id"])
        PlaylistSong.objects.create(playlist=playlist, song_id=song_id)
    else:
        memberships.filter(song_id=song_id).delete()
