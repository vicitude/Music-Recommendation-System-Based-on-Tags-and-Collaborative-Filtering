import unittest

from clap_library_repair import combine_plan


class LibraryRepairTests(unittest.TestCase):
    def fixture(self):
        old = dict(items=[dict(sha256=str(index)) for index in range(40)])
        diagnosis = dict(matched_unique=36, missing=[dict(sha256=str(index)) for index in range(4)], duplicates=[], non_target_songs=[{}] * 4)
        additions = [dict(sha256=str(index)) for index in range(40, 44)]
        return old, diagnosis, additions

    def test_exact36_preserved_four_replaced_no_title_matching(self):
        old, diagnosis, additions = self.fixture()
        result = combine_plan(old, diagnosis, additions)
        self.assertEqual({item["sha256"] for item in result["items"]}, {str(index) for index in range(4, 44)})
        self.assertEqual(len(old["items"]), 40)

    def test_ambiguous_or_inconsistent_partition_rejected(self):
        old, diagnosis, additions = self.fixture()
        diagnosis["duplicates"] = [{}]
        with self.assertRaises(ValueError):
            combine_plan(old, diagnosis, additions)
        diagnosis["duplicates"] = []
        additions[0]["sha256"] = "4"
        with self.assertRaises(ValueError):
            combine_plan(old, diagnosis, additions)
