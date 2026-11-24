from django.db import transaction
from django.db.models import Exists, OuterRef

from music.api.errors import ApiError
from music.models import Follow, User


def active_relations():
    return Follow.objects.filter(source__is_active=True, target__is_active=True)


def active_user(user_id):
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ApiError("NOT_FOUND")
    return user


def summary(viewer, user):
    relations = active_relations()
    return {
        "id": user.pk,
        "username": user.username,
        "following_count": relations.filter(source=user).count(),
        "follower_count": relations.filter(target=user).count(),
        "is_following": relations.filter(source=viewer, target=user).exists(),
        "is_self": viewer.pk == user.pk,
    }


def relation_list(viewer, user, direction):
    relation_field, member_field = ("source", "target") if direction == "following" else ("target", "source")
    viewer_follows = active_relations().filter(source=viewer, target_id=OuterRef(f"{member_field}_id"))
    return active_relations().filter(**{relation_field: user}).select_related(member_field).annotate(
        viewer_follows=Exists(viewer_follows),
    ).order_by("-created_at", "-id"), member_field


@transaction.atomic
def change_follow(viewer, user_id, following):
    users = {user.pk: user for user in User.objects.select_for_update().filter(
        pk__in=[viewer.pk, user_id],
    ).order_by("pk")}
    source = users.get(viewer.pk)
    if source is None or not source.is_active:
        raise ApiError("AUTH_REQUIRED")
    target = users.get(user_id)
    if target is None or not target.is_active:
        raise ApiError("NOT_FOUND")
    if source.pk == target.pk:
        raise ApiError("VALIDATION_ERROR", ["id"])
    if following:
        Follow.objects.get_or_create(source=source, target=target)
    else:
        Follow.objects.filter(source=source, target=target).delete()
    return summary(source, target)
