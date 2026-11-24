"""Deterministic, bounded list reranking and offline discovery proxies."""
import math
from copy import deepcopy


def _check_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('Invalid song or tag ID')


def _validate_metadata(song_tags, popularity, user_history_tags):
    if not isinstance(song_tags, dict) or not isinstance(popularity, dict) or not isinstance(user_history_tags, set):
        raise ValueError('Invalid reranking metadata')
    for sid, tags in song_tags.items():
        _check_id(sid)
        if not isinstance(tags, tuple):
            raise ValueError('Invalid tag tuple')
        for tag in tags:
            _check_id(tag)
    for sid, count in popularity.items():
        _check_id(sid)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError('Invalid popularity')
    for tag in user_history_tags:
        _check_id(tag)


def tag_distance(left_tags: tuple[int, ...], right_tags: tuple[int, ...]) -> float:
    if not isinstance(left_tags, tuple) or not isinstance(right_tags, tuple):
        raise ValueError('Invalid tag tuple')
    for tag in (*left_tags, *right_tags):
        _check_id(tag)
    left, right = set(left_tags), set(right_tags)
    union = left | right
    return 0.0 if not union else 1.0 - len(left & right) / len(union)


def serendipity_score(*, song_id: int, user_history_tags: set[int], song_tags: dict[int, tuple[int, ...]], popularity: dict[int, int]) -> float:
    """Exploration heuristic, not a measured user-surprise outcome."""
    _check_id(song_id)
    _validate_metadata(song_tags, popularity, user_history_tags)
    return _exploration(song_id, user_history_tags, song_tags, popularity, max(popularity.values(), default=0))


def _exploration(song_id, history_tags, song_tags, popularity, maximum):
    tags = set(song_tags.get(song_id, ()))
    union = history_tags | tags
    affinity = len(history_tags & tags) / len(union) if union else 0.0
    novelty = 1 - popularity.get(song_id, 0) / maximum if maximum else 1.0
    return novelty * affinity


def rerank_diverse(*, items: list[dict], song_tags: dict[int, tuple[int, ...]], popularity: dict[int, int], user_history_tags: set[int], limit: int, diversity_weight: float = 0.25, serendipity_weight: float = 0.10) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 20:
        raise ValueError('Invalid limit')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (diversity_weight, serendipity_weight)) or diversity_weight + serendipity_weight > 1:
        raise ValueError('Invalid diversity weights')
    _validate_metadata(song_tags, popularity, user_history_tags)
    if not isinstance(items, list) or len(items) > 20:
        raise ValueError('Invalid candidate list')
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Invalid item')
        sid = item.get('song_id')
        _check_id(sid)
        if sid in ids:
            raise ValueError('Duplicate song IDs')
        ids.add(sid)
        score = item.get('score')
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid recommendation score')
    if diversity_weight == serendipity_weight == 0:
        selected = deepcopy(items[:limit])
    else:
        # Do not let exploratory HOT songs outrank personalized evidence.
        personalized = [item for item in items if item.get('source') != 'HOT']
        hot = [item for item in items if item.get('source') == 'HOT']
        remaining = deepcopy(personalized)
        selected = remaining[:1] if limit else []
        remaining = remaining[1:]
        maximum = max(popularity.values(), default=0)
        exploration = {sid: _exploration(sid, user_history_tags, song_tags, popularity, maximum) for sid in ids}
        distances = {(left, right): tag_distance(song_tags.get(left, ()), song_tags.get(right, ())) for left in ids for right in ids}
        while remaining and len(selected) < limit:
            def key(item):
                sid = item['song_id']
                distance = sum(distances[sid, old['song_id']] for old in selected) / len(selected)
                utility = (1-diversity_weight-serendipity_weight)*item['score'] + diversity_weight*distance + serendipity_weight*exploration[sid]
                return utility, item['score'], -sid
            best = max(remaining, key=key)
            selected.append(best)
            remaining.remove(best)
        selected.extend(deepcopy(hot[:max(0, limit-len(selected))]))
    for rank, item in enumerate(selected, 1):
        item['rank'] = rank
    return selected


def discovery_metrics(*, recommendations: dict[int, list[int]], targets: dict[int, set[int]], histories: dict[int, set[int]], song_tags: dict[int, tuple[int, ...]], k: int = 10) -> dict[str, float | None]:
    """History-distance unexpectedness and held-out-hit-weighted serendipity."""
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError('Invalid k')
    _validate_metadata(song_tags, {}, set())
    for mapping in (recommendations, targets, histories):
        if not isinstance(mapping, dict):
            raise ValueError('Invalid metric mapping')
        for uid, songs in mapping.items():
            _check_id(uid)
            if not isinstance(songs, (list, set, tuple)):
                raise ValueError('Invalid metric song IDs')
            for sid in songs:
                _check_id(sid)
    unexpectedness, serendipity = [], []
    for uid, ranked in sorted(recommendations.items()):
        history = histories.get(uid, set())
        ranked = list(dict.fromkeys(ranked))[:k]
        if not history or not ranked:
            continue
        distances = []
        for sid in ranked:
            tags = song_tags.get(sid, ())
            # Missing features cannot establish unexpectedness.
            distance = min((tag_distance(tags, song_tags.get(old, ())) if tags and song_tags.get(old) else 0.0) for old in sorted(history))
            distances.append(distance)
        unexpectedness.append(sum(distances) / len(ranked))
        serendipity.append(sum(distance for sid, distance in zip(ranked, distances) if sid in targets.get(uid, set())) / k)
    return {'unexpectedness': sum(unexpectedness)/len(unexpectedness) if unexpectedness else None,
            'serendipity': sum(serendipity)/len(serendipity) if serendipity else None}
