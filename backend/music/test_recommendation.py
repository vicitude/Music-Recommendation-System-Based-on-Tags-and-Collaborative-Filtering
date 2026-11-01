import itertools
import json
import math
import random
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from music.recommendation import (
    SongFeatures,
    TimedSong,
    UserSignals,
    compute_cf,
    compute_profile,
    content_weight,
    fuse_candidates,
    positive_matrix,
    recommend,
)


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 4, tzinfo=timezone.utc)
        self.past = self.now - timedelta(days=2)
        self.tags = {1: "民谣", 2: "治愈", 3: "通勤"}

    def event(self, song_id, when=None):
        return TimedSong(song_id, when or self.past)

    def song(self, song_id, tag_ids=()):
        return SongFeatures(song_id, tag_ids, True, True, True, True)

    def run_engine(self, *, songs=(), users=None, active_tags=None, limit=20):
        return recommend(
            user_id=1, now=self.now, songs=tuple(songs),
            users=tuple(users if users is not None else [UserSignals(1, "REAL")]),
            active_tags=self.tags if active_tags is None else active_tags, limit=limit,
        )

    def fuse(self, *, candidates=(1, 2), content=None, collaborative=None, tags=None, counts=None, popularity=None, maturity=10, limit=20):
        return fuse_candidates(
            candidate_ids=candidates, content_scores=content or {}, cf_scores=collaborative or {},
            evidence_tags=tags or {}, neighbor_counts=counts or {}, popularity=popularity or {},
            active_tags=self.tags, positive_song_count=maturity, limit=limit,
        )

    def test_tc_m_008_exact_fusion_oracle(self):
        result = self.fuse(content={1: 0.8, 2: 1.0}, collaborative={1: 0.5, 2: 1.0}, tags={1: (1,), 2: (2,)}, counts={1: 1, 2: 1})
        self.assertEqual(result.alpha_target, 0.6)
        item = next(item for item in result.items if item["song_id"] == 1)
        self.assertEqual(item["score"], 0.68)
        self.assertEqual(item["source"], "HYBRID")

    def test_pt_m_002_weight_monotonicity(self):
        previous = 0.9
        for count in range(100001):
            weight = content_weight(positive_song_count=count)
            self.assertGreater(weight, 0.3)
            self.assertLessEqual(weight, previous)
            self.assertLessEqual(weight, 0.9)
            previous = weight
        self.assertAlmostEqual(content_weight(positive_song_count=0), 0.9)
        self.assertEqual(content_weight(positive_song_count=10), 0.6)

    def test_weight_rejects_invalid_maturity(self):
        for value in [-1, True, 1.0, "10", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                content_weight(positive_song_count=value)

    def test_positive_matrix_deduplicates_and_caps_at_eight(self):
        signals = UserSignals(1, "REAL", favorites=(self.event(1), self.event(1)), completions=(self.event(1), self.event(1), self.event(2)))
        matrix = positive_matrix(users=(signals,), cutoff=self.now, origin="REAL")
        self.assertEqual(matrix, {1: {1: 8.0, 2: 3.0}})
        without_favorite = replace(signals, favorites=())
        self.assertEqual(positive_matrix(users=(without_favorite,), cutoff=self.now, origin="REAL"), {1: {1: 3.0, 2: 3.0}})

    def test_cutoff_is_strict_and_origin_groups_are_separate(self):
        signals = UserSignals(1, "REAL", favorites=(self.event(1), self.event(2, self.now)), completions=(self.event(3, self.now + timedelta(seconds=1)),))
        simulated = UserSignals(2, "SIMULATED", favorites=(self.event(4),))
        matrix = positive_matrix(users=(signals, simulated), cutoff=self.now, origin="REAL")
        self.assertEqual(matrix, {1: {1: 5.0}})

    def test_profile_blends_initial_and_behavior_vectors(self):
        result = compute_profile(interest_ids=(1,), positive_scores={10: 5.0}, song_vectors={10: {2: 1.0}})
        self.assertAlmostEqual(result[1], 10 / math.sqrt(101))
        self.assertAlmostEqual(result[2], 1 / math.sqrt(101))
        self.assertAlmostEqual(math.fsum(value * value for value in result.values()), 1)

    def test_profile_zero_and_single_route_cases(self):
        self.assertEqual(compute_profile(interest_ids=(), positive_scores={}, song_vectors={}), {})
        self.assertEqual(compute_profile(interest_ids=(1, 1), positive_scores={90: 3}, song_vectors={}), {1: 1.0})
        self.assertEqual(compute_profile(interest_ids=(), positive_scores={90: 3}, song_vectors={90: {2: 1.0}}), {2: 1.0})

    def test_cf_requires_two_shared_positive_songs(self):
        scores, counts = compute_cf(user_id=1, matrix={1: {1: 5}, 2: {1: 5, 9: 8}}, candidate_ids=(9,))
        self.assertEqual(scores, {9: 0.0})
        self.assertEqual(counts, {9: 0})

    def test_cf_uses_only_contributing_neighbors_in_denominator(self):
        scores, counts = compute_cf(
            user_id=1, matrix={1: {1: 5, 2: 5}, 2: {1: 5, 2: 5, 9: 8}, 3: {1: 5, 2: 5}},
            candidate_ids=(9, 10),
        )
        self.assertAlmostEqual(scores[9], 8.0)
        self.assertEqual(counts, {9: 1, 10: 0})

    def test_cf_top_twenty_ties_use_user_id(self):
        matrix = {1: {1: 5, 2: 5}}
        for user_id in range(2, 23):
            matrix[user_id] = {1: 5, 2: 5, 100 + user_id: 5}
        scores, counts = compute_cf(user_id=1, matrix=matrix, candidate_ids=(102, 121, 122))
        self.assertEqual(counts, {102: 1, 121: 1, 122: 0})
        self.assertEqual(scores[122], 0)

    def test_cf_weighted_average_matches_hand_calculation(self):
        matrix = {1: {1: 5, 2: 5}, 2: {1: 5, 2: 5, 3: 5}, 3: {1: 8, 2: 3, 3: 8}}
        first_similarity = 50 / (math.sqrt(50) * math.sqrt(75))
        second_similarity = 55 / (math.sqrt(50) * math.sqrt(137))
        expected = (5 * first_similarity + 8 * second_similarity) / (first_similarity + second_similarity)
        scores, counts = compute_cf(user_id=1, matrix=matrix, candidate_ids=(3,))
        self.assertAlmostEqual(scores[3], expected)
        self.assertEqual(counts[3], 2)

    def test_tc_m_009_new_user_tags_fall_back_to_content(self):
        result = self.run_engine(songs=[self.song(1, (1,)), self.song(2, (2,))], users=[UserSignals(1, "REAL", (1,))])
        self.assertEqual(result.alpha_effective, 1.0)
        self.assertEqual(result.items[0]["source"], "CONTENT")
        self.assertEqual(result.items[0]["evidence"], {"tag_ids": [1], "neighbor_count": 0})
        self.assertEqual(result.items[1]["source"], "HOT")

    def test_cf_only_fallback_has_no_fabricated_tags(self):
        target = UserSignals(1, "REAL", favorites=(self.event(1), self.event(2)))
        neighbor = UserSignals(2, "REAL", favorites=(self.event(1), self.event(2), self.event(3)))
        result = self.run_engine(songs=[self.song(3)], users=[target, neighbor])
        self.assertEqual(result.alpha_effective, 0.0)
        self.assertEqual(result.items[0]["source"], "CF")
        self.assertEqual(result.items[0]["evidence"], {"tag_ids": [], "neighbor_count": 1})
        self.assertEqual(result.items[0]["explanation"], "与你偏好相近的用户也喜欢")

    def test_tc_m_010_empty_candidates_return_reason(self):
        for songs in [[], [SongFeatures(1)], [replace(self.song(1), file_exists=False)]]:
            result = self.run_engine(songs=songs)
            self.assertEqual(result.items, [])
            self.assertIsNone(result.alpha_effective)
            self.assertEqual(result.empty_reason, "NO_ELIGIBLE_SONGS")

    def test_tc_m_011_popular_fallback_is_honest_and_group_local(self):
        users = [
            UserSignals(1, "REAL"),
            UserSignals(2, "REAL", favorites=(self.event(3),)),
            UserSignals(3, "REAL", favorites=(self.event(3), self.event(2))),
            UserSignals(4, "SIMULATED", favorites=(self.event(1),)),
            UserSignals(5, "SIMULATED", favorites=(self.event(1),)),
        ]
        result = self.run_engine(songs=[self.song(1), self.song(2), self.song(3)], users=users)
        self.assertEqual([item["song_id"] for item in result.items], [3, 2, 1])
        self.assertIsNone(result.alpha_effective)
        for item in result.items:
            self.assertEqual(item["source"], "HOT")
            self.assertEqual(item["score"], 0)
            self.assertEqual(item["evidence"], {"tag_ids": [], "neighbor_count": 0})
            self.assertEqual(item["explanation"], "热门歌曲，供你探索")

    def test_recent_completion_boundary_and_old_completion_eligibility(self):
        target = UserSignals(1, "REAL", completions=(
            self.event(1, self.now - timedelta(hours=24)),
            self.event(2, self.now - timedelta(hours=24, microseconds=1)),
            self.event(3, self.now),
        ), favorites=(self.event(4), self.event(5, self.now)))
        result = self.run_engine(songs=[self.song(song_id) for song_id in range(1, 6)], users=[target])
        self.assertEqual({item["song_id"] for item in result.items}, {2, 3, 5})

    def test_pt_m_003_all_eligibility_flag_combinations(self):
        songs = tuple(SongFeatures(index, (), *flags) for index, flags in enumerate(itertools.product([False, True], repeat=4), start=1))
        result = self.run_engine(songs=songs)
        self.assertEqual([item["song_id"] for item in result.items], [16])

    def test_pt_m_003_random_candidates_are_unique_and_eligible(self):
        generator = random.Random(42)
        for count in [0, 1, 20, 100, 300]:
            songs = [SongFeatures(song_id, (1,), *(generator.choice([False, True]) for _ in range(4))) for song_id in range(1, count + 1)]
            excluded = {song_id for song_id in range(1, count + 1) if generator.random() < 0.15}
            target = UserSignals(1, "REAL", (1,), favorites=tuple(self.event(song_id) for song_id in excluded))
            result = self.run_engine(songs=songs, users=[target])
            eligible = {song.song_id for song in songs if song.active and song.playback_allowed and song.checked and song.file_exists} - excluded
            identifiers = [item["song_id"] for item in result.items]
            self.assertEqual(len(set(identifiers)), len(identifiers))
            self.assertTrue(set(identifiers) <= eligible)
            self.assertEqual(len(identifiers), min(20, len(eligible)))

    def test_pt_m_004_four_sources_have_matching_evidence(self):
        result = self.fuse(
            candidates=(1, 2, 3, 4), content={1: 1, 3: 1}, collaborative={2: 1, 3: 1},
            tags={1: (1,), 3: (1, 2)}, counts={2: 1, 3: 2},
        )
        by_source = {item["source"]: item for item in result.items}
        self.assertEqual(set(by_source), {"CONTENT", "CF", "HYBRID", "HOT"})
        self.assertEqual(by_source["CONTENT"]["evidence"], {"tag_ids": [1], "neighbor_count": 0})
        self.assertEqual(by_source["CF"]["evidence"], {"tag_ids": [], "neighbor_count": 1})
        self.assertEqual(by_source["HYBRID"]["explanation"], "匹配民谣、治愈，相近偏好用户也喜欢")
        self.assertEqual(by_source["HOT"]["evidence"], {"tag_ids": [], "neighbor_count": 0})

    def test_behavior_tags_do_not_claim_manual_selection(self):
        target = UserSignals(1, "REAL", completions=(self.event(1),))
        result = self.run_engine(songs=[self.song(1, (2,)), self.song(2, (2,))], users=[target])
        item = next(item for item in result.items if item["song_id"] == 2)
        self.assertEqual(item["explanation"], "符合你的听歌偏好：治愈")
        self.assertNotIn("选择", item["explanation"])

    def test_evidence_has_top_two_tags_with_deterministic_ties(self):
        result = self.run_engine(songs=[self.song(1, (3, 2, 1))], users=[UserSignals(1, "REAL", (3, 2, 1))])
        self.assertEqual(result.items[0]["evidence"]["tag_ids"], [1, 2])

    def test_evidence_ranks_contribution_before_tag_id(self):
        target = UserSignals(1, "REAL", (3,), completions=(self.event(1),))
        result = self.run_engine(songs=[self.song(1, (2,)), self.song(2, (1, 2, 3))], users=[target])
        item = next(item for item in result.items if item["song_id"] == 2)
        self.assertEqual(item["evidence"]["tag_ids"], [3, 2])

    def test_end_to_end_hybrid_uses_history_and_neighbor_evidence(self):
        target = UserSignals(1, "REAL", (1,), favorites=(self.event(1), self.event(2)))
        neighbor = UserSignals(2, "REAL", favorites=(self.event(1), self.event(2), self.event(3)))
        result = self.run_engine(songs=[self.song(1, (1,)), self.song(2, (1,)), self.song(3, (1,))], users=[target, neighbor])
        self.assertAlmostEqual(result.alpha_target, 0.8)
        self.assertEqual(result.alpha_effective, result.alpha_target)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["source"], "HYBRID")
        self.assertEqual(result.items[0]["score"], 1.0)
        self.assertEqual(result.items[0]["evidence"], {"tag_ids": [1], "neighbor_count": 1})

    def test_inactive_tags_do_not_contribute_to_profile_or_evidence(self):
        result = self.run_engine(songs=[self.song(1, (1,))], users=[UserSignals(1, "REAL", (1,))], active_tags={2: "治愈"})
        self.assertEqual(result.items[0]["source"], "HOT")
        self.assertEqual(result.items[0]["evidence"]["tag_ids"], [])

    def test_single_positive_candidate_uses_max_not_min_max(self):
        result = self.fuse(candidates=(1,), content={1: 0.17}, tags={1: (1,)})
        self.assertEqual(result.items[0]["content_score"], 1.0)
        self.assertEqual(result.items[0]["score"], 1.0)

    def test_normalization_uses_full_candidates_before_output_limit(self):
        result = self.fuse(content={1: 0.8, 2: 1.0}, collaborative={1: 1, 2: 0}, tags={1: (1,), 2: (2,)}, counts={1: 1}, limit=1)
        self.assertEqual(result.items[0]["song_id"], 1)
        self.assertEqual(result.items[0]["content_score"], 0.8)
        self.assertEqual(result.items[0]["score"], 0.88)

    def test_hot_counts_distinct_positive_users_not_event_volume(self):
        target = UserSignals(1, "REAL")
        frequent = UserSignals(2, "REAL", completions=tuple(self.event(1) for _ in range(100)))
        neighbors = [UserSignals(user_id, "REAL", completions=(self.event(2),)) for user_id in (3, 4)]
        result = self.run_engine(songs=[self.song(1), self.song(2)], users=[target, frequent, *neighbors])
        self.assertEqual([item["song_id"] for item in result.items], [2, 1])

    def test_sorting_precedes_rounding_and_equal_scores_use_song_id(self):
        result = self.fuse(content={1: 0.9999997, 2: 1.0}, tags={1: (1,), 2: (1,)})
        self.assertEqual([item["song_id"] for item in result.items], [2, 1])
        self.assertEqual([item["score"] for item in result.items], [1.0, 1.0])
        result = self.fuse(candidates=(2, 1), content={1: 1, 2: 1}, tags={1: (1,), 2: (1,)})
        self.assertEqual([item["song_id"] for item in result.items], [1, 2])

    def test_hot_popularity_never_overrides_personalized_scores(self):
        result = self.fuse(content={1: 0.1}, tags={1: (1,)}, popularity={2: 10000})
        self.assertEqual([item["song_id"] for item in result.items], [1, 2])
        self.assertEqual(result.items[1]["score"], 0)

    def test_pt_m_006_permuted_inputs_have_identical_output(self):
        generator = random.Random(42)
        songs = [self.song(song_id, tuple(generator.sample([1, 2, 3], generator.randint(0, 3)))) for song_id in range(1, 40)]
        users = [UserSignals(1, "REAL", (1, 2), favorites=(self.event(1), self.event(2)))]
        for user_id in range(2, 30):
            users.append(UserSignals(user_id, "REAL" if user_id < 26 else "SIMULATED", favorites=tuple(self.event(song_id) for song_id in [1, 2, *generator.sample(range(3, 40), 8)])))
        expected = self.run_engine(songs=songs, users=users)
        for iteration in range(20):
            generator.shuffle(songs)
            generator.shuffle(users)
            songs = [replace(song, tag_ids=tuple(reversed(song.tag_ids))) for song in songs]
            users = [replace(user, favorites=tuple(reversed(user.favorites)), interest_ids=tuple(reversed(user.interest_ids))) for user in users]
            self.assertEqual(self.run_engine(songs=songs, users=users, active_tags=dict(reversed(list(self.tags.items())))), expected)

    def test_simulated_neighbors_do_not_affect_real_collaborative_scores(self):
        target = UserSignals(1, "REAL", favorites=(self.event(1), self.event(2)))
        simulated = UserSignals(2, "SIMULATED", favorites=(self.event(1), self.event(2), self.event(3)))
        result = self.run_engine(songs=[self.song(3)], users=[target, simulated])
        self.assertEqual(result.items[0]["source"], "HOT")
        self.assertEqual(result.items[0]["evidence"]["neighbor_count"], 0)

    def test_output_matches_entity_and_api_schemas(self):
        root = Path(__file__).resolve().parents[2] / "specs/music/system"
        entities = json.loads((root / "entities.schema.json").read_text(encoding="utf-8"))
        api = json.loads((root / "openapi.yaml").read_text(encoding="utf-8"))
        validators = [
            Draft202012Validator({"$ref": "#/$defs/RecommendationItem", "$defs": entities["$defs"]}),
            Draft202012Validator({"$ref": "#/components/schemas/RecommendationItem", "components": api["components"]}),
        ]
        result = self.fuse(candidates=(1, 2, 3, 4), content={1: 1, 3: 1}, collaborative={2: 1, 3: 1}, tags={1: (1,), 3: (1, 2)}, counts={2: 1, 3: 2})
        for item in result.items:
            for validator in validators:
                validator.validate(item)
            for field in ["score", "content_score", "cf_score"]:
                self.assertTrue(math.isfinite(item[field]))
                self.assertTrue(0 <= item[field] <= 1)

    def test_invalid_input_is_rejected_without_silent_fallback(self):
        for limit in [0, 21, True, 1.0]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.run_engine(limit=limit)
        with self.assertRaises(ValueError):
            self.run_engine(users=[])
        with self.assertRaises(ValueError):
            self.run_engine(songs=[self.song(1), self.song(1)])
        with self.assertRaises(ValueError):
            self.run_engine(users=[UserSignals(1, "REAL"), UserSignals(1, "REAL")])
        with self.assertRaises(ValueError):
            TimedSong(1, datetime(2026, 10, 30))
        with self.assertRaises(ValueError):
            UserSignals(1, "UNKNOWN")
        for score in [-1, math.nan, math.inf, True]:
            with self.subTest(score=score), self.assertRaises(ValueError):
                self.fuse(content={1: score}, tags={1: (1,)})
        with self.assertRaises(ValueError):
            self.fuse(content={1: 1})
        with self.assertRaises(ValueError):
            self.fuse(collaborative={1: 1})


if __name__ == "__main__":
    unittest.main()
