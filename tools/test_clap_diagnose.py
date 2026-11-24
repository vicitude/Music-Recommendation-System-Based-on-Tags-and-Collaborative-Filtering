import unittest

from clap_diagnose import diagnose_dimensions
from clap_policy import decide_candidates
from test_clap_policy import segment


class DiagnosisTests(unittest.TestCase):
    def test_explicit_failures_and_production_agree(self):
        for samples in ([segment(0), segment(20)], [segment(0, score=0.25), segment(20, score=0.25)], [segment(0, second=0.49), segment(20, second=0.49)], [segment(0, control=0.49), segment(20, control=0.49)], [segment(0), segment(20, winner="流行")]):
            result = diagnose_dimensions(dict(segments=samples))
            candidates, _ = decide_candidates(samples)
            self.assertEqual({kind for kind, evidence in result.items() if evidence["passed"]}, {item["kind"] for item in candidates})
        self.assertIn("SCORE", diagnose_dimensions(dict(segments=[segment(0, score=0.25), segment(20, score=0.25)]))["STYLE"]["failures"])

    def test_no_valid_segments_reported_as_insufficient(self):
        result = diagnose_dimensions(dict(segments=[]))
        self.assertEqual(result["STYLE"]["failures"], ["INSUFFICIENT_SEGMENTS"])


if __name__ == "__main__":
    unittest.main()
