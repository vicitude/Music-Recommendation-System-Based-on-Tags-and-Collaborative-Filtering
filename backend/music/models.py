from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    username = models.CharField(max_length=30, unique=True)
    onboarding_completed = models.BooleanField(default=False)
    origin = models.CharField(max_length=9, choices=[("REAL", "真实"), ("SIMULATED", "模拟")], default="REAL")

    class Meta:
        db_table = "music_user"


class Tag(models.Model):
    STYLE = "STYLE"
    MOOD = "MOOD"
    SCENE = "SCENE"
    KIND_CHOICES = [(STYLE, "风格"), (MOOD, "情绪"), (SCENE, "场景")]
    name = models.CharField(max_length=30)
    kind = models.CharField(max_length=5, choices=KIND_CHOICES)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "music_tag"
        constraints = [models.UniqueConstraint(fields=["kind", "name"], name="uq_tag_kind_name")]


class Song(models.Model):
    title = models.CharField(max_length=120)
    artist = models.CharField(max_length=120)
    album = models.CharField(max_length=120, default="")
    duration_ms = models.PositiveIntegerField()
    file_path = models.CharField(max_length=255, default="")
    mime = models.CharField(max_length=10, choices=[("audio/mpeg", "MP3"), ("audio/wav", "WAV"), ("audio/ogg", "OGG")])
    active = models.BooleanField(default=False)
    source_name = models.CharField(max_length=120)
    source_url = models.URLField(max_length=2000)
    license_name = models.CharField(max_length=120)
    license_url = models.URLField(max_length=2000)
    attribution_text = models.TextField(default="")
    checked_at = models.DateTimeField(null=True, blank=True)
    playback_allowed = models.BooleanField(default=False)
    redistribution_allowed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "music_song"


class SongTag(models.Model):
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)
    weight = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "music_song_tag"
        constraints = [models.UniqueConstraint(fields=["song", "tag"], name="uq_song_tag")]


class UserTag(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

    class Meta:
        db_table = "music_user_tag"
        constraints = [models.UniqueConstraint(fields=["user", "tag"], name="uq_user_tag")]


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "music_favorite"
        constraints = [models.UniqueConstraint(fields=["user", "song"], name="uq_favorite")]


class Playlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "music_playlist"


class PlaylistSong(models.Model):
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "music_playlist_song"
        constraints = [models.UniqueConstraint(fields=["playlist", "song"], name="uq_playlist_song")]

class Behavior(models.Model):
    PLAY = "PLAY"
    COMPLETE = "COMPLETE"
    SKIP = "SKIP"
    KIND_CHOICES = [(PLAY, "????"), (COMPLETE, "????"), (SKIP, "??")]
    event_id = models.UUIDField(unique=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    song = models.ForeignKey(Song, on_delete=models.PROTECT)
    listening_session_id = models.UUIDField()
    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    position_ms = models.PositiveIntegerField()
    listened_ms = models.PositiveIntegerField()
    effective_ms = models.PositiveIntegerField()
    occurred_at = models.DateTimeField()
    origin = models.CharField(max_length=9, choices=User._meta.get_field("origin").choices)

    class Meta:
        db_table = "music_behavior"
        constraints = [
            models.UniqueConstraint(fields=["user", "listening_session_id", "kind"], name="uq_behavior_session_kind"),
        ]
        indexes = [
            models.Index(fields=["user", "occurred_at"], name="ix_behavior_user_time"),
            models.Index(fields=["user", "listening_session_id"], name="ix_behavior_session"),
        ]


class RecommendationSnapshot(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    day = models.DateField()
    revision = models.PositiveIntegerField(default=1)
    algorithm_version = models.CharField(max_length=32, default="adaptive-v0.1.0")
    alpha_target = models.FloatField()
    alpha_effective = models.FloatField(null=True, blank=True)
    items = models.JSONField(default=list)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "music_recommendation_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["user", "day"], name="uq_snapshot_user_day"),
        ]
