from django.core.exceptions import ValidationError

from music.forms import SongAdminForm
from music.models import Tag


def publish_song(song):
    fields = {name: getattr(song, name) for name in ("title", "artist", "album", "duration_ms", "mime")}
    form = SongAdminForm(data={**fields, "_publish": "1"}, instance=song)
    if not form.is_valid():
        raise ValidationError([f"{name}：{message}" for name, errors in form.errors.items() for message in errors])
    tags = list(Tag.objects.filter(songtag__song=song))
    for kind, limit in ((Tag.STYLE, 2), (Tag.MOOD, 3), (Tag.SCENE, 2)):
        matching = [tag for tag in tags if tag.kind == kind]
        if len(matching) > limit or not any(tag.active for tag in matching):
            raise ValidationError("标签未达发布要求：曲风1—2、情绪1—3、场景1—2，每类至少一个启用标签。")
    return form.save()
