import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from music.evaluation import EvaluationError, evaluate_methods, load_dataset, time_split


class Command(BaseCommand):
    help = "Generate a reproducible simulated research dataset and evaluate all methods."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Output directory for simulated data and report")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--users", type=int, default=60)
        parser.add_argument("--songs", type=int, default=120)
        parser.add_argument("--interactions", type=int, default=1200)

    def handle(self, *args, **options):
        seed = options["seed"]
        user_count = options["users"]
        song_count = options["songs"]
        interaction_count = options["interactions"]
        if min(user_count, song_count, interaction_count) < 1:
            raise CommandError("users, songs and interactions must be positive")
        generator = random.Random(seed)
        output = Path(options["output"]).resolve()
        output.mkdir(parents=True, exist_ok=True)
        tag_count = 18
        songs = []
        for song_id in range(1, song_count + 1):
            tag_ids = sorted(generator.sample(range(1, tag_count + 1), generator.randint(1, 3)))
            songs.append({"song_id": song_id, "tag_ids": tag_ids})
        users = []
        for user_id in range(1, user_count + 1):
            interests = sorted(generator.sample(range(1, tag_count + 1), generator.randint(1, 3)))
            users.append({"user_id": user_id, "interest_tag_ids": interests})
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        interactions = []
        for index in range(interaction_count):
            user = users[index % user_count]
            preferred = [song for song in songs if set(song["tag_ids"]) & set(user["interest_tag_ids"])]
            pool = preferred if preferred and generator.random() < 0.75 else songs
            song = generator.choice(pool)
            interactions.append({
                "user_id": user["user_id"],
                "song_id": song["song_id"],
                "occurred_at": (start + timedelta(minutes=index)).isoformat(),
                "positive": True,
            })
        data = {"songs": songs, "users": users, "interactions": interactions}
        manifest = {
            "manifest_version": "v1",
            "source": "SIMULATED_GENERATOR_V1",
            "license_evidence": "generated synthetic records; not a research result",
            "origin": "SIMULATED",
            "timezone": "UTC",
            "timestamps_are_real": True,
            "data_file": "data.json",
            "generator": {"seed": seed, "users": user_count, "songs": song_count, "interactions": interaction_count},
        }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            dataset = load_dataset(output / "manifest.json")
            split = time_split(dataset)
            metrics = evaluate_methods(dataset, split, k=10)
        except EvaluationError as error:
            raise CommandError(str(error)) from error
        report = {
            "status": "SIMULATED_SELF_TEST",
            "source": manifest["source"],
            "origin": manifest["origin"],
            "generator": manifest["generator"],
            "split": {
                "train_count": len(split.train),
                "validation_count": len(split.validation),
                "test_count": len(split.test),
                "train_end": split.train_end.isoformat(),
                "validation_end": split.validation_end.isoformat(),
            },
            "metrics": metrics,
            "note": "Synthetic data only validates the pipeline and must not be presented as real user effectiveness.",
        }
        (output / "evaluation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Simulated evaluation written: {output / 'evaluation-report.json'}"))
