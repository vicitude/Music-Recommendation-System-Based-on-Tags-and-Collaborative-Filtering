import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from music.evaluation import evaluate_methods, load_dataset, time_split
from music.evaluation import _features, _signals
from music.recommendation import recommend, time_context


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        output = Path(options["output"]).resolve()
        if output.exists():
            raise CommandError("Use a new output directory; previous evidence must not be overwritten")
        call_command("export_simulated_dataset", output=str(output), source="C1_FORMAL_V1_SEED42")
        dataset = load_dataset(output / "manifest.json")
        if len(dataset.users) != 200:
            raise CommandError("C2 requires the approved 200-user cohort")
        split = time_split(dataset)
        metrics = evaluate_methods(dataset, split, c2=True)
        songs, tags = _features(dataset)
        users = _signals(dataset=dataset, train=split.train)
        scenes = {tag["name"]: tag["id"] for tag in dataset.manifest["tags"] if tag["kind"] == "SCENE"}
        if "学习" not in scenes:
            raise CommandError("Fixed study context missing")
        day = (split.train_end.astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        contexts = []
        for hour in (2, 6, 9, 12, 15, 18, 21, 23):
            now = day.replace(hour=hour)
            changed = 0
            weights = Counter()
            for user in users:
                common = dict(user_id=user.user_id, now=now, songs=songs, users=users, active_tags=tags, scene_ids_by_name=scenes, limit=10)
                dynamic = recommend(**common)
                fixed = recommend(**common, selected_scene_id=scenes["学习"])
                changed += [item["song_id"] for item in dynamic.items] != [item["song_id"] for item in fixed.items]
                weights.update(dynamic.route_weights)
            contexts.append(dict(context=time_context(hour=hour), hour=hour, changed_users=changed, users=len(users), mean_weights={key: value / len(users) for key, value in weights.items()}))
        counts = Counter(tag for user in dataset.users for tag in user["interest_tag_ids"])
        names = {tag["id"]: tag["name"] for tag in dataset.manifest["tags"]}
        report = dict(status="SIMULATED_SELF_TEST", source=dataset.manifest["source"], versions=dict(profile="formal-v1", vocabulary="formal53", context="eight-period-v1", evaluation="c2-six-route-v1"), timestamp_provenance=dataset.manifest["timestamp_provenance"], seed=42, users=len(users), songs=len(songs), interactions=len(dataset.interactions), split=dict(train=len(split.train), validation=len(split.validation), test=len(split.test), train_end=split.train_end.isoformat(), validation_end=split.validation_end.isoformat()), metrics=metrics, contexts=contexts, preference=[dict(name=names[tag], count=count) for tag, count in counts.most_common(5)], sha256={name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ("manifest.json", "data.json")}, limitations=["Synthetic timestamps and preferences; not real user effectiveness", "Only completed plays used as implicit positive feedback", "Validation held out; no tuning", "Context comparison measures sensitivity, not context relevance"])
        (output / "evaluation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(dict(status=report["status"], output=str(output), split=report["split"], metrics=metrics), ensure_ascii=False))
