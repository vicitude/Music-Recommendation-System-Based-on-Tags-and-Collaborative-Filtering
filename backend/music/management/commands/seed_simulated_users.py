import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from music.models import (
    Behavior,
    Favorite,
    Playlist,
    PlaylistSong,
    Rating,
    Song,
    SongTag,
    Tag,
    User,
    UserTag,
)


ARCHETYPES = (
    ("流行探索者", ("流行", "华语流行", "欧美流行"), ("愉悦", "治愈"), ("通勤", "日常")),
    ("摇滚能量派", ("摇滚", "独立摇滚", "朋克"), ("激昂", "热烈"), ("运动", "驾驶")),
    ("电子夜行者", ("电子", "氛围电子", "Synthwave"), ("冷静", "迷幻"), ("夜晚", "通勤")),
    ("民谣故事党", ("民谣", "独立", "乡村"), ("温柔", "伤感"), ("散步", "旅行")),
    ("轻音乐专注者", ("轻音乐", "钢琴", "古典"), ("平静", "治愈"), ("学习", "阅读")),
    ("国风爱好者", ("国风", "古风", "戏曲"), ("悠扬", "怀旧"), ("放松", "夜晚")),
    ("爵士慢生活", ("爵士", "蓝调", "Soul"), ("慵懒", "浪漫"), ("咖啡", "夜晚")),
    ("节奏舞曲派", ("舞曲", "嘻哈", "R&B"), ("快乐", "热烈"), ("运动", "聚会")),
)


class Command(BaseCommand):
    help = "Seed deterministic simulated users and behaviors without deleting existing data."

    def add_arguments(self, parser):
        parser.add_argument("--profile-version", choices=["legacy", "formal-v1"], default="legacy")
        parser.add_argument("--count", type=int, default=200)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--username-prefix", default="sim_user_")
        parser.add_argument("--login-password", default="", help="Optional local password so simulated accounts can log in on this machine")

    def handle(self, *args, **options):
        count = options["count"]
        seed = options["seed"]
        prefix = options["username_prefix"]
        login_password = options["login_password"]
        if not prefix or len(prefix) > 25 or not prefix.isascii() or not all(character.isalnum() or character == "_" for character in prefix):
            raise CommandError("username prefix must contain at most 25 ASCII letters, digits or underscores")
        formal = options["profile_version"] == "formal-v1"
        archetypes = ARCHETYPES
        if formal:
            from music.simulation_profiles import ARCHETYPES as FORMAL_ARCHETYPES, formal_tags
            archetypes = FORMAL_ARCHETYPES
            tags = formal_tags()
            if prefix == "sim_user_":
                prefix = "sim_c1_"
            usernames = [f"{prefix}{index:03d}" for index in range(1, count + 1)]
            if User.objects.filter(username__in=usernames).exists():
                raise CommandError("C1目标账号已存在；停止生成，先盘点并单独确认处理，不自动覆盖或删除。")
            if any(not any(name in tags[kind] for name in names) for archetype in archetypes for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), archetype[1:])):
                raise CommandError("正式标签不足以覆盖八类画像，请先在标签词库补齐启用项。")
        if count < 1 or count > 10000:
            raise CommandError("count must be between 1 and 10000")
        songs = list(Song.objects.filter(active=True).order_by("id"))
        if not songs:
            raise CommandError("no active songs found; publish songs before seeding simulated users")
        if not formal:
            tags = self._load_or_create_tags()
        song_tags = self._load_song_tags(songs)
        now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        created_users = 0
        created_interactions = 0
        created_favorites = 0
        created_ratings = 0
        created_playlists = 0
        created_playlist_songs = 0
        created_user_tags = 0
        generator = random.Random(seed)

        with transaction.atomic():
            for index in range(1, count + 1):
                username = f"{prefix}{index:03d}"
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "origin": User._meta.get_field("origin").default,
                        "onboarding_completed": True,
                        "is_active": True,
                    },
                )
                if created:
                    user.origin = "SIMULATED"
                    user.onboarding_completed = True
                    user.set_unusable_password()
                    user.save(update_fields=["origin", "onboarding_completed", "password"])
                    created_users += 1
                elif user.origin != "SIMULATED":
                    raise CommandError(f"refusing to reuse non-simulated account: {username}")
                if login_password:
                    user.set_password(login_password)
                    user.save(update_fields=["password"])

                archetype = archetypes[(index - 1) % len(archetypes)]
                profile_tags = self._choose_profile_tags(tags, archetype, generator)
                for tag in profile_tags:
                    _, relation_created = UserTag.objects.get_or_create(user=user, tag=tag)
                    created_user_tags += int(relation_created)

                ranked_songs = self._rank_songs(songs, song_tags, profile_tags, generator)
                interaction_count = 8 + ((index * 7) % 23)
                selected = ranked_songs[: min(interaction_count, len(ranked_songs))]
                playlist, playlist_created = Playlist.objects.get_or_create(
                    user=user,
                    name=f"模拟·{archetype[0]}精选",
                )
                created_playlists += int(playlist_created)

                for position, song in enumerate(selected):
                    occurred_at = now - timedelta(days=position % 45, hours=(index * 3 + position) % 24)
                    if formal:
                        from music.simulation_profiles import HOURS, PREFERRED_BUCKETS
                        bucket = position % 8 if position < 8 else generator.choices(range(8), weights=[5 if value == PREFERRED_BUCKETS[(index - 1) % 8] else 1 for value in range(8)])[0]
                        local_zone = timezone(timedelta(hours=8))
                        occurred_at = (now.astimezone(local_zone) - timedelta(days=1 + position % 45)).replace(hour=HOURS[bucket], minute=generator.randrange(40), second=0, microsecond=0).astimezone(timezone.utc)
                    identity = f"{seed}:{prefix}:{index}" if formal else f"{seed}:{index}"
                    session_id = uuid.uuid5(uuid.NAMESPACE_URL, f"music-sim-session:{identity}:{song.id}")
                    play_id = uuid.uuid5(uuid.NAMESPACE_URL, f"music-sim-play:{identity}:{song.id}")
                    play, play_created = Behavior.objects.get_or_create(
                        event_id=play_id,
                        defaults={
                            "user": user,
                            "song": song,
                            "listening_session_id": session_id,
                            "kind": Behavior.PLAY,
                            "position_ms": 0,
                            "listened_ms": 0,
                            "effective_ms": 0,
                            "occurred_at": occurred_at,
                            "origin": "SIMULATED",
                        },
                    )
                    if play_created:
                        created_interactions += 1

                    preference_score = self._preference_score(song, song_tags, profile_tags)
                    if preference_score >= 2 or position % 4 != 0:
                        terminal_kind = Behavior.COMPLETE
                        listened_ms = max(1, int(song.duration_ms * 0.92))
                        position_ms = max(1, int(song.duration_ms * 0.95))
                    else:
                        terminal_kind = Behavior.SKIP
                        listened_ms = max(1000, int(song.duration_ms * 0.18))
                        position_ms = max(1000, int(song.duration_ms * 0.18))
                    terminal_id = uuid.uuid5(uuid.NAMESPACE_URL, f"music-sim-{terminal_kind.lower()}:{identity}:{song.id}")
                    _, terminal_created = Behavior.objects.get_or_create(
                        event_id=terminal_id,
                        defaults={
                            "user": user,
                            "song": song,
                            "listening_session_id": session_id,
                            "kind": terminal_kind,
                            "position_ms": min(position_ms, song.duration_ms),
                            "listened_ms": listened_ms,
                            "effective_ms": listened_ms,
                            "occurred_at": occurred_at + timedelta(minutes=3),
                            "origin": "SIMULATED",
                        },
                    )
                    created_interactions += int(terminal_created)

                    favorite_target = preference_score >= 1 or position < 3
                    if favorite_target:
                        _, favorite_created = Favorite.objects.get_or_create(user=user, song=song)
                        created_favorites += int(favorite_created)
                        if formal and favorite_created:
                            Favorite.objects.filter(user=user, song=song).update(created_at=occurred_at + timedelta(minutes=3))
                    if position < 8 or preference_score >= 1:
                        if preference_score >= 2:
                            score = 5
                        elif preference_score == 1:
                            score = 4
                        else:
                            score = 3 if position % 3 else 2
                        _, rating_created = Rating.objects.get_or_create(
                            user=user,
                            song=song,
                            defaults={"score": score},
                        )
                        created_ratings += int(rating_created)
                        if formal and rating_created:
                            Rating.objects.filter(user=user, song=song).update(created_at=occurred_at + timedelta(minutes=3), updated_at=occurred_at + timedelta(minutes=3))
                    if position < 8:
                        _, playlist_song_created = PlaylistSong.objects.get_or_create(playlist=playlist, song=song)
                        created_playlist_songs += int(playlist_song_created)

        self.stdout.write(self.style.SUCCESS(
            "Simulated data ready: "
            f"users_created={created_users}, user_tags_created={created_user_tags}, "
            f"behaviors_created={created_interactions}, favorites_created={created_favorites}, "
            f"ratings_created={created_ratings}, playlists_created={created_playlists}, "
            f"playlist_songs_created={created_playlist_songs}, origin=SIMULATED, seed={seed}, profile_version={options['profile_version']}"
        ))

    @staticmethod
    def _load_song_tags(songs):
        result = defaultdict(set)
        for song_id, tag_id in SongTag.objects.filter(song__in=songs).values_list("song_id", "tag_id"):
            result[song_id].add(tag_id)
        return result

    @staticmethod
    def _load_or_create_tags():
        names_by_kind = {
            Tag.STYLE: sorted({item for archetype in ARCHETYPES for item in archetype[1]}),
            Tag.MOOD: sorted({item for archetype in ARCHETYPES for item in archetype[2]}),
            Tag.SCENE: sorted({item for archetype in ARCHETYPES for item in archetype[3]}),
        }
        result = {}
        for kind, names in names_by_kind.items():
            result[kind] = {
                name: Tag.objects.get_or_create(name=name, kind=kind, defaults={"active": True})[0]
                for name in names
            }
        return result

    @staticmethod
    def _choose_profile_tags(tags, archetype, generator):
        chosen = []
        for kind, names in zip((Tag.STYLE, Tag.MOOD, Tag.SCENE), archetype[1:]):
            available = [tags[kind][name] for name in names if name in tags[kind]]
            chosen.extend(generator.sample(available, min(len(available), 2 if kind == Tag.STYLE else 1)))
        return chosen

    @staticmethod
    def _preference_score(song, song_tags, profile_tags):
        profile_ids = {tag.id for tag in profile_tags}
        return len(song_tags.get(song.id, set()) & profile_ids)

    @classmethod
    def _rank_songs(cls, songs, song_tags, profile_tags, generator):
        ranked = []
        for song in songs:
            score = cls._preference_score(song, song_tags, profile_tags)
            ranked.append((score, generator.random(), song))
        ranked.sort(key=lambda item: (-item[0], item[1], item[2].id))
        return [item[2] for item in ranked]
