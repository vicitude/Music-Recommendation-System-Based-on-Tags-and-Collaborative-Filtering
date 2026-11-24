import unittest

from clap_multilabel import EXPERIMENT_LABELS, decide, texts


class MultiLabelTests(unittest.TestCase):
    def segments(self, names):
        scores = [0.05] * len(texts())
        for index, (_, name, _) in enumerate(EXPERIMENT_LABELS):
            if name in names:
                scores[index * 2:index * 2 + 2] = [0.42, 0.43]
        return [dict(start_seconds=start, quality="OK", scores=list(scores)) for start in (0, 20, 40)]

    def test_multiselect_limits_not_top_one(self):
        candidates, _ = decide(self.segments({"流行", "摇滚", "电子", "活力", "欢快", "浪漫", "甜蜜"}))
        self.assertEqual(sum(item["kind"] == "STYLE" for item in candidates), 2)
        self.assertEqual(sum(item["kind"] == "MOOD" for item in candidates), 3)
        self.assertTrue(all(item["auto_apply"] is False for item in candidates))

    def test_no_padding_and_single_energy_not_scene(self):
        self.assertEqual(decide(self.segments(set()))[0], [])
        candidates, _ = decide(self.segments({"活力"}))
        self.assertEqual([item["name"] for item in candidates], ["活力"])

    def test_dual_prompt_disagreement_and_controls_reject(self):
        segments = self.segments({"流行"})
        for segment in segments:
            segment["scores"][1] = 0.1
        self.assertEqual(decide(segments)[0], [])
        segments = self.segments({"流行"})
        for segment in segments:
            segment["scores"][-1] = 0.40
        self.assertEqual(decide(segments)[0], [])

    def test_bad_scores_and_duplicate_segments(self):
        segments = self.segments({"流行"})
        for segment in segments:
            segment["start_seconds"] = 0
        self.assertEqual(decide(segments)[0], [])
        segments[0]["scores"][0] = float("nan")
        with self.assertRaises(ValueError):
            decide(segments)

    def test_scene_requires_joint_independent_evidence(self):
        candidates, _ = decide(self.segments({"平静", "放松", "活力", "欢快"}))
        self.assertEqual({item["name"] for item in candidates if item["kind"] == "SCENE"}, {"助眠", "运动"})


if __name__ == "__main__":
    unittest.main()
