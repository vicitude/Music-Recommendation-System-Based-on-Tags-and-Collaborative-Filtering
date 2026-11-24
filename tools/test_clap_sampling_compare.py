import unittest

from clap_policy import segment_starts
from clap_sampling_compare import internal_starts


class SamplingComparisonTests(unittest.TestCase):
    def test_exact_internal_positions_and_unchanged_middle(self):
        self.assertEqual(internal_starts(210000), [40.0, 100.0, 160.0])
        for duration in (44000, 180123, 257332, 86400000):
            starts = internal_starts(duration)
            self.assertEqual(starts[1], segment_starts(duration)[1])
            self.assertGreater(starts[0], 0)
            self.assertLess(starts[-1] + 10, duration / 1000)
            self.assertTrue(all(after - before >= 10 for before, after in zip(starts, starts[1:])))

    def test_invalid_or_overlapping_segments_fail_not_resample(self):
        for duration in (None, True, 20000, 40000, 86400001, -1):
            with self.assertRaises(ValueError):
                internal_starts(duration)


if __name__ == "__main__":
    unittest.main()
