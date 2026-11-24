import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music.evaluation import EvaluationDataset, Interaction, time_split, user_groups, EvaluationError
from music.evaluation.catalog_simulation import generate, compare, run, encoded, METHODS
from datetime import datetime


def catalog():
    return {'catalog_version': 'catalog-472-v1', 'scope': 'synthetic test fixture',
        'tags': [{'id': t, 'name': str(t), 'kind': 'STYLE'} for t in range(1, 13)],
        'songs': [{'song_id': sid, 'tag_ids': [sid % 12 + 1]} for sid in range(1, 473)]}


def dataset(data):
    return EvaluationDataset({'origin': 'SIMULATED'}, tuple(data['songs']), tuple(data['users']),
        tuple(Interaction(e['user_id'], e['song_id'], datetime.fromisoformat(e['occurred_at']), e['positive']) for e in data['interactions']))


class CatalogSimulationTests(unittest.TestCase):
    def test_generation_reproducibility_and_split(self):
        # PT-SIM472-001: ordering independence, quotas, no train/heldout pairs overlap.
        c = catalog()
        data = generate(c, 42)
        c['songs'].reverse()
        c['tags'].reverse()
        self.assertEqual(encoded(data), encoded(generate(c, 42)))
        split = time_split(dataset(data))
        self.assertEqual(tuple(map(len, (split.train, split.validation, split.test))), (2800, 400, 800))
        self.assertEqual([len(g) for g in user_groups(dataset=dataset(data), train=split.train).values()], [50] * 4)
        train = {(e.user_id, e.song_id) for e in split.train}
        self.assertFalse(train & {(e.user_id, e.song_id) for e in split.validation + split.test})
        self.assertEqual(sum(not u['interest_tag_ids'] for u in data['users']), 25)

    def test_candidate_closure_and_heldout_independence(self):
        # PT-SIM472-002: nine methods, only training used by scorer, one fit per compare.
        data = generate(catalog(), 42)
        ds = dataset(data)
        split = time_split(ds)
        from music.evaluation.catalog_simulation import fit_ncf
        with patch('music.evaluation.catalog_simulation.fit_ncf', wraps=fit_ncf) as fitting:
            report, rankings = compare(ds, split)
            self.assertEqual(fitting.call_count, 1)
        changed = copy.deepcopy(data)
        for event in changed['interactions'][2800:]:
            event['song_id'] = event['song_id'] % 472 + 1
        altered = dataset(changed)
        _, other = compare(altered, time_split(altered))
        self.assertEqual(rankings, other)
        self.assertEqual(set(rankings), set(METHODS))
        self.assertEqual(report['methods']['NCF']['signal_users'], 150)
        histories = {}
        for e in split.train:
            histories.setdefault(e.user_id, set()).add(e.song_id)
        for values in rankings.values():
            for uid, ids in values.items():
                self.assertEqual(len(ids), 20)
                self.assertEqual(len(set(ids)), 20)
                self.assertFalse(set(ids) & histories.get(uid, set()))
                self.assertTrue(set(ids) <= set(range(1, 473)))
        for uid in rankings['ADAPTIVE_4']:
            self.assertEqual(set(rankings['ADAPTIVE_4'][uid]), set(rankings['ADAPTIVE_4_RERANK'][uid]))
            self.assertEqual(rankings['ADAPTIVE_4'][uid][0], rankings['ADAPTIVE_4_RERANK'][uid][0])

    def test_invalid_input_and_preserve_output(self):
        # UT-SIM472-003
        with self.assertRaisesRegex(EvaluationError, 'INVALID_CATALOG'):
            generate({}, 42)
        for seed in (True, -1, 4294967296):
            with self.assertRaises(EvaluationError):
                generate(catalog(), seed)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'keep.txt'
            marker.write_text('unchanged')
            with self.assertRaisesRegex(EvaluationError, 'OUTPUT_EXISTS'):
                run(root / 'missing.json', root)
            self.assertEqual(marker.read_text(), 'unchanged')
            invalid = root / 'invalid.json'
            invalid.write_text(json.dumps({}))
            with self.assertRaisesRegex(EvaluationError, 'INVALID_CATALOG'):
                run(invalid, root / 'absent')
            self.assertFalse((root / 'absent').exists())
