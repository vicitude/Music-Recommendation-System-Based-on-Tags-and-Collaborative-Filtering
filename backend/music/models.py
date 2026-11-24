from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    username = models.CharField(max_length=30, unique=True)
    onboarding_completed = models.BooleanField(default=False)
    origin = models.CharField(max_length=9, choices=[("REAL", "真实"), ("SIMULATED", "模拟")], default="REAL")

    class Meta:
        db_table = "music_user"


class Follow(models.Model):
    source = models.ForeignKey(User, on_delete=models.CASCADE, related_name="outgoing_follows")
    target = models.ForeignKey(User, on_delete=models.CASCADE, related_name="incoming_follows")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "music_follow"
        constraints = [
            models.UniqueConstraint(fields=["source", "target"], name="uq_follow_source_target"),
            models.CheckConstraint(condition=~models.Q(source=models.F("target")), name="ck_follow_not_self"),
        ]
        indexes = [
            models.Index(fields=["source", "-created_at", "-id"], name="ix_follow_source_created_id"),
            models.Index(fields=["target", "-created_at", "-id"], name="ix_follow_target_created_id"),
        ]


class Tag(models.Model):
    STYLE = "STYLE"
    MOOD = "MOOD"
    SCENE = "SCENE"
    KIND_CHOICES = [(STYLE, "风格"), (MOOD, "情绪"), (SCENE, "场景")]
    name = models.CharField(max_length=30)
    kind = models.CharField(max_length=5, choices=KIND_CHOICES)
    active = models.BooleanField(default=True)

    def __str__(self):
        suffix = "" if self.active else "（已停用）"
        return f"{self.get_kind_display()}｜{self.name}{suffix}"

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

    def __str__(self):
        return str(self.tag) if self.tag_id else "未选择标签"

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


class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    song = models.ForeignKey(Song, on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "music_rating"
        constraints = [
            models.UniqueConstraint(fields=["user", "song"], name="uq_rating_user_song"),
            models.CheckConstraint(condition=models.Q(score__gte=1, score__lte=5), name="ck_rating_score_1_5"),
        ]
        indexes = [models.Index(fields=["song", "score"], name="ix_rating_song_score")]


class Comment(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="作者")
    song = models.ForeignKey(Song, on_delete=models.PROTECT, verbose_name="歌曲")
    content = models.CharField("评论内容", max_length=500)
    created_at = models.DateTimeField("发表时间", auto_now_add=True)

    class Meta:
        db_table = "music_comment"
        verbose_name = "歌曲评论"
        verbose_name_plural = "歌曲评论"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["song", "-created_at", "-id"], name="ix_comment_song_created_id")]


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
    route_weights = models.JSONField(default=dict)
    scene_id = models.PositiveBigIntegerField(null=True, blank=True)
    scene_source = models.CharField(max_length=4, blank=True, default="")
    scene_match_rate = models.FloatField(default=0)
    generated_at = models.DateTimeField()

    class Meta:
        db_table = "music_recommendation_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["user", "day"], name="uq_snapshot_user_day"),
        ]
