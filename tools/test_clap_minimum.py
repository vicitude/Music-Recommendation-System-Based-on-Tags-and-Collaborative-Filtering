import unittest

from clap_minimum import decide_minimum, remaining_items
from clap_multilabel import EXPERIMENT_LABELS, texts


class MinimumTests(unittest.TestCase):
    def segments(self):
        scores = [0.1] * len(texts())
        scores[0:2] = [0.25, 0.26]
        scores[-3:] = [0, 0, 0]
        return [dict(quality="OK", start_seconds=start, scores=list(scores)) for start in (0, 20, 40)]

    def test_minimum_counts_and_fallback_provenance(self):
        candidates, _ = decide_minimum(self.segments())
        self.assertEqual([candidate["kind"] for candidate in candidates], ["STYLE", "MOOD", "SCENE"])
        self.assertTrue(all(candidate["evidence_level"] == "LOW_FALLBACK" and candidate["auto_apply"] is False for candidate in candidates))

    def test_maximums_and_supported_not_relabelled_as_fallback(self):
        segments = self.segments()
        for segment in segments:
            segment["scores"][:-3] = [0.45] * (len(texts()) - 3)
        candidates, _ = decide_minimum(segments)
        for kind, maximum in (("STYLE", 2), ("MOOD", 3), ("SCENE", 2)):
            self.assertTrue(1 <= sum(candidate["kind"] == kind for candidate in candidates) <= maximum)
        self.assertTrue(all(candidate["evidence_level"] == "SUPPORTED_HEURISTIC" for candidate in candidates if candidate["kind"] != "SCENE"))

    def test_invalid_quality_nonmusic_and_duplicate_do_not_force(self):
        for change in ("SILENCE", "NONMUSIC", "DUPLICATE"):
            segments = self.segments()
            if change == "SILENCE":
                segments[0]["quality"] = "SILENCE"
            elif change == "NONMUSIC":
                segments[0]["scores"][-1] = 0.5
            else:
                segments[0]["start_seconds"] = 20
            self.assertEqual(decide_minimum(segments)[0], [])
        segments = self.segments()
        segments[0]["scores"][0] = float("nan")
        with self.assertRaises(ValueError):
            decide_minimum(segments)

    def test_remaining_partition(self):
        items = [dict(sha256=str(index)) for index in range(40)]
        previous = dict(completed=True, policy_version="multilabel-neutral-v1", prompts=texts(), results=[dict(analysis=dict(input_sha256=str(index))) for index in range(15)])
        remaining = remaining_items(items, previous)
        self.assertEqual(len(remaining), 25)
        self.assertFalse({item["sha256"] for item in remaining} & {str(index) for index in range(15)})
        previous["results"].append(previous["results"][0])
        with self.assertRaises(ValueError):
            remaining_items(items, previous)


if __name__ == "__main__":
    unittest.main()
