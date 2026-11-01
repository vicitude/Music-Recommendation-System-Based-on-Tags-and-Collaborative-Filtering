import logging
from pathlib import Path

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponseRedirect, HttpResponseNotAllowed
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from music.forms import SongAdminForm, TagAdminForm
from music.api.errors import ApiError
from music.media import controlled_media_path, media_response, store_audio
from music.local_catalog import import_drafts, load_catalog
from music.local_media import bind_local_audio, catalog_audio_rows
from music.models import Song, SongTag, Tag, User


logger = logging.getLogger(__name__)
admin.site.site_header = "音律 · 内容管理"
admin.site.site_title = "音律管理台"
admin.site.index_title = "工作台"
admin.site.site_url = "http://127.0.0.1:5173/"


@admin.register(User)
class MusicUserAdmin(UserAdmin):
    readonly_fields = UserAdmin.readonly_fields + ("origin", "onboarding_completed")
    fieldsets = UserAdmin.fieldsets + (
        ("推荐状态", {"fields": ("origin", "onboarding_completed")}),
    )


class SongTagInline(admin.TabularInline):
    model = SongTag
    fields = ("tag",)
    extra = 0

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    form = SongAdminForm
    change_list_template = "admin/music/song/change_list.html"
    readonly_fields = ("file_path", "preview")
    list_display = ("title", "artist", "active", "playback_allowed", "checked_at")
    list_filter = ("active", "playback_allowed")
    search_fields = ("title", "artist", "album")
    list_per_page = 20
    fieldsets = (
        ("歌曲信息", {"fields": ("title", "artist", "album", "duration_ms"), "description": "填写歌曲与歌手信息。时长单位为毫秒，例如10秒填写10000。"}),
        ("音频与预览", {"fields": ("upload", "mime", "file_path", "preview"), "description": "支持WAV / MP3 / OGG，每首不超过30MiB。MP3和OGG先保存草稿，再实际预览。"}),
        ("来源与许可", {"fields": ("source_name", "source_url", "license_name", "license_url", "attribution_text", "redistribution_allowed"), "description": "素材来源不等于播放授权，请保留许可与署名证据。"}),
        ("核验与发布", {"fields": ("playback_allowed", "rights_confirmed", "preview_confirmed", "checked_at", "active"), "description": "完成许可核验和必要的实际预览后才能发布。不勾选发布即保留为草稿或下架。"}),
    )
    inlines = (SongTagInline,)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="受控预览")
    def preview(self, obj):
        if not obj.pk or not obj.file_path:
            return "先保存草稿音频，再实际预览核验；不得仅凭文件头发布。"
        url = reverse("admin:music_song_preview", args=[obj.pk])
        return format_html('<audio controls preload="metadata" src="{}"></audio><p>实际播放后人工填写时长与核验时间；不会自动确认版权。</p>', url)

    def get_urls(self):
        return [
            path("local-audio/", self.admin_site.admin_view(self.local_audio), name="music_song_local_audio"),
            path("local-import/", self.admin_site.admin_view(self.local_import), name="music_song_local_import"),
            path("<int:object_id>/preview/", self.admin_site.admin_view(self.preview_audio), name="music_song_preview"),
        ] + super().get_urls()

    def local_import(self, request):
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        if not request.user.is_active or not request.user.is_staff or not request.user.has_perms(["music.add_song", "music.change_song"]):
            raise PermissionDenied
        error = ""
        try:
            items = load_catalog()
        except (OSError, ValueError, ValidationError):
            items = []
            error = "本地歌曲清单不可用，请先重新整理资料；未修改曲库。"
        if request.method == "POST" and not error:
            if request.POST.get("confirm_drafts") != "yes":
                error = "请明确确认仅创建资料草稿。"
            else:
                accept_tags = request.POST.get("accept_tags") == "yes"
                if accept_tags and not request.user.has_perms(["music.add_tag", "music.add_songtag"]):
                    raise PermissionDenied
                try:
                    result = import_drafts(items=items, selected_hashes=request.POST.getlist("selected"), owner_id=request.user.id, accept_tags=accept_tags)
                except (ValidationError, DatabaseError):
                    error = "导入未完成：请选择资料完整的条目，或检查数据库状态；本次关系写入已回滚。"
                else:
                    self.message_user(request, f"新建{result['created']}首资料草稿，跳过{result['skipped']}首既有记录。未复制音频、未开启播放。", messages.SUCCESS)
                    return HttpResponseRedirect(reverse("admin:music_song_changelist"))
        return TemplateResponse(request, "admin/music/song/local_import.html", {
            **self.admin_site.each_context(request), "title": "本地歌曲资料导入", "opts": self.model._meta,
            "items": items, "error": error, "eligible_count": sum(item["eligible"] for item in items),
            "can_apply_tags": request.user.has_perms(["music.add_tag", "music.add_songtag"]),
        }, status=400 if error and request.method == "POST" else 200)

    def local_audio(self, request):
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        if not request.user.is_active or not request.user.is_staff or not self.has_change_permission(request):
            raise PermissionDenied
        error, result = "", None
        items, rows = [], []
        try:
            items = load_catalog()
            rows = catalog_audio_rows(items)
            if request.method == "POST":
                if request.POST.get("confirm_audio") != "yes":
                    raise ValidationError("请确认复制音频并保留草稿状态")
                result = bind_local_audio(items=items, selected_hashes=request.POST.getlist("selected"))
                self.message_user(request, f"关联{result['linked']}首，跳过{result['skipped']}首，失败{result['failed']}首。未自动发布，原文件未修改。", messages.WARNING if result["failed"] else messages.SUCCESS)
            rows = catalog_audio_rows(items)
        except ValidationError as failure:
            error = "；".join(failure.messages)
        except (OSError, ValueError, DatabaseError):
            error = "清单或数据库暂不可用，请检查本机服务；若已提交请核对逐首状态，不要重复导入资料。"
        return TemplateResponse(request, "admin/music/song/local_audio.html", {
            **self.admin_site.each_context(request), "title": "批量关联本机音频", "opts": self.model._meta,
            "rows": rows, "error": error, "result": result,
            "selectable_count": sum(row["selectable"] for row in rows),
        }, status=400 if error and request.method == "POST" else 200)

    def preview_audio(self, request, object_id):
        if not request.user.is_active or not request.user.is_staff:
            raise PermissionDenied
        song = self.get_object(request, object_id)
        if song is None:
            raise Http404
        if not self.has_view_or_change_permission(request, song):
            raise PermissionDenied
        media_path = controlled_media_path(song.file_path)
        if media_path is None or song.mime not in {"audio/mpeg", "audio/wav", "audio/ogg"}:
            raise Http404
        try:
            return media_response(path=media_path, mime=song.mime, range_header=request.headers.get("Range"))
        except ApiError:
            raise Http404 from None

    def save_model(self, request, obj, form, change):
        permission = "music.change_song" if change else "music.add_song"
        if not request.user.is_active or not request.user.is_staff or not request.user.has_perm(permission):
            raise PermissionDenied
        new_file = None
        if form.cleaned_data.get("upload"):
            new_file = store_audio(data=form.audio_data, extension=Path(form.cleaned_data["upload"].name).suffix.lower())
            obj.file_path = new_file
        try:
            super().save_model(request, obj, form, change)
        except Exception:
            if new_file:
                logger.error("Orphan media file retained: %s", new_file)
            raise


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    form = TagAdminForm
    list_display = ("name", "kind", "active")
    list_filter = ("kind", "active")
    search_fields = ("name",)
    list_per_page = 30

    def has_delete_permission(self, request, obj=None):
        return False
