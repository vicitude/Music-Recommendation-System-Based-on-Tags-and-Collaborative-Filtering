from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from music.media import MAX_AUDIO_BYTES, controlled_media_path, inspect_audio
from music.models import Song, SongTag, Tag


class GroupedTagChoiceIterator(forms.models.ModelChoiceIterator):
    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        tags = list(self.queryset.order_by("kind", "name", "id"))
        for kind, label in Tag.KIND_CHOICES:
            options = [self.choice(tag) for tag in tags if tag.kind == kind]
            if options:
                yield (label, options)


class GroupedTagChoiceField(forms.ModelChoiceField):
    iterator = GroupedTagChoiceIterator


class SongTagAdminForm(forms.ModelForm):
    tag = GroupedTagChoiceField(queryset=Tag.objects.all(), label="歌曲标签", help_text="曲风1—2项、情绪1—3项、场景1—2项；未完成可保存草稿，发布时三类均须至少一项。已停用项不参与推荐。")

    class Meta:
        model = SongTag
        fields = ("tag",)


class SongTagInlineFormSet(forms.models.BaseInlineFormSet):
    def clean(self):
        if any(self.errors):
            return
        remaining = [form for form in self.forms if form.cleaned_data and not (self.can_delete and self._should_delete_form(form))]
        seen = {}
        duplicate = False
        kind_counts = {Tag.STYLE: 0, Tag.MOOD: 0, Tag.SCENE: 0}
        for form in remaining:
            tag = form.cleaned_data.get("tag")
            if tag is None:
                continue
            kind_counts[tag.kind] = kind_counts.get(tag.kind, 0) + 1
            if tag.pk in seen:
                form.add_error("tag", f"重复选择了“{tag}”，同一首歌只需选择一次。")
                duplicate = True
            else:
                seen[tag.pk] = form
        if duplicate:
            raise ValidationError("歌曲标签重复，请修改或删除重复行后再保存。")
        limits = {Tag.STYLE: 2, Tag.MOOD: 3, Tag.SCENE: 2}
        exceeded = [kind for kind, limit in limits.items() if kind_counts.get(kind, 0) > limit]
        if exceeded:
            raise ValidationError("tag count exceeds the per-kind limit")
        if self.data.get("_publish") and any(not any(form.cleaned_data.get("tag") and form.cleaned_data["tag"].kind == kind and form.cleaned_data["tag"].active for form in remaining) for kind in limits):
            raise ValidationError("发布前请至少选择一个启用的曲风、情绪和场景标签。未完成可先保存草稿。")
        deleted_ids = {form.instance.pk for form in self.forms if form.cleaned_data and self.can_delete and self._should_delete_form(form)}
        occupied = dict(SongTag.objects.filter(song_id=self.instance.pk).exclude(pk__in=deleted_ids).values_list("tag_id", "pk")) if self.instance.pk else {}
        for form in remaining:
            tag = form.cleaned_data.get("tag")
            if tag is not None and tag.pk in occupied and occupied[tag.pk] != form.instance.pk:
                form.add_error("tag", f"“{tag}”已关联到这首歌；请保留原行，或先移除原行并保存后再调整。")
                duplicate = True
        if duplicate:
            raise ValidationError("标签与已有记录冲突，请检查重复选择；交换标签时请分两次保存。")
        super().clean()

    def save_existing_objects(self, commit=True):
        self.changed_objects = []
        self.deleted_objects = []
        saved = []
        for form in self.deleted_forms:
            if form in self.initial_forms and form.instance.pk and not form.instance._state.adding:
                self.deleted_objects.append(form.instance)
                self.delete_existing(form.instance, commit=commit)
        for form in self.initial_forms:
            if form in self.deleted_forms or not form.instance.pk or form.instance._state.adding:
                continue
            if form.has_changed():
                self.changed_objects.append((form.instance, form.changed_data))
                saved.append(self.save_existing(form, form.instance, commit=commit))
                if not commit:
                    self.saved_forms.append(form)
        return saved


class SongAdminForm(forms.ModelForm):
    album = forms.CharField(required=False, max_length=120, label="专辑")
    upload = forms.FileField(required=False, label="音频文件")

    class Meta:
        model = Song
        exclude = ["file_path", "source_name", "source_url", "license_name", "license_url", "attribution_text", "redistribution_allowed", "active", "playback_allowed", "checked_at"]
        labels = {
            "title": "歌曲名称", "artist": "歌手 / 创作者", "album": "专辑", "duration_ms": "时长（毫秒）",
            "mime": "音频格式", "active": "发布 / 上架",
            "checked_at": "试听核验时间", "playback_allowed": "开启前台播放",
        }

    def clean_file_path(self) -> str:
        original = self.instance.file_path
        if original and controlled_media_path(original) is None:
            raise ValidationError("原媒体路径无效或文件不存在")
        return original

    def clean(self) -> dict:
        cleaned = super().clean()
        self.audio_data = None
        if "_publish" in self.data and "_unpublish" in self.data:
            raise ValidationError("不能同时发布和下架")
        self.publish_requested = "_publish" in self.data
        self.unpublish_requested = "_unpublish" in self.data
        self.will_publish = self.publish_requested or (self.instance.active and not self.unpublish_requested)
        upload = cleaned.get("upload")
        if len(self.files) > 1 or any(len(self.files.getlist(key)) > 1 for key in self.files if hasattr(self.files, "getlist")):
            raise ValidationError("一次只能上传一个音频文件")
        if not 1 <= cleaned.get("duration_ms", 0) <= 86400000:
            self.add_error("duration_ms", "时长必须为1—86400000毫秒")
        detected = None
        duration = None
        if upload:
            if not 1 <= upload.size <= MAX_AUDIO_BYTES:
                self.add_error("upload", "音频为空或超过30MiB")
            else:
                self.audio_data = upload.read(MAX_AUDIO_BYTES + 1)
                try:
                    detected, duration = inspect_audio(self.audio_data, upload.name)
                except ValidationError as error:
                    self.add_error("upload", error)
        elif self.instance.file_path:
            path = controlled_media_path(self.instance.file_path)
            if path is None:
                raise ValidationError("原媒体路径无效或文件不存在")
            if self.will_publish:
                try:
                    with path.open("rb") as source:
                        detected, duration = inspect_audio(source.read(MAX_AUDIO_BYTES + 1), path.name)
                except OSError:
                    raise ValidationError("无法读取媒体文件") from None
        if detected and detected != cleaned.get("mime"):
            self.add_error("mime", "MIME与实际文件类型不一致")
        if duration is not None and abs(duration - cleaned.get("duration_ms", 0)) > 1000:
            self.add_error("duration_ms", "WAV时长与实测差异超过1000毫秒")
        if self.will_publish:
            if not (upload or self.instance.file_path):
                self.add_error("upload", "发布必须有有效音频")
        return cleaned

    def save(self, commit=True):
        song = super().save(commit=False)
        if self.publish_requested:
            song.active = song.playback_allowed = True
            song.checked_at = timezone.now()
        elif self.unpublish_requested:
            song.active = song.playback_allowed = False
        if commit:
            song.save()
            self.save_m2m()
        return song


class TagAdminForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = "__all__"
        labels = {"name": "标签名称", "kind": "标签类型", "active": "启用标签"}

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        if not 1 <= len(name) <= 30:
            raise ValidationError("标签长度须为1—30字符")
        return name
