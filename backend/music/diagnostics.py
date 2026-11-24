from music.daily import DAILY_LIMIT, load_inputs
from music.models import RecommendationSnapshot, Song
from music.recommendation import time_context
from music.recommendation import positive_matrix, recommend


def build_diagnostics(*, user_id, now):
    inputs = load_inputs(user_id=user_id, cutoff=now)
    target = next(member for member in inputs["users"] if member.user_id == user_id)
    matrix = positive_matrix(users=inputs["users"], cutoff=now, origin=target.origin)
    result = recommend(**inputs, limit=DAILY_LIMIT)
    songs = {song.pk: song for song in Song.objects.filter(pk__in=[item["song_id"] for item in result.items])}
    rows = []
    source_labels = {"CONTENT": "标签推荐", "CF": "协同推荐", "USER_CF": "用户协同", "ITEM_CF": "歌曲协同", "NCF": "神经协同", "HYBRID": "三路混合", "HOT": "热门补充"}
    for item in result.items:
        song = songs.get(item["song_id"])
        rows.append({**item, "title": song.title if song else "歌曲已不可用", "artist": song.artist if song else "",
                     "source_label": source_labels[item["source"]],
                     "tags": [inputs["active_tags"][tag_id] for tag_id in item["evidence"]["tag_ids"]]})
    alpha = result.alpha_effective
    route = "标签与协同共同参与" if alpha is not None and 0 < alpha < 1 else "仅标签信号有效，退化为标签推荐" if alpha == 1 else "仅协同信号有效，退化为协同推荐" if alpha == 0 else "当前候选无个性化信号，使用热门补充"
    if not result.items:
        route = "没有符合条件的候选歌曲"
    return {"rows": rows, "now": now, "origin": target.origin,
            "interests": [inputs["active_tags"][tag_id] for tag_id in target.interest_ids],
            "positive_count": len(matrix.get(user_id, {})), "peer_count": len(inputs["users"]) - 1,
            "alpha_target": result.alpha_target, "alpha_effective": alpha,
            "content_percent": None if alpha is None else alpha * 100,
            "cf_percent": None if alpha is None else (1 - alpha) * 100,
            "route_weights": result.route_weights,
            "user_cf_percent": result.route_weights.get("user_cf", 0) * 100,
            "item_cf_percent": result.route_weights.get("item_cf", 0) * 100,
            "ncf_percent": result.route_weights.get("ncf", 0) * 100,
            "time_context": result.time_context,
            "scene_id": result.scene_id,
            "scene_name": next((name for name, tag_id in inputs.get("scene_ids_by_name", {}).items() if tag_id == result.scene_id), None),
            "scene_source": result.scene_source,
            "scene_match_percent": result.scene_match_rate * 100,
            "route": route,
            "snapshot": RecommendationSnapshot.objects.filter(user_id=user_id).order_by("-generated_at", "-id").first()}
