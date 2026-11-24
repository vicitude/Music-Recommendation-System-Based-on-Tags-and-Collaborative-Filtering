import copy
import random
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from music.diversity import discovery_metrics, rerank_diverse, serendipity_score, tag_distance
from music.recommendation import SongFeatures, TimedSong, UserSignals, recommend


class DiversityTests(unittest.TestCase):
    def setUp(self):
        self.items = [{'song_id': 1, 'score': .9}, {'song_id': 2, 'score': .89}, {'song_id': 3, 'score': .88}, {'song_id': 4, 'score': .87}]
        self.tags = {1: (1,), 2: (1,), 3: (2,), 4: (3,)}
        self.pop = {1: 100, 2: 90, 3: 5, 4: 1}

    def rerank(self, **overrides):
        args = dict(items=self.items, song_tags=self.tags, popularity=self.pop, user_history_tags=set(), limit=4)
        args.update(overrides)
        return rerank_diverse(**args)

    def test_ut_div_001_tag_jaccard(self):
        self.assertEqual(tag_distance((1, 1), (1,)), 0)
        self.assertEqual(tag_distance((1,), (2,)), 1)
        self.assertEqual(tag_distance((), ()), 0)
        self.assertAlmostEqual(tag_distance((1, 2), (2, 3)), 2/3)

    def test_ut_div_002_serendipity(self):
        args = dict(user_history_tags={3}, song_tags=self.tags, popularity=self.pop)
        self.assertAlmostEqual(serendipity_score(song_id=4, **args), .99)
        self.assertEqual(serendipity_score(song_id=3, **args), 0)
        self.assertEqual(serendipity_score(song_id=1, user_history_tags={1}, song_tags=self.tags, popularity=self.pop), 0)
        self.assertEqual(serendipity_score(song_id=4, user_history_tags={3}, song_tags=self.tags, popularity={}), 1)
        self.assertEqual(serendipity_score(song_id=99, **args), 0)

    def test_ut_div_003_zero_preserves_order(self):
        unsorted = [dict(item, score=.5) for item in reversed(self.items)]
        out = self.rerank(items=unsorted, limit=3, diversity_weight=0, serendipity_weight=0)
        self.assertEqual([i['song_id'] for i in out], [4, 3, 2])

    def test_ut_div_004_diversifies(self):
        out = self.rerank(items=self.items[:3], limit=3, serendipity_weight=0)
        # After fixed first: same tag=.75*.89=.6675; different=.75*.88+.25=.91.
        self.assertEqual([i['song_id'] for i in out], [1, 3, 2])

    def test_ut_div_005_validation(self):
        bad = [dict(limit=True), dict(limit=21), dict(diversity_weight=.8, serendipity_weight=.3),
               dict(serendipity_weight=float('nan')), dict(popularity={2: -1}), dict(popularity={2: True}),
               dict(popularity={2: float('inf')}), dict(song_tags={1: (True,)}), dict(items=[{'song_id': True, 'score': .5}]),
               dict(items=self.items*2), dict(items=[{'song_id': 1, 'score': -1}]),
               dict(items=[{'song_id': 1, 'score': float('nan')}]), dict(user_history_tags={False})]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.rerank(**args)
        with self.assertRaises(ValueError):
            discovery_metrics(recommendations={}, targets={}, histories={}, song_tags={}, k=0)

    def test_ut_div_006_copy_hot_and_missing(self):
        original = [dict(item, source='HOT', evidence={'tag_ids': [1]}) for item in self.items]
        before = copy.deepcopy(original)
        out = self.rerank(items=original, limit=3)
        self.assertEqual([i['song_id'] for i in out], [1, 2, 3])
        out[0]['evidence']['tag_ids'].append(9)
        self.assertEqual(original, before)
        mixed = [dict(self.items[0], source='CONTENT'), dict(self.items[1], source='HOT'), dict(self.items[2], source='NCF')]
        self.assertEqual([i['song_id'] for i in self.rerank(items=mixed)], [1, 3, 2])
        self.assertEqual([i['song_id'] for i in self.rerank(song_tags={}, popularity={})], [1, 2, 3, 4])
        self.assertEqual(self.rerank(limit=0), [])

    def engine_args(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        past = now-timedelta(days=2)
        songs = tuple(SongFeatures(i, tags, True, True, True, True) for i, tags in ((1, (1,)), (2, (1,)), (3, (2,)), (4, (3,)), (5, (1,))))
        return dict(user_id=1, now=now, songs=songs,
                    users=(UserSignals(1, 'REAL', interest_ids=(1, 2, 3), favorites=(TimedSong(5, past),)),),
                    active_tags={1: '民谣', 2: '治愈', 3: '工作'}, limit=4)

    def test_ut_div_007_integration_mapping(self):
        args = self.engine_args()
        with patch('music.recommendation.rerank_diverse', wraps=rerank_diverse) as call:
            recommend(**args)
        kw = call.call_args.kwargs
        self.assertEqual(kw['user_history_tags'], {1})
        self.assertEqual(kw['song_tags'][3], (2,))
        self.assertTrue(all(count == 0 for count in kw['popularity'].values()))
        self.assertNotIn(5, [i['song_id'] for i in kw['items']])

    def test_ut_div_008_integration_changes_order(self):
        from dataclasses import replace
        args = self.engine_args()
        args['users'] = (replace(args['users'][0], interest_ids=()),)
        args['songs'] = tuple(replace(song, tag_ids=()) if song.song_id == 5 else song for song in args['songs'])
        # Controlled NCF scores isolate the post-fusion reranking mechanism.
        with patch('music.recommendation.compute_ncf', return_value={1: .9, 2: .89, 3: .88, 4: .87}):
            base = recommend(**args, enable_rerank=False)
            out = recommend(**args)
        self.assertEqual(base.items[0]['song_id'], out.items[0]['song_id'])
        self.assertNotEqual([i['song_id'] for i in base.items], [i['song_id'] for i in out.items])
        self.assertEqual({i['song_id'] for i in base.items}, {i['song_id'] for i in out.items})

    def test_ut_div_009_switch_scores_and_isolation(self):
        from dataclasses import replace
        args = self.engine_args()
        base = recommend(**args, enable_rerank=False)
        out = recommend(**args)
        by_id = lambda items: {i['song_id']: {k: v for k, v in i.items() if k != 'rank'} for i in items}
        self.assertEqual(by_id(base.items), by_id(out.items))
        changed = dict(args)
        changed['users'] = (replace(args['users'][0], favorites=args['users'][0].favorites+(TimedSong(3, args['now']+timedelta(days=1)),)),
                            UserSignals(2, 'SIMULATED', favorites=(TimedSong(3, args['now']-timedelta(days=1)),)))
        self.assertEqual(out, recommend(**changed))
        with self.assertRaises(ValueError):
            recommend(**args, enable_rerank=1)

    def test_ut_div_010_metric_oracles(self):
        args = dict(recommendations={1: [2, 3]}, targets={1: {3}}, histories={1: {1}}, song_tags={1: (1,), 2: (1,), 3: (2,)}, k=2)
        self.assertEqual(discovery_metrics(**args), {'unexpectedness': .5, 'serendipity': .5})
        self.assertEqual(discovery_metrics(**dict(args, targets={})), {'unexpectedness': .5, 'serendipity': 0})
        self.assertEqual(discovery_metrics(**dict(args, histories={})), {'unexpectedness': None, 'serendipity': None})
        self.assertEqual(discovery_metrics(**dict(args, song_tags={})), {'unexpectedness': 0, 'serendipity': 0})
        self.assertEqual(discovery_metrics(**dict(args, recommendations={1: [3, 3]}, k=10))['serendipity'], .1)

    def test_pt_div_001_zero_and_no_mutation(self):
        for seed in range(10):
            items = copy.deepcopy(self.items)
            random.Random(seed).shuffle(items)
            before = copy.deepcopy(items)
            out = self.rerank(items=items, limit=3, diversity_weight=0, serendipity_weight=0)
            self.assertEqual([i['song_id'] for i in out], [i['song_id'] for i in items[:3]])
            self.assertEqual(items, before)

    def test_pt_div_002_closure(self):
        for seed in range(10):
            rng = random.Random(seed)
            items = [{'song_id': i, 'score': rng.random()} for i in range(1, 21)]
            out = self.rerank(items=items, limit=10)
            self.assertEqual(len(out), 10)
            self.assertEqual(len({i['song_id'] for i in out}), 10)
            self.assertEqual(out[0]['song_id'], items[0]['song_id'])
            self.assertEqual([i['rank'] for i in out], list(range(1, 11)))

    def test_pt_div_003_determinism(self):
        for seed in range(10):
            tail = self.items[1:]
            random.Random(seed).shuffle(tail)
            self.assertEqual(self.rerank(), self.rerank(items=self.items[:1]+tail))
