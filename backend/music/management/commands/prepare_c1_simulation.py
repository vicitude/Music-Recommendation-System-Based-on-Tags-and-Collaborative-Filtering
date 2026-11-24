import io
import json

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from music.models import Song, SongTag, Tag, User
from music.tag_library import formal_tag_keys, import_library


class Command(BaseCommand):
    help = "Apply the approved additive C1 vocabulary and 200-user simulation in one transaction."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        if options["confirm"] != "C1 ADD 200":
            raise CommandError("Explicit C1 confirmation required")
        if User.objects.filter(origin="SIMULATED").exists() or User.objects.filter(username__startswith="sim_c1_").exists():
            raise CommandError("Existing simulated accounts found; refusing automatic replacement")
        songs = list(Song.objects.order_by("pk").values())
        relations = list(SongTag.objects.order_by("pk").values())
        real = list(User.objects.filter(origin="REAL").order_by("pk").values())
        existing_tags = list(Tag.objects.order_by("pk").values())
        tags = import_library(sorted(formal_tag_keys()))
        call_command("seed_simulated_users", count=200, seed=42, username_prefix="sim_c1_", profile_version="formal-v1", stdout=io.StringIO())
        if songs != list(Song.objects.order_by("pk").values()) or relations != list(SongTag.objects.order_by("pk").values()) or real != list(User.objects.filter(origin="REAL").order_by("pk").values()):
            raise CommandError("Protected data changed; transaction rolled back")
        if existing_tags != list(Tag.objects.filter(pk__in=[tag["id"] for tag in existing_tags]).order_by("pk").values()):
            raise CommandError("Existing dictionary changed; transaction rolled back")
        count = User.objects.filter(origin="SIMULATED", username__startswith="sim_c1_").count()
        if count != 200:
            raise CommandError("Simulation count mismatch; transaction rolled back")
        self.stdout.write(json.dumps(dict(status="VERIFIED_IN_TRANSACTION", tags_created=tags["created"], simulated_users=count, protected_songs=len(songs), protected_real_users=len(real), seed=42, profile_version="formal-v1")))
