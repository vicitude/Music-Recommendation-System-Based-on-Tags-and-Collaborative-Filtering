"""Frozen-catalog synthetic experiment. No Django/database access."""
import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from music.ncf import fit_ncf, predict_ncf, save_ncf, load_ncf
from music.diversity import rerank_diverse, discovery_metrics
from music.recommendation import (build_tfidf_vectors, compute_profile, dot,
    positive_matrix, compute_cf, compute_item_cf, fuse_candidates)
from music.evaluation import (EvaluationError, EvaluationDataset, TimeSplit,
    _signals, _features, load_dataset, time_split, user_groups, ranking_metrics, catalog_metrics)

METHODS = ('HOT', 'CONTENT', 'USER_CF', 'ITEM_CF', 'NCF', 'FIXED_4',
           'ADAPTIVE_4', 'ADAPTIVE_4_RERANK', 'ADAPTIVE_NO_NCF')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def validate_catalog(catalog):
    def ident(value):
        return type(value) is int and value > 0
    try:
        assert catalog['catalog_version'] == 'catalog-472-v1'
        assert isinstance(catalog['scope'], str) and catalog['scope'].strip()
        songs, tags = catalog['songs'], catalog['tags']
        assert isinstance(songs, list) and len(songs) == 472
        assert isinstance(tags, list) and tags
        tag_ids = set()
        for tag in tags:
            assert ident(tag['id']) and tag['id'] not in tag_ids
            assert tag['kind'] in ('STYLE', 'MOOD', 'SCENE')
            assert isinstance(tag['name'], str) and tag['name'] == tag['name'].strip() and 1 <= len(tag['name']) <= 30
            tag_ids.add(tag['id'])
        song_ids = set()
        for song in songs:
            assert ident(song['song_id']) and song['song_id'] not in song_ids
            song_ids.add(song['song_id'])
            refs = song['tag_ids']
            assert isinstance(refs, list) and refs and all(ident(t) for t in refs)
            assert len(set(refs)) == len(refs) and set(refs) <= tag_ids
    except (AssertionError, KeyError, TypeError):
        raise EvaluationError('INVALID_CATALOG') from None


def generate(catalog: dict, seed: int) -> dict:
    validate_catalog(catalog)
    if type(seed) is not int or not 0 <= seed <= 4294967295:
        raise EvaluationError('Invalid seed')
    rng = random.Random(seed)
    songs = [{'song_id': s['song_id'], 'tag_ids': sorted(s['tag_ids'])}
             for s in sorted(catalog['songs'], key=lambda s: s['song_id'])]
    classes = {s['song_id']: rng.randrange(12) for s in songs}
    eligible = sorted(t['id'] for t in catalog['tags'] if t['kind'] in ('STYLE', 'MOOD'))
    if not eligible:
        eligible = sorted(t['id'] for t in catalog['tags'])
    users, windows = [], [[], [], []]
    for uid in range(1, 201):
        preferred = rng.randrange(12)
        interests = set(rng.sample(eligible, min(2, len(eligible))))
        users.append({'user_id': uid, 'interest_tag_ids': [] if uid <= 25 else sorted(interests)})
        quota = 0 if uid <= 50 else 5 if uid <= 100 else 17 if uid <= 150 else 34
        available = list(songs)
        draw = 0
        for window, count in zip(windows, (quota, 2, 4)):
            for _ in range(count):
                draw += 1
                weights = [1 if draw % 5 == 0 else 1 + 4 * (classes[s['song_id']] == preferred)
                           + len(interests.intersection(s['tag_ids'])) for s in available]
                index = rng.choices(range(len(available)), weights=weights, k=1)[0]
                sid = available.pop(index)['song_id']
                window.append({'user_id': uid, 'song_id': sid, 'positive': True})
    events = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for window in windows:
        rng.shuffle(window)
        for event in window:
            events.append(dict(event, occurred_at=(start + timedelta(minutes=len(events))).isoformat()))
    return {'songs': songs, 'users': users, 'interactions': events}


def _compare(dataset, split):
    songs, active_tags = _features(dataset)
    users = _signals(dataset=dataset, train=split.train)
    cutoff = split.train_end + timedelta(microseconds=1)
    matrix = positive_matrix(users=users, cutoff=cutoff, origin=dataset.manifest['origin'])
    all_ids = tuple(s.song_id for s in songs)
    model = fit_ncf(matrix=matrix, item_ids=all_ids, factors=8, epochs=30, seed=42, learning_rate=0.01)
    vectors, idf = build_tfidf_vectors(songs=songs, active_tags=active_tags)
    song_tags = {s.song_id: s.tag_ids for s in songs}
    popularity = {sid: sum(row.get(sid, 0) > 0 for row in matrix.values()) for sid in all_ids}
    rankings = {name: {} for name in METHODS}
    signal_users = dict.fromkeys(METHODS, 0)
    route_summary = {}
    histories = {u.user_id: set(matrix.get(u.user_id, {})) for u in users}
    for user in users:
        uid = user.user_id
        positives = matrix.get(uid, {})
        candidates = tuple(sid for sid in all_ids if sid not in positives)
        profile = compute_profile(interest_ids=user.interest_ids, positive_scores=positives, song_vectors=vectors, tag_idf=idf)
        content, evidence = {}, {}
        for sid in candidates:
            content[sid] = min(1.0, max(0.0, dot(profile, vectors[sid])))
            contributions = sorted(((tag, profile.get(tag, 0) * v) for tag, v in vectors[sid].items() if profile.get(tag, 0) > 0), key=lambda p: (-p[1], p[0]))
            evidence[sid] = tuple(tag for tag, _ in contributions[:2])
        cf, counts = compute_cf(user_id=uid, matrix=matrix, candidate_ids=candidates)
        item, item_counts = compute_item_cf(user_id=uid, matrix=matrix, candidate_ids=candidates)
        ncf = predict_ncf(model, user_id=uid, candidate_ids=candidates)
        routes = (content, cf, item, ncf)
        def ranked(scores):
            return sorted(candidates, key=lambda sid: (-scores.get(sid, 0), -popularity[sid] if not scores.get(sid, 0) else 0, sid))[:20]
        for name, scores in zip(METHODS[:5], (popularity,) + routes):
            rankings[name][uid] = ranked(scores)
            signal_users[name] += any(scores.get(sid, 0) > 0 for sid in candidates)
        available = [(scores, max(scores.values(), default=0)) for scores in routes if max(scores.values(), default=0) > 0]
        fixed = {sid: sum(scores.get(sid, 0) / maximum for scores, maximum in available) / max(1, len(available)) for sid in candidates}
        rankings['FIXED_4'][uid] = ranked(fixed)
        signal_users['FIXED_4'] += bool(available)
        for name, neural in (('ADAPTIVE_4', ncf), ('ADAPTIVE_NO_NCF', {})):
            result = fuse_candidates(candidate_ids=candidates, content_scores=content, user_cf_scores=cf,
                item_cf_scores=item, ncf_scores=neural, evidence_tags=evidence, user_neighbor_counts=counts,
                item_neighbor_counts=item_counts, popularity=popularity, active_tags=active_tags,
                positive_song_count=len(positives), limit=20)
            rankings[name][uid] = [x['song_id'] for x in result.items]
            signal_users[name] += any(result.route_weights.values())
            if name == 'ADAPTIVE_4':
                route_summary[uid] = result.route_weights
                history_tags = {tag for sid in positives for tag in song_tags.get(sid, ())}
                reordered = rerank_diverse(items=result.items, song_tags=song_tags, popularity=popularity,
                    user_history_tags=history_tags, limit=20)
                rankings['ADAPTIVE_4_RERANK'][uid] = [x['song_id'] for x in reordered]
                signal_users['ADAPTIVE_4_RERANK'] += any(result.route_weights.values())
    targets = {}
    for event in split.test:
        if event.positive and event.song_id not in histories[event.user_id]:
            targets.setdefault(event.user_id, set()).add(event.song_id)
    groups = user_groups(dataset=dataset, train=split.train)
    def metrics(values, selected):
        recs = {uid: values[uid] for uid in sorted(selected) if targets.get(uid)}
        truth = {uid: targets[uid] for uid in recs}
        result = ranking_metrics(recommendations=recs, targets=truth, candidate_ids=set(all_ids), k=10)
        result.update(catalog_metrics(recommendations=recs, dataset=dataset, train=split.train, k=10))
        result.update(discovery_metrics(recommendations=recs, targets=truth, histories=histories, song_tags=song_tags, k=10))
        return result
    report = {'groups': {g: len(ids) for g, ids in groups.items()}, 'methods': {
        name: {'overall': metrics(values, set(histories)), 'groups': {g: metrics(values, ids) for g, ids in groups.items()},
               'signal_users': int(signal_users[name])} for name, values in rankings.items()},
        'route_weights_by_user': route_summary}
    return report, rankings, model


def compare(dataset: EvaluationDataset, split: TimeSplit) -> tuple[dict, dict]:
    report, rankings, _ = _compare(dataset, split)
    return report, rankings


def run(catalog_path, output, seed=42):
    output = Path(output)
    if output.exists():
        raise EvaluationError('OUTPUT_EXISTS')
    raw = Path(catalog_path).read_bytes()
    try:
        catalog = json.loads(raw)
        validate_catalog(catalog)
    except (ValueError, TypeError) as exc:
        raise EvaluationError('INVALID_CATALOG') from exc
    data = generate(catalog, seed)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'manifest_version': 'v1', 'source': 'SIM472_V1', 'origin': 'SIMULATED', 'timezone': 'UTC',
        'timestamps_are_real': True, 'timestamp_origin': 'SYNTHETIC', 'data_file': 'data.json',
        'license_evidence': '本机离线元数据与合成行为；不授权音频再分发',
        'catalog_sha256': hashlib.sha256(raw).hexdigest(), 'data_sha256': digest(data), 'seed': seed}
    (output / 'data.json').write_bytes(encoded(data))
    (output / 'manifest.json').write_bytes(encoded(manifest))
    dataset = load_dataset(output / 'manifest.json')
    split = time_split(dataset)
    if tuple(map(len, (split.train, split.validation, split.test))) != (2800, 400, 800):
        raise EvaluationError('Unexpected time split')
    report, rankings, model = _compare(dataset, split)
    save_ncf(model, output / 'ncf-model.json')
    restored = load_ncf(output / 'ncf-model.json')
    probe = dict(user_id=51, candidate_ids=tuple(s['song_id'] for s in data['songs']))
    if predict_ncf(restored, **probe) != predict_ncf(model, **probe):
        raise EvaluationError('Model roundtrip failed')
    report.update(origin='SIMULATED', catalog_sha256=manifest['catalog_sha256'], data_sha256=manifest['data_sha256'],
        ranking_sha256=digest(rankings), seed=seed,
        configuration={'k': 10, 'shortlist': 20, 'scene_enabled': False, 'tuned': False,
            'ncf_factors': 8, 'ncf_epochs': 30, 'ncf_seed': 42, 'ncf_learning_rate': 0.01},
        split={'train': len(split.train), 'validation': len(split.validation), 'test': len(split.test),
            'train_end': split.train_end.isoformat(), 'validation_end': split.validation_end.isoformat()},
        ncf_training={'initial_loss': model.losses[0], 'final_loss': model.losses[-1], 'losses': list(model.losses)})
    (output / 'rankings.json').write_bytes(encoded(rankings))
    (output / 'report.json').write_bytes(encoded(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    try:
        run(args.catalog, args.output, args.seed)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(args.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
