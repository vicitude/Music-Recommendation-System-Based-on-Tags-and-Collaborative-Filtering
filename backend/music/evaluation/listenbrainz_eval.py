"""Compare existing rankers on private ListenBrainz files without Django or MySQL."""
import argparse
from collections import Counter
from datetime import datetime
import itertools
import json
import math
from pathlib import Path
import sys

from music.diversity import rerank_diverse
from music.evaluation import ranking_metrics
from music.evaluation.listenbrainz_import import (SCHEMA, MAX_DATA_BYTES, MAX_EVENTS, MAX_ITEMS, MAX_USERS,
                                                   check_event_budget, digest, epoch, mbid, write_json)
from music.ncf import fit_ncf, predict_ncf
from music.recommendation import (SongFeatures, build_tfidf_vectors, compute_cf,
                                  compute_item_cf, compute_profile, dot, fuse_candidates)


K = 10
MIN_DISCLOSURE_USERS = 5
NCF = {'factors': 8, 'epochs': 30, 'seed': 42, 'learning_rate': .01}
GROUPS = ('cold_start_0', 'light_1_9', 'regular_10_29', 'heavy_30_plus')


def group(count):
    return GROUPS[0 if count == 0 else 1 if count < 10 else 2 if count < 30 else 3]


def id_list(records, field, cap):
    result = tuple(row[field] for row in records)
    if not 0 < len(result) <= cap or any(type(i) is not int or i <= 0 for i in result) or len(set(result)) != len(result):
        raise ValueError('Invalid experiment IDs')
    return tuple(sorted(result))


def load_json(path, max_bytes):
    with Path(path).open('rb') as input_file:
        raw = input_file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('Local experiment artifact exceeds size limit')
    return json.loads(raw)


def load(path):
    path = Path(path)
    manifest = load_json(path, 65536)
    if manifest['schema'] != SCHEMA or manifest['origin'] != 'REAL' or manifest['data_file'] != 'data.json':
        raise ValueError('Unexpected origin, schema or data path')
    local = path.parent / 'data.json'
    max_events = check_event_budget(manifest.get('max_events', MAX_EVENTS))
    max_bytes = min(MAX_DATA_BYTES, max(40_000_000, max_events * 150))
    if local.is_symlink() or local.stat().st_size > max_bytes or digest(local) != manifest['data_sha256']:
        raise ValueError('Data file integrity check failed')
    return manifest, load_json(local, max_bytes)


def tag_features(songs, frozen, train_cut):
    if frozen is None:
        return {}, {}
    if (frozen['schema'] != 'recording-tags-v1' or epoch(frozen['available_at']) >= train_cut
            or not all(isinstance(frozen.get(key), str) and frozen[key].strip()
                       for key in ('source', 'license', 'source_url'))):
        raise ValueError('Tags require an independently sourced pre-cutoff snapshot with license evidence')
    tags = frozen['tags']
    relevant = {row['recording_mbid']: row['song_id'] for row in songs}
    if not isinstance(tags, dict) or set(tags) - relevant.keys():
        raise ValueError('Tag file must contain only experiment recording MBIDs')
    all_names = set()
    for names in tags.values():
        if not isinstance(names, list) or len(names) > 32 or any(not isinstance(n, str) or not 1 <= len(n) <= 30 or n.strip() != n for n in names):
            raise ValueError('Invalid recording tags')
        all_names.update(names)
    ids = {name: i for i, name in enumerate(sorted(all_names), 1)}
    return {relevant[key]: tuple(sorted({ids[n] for n in names})) for key, names in tags.items()}, {v: k for k, v in ids.items()}


def prepare(data, train_cut, validation_cut, *, identity='mbid', max_events=MAX_EVENTS):
    check_event_budget(max_events)
    if identity not in {'mbid', 'msid'}:
        raise ValueError('Unknown recording identity mode')
    id_field = 'recording_' + identity
    users = id_list(data['users'], 'user_id', MAX_USERS)
    items = id_list(data['songs'], 'song_id', MAX_ITEMS)
    recording_ids = [row[id_field] for row in data['songs']]
    if any(mbid(r) != r for r in recording_ids) or len(set(recording_ids)) != len(items):
        raise ValueError('Invalid or duplicate recording MBID')
    if any(set(row) != {'user_id'} for row in data['users']) or any(set(row) != {'song_id', id_field, 'tag_ids'} or row['tag_ids'] != [] for row in data['songs']):
        raise ValueError('Unreviewed identity or tag features present in listen data')
    item_set = set(items)
    if train_cut >= validation_cut or sum(map(len, data['partitions'].values())) > max_events:
        raise ValueError('Invalid cutoff or data budget')
    matrix = {uid: {} for uid in users}
    seen = set()
    holdouts = {'validation': {}, 'test': {}}
    for name, lower, upper in (('train', None, train_cut), ('validation', train_cut, validation_cut), ('test', validation_cut, None)):
        for row in data['partitions'][name]:
            u, s, t = row['user_id'], row['song_id'], epoch(row['occurred_at'])
            if (set(row) != {'user_id', 'song_id', 'occurred_at', 'kind', 'positive'} or row['kind'] != 'LISTEN'
                    or row['positive'] is not True or type(u) is not int or type(s) is not int or u not in matrix or s not in item_set
                    or lower is not None and t < lower or upper is not None and t >= upper or (u, s, t) in seen):
                raise ValueError('Invalid listen, duplicate event or temporal boundary violation')
            seen.add((u, s, t))
            if name == 'train':
                matrix[u][s] = 1.0
            elif s not in matrix[u]:
                holdouts[name].setdefault(u, set()).add(s)
    population = Counter(s for row in matrix.values() for s in row)
    if not items or any(population[s] < 3 for s in items):
        raise ValueError('Candidate catalogue does not meet three-listener training floor')
    if not holdouts['test']:
        raise ValueError('No eligible test targets under frozen candidate rule')
    return users, items, matrix, population, holdouts


def summarize(recs, truth, catalogue, tags, popularity, *, public_floor=MIN_DISCLOSURE_USERS):
    if len(truth) < public_floor:
        return {'users': len(truth), 'suppressed': True}
    data = ranking_metrics(recommendations=recs, targets=truth, candidate_ids=set(catalogue), k=K)
    data['no_recommendation'] = sum(not recs[u] for u in truth)
    exposure_total = sum(popularity.values()) + len(catalogue)
    novelty, distances, pairs = [], [], 0
    for u in truth:
        ranked = recs[u][:K]
        if ranked:
            novelty.append(math.fsum(-math.log2((1 + popularity[s]) / exposure_total) for s in ranked) / len(ranked))
        for a, b in itertools.combinations(ranked, 2):
            pairs += 1
            left, right = set(tags.get(a, ())), set(tags.get(b, ()))
            if left and right:
                distances.append(1 - len(left & right) / len(left | right))
    data['novelty_bits'] = math.fsum(novelty) / len(novelty) if novelty else None
    data['diversity_jaccard'] = math.fsum(distances) / len(distances) if distances else None
    data['diversity_pair_coverage'] = len(distances) / pairs if pairs else None
    return data


def evaluate(manifest, data, *, frozen=None):
    train_cut = epoch(manifest['split']['train_cut'])
    validation_cut = epoch(manifest['split']['validation_cut'])
    identity = manifest.get('recording_id_kind', 'mbid')
    if identity == 'msid' and frozen is not None:
        raise ValueError('MSID-only datasets cannot join MusicBrainz tags')
    users, items, matrix, pop, targets = prepare(data, train_cut, validation_cut, identity=identity,
                                               max_events=manifest.get('max_events', MAX_EVENTS))
    # Holdout-only users are excluded from all model fitting, including the RNG's
    # embedding initialization. Empty rows are attached only for scoring.
    model_matrix = {u: row for u, row in matrix.items() if row}
    ncf = fit_ncf(matrix=model_matrix, item_ids=items, **NCF)
    tags, active = tag_features(data['songs'], frozen, train_cut)
    tags = {sid: names for sid, names in tags.items() if names}
    tagged_profile_users = sum(any(sid in tags for sid in row) and any(sid not in row for sid in tags)
                               for row in model_matrix.values())
    content_enabled = 2 * len(tags) >= len(items) and tagged_profile_users >= MIN_DISCLOSURE_USERS
    vectors, idf = build_tfidf_vectors(songs=tuple(SongFeatures(song_id=s, tag_ids=tags.get(s, ())) for s in items), active_tags=active)
    methods = ['HOT', 'USER_CF', 'ITEM_CF', 'NCF']
    if content_enabled:
        methods += ['CONTENT', 'FIXED_4', 'ADAPTIVE_4', 'ADAPTIVE_NO_NCF', 'ADAPTIVE_4_RERANK']
    recs = {name: {} for name in methods}
    diagnostics = Counter()
    truth = targets['test']
    # Frozen model scores can serve either window, but the first protocol uses
    # preset parameters and does not select on validation or test metrics.
    for u in sorted(truth):
        row = matrix[u]
        candidates = tuple(s for s in items if s not in row)
        cf, neighbors = compute_cf(user_id=u, matrix=model_matrix, candidate_ids=candidates)
        item, item_neighbors = compute_item_cf(user_id=u, matrix=model_matrix if row else {**model_matrix, u: {}}, candidate_ids=candidates)
        neural = predict_ncf(ncf, user_id=u, candidate_ids=candidates)
        def ranked(scores):
            return sorted(candidates, key=lambda s: (-scores.get(s, 0), -pop[s], s))[:K]
        for name, scores in (('HOT', pop), ('USER_CF', cf), ('ITEM_CF', item), ('NCF', neural)):
            recs[name][u] = ranked(scores)
            diagnostics[f'{name}_no_positive_signal'] += not any(scores.get(s, 0) > 0 for s in candidates)
        supported = [value for value in cf.values() if value > 0]
        diagnostics['USER_CF_all_supported_scores_tied'] += len(supported) > 1 and max(supported) - min(supported) < 1e-12
        if not content_enabled:
            continue
        profile = compute_profile(interest_ids=(), positive_scores=row, song_vectors=vectors, tag_idf=idf)
        content = {s: max(0.0, dot(profile, vectors[s])) for s in candidates}
        recs['CONTENT'][u] = ranked(content)
        diagnostics['CONTENT_no_positive_signal'] += not any(content.values())
        scores_and_max = [(scores, max(scores.values(), default=0)) for scores in (content, cf, item, neural)]
        fixed = {s: math.fsum(scores.get(s, 0) / maximum for scores, maximum in scores_and_max if maximum) for s in candidates}
        recs['FIXED_4'][u] = ranked(fixed)
        evidence = {s: tuple(sorted((t for t in vectors[s] if t in profile),
                                    key=lambda t: (-vectors[s][t] * profile[t], t))[:2]) for s in candidates}
        for name, n_scores in (('ADAPTIVE_4', neural), ('ADAPTIVE_NO_NCF', {})):
            result = fuse_candidates(candidate_ids=candidates, content_scores=content, user_cf_scores=cf, item_cf_scores=item,
                                     ncf_scores=n_scores, evidence_tags=evidence, user_neighbor_counts=neighbors,
                                     item_neighbor_counts=item_neighbors, popularity=pop, active_tags=active, positive_song_count=len(row), limit=20)
            recs[name][u] = [entry['song_id'] for entry in result.items[:K]]
            if name == 'ADAPTIVE_4':
                reranked = rerank_diverse(items=result.items, song_tags=tags, popularity=pop,
                                         user_history_tags={t for s in row for t in tags.get(s, ())}, limit=20)
                recs['ADAPTIVE_4_RERANK'][u] = [entry['song_id'] for entry in reranked[:K]]
    counts = Counter(group(len(matrix[u])) for u in users)
    subgroups = {g: {u: truth[u] for u in truth if group(len(matrix[u])) == g} for g in GROUPS}
    metrics = {name: {'overall': summarize(values, truth, items, tags, pop),
                      'groups': {g: summarize(values, subgroup, items, tags, pop) for g, subgroup in subgroups.items()}}
               for name, values in recs.items()}
    return {'schema': 'listenbrainz-report-v1', 'origin': 'REAL', 'source': 'ListenBrainz', 'data_sha256': manifest['data_sha256'],
            'archive_sha256': manifest['archive_sha256'], 'split': manifest['split'], 'methods': metrics,
             'recording_id_kind': identity,
            'dataset': {'users': len(users), 'recordings': len(items), 'training_pairs': sum(pop.values()),
                        'training_density': sum(pop.values()) / (len(users) * len(items)),
                        'validation_target_users': len(targets['validation']),
                        'validation_target_pairs': sum(map(len, targets['validation'].values())),
                        'test_target_users': len(truth), 'test_target_pairs': sum(map(len, truth.values())),
                        'no_test_target_users': len(users) - len(truth), 'groups': dict(counts)},
            'settings': {'k': K, 'ncf': NCF, 'timestamps': 'UTC listen time with available insertion time training guard',
                         'tuning': False, 'scene_enabled': False, 'small_group_disclosure_floor': MIN_DISCLOSURE_USERS,
                         'hot_fallback': 'training unique listeners', 'positive_feedback': 'binary implicit listen',
                         'novelty': 'macro mean per-list -log2((unique training listeners + 1)/(training pairs + catalogue size))'},
            'status': {'tag_dependent_methods': 'RUN' if content_enabled else 'NOT_RUN_INSUFFICIENT_INDEPENDENT_TAGS',
                       'tagged_recordings': len(tags), 'usable_tag_profile_users': tagged_profile_users,
                       'item_cold_start': 'NOT_MEASURED_TRAINING_CATALOG_ONLY'},
            'diagnostics_on_target_users': dict(diagnostics), 'ncf_training_bce': {'first': ncf.losses[0], 'last': ncf.losses[-1]}}


def run(manifest_path, output, *, tags_path=None):
    output = Path(output)
    if output.exists():
        raise ValueError('Output directory already exists')
    manifest, data = load(manifest_path)
    frozen = load_json(tags_path, 8_000_000) if tags_path else None
    report = evaluate(manifest, data, frozen=frozen)
    if frozen:
        report['tag_source'] = {k: frozen[k] for k in ('source', 'source_url', 'license', 'available_at')}
        report['tag_source']['file_sha256'] = digest(tags_path)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tags')
    args = parser.parse_args()
    try:
        run(args.manifest, args.output, tags_path=args.tags)
    except (OSError, KeyError, TypeError, ValueError):
        print('Evaluation failed: check manifest/hash, time split, eligible targets, or fresh output path', file=sys.stderr)
        return 2
    print('Evaluation report written (aggregate only)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
