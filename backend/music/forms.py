from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone

from music.media import MAX_AUDIO_BYTES, controlled_media_path, inspect_audio
from music.models import Song, Tag


class SongAdminForm(forms.ModelForm):
    album = forms.CharField(required=False, max_length=120, label="专辑")
    attribution_text = forms.CharField(required=False, widget=forms.Textarea, label="署名说明")
    upload = forms.FileField(required=False, label="音频文件")
    rights_confirmed = forms.BooleanField(required=False, label="已人工核验来源和播放许可")
    preview_confirmed = forms.BooleanField(required=False, label="已预览实际播放至少5秒（短曲完整播放）")

    class Meta:
        model = Song
        exclude = ["file_path"]
        labels = {
            "title": "歌曲名称", "artist": "歌手 / 创作者", "album": "专辑", "duration_ms": "时长（毫秒）",
            "mime": "音频格式", "active": "发布 / 上架", "source_name": "来源名称", "source_url": "来源链接",
            "license_name": "许可名称", "license_url": "许可条款链接", "attribution_text": "署名说明",
            "checked_at": "人工核验时间", "playback_allowed": "已确认允许应用内播放", "redistribution_allowed": "允许再分发",
        }

    def clean_file_path(self) -> str:
        original = self.instance.file_path
        if original and controlled_media_path(original) is None:
            raise ValidationError("原媒体路径无效或文件不存在")
        return original

    def clean(self) -> dict:
        cleaned = super().clean()
        self.audio_data = None
        upload = cleaned.get("upload")
        if len(self.files) > 1 or any(len(self.files.getlist(key)) > 1 for key in self.files if hasattr(self.files, "getlist")):
            raise ValidationError("一次只能上传一个音频文件")
        if not 1 <= cleaned.get("duration_ms", 0) <= 86400000:
            self.add_error("duration_ms", "时长必须为1—86400000毫秒")
        for field in ("source_url", "license_url"):
            if cleaned.get(field):
                try:
                    URLValidator(schemes=["http", "https"])(cleaned[field])
                except ValidationError:
                    self.add_error(field, "仅支持http/https来源")
        checked = cleaned.get("checked_at")
        if checked is not None and checked > timezone.now():
            self.add_error("checked_at", "核验时间不能在未来")
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
            if cleaned.get("active"):
                try:
                    with path.open("rb") as source:
                        detected, duration = inspect_audio(source.read(MAX_AUDIO_BYTES + 1), path.name)
                except OSError:
                    raise ValidationError("无法读取媒体文件") from None
        if detected and detected != cleaned.get("mime"):
            self.add_error("mime", "MIME与实际文件类型不一致")
        if duration is not None and abs(duration - cleaned.get("duration_ms", 0)) > 1000:
            self.add_error("duration_ms", "WAV时长与实测差异超过1000毫秒")
        if upload and detected in {"audio/mpeg", "audio/ogg"}:
            if cleaned.get("active"):
                self.add_error("active", "MP3/OGG先保存草稿并预览，再填写核验时间发布")
            cleaned["checked_at"] = None
        if cleaned.get("active"):
            if not (upload or self.instance.file_path):
                self.add_error("upload", "发布必须有有效音频")
            for field in ("source_name", "source_url", "license_name", "license_url"):
                if not cleaned.get(field):
                    self.add_error(field, "发布必须提供来源与许可")
            if not cleaned.get("playback_allowed") or not cleaned.get("rights_confirmed") or cleaned.get("checked_at") is None:
                self.add_error("active", "发布须允许播放、填写核验时间并人工确认许可")
            if cleaned.get("mime") in {"audio/mpeg", "audio/ogg"} and not cleaned.get("preview_confirmed"):
                self.add_error("preview_confirmed", "MP3/OGG必须实际预览核验")
        return cleaned


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
