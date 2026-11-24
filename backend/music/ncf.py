"""CPU neural collaborative filtering: embedding concatenation and a two-layer MLP."""
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class NCFModel:
    user_ids: tuple[int, ...]
    item_ids: tuple[int, ...]
    positive_user_ids: tuple[int, ...]
    factors: int
    epochs: int
    seed: int
    learning_rate: float
    fingerprint: str
    losses: tuple[float, ...]
    parameters: dict[str, np.ndarray]


def validate_inputs(matrix, item_ids, factors, epochs, seed, learning_rate) -> tuple:
    def integer(value, low, high):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError('Invalid integer parameter')
    integer(factors, 2, 32)
    integer(epochs, 1, 200)
    integer(seed, 0, 2147483647)
    if isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float)) or not math.isfinite(learning_rate) or not 0 < learning_rate <= 1:
        raise ValueError('Invalid learning rate')
    if not isinstance(matrix, dict) or not isinstance(item_ids, tuple):
        raise ValueError('Invalid matrix or item IDs')
    for sid in item_ids:
        integer(sid, 1, 2**63 - 1)
    if len(set(item_ids)) != len(item_ids):
        raise ValueError('Duplicate item IDs')
    items = set(item_ids)
    for uid, row in matrix.items():
        integer(uid, 1, 2**63 - 1)
        if not isinstance(row, dict):
            raise ValueError('Invalid matrix row')
        for sid, value in row.items():
            integer(sid, 1, 2**63 - 1)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Matrix scores must be finite and nonnegative')
            if value > 0:
                items.add(sid)
    rows = tuple((uid, tuple(sorted(row.items()))) for uid, row in sorted(matrix.items()))
    return rows, tuple(sorted(items))


def forward(parameters, user_indices, item_indices) -> tuple:
    p = parameters
    x = np.concatenate((p['eu'][user_indices], p['ei'][item_indices]), axis=1)
    h1 = np.tanh(x @ p['w1'] + p['b1'])
    h2 = np.tanh(h1 @ p['w2'] + p['b2'])
    logits = (h2 @ p['wo'] + p['bo']).reshape(-1)
    probability = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
    return x, h1, h2, logits, probability


def loss_gradients(parameters, user_indices, item_indices, labels) -> tuple:
    p = parameters
    gradients = {key: np.zeros_like(value) for key, value in p.items()}
    if not len(labels):
        return 0.0, gradients
    x, h1, h2, logits, probability = forward(p, user_indices, item_indices)
    loss = float(np.mean(np.logaddexp(0, logits) - labels * logits))
    d = ((probability - labels) / len(labels))[:, None]
    gradients['wo'] = h2.T @ d
    gradients['bo'] = d.sum(axis=0)
    d2 = (d @ p['wo'].T) * (1 - h2**2)
    gradients['w2'] = h1.T @ d2
    gradients['b2'] = d2.sum(axis=0)
    d1 = (d2 @ p['w2'].T) * (1 - h1**2)
    gradients['w1'] = x.T @ d1
    gradients['b1'] = d1.sum(axis=0)
    dx = d1 @ p['w1'].T
    factors = p['eu'].shape[1]
    np.add.at(gradients['eu'], user_indices, dx[:, :factors])
    np.add.at(gradients['ei'], item_indices, dx[:, factors:])
    return loss, gradients


def fit_ncf(*, matrix: dict[int, dict[int, float]], item_ids: tuple[int, ...], factors: int = 8, epochs: int = 30, seed: int = 42, learning_rate: float = 0.01) -> NCFModel:
    rows, items = validate_inputs(matrix, item_ids, factors, epochs, seed, learning_rate)
    users = tuple(uid for uid, _ in rows)
    positive_users = tuple(uid for uid, row in rows if any(value > 0 for _, value in row))
    rng = np.random.default_rng(seed)
    p = {'eu': rng.normal(0, .1, (len(users), factors)),
         'ei': rng.normal(0, .1, (len(items), factors))}
    for key, shape in (('w1', (2*factors, 16)), ('w2', (16, 8)), ('wo', (8, 1))):
        p[key] = rng.normal(0, math.sqrt(2 / sum(shape)), shape)
    p.update(b1=np.zeros(16), b2=np.zeros(8), bo=np.zeros(1))
    item_index = {sid: i for i, sid in enumerate(items)}
    pairs = []
    for ui, (_, row) in enumerate(rows):
        positives = {sid for sid, value in row if value > 0}
        if not positives:
            continue
        pairs.extend((ui, item_index[sid], 1.) for sid in sorted(positives))
        negatives = [sid for sid in items if sid not in positives]
        selected = rng.choice(len(negatives), min(4*len(positives), len(negatives)), replace=False)
        pairs.extend((ui, item_index[negatives[int(i)]], 0.) for i in selected)
    ui = np.array([v[0] for v in pairs], dtype=np.int64)
    ii = np.array([v[1] for v in pairs], dtype=np.int64)
    labels = np.array([v[2] for v in pairs], dtype=np.float64)
    losses = [loss_gradients(p, ui, ii, labels)[0]]
    first = {k: np.zeros_like(v) for k, v in p.items()}
    second = {k: np.zeros_like(v) for k, v in p.items()}
    for step in range(1, epochs + 1):
        _, gradients = loss_gradients(p, ui, ii, labels)
        for key, gradient in gradients.items():
            first[key] = .9*first[key] + .1*gradient
            second[key] = .999*second[key] + .001*gradient**2
            p[key] -= learning_rate * (first[key]/(1-.9**step)) / (np.sqrt(second[key]/(1-.999**step)) + 1e-8)
        losses.append(loss_gradients(p, ui, ii, labels)[0])
    encoded = json.dumps([rows, items, factors, epochs, seed, learning_rate], separators=(',', ':'), allow_nan=False).encode()
    for value in p.values():
        value.setflags(write=False)
    return NCFModel(users, items, positive_users, factors, epochs, seed, float(learning_rate), hashlib.sha256(encoded).hexdigest(), tuple(losses), p)


def predict_ncf(model: NCFModel, *, user_id: int, candidate_ids: tuple[int, ...]) -> dict[int, float]:
    validate_inputs({}, candidate_ids, model.factors, model.epochs, model.seed, model.learning_rate)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError('Invalid user ID')
    if user_id not in model.positive_user_ids:
        return {}
    index = {sid: i for i, sid in enumerate(model.item_ids)}
    candidates = tuple(sorted(sid for sid in candidate_ids if sid in index))
    if not candidates:
        return {}
    ui = np.full(len(candidates), model.user_ids.index(user_id), dtype=np.int64)
    ii = np.array([index[sid] for sid in candidates], dtype=np.int64)
    probabilities = forward(model.parameters, ui, ii)[-1]
    return {sid: float(value) for sid, value in zip(candidates, probabilities)}


def save_ncf(model: NCFModel, path: Path) -> None:
    data = dict(vars(model))
    data['format'] = 'music-ncf-mlp-v1'
    data['parameters'] = {k: v.tolist() for k, v in model.parameters.items()}
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def load_ncf(path: Path) -> NCFModel:
    path = Path(path)
    if path.stat().st_size > 16*1024*1024:
        raise ValueError('Model exceeds size limit')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) != set(NCFModel.__dataclass_fields__) | {'format'} or data.pop('format') != 'music-ncf-mlp-v1':
            raise ValueError('Invalid model format')
        for key in ('user_ids', 'item_ids', 'positive_user_ids'):
            values = data[key]
            if not isinstance(values, list) or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in values) or values != sorted(set(values)):
                raise ValueError('Invalid model IDs')
            data[key] = tuple(values)
        validate_inputs({uid: {} for uid in data['user_ids']}, data['item_ids'], data['factors'], data['epochs'], data['seed'], data['learning_rate'])
        if not set(data['positive_user_ids']) <= set(data['user_ids']) or not re.fullmatch('[0-9a-f]{64}', data['fingerprint']):
            raise ValueError('Invalid model metadata')
        losses = data['losses']
        if not isinstance(losses, list) or len(losses) != data['epochs']+1 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in losses):
            raise ValueError('Invalid model losses')
        data['losses'] = tuple(losses)
        f = data['factors']
        shapes = {'eu': (len(data['user_ids']), f), 'ei': (len(data['item_ids']), f), 'w1': (2*f, 16), 'b1': (16,), 'w2': (16, 8), 'b2': (8,), 'wo': (8, 1), 'bo': (1,)}
        if not isinstance(data['parameters'], dict) or set(data['parameters']) != set(shapes):
            raise ValueError('Invalid model parameters')
        parameters = {}
        for key, shape in shapes.items():
            raw = np.asarray(data['parameters'][key])
            if raw.dtype.kind not in 'fi' or (raw.shape != shape and not (0 in shape and raw.shape == (0,))):
                raise ValueError('Invalid parameter shape or type')
            value = np.asarray(raw, dtype=np.float64).reshape(shape)
            if not np.all(np.isfinite(value)):
                raise ValueError('Nonfinite model parameters')
            value.setflags(write=False)
            parameters[key] = value
        data['parameters'] = parameters
        return NCFModel(**data)
    except (TypeError, KeyError, OverflowError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid model artifact') from exc
