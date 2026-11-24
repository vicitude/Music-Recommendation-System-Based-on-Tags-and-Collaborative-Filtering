import copy
import unittest

from clap_policy import MAPPING_VERSION, POLICY_VERSION, PROMPTS_VERSION, REVISION, prompt_texts
from clap_prompt_compare import comparison_prompts, score_delta, summarize, validate_baseline


class PromptComparisonTests(unittest.TestCase):
    def test_only_style_changes_and_pairs_are_symmetric(self):
        original, variant = prompt_texts(), comparison_prompts()
        self.assertEqual(len(variant), 41)
        self.assertEqual(original[28:], variant[28:])
        self.assertNotEqual(original[:28], variant[:28])
        for index in range(14):
            genre = variant[index * 2].removeprefix("This is a recording of ").removesuffix(" music.")
            self.assertEqual(variant[index * 2 + 1], f"The music genre is {genre}.")

    def baseline(self):
        segment = dict(start_seconds=0.0, sample_seconds=10, quality="OK", scores=[0.1] * 41)
        segments = [dict(segment, start_seconds=start) for start in (0.0, 15.0, 30.0)]
        return dict(completed=True, revision=REVISION, policy_version=POLICY_VERSION, prompts_version=PROMPTS_VERSION, mapping_version=MAPPING_VERSION, prompts=prompt_texts(), random_seed=42, scan=dict(items=[dict(status="READY", relative_path=str(index), sha256=str(index), duration_ms=40000) for index in range(40)]), results=[dict(filename=str(index), analysis=dict(input_sha256=str(index), status="REJECTED", segments=copy.deepcopy(segments))) for index in range(40)])

    def test_fixed_baseline_contract(self):
        report = self.baseline()
        self.assertEqual(len(validate_baseline(report)), 40)
        for field, value in (("completed", False), ("revision", "other"), ("prompts", [])):
            changed = dict(report, **{field: value})
            with self.assertRaises(ValueError):
                validate_baseline(changed)
        report["results"][0]["analysis"]["segments"][0]["start_seconds"] = 1
        with self.assertRaises(ValueError):
            validate_baseline(report)

    def test_score_delta_checks_metadata_and_lengths(self):
        segments = self.baseline()["results"][0]["analysis"]["segments"]
        self.assertEqual(score_delta(segments, segments), 0)
        changed = copy.deepcopy(segments)
        changed[0]["scores"][0] += 0.02
        self.assertAlmostEqual(score_delta(segments, changed), 0.02)
        with self.assertRaises(ValueError):
            score_delta(segments, changed[:1])
        changed[0]["quality"] = "SILENCE"
        with self.assertRaises(ValueError):
            score_delta(segments, changed)

    def test_summary_denominators_and_no_candidates(self):
        result = dict(self.baseline()["results"][0]["analysis"], candidates=[])
        summary = summarize([dict(original=result)], "original")
        self.assertEqual(summary["songs"], 1)
        self.assertEqual(summary["songs_with_candidates"], 0)
        self.assertEqual(summary["dimensions"]["STYLE"]["segment_count"], 3)
        self.assertEqual(summary["dimensions"]["STYLE"]["failures"]["SCORE"], 1)


if __name__ == "__main__":
    unittest.main()
