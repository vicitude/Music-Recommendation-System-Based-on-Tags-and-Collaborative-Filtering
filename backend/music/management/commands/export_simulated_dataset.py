import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from music.models import Behavior, Song, SongTag, Tag, User, UserTag


class Command(BaseCommand):
    help = "Export SIMULATED users, songs and behaviors into a research dataset manifest."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Output directory for manifest.json and data.json")
        parser.add_argument("--source", default="LOCAL_SIMULATED_USERS_V1")

    def handle(self, *args, **options):
        output = Path(options["output"]).resolve()
        output.mkdir(parents=True, exist_ok=True)
        users = list(User.objects.filter(origin="SIMULATED").order_by("id"))
        if not users:
            raise CommandError("no SIMULATED users found; run seed_simulated_users first")
        user_ids = [user.id for user in users]
        songs = list(Song.objects.filter(active=True).order_by("id"))
        if not songs:
            raise CommandError("no active songs found")
        song_ids = [song.id for song in songs]
        tag_map = {}
        for song_id, tag_id in SongTag.objects.filter(song_id__in=song_ids, tag__active=True).order_by("song_id", "tag_id").values_list("song_id", "tag_id"):
            tag_map.setdefault(song_id, []).append(tag_id)
        interest_map = {}
        for user_id, tag_id in UserTag.objects.filter(user_id__in=user_ids, tag__active=True).order_by("user_id", "tag_id").values_list("user_id", "tag_id"):
            interest_map.setdefault(user_id, []).append(tag_id)
        interactions = []
        for user_id, song_id, occurred_at in Behavior.objects.filter(
            user_id__in=user_ids, origin="SIMULATED", kind=Behavior.COMPLETE,
        ).order_by("occurred_at", "id").values_list("user_id", "song_id", "occurred_at"):
            interactions.append({
                "user_id": user_id,
                "song_id": song_id,
                "occurred_at": occurred_at.isoformat(),
                "positive": True,
            })
        if len(interactions) < 10:
            raise CommandError(f"only {len(interactions)} positive interactions exported; need at least 10")
        data = {
            "songs": [{"song_id": song.id, "tag_ids": tag_map.get(song.id, [])} for song in songs],
            "users": [{"user_id": user.id, "interest_tag_ids": interest_map.get(user.id, [])} for user in users],
            "interactions": interactions,
        }
        manifest = {
            "manifest_version": "v1",
            "source": options["source"],
            "license_evidence": "locally generated synthetic accounts for algorithm verification; not real user research data",
            "origin": "SIMULATED",
            "timezone": "UTC",
            "timestamps_are_real": True,
            "data_file": "data.json",
            "timestamp_provenance": "synthetic event times, not real user observations",
            "tags": list(Tag.objects.filter(active=True).order_by("id").values("id", "name", "kind")),
        }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Simulated dataset exported: users={len(users)}, songs={len(songs)}, "
            f"interactions={len(interactions)} -> {output / 'data.json'}"
        ))
