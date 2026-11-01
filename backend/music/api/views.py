import re
from functools import wraps

from django.core.paginator import Paginator
from django.core.exceptions import RequestDataTooBig
from django.db.models import Q
from django.middleware.csrf import get_token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from music import behavior, daily, services
from music.api.errors import ApiError
from music.api.serializers import (
    BehaviorRequestSerializer,
    InterestSerializer,
    LoginSerializer,
    PlaylistDetailSerializer,
    PlaylistSerializer,
    PlaylistWriteSerializer,
    RegisterSerializer,
    SongSerializer,
    TagSerializer,
    UserSerializer,
)
from music.models import Playlist, Song, Tag, UserTag
from music.media import media_response, resolve_media


def endpoint(handlers: dict, *, public: bool = False, body_methods: tuple = ()):
    @api_view(list(handlers))
    @permission_classes([AllowAny])
    @wraps(next(iter(handlers.values())))
    def dispatch(request, **kwargs):
        if request.method == "OPTIONS":
            return Response(status=200)
        if not public and (not request.user.is_authenticated or not request.user.is_active):
            raise ApiError("AUTH_REQUIRED")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.content_type != "application/json":
                from rest_framework.exceptions import UnsupportedMediaType

                raise UnsupportedMediaType(request.content_type)
            try:
                body_size = len(request.body)
            except RequestDataTooBig:
                raise ApiError("VALIDATION_ERROR", ["request"]) from None
            if body_size > 65536:
                raise ApiError("VALIDATION_ERROR", ["request"])
            if request.method not in body_methods and request.body:
                raise ApiError("VALIDATION_ERROR", ["request"])
        return handlers[request.method](request, **kwargs)

    return dispatch


def validated(serializer_class, request):
    if not request.body:
        raise ApiError("VALIDATION_ERROR", ["request"])
    serializer = serializer_class(data=request.data)
    if not serializer.is_valid():
        raise ApiError("VALIDATION_ERROR", list(serializer.errors))
    return serializer.validated_data


def check_query(request, allowed):
    if set(request.query_params) - set(allowed) or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise ApiError("VALIDATION_ERROR", ["request"])


def query_integer(request, key, default=None, maximum=None):
    value = request.query_params.get(key)
    if value is None:
        return default
    if not re.fullmatch(r"[0-9]+", value) or len(value) > 20:
        raise ApiError("VALIDATION_ERROR", [key])
    number = int(value)
    if number < 1 or maximum is not None and number > maximum:
        raise ApiError("VALIDATION_ERROR", [key])
    return number


def paginated_songs(request, songs):
    page = query_integer(request, "page", 1)
    page_size = query_integer(request, "page_size", 20, 100)
    paginator = Paginator(songs, page_size)
    if page > paginator.num_pages:
        raise ApiError("NOT_FOUND", ["page"])
    return Response({
        "count": paginator.count,
        "page": page,
        "page_size": page_size,
        "results": SongSerializer(paginator.page(page).object_list, many=True).data,
    })


def getCsrf(request: Request) -> Response:
    return Response({"csrf_token": get_token(request)})


def register(request: Request) -> Response:
    data = validated(RegisterSerializer, request)
    user = services.register_user(**data, now=request.now)
    return Response(UserSerializer(user).data, status=201)


def login(request: Request) -> Response:
    data = validated(LoginSerializer, request)
    user = services.authenticate_user(request=request, **data)
    return Response(UserSerializer(user).data)


def logout(request: Request) -> Response:
    services.logout_user(request=request)
    return Response(status=204)


def getMe(request: Request) -> Response:
    return Response(UserSerializer(request.user).data)


def getInterests(request: Request) -> Response:
    tag_ids = list(UserTag.objects.filter(user=request.user, tag__active=True)
                   .order_by("tag_id").values_list("tag_id", flat=True))
    return Response({"tag_ids": tag_ids, "onboarding_completed": request.user.onboarding_completed})


def setInterests(request: Request) -> Response:
    data = validated(InterestSerializer, request)
    tag_ids = services.set_interests(user_id=request.user.id, **data)
    return Response({"tag_ids": tag_ids, "onboarding_completed": True})


def listTags(request: Request) -> Response:
    check_query(request, {"kind"})
    tags = Tag.objects.filter(active=True)
    kind = request.query_params.get("kind")
    if kind is not None:
        if kind not in {"STYLE", "MOOD", "SCENE"}:
            raise ApiError("VALIDATION_ERROR", ["kind"])
        tags = tags.filter(kind=kind)
    order = {"STYLE": 0, "MOOD": 1, "SCENE": 2}
    return Response(TagSerializer(sorted(tags, key=lambda tag: (order[tag.kind], tag.id)), many=True).data)


def listSongs(request: Request) -> Response:
    check_query(request, {"page", "page_size", "q", "tag_id"})
    songs = Song.objects.filter(active=True).order_by("id")
    query = request.query_params.get("q", "").strip()
    if len(query) > 100:
        raise ApiError("VALIDATION_ERROR", ["q"])
    if query:
        songs = songs.filter(Q(title__icontains=query) | Q(artist__icontains=query))
    tag_id = query_integer(request, "tag_id")
    if tag_id is not None:
        if not Tag.objects.filter(id=tag_id, active=True).exists():
            raise ApiError("VALIDATION_ERROR", ["tag_id"])
        songs = songs.filter(songtag__tag_id=tag_id, songtag__tag__active=True).distinct()
    return paginated_songs(request, songs)


def getSong(request: Request, id: int) -> Response:
    try:
        song = Song.objects.get(id=id, active=True)
    except Song.DoesNotExist:
        raise ApiError("NOT_FOUND", ["id"]) from None
    return Response(SongSerializer(song).data)


def listFavorites(request: Request) -> Response:
    check_query(request, {"page", "page_size"})
    songs = Song.objects.filter(favorite__user=request.user, active=True).order_by(
        "-favorite__created_at", "-favorite__id",
    )
    return paginated_songs(request, songs)


def addFavorite(request: Request, id: int) -> Response:
    services.set_favorite(user_id=request.user.id, song_id=id, present=True)
    return Response(status=204)


def removeFavorite(request: Request, id: int) -> Response:
    services.set_favorite(user_id=request.user.id, song_id=id, present=False)
    return Response(status=204)


def listPlaylists(request: Request) -> Response:
    check_query(request, set())
    return Response(PlaylistSerializer(Playlist.objects.filter(user=request.user).order_by("id"), many=True).data)


def createPlaylist(request: Request) -> Response:
    data = validated(PlaylistWriteSerializer, request)
    playlist = services.create_playlist(user_id=request.user.id, now=request.now, **data)
    return Response(PlaylistSerializer(playlist).data, status=201)


def getPlaylist(request: Request, id: int) -> Response:
    playlist = services.owned_playlist(user_id=request.user.id, playlist_id=id)
    return Response(PlaylistDetailSerializer(playlist).data)


def renamePlaylist(request: Request, id: int) -> Response:
    data = validated(PlaylistWriteSerializer, request)
    playlist = services.rename_playlist(user_id=request.user.id, playlist_id=id, **data)
    return Response(PlaylistSerializer(playlist).data)


def deletePlaylist(request: Request, id: int) -> Response:
    services.delete_playlist(user_id=request.user.id, playlist_id=id)
    return Response(status=204)


def addPlaylistSong(request: Request, id: int, song_id: int) -> Response:
    services.set_playlist_song(user_id=request.user.id, playlist_id=id, song_id=song_id, present=True)
    return Response(status=204)


def removePlaylistSong(request: Request, id: int, song_id: int) -> Response:
    services.set_playlist_song(user_id=request.user.id, playlist_id=id, song_id=song_id, present=False)
    return Response(status=204)


def getDaily(request: Request) -> Response:
    check_query(request, set())
    snapshot = daily.get_daily(user_id=request.user.id, now=request.now)
    return Response(daily.serialize_daily(snapshot=snapshot, user_id=request.user.id, now=request.now))


def refreshDaily(request: Request) -> Response:
    check_query(request, set())
    snapshot = daily.refresh_daily(user_id=request.user.id, now=request.now)
    return Response(daily.serialize_daily(snapshot=snapshot, user_id=request.user.id, now=request.now))


def recordBehavior(request: Request) -> Response:
    check_query(request, set())
    data = validated(BehaviorRequestSerializer, request)
    event, created = behavior.record_behavior(user_id=request.user.id, now=request.now, **data)
    return Response(
        {"id": event.id, "event_id": str(event.event_id), "effective_ms": event.effective_ms},
        status=201 if created else 200,
    )


def streamSong(request: Request, id: int):
    check_query(request, set())
    path, mime, _ = resolve_media(song_id=id, user_id=request.user.id)
    return media_response(path=path, mime=mime, range_header=request.headers.get("Range"))
