import re
from uuid import UUID

from rest_framework import serializers

from music.media import playable_media_path
from music.models import Playlist, PlaylistSong, Rating, Song, SongTag, Tag, User


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"request": "Expected an object"})
        if set(data) - set(self.fields):
            raise serializers.ValidationError({"request": "Unknown fields"})
        return super().to_internal_value(data)


class StrictCharField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class CommentWriteSerializer(StrictSerializer):
    content = StrictCharField(min_length=1, max_length=500, trim_whitespace=True)


class CommentItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    song_id = serializers.IntegerField()
    author = serializers.SerializerMethodField()
    content = serializers.CharField()
    created_at = serializers.DateTimeField()
    can_delete = serializers.SerializerMethodField()

    def get_author(self, comment):
        return {"id": comment.user_id, "username": comment.user.username}

    def get_can_delete(self, comment):
        user = self.context["request"].user
        return bool(user.is_authenticated and user.is_active and user.pk == comment.user_id)


class UsernameField(StrictCharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data).lower()
        if not 3 <= len(value) <= 30 or any(
            not character.isascii() or not (character.isalnum() or character == "_")
            for character in value
        ):
            self.fail("invalid")
        return value


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "onboarding_completed"]
        read_only_fields = fields


class RegisterSerializer(StrictSerializer):
    username = UsernameField()
    password = StrictCharField(min_length=10, max_length=128, write_only=True, trim_whitespace=False)


class LoginSerializer(StrictSerializer):
    username = UsernameField()
    password = StrictCharField(min_length=1, max_length=128, write_only=True, trim_whitespace=False)


class InterestSerializer(StrictSerializer):
    tag_ids = serializers.ListField(child=StrictIntegerField(min_value=1), allow_empty=True)

    def validate_tag_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("tag_ids")
        if value and not 3 <= len(value) <= 5:
            raise serializers.ValidationError("tag_ids")
        return sorted(value)


class PlaylistWriteSerializer(StrictSerializer):
    name = StrictCharField(min_length=1, max_length=60)


class RatingWriteSerializer(StrictSerializer):
    score = StrictIntegerField(min_value=1, max_value=5)


class StrictUuidField(StrictCharField):
    def to_internal_value(self, data):
        if isinstance(data, UUID):
            return data
        value = super().to_internal_value(data)
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
            self.fail("invalid")
        return UUID(value)


class BehaviorRequestSerializer(StrictSerializer):
    event_id = StrictUuidField()
    song_id = StrictIntegerField(min_value=1)
    listening_session_id = StrictUuidField()
    kind = StrictCharField()
    position_ms = StrictIntegerField(min_value=0, max_value=86400000)
    listened_ms = StrictIntegerField(min_value=0, max_value=86400000)

    def validate_kind(self, value):
        if value not in {"PLAY", "COMPLETE", "SKIP"}:
            raise serializers.ValidationError("kind")
        return value


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "kind"]
        read_only_fields = fields


class SongSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()
    playable = serializers.SerializerMethodField()
    stream_url = serializers.SerializerMethodField()
    current_rating = serializers.SerializerMethodField()

    class Meta:
        model = Song
        fields = [
            "id", "title", "artist", "album", "duration_ms", "tags", "playable",
            "stream_url", "attribution_text", "source_url", "license_name", "license_url",
            "current_rating",
        ]
        read_only_fields = fields

    def get_tags(self, song):
        return TagSerializer(
            [relation.tag for relation in SongTag.objects.filter(song=song, tag__active=True).select_related("tag")],
            many=True,
        ).data

    def get_playable(self, song):
        return self._is_playable(song)

    def get_stream_url(self, song):
        return f"/api/v1/songs/{song.id}/stream/" if self._is_playable(song) else None

    def _is_playable(self, song):
        return playable_media_path(song) is not None

    def get_current_rating(self, song):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        return Rating.objects.filter(user=request.user, song=song).values_list("score", flat=True).first()


class HistoryItemSerializer(serializers.Serializer):
    song = SongSerializer(source="*", read_only=True)
    last_played_at = serializers.DateTimeField(read_only=True)


class PlaylistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Playlist
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class PlaylistDetailSerializer(PlaylistSerializer):
    songs = serializers.SerializerMethodField()

    class Meta(PlaylistSerializer.Meta):
        fields = PlaylistSerializer.Meta.fields + ["songs"]

    def get_songs(self, playlist):
        songs = [
            membership.song
            for membership in PlaylistSong.objects.filter(playlist=playlist).select_related("song").order_by("created_at", "id")
            if membership.song.active
        ]
        return SongSerializer(songs, many=True, context=self.context).data


class FavoriteSongSerializer(SongSerializer):
    pass
