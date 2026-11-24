import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from music.evaluation import EvaluationError, catalog_metrics, evaluate_methods, load_dataset, ranking_metrics, time_split, user_groups


class EvaluationTests(unittest.TestCase):
    def test_c2_six_methods_and_future_events_do_not_change_training_ranks(self):
        from dataclasses import replace
        from unittest.mock import patch
        from music import evaluation
        dataset = load_dataset(self.write_dataset(count=20))
        dataset = replace(dataset, songs=dataset.songs + ({"song_id": 4, "tag_ids": []},))
        split = time_split(dataset)
        self.assertEqual(set(evaluate_methods(dataset, split, c2=True)), {"HOT", "CONTENT", "USER_CF", "ITEM_CF", "FIXED", "ADAPTIVE"})
        original = evaluation.recommend
        calls = []
        def capture(**kwargs):
            calls.append(kwargs)
            return original(**kwargs)
        with patch("music.evaluation.recommend", side_effect=capture):
            evaluate_methods(dataset, split, c2=True)
        self.assertTrue(calls)
        self.assertTrue(all(event.occurred_at <= split.train_end for call in calls for user in call["users"] for event in user.favorites))
        with self.assertRaises(EvaluationError):
            evaluate_methods(dataset, split, c2=True, context_now=split.train_end - timedelta(days=1))

    def write_dataset(self, *, timestamps_are_real=True, include_license=True, count=10):
        root = Path(tempfile.mkdtemp())
        data = {
            "songs": [{"song_id": index} for index in range(1, 4)],
            "users": [{"user_id": 1}, {"user_id": 2}],
            "interactions": [
                {
                    "user_id": 1 if index % 2 else 2,
                    "song_id": index % 3 + 1,
                    "occurred_at": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat(),
                    "positive": True,
                }
                for index in range(count)
            ],
        }
        (root / "data.json").write_text(json.dumps(data), encoding="utf-8")
        manifest = {
            "manifest_version": "v1",
            "source": "SYNTHETIC_TEST_ONLY",
            "license_evidence": "test-only synthetic records",
            "origin": "SIMULATED",
            "timezone": "UTC",
            "timestamps_are_real": timestamps_are_real,
            "data_file": "data.json",
        }
        if not include_license:
            manifest.pop("license_evidence")
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root / "manifest.json"

    def test_manifest_requires_real_timestamps_and_license(self):
        with self.assertRaises(EvaluationError):
            load_dataset(self.write_dataset(timestamps_are_real=False))
        with self.assertRaises(EvaluationError):
            load_dataset(self.write_dataset(include_license=False))

    def test_time_split_is_ordered_and_non_empty(self):
        dataset = load_dataset(self.write_dataset())
        split = time_split(dataset)
        self.assertEqual(len(split.train), 7)
        self.assertEqual(len(split.validation), 1)
        self.assertEqual(len(split.test), 2)
        self.assertLessEqual(split.train[-1].occurred_at, split.validation[0].occurred_at)
        self.assertLessEqual(split.validation[-1].occurred_at, split.test[0].occurred_at)

    def test_time_split_rejects_too_small_dataset(self):
        with self.assertRaises(EvaluationError):
            time_split(load_dataset(self.write_dataset(count=9)))

    def test_metrics_use_fixed_k_and_skip_empty_targets(self):
        result = ranking_metrics(
            recommendations={1: [1, 2], 2: [3]},
            targets={1: {2}, 2: set()},
            candidate_ids={1, 2, 3, 4},
            k=10,
        )
        self.assertEqual(result["users"], 1)
        self.assertEqual(result["precision"], 0.1)
        self.assertEqual(result["recall"], 1.0)
        self.assertAlmostEqual(result["f1"], 0.1818181818)
        self.assertEqual(result["hit"], 1.0)
        self.assertEqual(result["coverage"], 0.5)

    def test_metrics_return_null_when_no_target(self):
        result = ranking_metrics(recommendations={1: [1]}, targets={1: set()}, candidate_ids={1})
        self.assertEqual(result["users"], 0)
        self.assertIsNone(result["precision"])
        self.assertIsNone(result["coverage"])

    def test_user_groups_and_catalog_metrics_are_reportable(self):
        dataset = load_dataset(self.write_dataset())
        split = time_split(dataset)
        groups = user_groups(dataset=dataset, train=split.train)
        self.assertEqual(set().union(*groups.values()), {1, 2})
        metrics = catalog_metrics(
            recommendations={1: [1, 2], 2: [2, 3]},
            dataset=dataset,
            train=split.train,
        )
        self.assertGreaterEqual(metrics["diversity"], 0)
        self.assertLessEqual(metrics["diversity"], 1)
        self.assertGreaterEqual(metrics["novelty"], 0)
        self.assertLessEqual(metrics["novelty"], 1)

    def test_all_five_methods_return_the_same_metric_contract(self):
        dataset = load_dataset(self.write_dataset())
        metrics = evaluate_methods(dataset, time_split(dataset))
        self.assertEqual(set(metrics), {"HOT", "CONTENT", "USER_CF", "FIXED", "ADAPTIVE"})
        for result in metrics.values():
            self.assertEqual(set(result), {"users", "precision", "recall", "f1", "hit", "ndcg", "coverage", "diversity", "novelty", "groups"})
