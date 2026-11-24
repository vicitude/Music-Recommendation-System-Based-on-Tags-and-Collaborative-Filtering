import copy
import unittest

from clap_policy import LABELS
from clap_reference import evaluate, select_samples, verify_dimension
import test_clap_prompt_compare


class ReferenceTests(unittest.TestCase):
    def fixture(self):
        baseline = test_clap_prompt_compare.PromptComparisonTests().baseline()
        for record in baseline["results"]:
            record["analysis"]["candidates"] = []
        samples = [dict(sha256=item["sha256"], dimensions={kind: dict(status="PENDING", labels=[], evidence={}, exhaustive=False) for kind in ("STYLE", "MOOD")}) for item in select_samples(baseline["scan"]["items"])]
        reference = dict(schema_version=1, selection="SHA256_ASC_FIRST12", samples=samples)
        return baseline, reference

    def verified(self, exhaustive=True):
        return dict(status="VERIFIED", labels=[LABELS[0][1]], exhaustive=exhaustive, evidence=dict(source_type="INDEPENDENT_REVIEW", locator="test-only fixture", quote="fixture reference", mapping_reason="exact test mapping", identity_match=True, independent_of_model=True, reviewer="synthetic test fixture, not real evidence", reviewed_at="2026-11-09"))

    def test_pending_has_no_accuracy(self):
        baseline, reference = self.fixture()
        report = evaluate(reference, baseline)
        self.assertEqual(report["status"], "INSUFFICIENT_REFERENCE")
        for field in ("precision", "recall", "f1"):
            self.assertIsNone(report[field])

    def test_selection_independent_of_input_order(self):
        baseline, reference = self.fixture()
        items = baseline["scan"]["items"]
        self.assertEqual(select_samples(items), select_samples(list(reversed(items))))
        items.append(items[0])
        with self.assertRaises(ValueError):
            select_samples(items)

    def test_model_weak_and_missing_provenance_rejected(self):
        value = self.verified()
        self.assertTrue(verify_dimension("STYLE", value))
        for source in ("CLAP", "SYNTHETIC", "EMBEDDED_METADATA"):
            changed = copy.deepcopy(value)
            changed["evidence"]["source_type"] = source
            with self.assertRaises(ValueError):
                verify_dimension("STYLE", changed)
        for field in ("identity_match", "independent_of_model", "quote", "reviewer"):
            changed = copy.deepcopy(value)
            changed["evidence"].pop(field)
            with self.assertRaises(ValueError):
                verify_dimension("STYLE", changed)

    def test_complete_reference_counts_false_and_abstention(self):
        baseline, reference = self.fixture()
        sample = reference["samples"][0]
        sample["dimensions"]["STYLE"] = self.verified()
        row = next(row for row in baseline["results"] if row["analysis"]["input_sha256"] == sample["sha256"])
        row["analysis"]["candidates"] = [dict(kind="STYLE", name=LABELS[1][1])]
        for record in baseline["results"]:
            record["analysis"].setdefault("candidates", [])
        report = evaluate(reference, baseline)
        self.assertEqual((report["precision"], report["recall"], report["f1"]), (0, 0, 0))
        row["analysis"]["candidates"] = []
        report = evaluate(reference, baseline)
        self.assertIsNone(report["precision"])
        self.assertEqual(report["counts"]["abstained_complete_dimensions"], 1)

    def test_partial_missing_label_is_unknown_not_false(self):
        baseline, reference = self.fixture()
        for record in baseline["results"]:
            record["analysis"]["candidates"] = [dict(kind="STYLE", name=LABELS[1][1])]
        reference["samples"][0]["dimensions"]["STYLE"] = self.verified(False)
        report = evaluate(reference, baseline)
        self.assertEqual(report["counts"]["partial_unknown_predictions"], 1)
        self.assertIsNone(report["precision"])
        self.assertIsNone(report["recall"])

    def test_wrong_identity_rejected(self):
        baseline, reference = self.fixture()
        reference["samples"][0]["sha256"] = "changed"
        with self.assertRaises(ValueError):
            evaluate(reference, baseline)


if __name__ == "__main__":
    unittest.main()
