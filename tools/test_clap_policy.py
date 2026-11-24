import unittest

from clap_policy import LABELS, decide_candidates, prompt_texts, segment_starts


def segment(start, winner="摇滚", score=0.5, control=0.1, second=0.15):
    scores = [0.1] * len(prompt_texts())
    for index, label in enumerate(LABELS):
        if label[0] == "STYLE":
            scores[index * 2:index * 2 + 2] = [score if label[1] == winner else second] * 2
    scores[-3:] = [control] * 3
    return dict(start_seconds=start, sample_seconds=10.0, quality="OK", scores=scores)


class PolicyTests(unittest.TestCase):
    def test_segment_starts_are_bounded_and_non_overlapping(self):
        self.assertEqual(segment_starts(19000), [])
        self.assertEqual(segment_starts(20000), [0.0, 10.0])
        self.assertEqual(segment_starts(30000), [0.0, 10.0, 20.0])
        self.assertEqual(segment_starts(180000), [0.0, 85.0, 170.0])
        self.assertEqual(segment_starts(True), [])

    def test_consistent_evidence_produces_review_only_candidate(self):
        candidates, reasons = decide_candidates([segment(0), segment(20), segment(40)])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "摇滚")
        self.assertFalse(candidates[0]["auto_apply"])
        self.assertTrue(candidates[0]["needs_review"])
        self.assertNotIn("confidence", candidates[0])

    def test_low_score_tie_controls_and_conflicting_segments_reject(self):
        for segments in ([segment(0, score=0.25), segment(20, score=0.25)], [segment(0, second=0.49), segment(20, second=0.49)], [segment(0, control=0.49), segment(20, control=0.49)], [segment(0, winner="摇滚"), segment(20, winner="流行")]):
            with self.subTest(segments=segments):
                self.assertEqual(decide_candidates(segments)[0], [])

    def test_short_duplicate_and_bad_quality_not_independent_evidence(self):
        self.assertEqual(decide_candidates([segment(0), segment(1)])[0], [])
        self.assertEqual(decide_candidates([dict(start_seconds=0, quality="SILENCE", scores=[])])[0], [])
        self.assertEqual(decide_candidates([dict(start_seconds=0, quality="TONAL_CONTROL", scores=[])])[0], [])

    def test_invalid_scores_are_rejected(self):
        for value in (float("nan"), float("inf"), True, 2.0):
            sample = segment(0)
            sample["scores"][0] = value
            with self.assertRaises(ValueError):
                decide_candidates([sample, segment(20)])


if __name__ == "__main__":
    unittest.main()
