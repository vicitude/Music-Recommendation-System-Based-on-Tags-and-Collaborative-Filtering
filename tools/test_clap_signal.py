import unittest

import numpy as np

from clap_batch import signal_quality


class SignalTests(unittest.TestCase):
    def test_silence_short_and_pure_tone_rejected(self):
        rate = 48000
        self.assertEqual(signal_quality(np.zeros(rate), rate), "TOO_SHORT")
        self.assertEqual(signal_quality(np.zeros(rate * 6), rate), "SILENCE")
        tone = 0.1 * np.sin(2 * np.pi * 440 * np.arange(rate * 6) / rate)
        self.assertEqual(signal_quality(tone, rate), "TONAL_CONTROL")

    def test_broadband_is_not_tonal_but_still_requires_model_controls(self):
        signal = np.random.default_rng(42).normal(0, 0.1, 48000 * 6)
        self.assertEqual(signal_quality(signal, 48000), "OK")


if __name__ == "__main__":
    unittest.main()
