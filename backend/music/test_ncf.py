import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from music.ncf import fit_ncf, forward, load_ncf, loss_gradients, predict_ncf, save_ncf
from music.recommendation import _cached_model, compute_ncf


class NCFTests(unittest.TestCase):
    def setUp(self):
        self.matrix = {1: {1: 1, 2: 1}, 2: {1: 1, 2: 1}, 3: {3: 1, 4: 1}, 4: {3: 1, 4: 1}, 5: {}}
        self.items = (1, 2, 3, 4, 5, 6)

    def test_tc_ncf_001_learning(self):
        initial = fit_ncf(matrix=self.matrix, item_ids=self.items, epochs=1, learning_rate=1e-15)
        model = fit_ncf(matrix=self.matrix, item_ids=self.items, epochs=100)
        self.assertLess(model.losses[-1], model.losses[0] * .5)
        for key in model.parameters:
            self.assertFalse(np.array_equal(initial.parameters[key], model.parameters[key]), key)
            self.assertFalse(model.parameters[key].flags.writeable)
        scores = predict_ncf(model, user_id=1, candidate_ids=self.items)
        self.assertGreater(min(scores[1], scores[2]), max(scores[3], scores[4], scores[5], scores[6]))
        self.assertEqual(model.parameters['w1'].shape, (16, 16))
        self.assertEqual(model.parameters['w2'].shape, (16, 8))

    def test_tc_ncf_002_cold_start(self):
        model = fit_ncf(matrix=self.matrix, item_ids=self.items)
        for uid in (5, 99):
            self.assertEqual(predict_ncf(model, user_id=uid, candidate_ids=self.items), {})
        empty = fit_ncf(matrix={}, item_ids=())
        self.assertEqual(empty.losses, (0.,) * 31)
        self.assertEqual(predict_ncf(empty, user_id=1, candidate_ids=(1,)), {})

    def test_tc_ncf_003_roundtrip(self):
        for matrix, items in ((self.matrix, self.items), ({}, ())):
            model = fit_ncf(matrix=matrix, item_ids=items)
            with tempfile.TemporaryDirectory(prefix='temp_ncf_') as directory:
                path = Path(directory) / 'model.json'
                save_ncf(model, path)
                loaded = load_ncf(path)
                self.assertEqual(model.fingerprint, loaded.fingerprint)
                self.assertEqual(predict_ncf(model, user_id=1, candidate_ids=self.items), predict_ncf(loaded, user_id=1, candidate_ids=self.items))
                with self.assertRaises(FileExistsError):
                    save_ncf(model, path)

    def test_tc_ncf_004_bad_artifact(self):
        model = fit_ncf(matrix=self.matrix, item_ids=self.items)
        with tempfile.TemporaryDirectory(prefix='temp_ncf_') as directory:
            good = Path(directory) / 'good.json'
            save_ncf(model, good)
            original = json.loads(good.read_text(encoding='utf-8'))
            mutations = [lambda d: d.update(format='pickle'), lambda d: d.update(extra=1),
                         lambda d: d.update(fingerprint=None), lambda d: d.update(losses=[0]),
                         lambda d: d['parameters'].update(w1=[[0]]),
                         lambda d: d['parameters']['bo'].__setitem__(0, float('nan')),
                         lambda d: d.update(user_ids=[True]), lambda d: d.update(positive_user_ids=[999])]
            for index, mutate in enumerate(mutations):
                data = copy.deepcopy(original)
                mutate(data)
                bad = Path(directory) / f'bad{index}.json'
                bad.write_text(json.dumps(data), encoding='utf-8')
                with self.subTest(index=index), self.assertRaises(ValueError):
                    load_ncf(bad)
            huge = Path(directory) / 'huge.json'
            with huge.open('wb') as stream:
                stream.truncate(16*1024*1024+1)
            with self.assertRaises(ValueError):
                load_ncf(huge)

    def test_tc_ncf_005_validation(self):
        for args in ({'matrix': {True: {1: 1}}}, {'matrix': {1: {1: True}}}, {'matrix': {1: {1: float('inf')}}},
                     {'matrix': {1: {1: -1}}}, {'matrix': {1: []}}, {'item_ids': (1, 1)}, {'item_ids': (False,)},
                     {'factors': 1}, {'epochs': 0}, {'seed': True}, {'learning_rate': float('nan')}):
            kw = {'matrix': self.matrix, 'item_ids': self.items}
            kw.update(args)
            with self.subTest(args=args), self.assertRaises(ValueError):
                fit_ncf(**kw)

    def test_tc_ncf_006_gradients(self):
        model = fit_ncf(matrix=self.matrix, item_ids=self.items, epochs=1)
        p = {k: v.copy() for k, v in model.parameters.items()}
        ui, ii, labels = np.array([0, 0, 1, 2]), np.array([0, 2, 1, 3]), np.array([1., 0., 1., 1.])
        _, gradients = loss_gradients(p, ui, ii, labels)
        epsilon = 1e-5
        for key, value in p.items():
            for index in np.ndindex(value.shape):
                old = value[index]
                value[index] = old + epsilon
                plus = loss_gradients(p, ui, ii, labels)[0]
                value[index] = old - epsilon
                minus = loss_gradients(p, ui, ii, labels)[0]
                value[index] = old
                self.assertAlmostEqual(gradients[key][index], (plus-minus)/(2*epsilon), delta=1e-6, msg=f'{key}{index}')

    def test_tc_ncf_007_cache(self):
        _cached_model.cache_clear()
        with patch('music.recommendation.fit_ncf', wraps=fit_ncf) as training:
            compute_ncf(user_id=1, matrix=self.matrix, candidate_ids=self.items)
            compute_ncf(user_id=2, matrix=self.matrix, candidate_ids=self.items)
            self.assertEqual(training.call_count, 1)
            changed = copy.deepcopy(self.matrix)
            changed[1][3] = 1
            compute_ncf(user_id=1, matrix=changed, candidate_ids=self.items)
            compute_ncf(user_id=1, matrix=changed, candidate_ids=self.items+(7,))
            self.assertEqual(training.call_count, 3)
        self.assertEqual(_cached_model.cache_info().maxsize, 8)

    def test_pt_ncf_001_candidates(self):
        for seed in range(5):
            model = fit_ncf(matrix=self.matrix, item_ids=self.items, seed=seed)
            full = predict_ncf(model, user_id=1, candidate_ids=self.items)
            for subset in ((3,), (4, 3), (999,), (1, 999), ()):
                scores = predict_ncf(model, user_id=1, candidate_ids=subset)
                self.assertLessEqual(set(scores), set(subset))
                for sid, score in scores.items():
                    self.assertAlmostEqual(score, full[sid])
                    self.assertTrue(0 < score < 1)
        # Previously the equal-score/single-candidate branch leaked history IDs.
        self.assertEqual(set(compute_ncf(user_id=1, matrix={1: {1: 1}}, candidate_ids=(2,))), {2})

    def test_pt_ncf_002_determinism(self):
        original = copy.deepcopy(self.matrix)
        a = fit_ncf(matrix=self.matrix, item_ids=self.items)
        reordered = {uid: dict(reversed(list(row.items()))) for uid, row in reversed(list(self.matrix.items()))}
        b = fit_ncf(matrix=reordered, item_ids=tuple(reversed(self.items)))
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(a.losses, b.losses)
        for key in a.parameters:
            np.testing.assert_array_equal(a.parameters[key], b.parameters[key])
        self.assertEqual(self.matrix, original)
