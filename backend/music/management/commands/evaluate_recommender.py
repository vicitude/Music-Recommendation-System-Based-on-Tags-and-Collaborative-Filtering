import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from music.evaluation import EvaluationError, evaluate_methods, load_dataset, time_split


class Command(BaseCommand):
    help = "Validate a research manifest and produce the reproducible time-split evaluation scaffold."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", required=True, help="Path to a research manifest JSON file")
        parser.add_argument("--output", required=True, help="Directory for the evaluation report")
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        try:
            dataset = load_dataset(options["dataset"])
            split = time_split(dataset)
        except EvaluationError as error:
            raise CommandError(str(error)) from error
        output = Path(options["output"]).resolve()
        output.mkdir(parents=True, exist_ok=True)
        train_positive = {(item.user_id, item.song_id) for item in split.train if item.positive}
        targets = {}
        for item in split.test:
            if item.positive and (item.user_id, item.song_id) not in train_positive:
                targets.setdefault(item.user_id, set()).add(item.song_id)
        candidate_ids = {song["song_id"] for song in dataset.songs}
        report = {
            "status": "SIMULATED_SELF_TEST" if dataset.manifest["origin"] == "SIMULATED" else "READY_FOR_RESEARCH_REPORT",
            "seed": options["seed"],
            "method_names": ["HOT", "CONTENT", "USER_CF", "FIXED", "ADAPTIVE"],
            "source": dataset.manifest["source"],
            "origin": dataset.manifest["origin"],
            "split": {
                "train_count": len(split.train),
                "validation_count": len(split.validation),
                "test_count": len(split.test),
                "train_end": split.train_end.isoformat(),
                "validation_end": split.validation_end.isoformat(),
            },
            "target_users": len(targets),
            "metrics": evaluate_methods(dataset, split, k=10),
            "note": "Metrics are valid only for the declared source, origin, timestamps and feature mapping.",
        }
        (output / "evaluation-scaffold.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Evaluation scaffold written: {output / 'evaluation-scaffold.json'}"))
