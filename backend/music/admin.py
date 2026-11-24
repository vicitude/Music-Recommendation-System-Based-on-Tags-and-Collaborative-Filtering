import logging
from pathlib import Path

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404, HttpResponseRedirect, HttpResponseNotAllowed, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone

from music.forms import SongAdminForm, SongTagAdminForm, SongTagInlineFormSet, TagAdminForm
from music.api.errors import ApiError
from music.media import controlled_media_path, media_response, store_audio
from music.local_catalog import import_drafts, load_catalog
from music.local_media import bind_local_audio, catalog_audio_rows
from music.models import Comment, Rating, Song, SongTag, Tag, User
from music.tag_library import import_library, library_groups
from music.diagnostics import build_diagnostics
from music.publishing import publish_song


logger = logging.getLogger(__name__)
admin.site.site_header = "音律 · 内容管理"
admin.site.site_title = "音律管理台"
admin.site.index_title = "工作台"
admin.site.site_url = "http://127.0.0.1:5173/"


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("user", "song", "content", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "user__username", "song__title")
    readonly_fields = ("user", "song", "content", "created_at")
    list_select_related = ("user", "song")
    list_per_page = 20

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ("user", "song", "score", "updated_at")
    list_filter = ("score",)
    search_fields = ("user__username", "song__title", "song__artist")
    readonly_fields = ("created_at", "updated_at")


@admin.register(User)
class MusicUserAdmin(UserAdmin):
    change_list_template = "admin/music/user/change_list.html"
    readonly_fields = UserAdmin.readonly_fields + ("origin", "onboarding_completed")
    fieldsets = UserAdmin.fieldsets + (
        ("推荐状态", {"fields": ("origin", "onboarding_completed")}),
    )

    def get_urls(self):
        return [path("recommendation-diagnostics/", self.admin_site.admin_view(self.diagnostics), name="music_recommendation_diagnostics")] + super().get_urls()

    def diagnostics(self, request):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        if not request.user.is_active or not request.user.is_staff or not request.user.has_perms(["music.view_user", "music.view_song"]):
            raise PermissionDenied
        error, report, selected, status = "", None, None, 200
        users = []
        try:
            users = list(User.objects.filter(is_active=True).order_by("id").only("id", "username", "origin"))
            value = request.GET.get("user_id", "")
            if value:
                selected = next((member for member in users if str(member.pk) == value), None)
                if selected is None:
                    error, status = "请选择有效的活跃账号。", 400
                else:
                    report = build_diagnostics(user_id=selected.pk, now=timezone.now())
        except (DatabaseError, ValueError, ApiError):
            error, status = "诊断暂时不可用，请检查本机服务和数据状态；未修改用户或推荐。", 503
        response = TemplateResponse(request, "admin/music/user/diagnostics.html", {
            **self.admin_site.each_context(request), "title": "推荐算法诊断", "opts": self.model._meta,
            "users": users, "selected": selected, "report": report, "error": error,
        }, status=status)
        response["Cache-Control"] = "private,no-store"
        return response


class SongTagInline(admin.TabularInline):
    model = SongTag
    form = SongTagAdminForm
    formset = SongTagInlineFormSet
    fields = ("tag",)
    extra = 1
    verbose_name = "歌曲标签"
    verbose_name_plural = "歌曲标签（每行选一个，可添加多行）"

@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    form = SongAdminForm
    change_list_template = "admin/music/song/change_list.html"
    change_form_template = "admin/music/song/change_form.html"
    readonly_fields = ("file_path", "preview", "tag_guide")
    list_display = ("title", "artist", "active", "playback_allowed", "checked_at")
    list_filter = ("active", "playback_allowed")
    search_fields = ("title", "artist", "album")
    list_per_page = 20
    fieldsets = (
        ("歌曲信息", {"fields": ("title", "artist", "album", "duration_ms"), "description": "填写歌曲与歌手信息。时长单位为毫秒，例如10秒填写10000。"}),
        ("标签选择说明", {"fields": ("tag_guide",)}),
        ("音频与预览", {"fields": ("upload", "mime", "file_path", "preview"), "description": "支持WAV / MP3 / OGG，每首不超过30MiB。MP3和OGG先保存草稿，再实际预览。"}),
    )
    inlines = (SongTagInline,)

    @admin.display(description="常用标签")
    def tag_guide(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">查看53个正式标签与说明 / 补充下拉选项</a><p>页面底部每行选择一个标签。曲风是音乐类型，情绪是听感，后台场景是适配建议；不知道可留空，不必每类填满。历史旧标签保留兼容，不代表新标准已确认。</p>', reverse("admin:music_tag_library"))

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="受控预览")
    def preview(self, obj):
        if not obj.pk or not obj.file_path:
            return "上传或关联音频后可试听，点击页面底部“保存并发布”即可进入前台。"
        url = reverse("admin:music_song_preview", args=[obj.pk])
        return format_html('<audio controls preload="metadata" src="{}"></audio><p>可在这里试听；点击页面底部“保存并发布”即可进入前台，无需填写时间。</p>', url)

    def get_urls(self):
        return [
            path("published/", self.admin_site.admin_view(self.published), name="music_song_published"),
            path("batch-publish/", self.admin_site.admin_view(self.batch_publish), name="music_song_batch_publish"),
            path("batch-import/", self.admin_site.admin_view(self.batch_import), name="music_song_batch_import"),
            path("local-audio/", self.admin_site.admin_view(self.local_audio), name="music_song_local_audio"),
            path("local-import/", self.admin_site.admin_view(self.local_import), name="music_song_local_import"),
            path("<int:object_id>/preview/", self.admin_site.admin_view(self.preview_audio), name="music_song_preview"),
        ] + super().get_urls()

    def published(self, request):
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET"])
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        songs = list(Song.objects.filter(active=True).prefetch_related("songtag_set__tag").order_by("-checked_at", "-id"))
        response = TemplateResponse(request, "admin/music/song/published.html", {
            **self.admin_site.each_context(request), "title": "已发布歌曲", "opts": self.model._meta,
            "songs": songs,
        })
        response["Cache-Control"] = "private,no-store"
        return response

    def batch_publish(self, request):
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        results, error = [], ""
        if request.method == "POST":
            selected = list(dict.fromkeys(request.POST.getlist("selected")))
            if request.POST.get("confirm_publish") != "yes":
                error = "请先确认发布选中的歌曲。"
            elif not selected or any(not value.isascii() or not value.isdigit() or len(value) > 18 for value in selected):
                error = "请至少选择一首有效歌曲。"
            else:
                for song_id in selected:
                    title = f"歌曲编号 {song_id}"
                    try:
                        with transaction.atomic():
                            song = Song.objects.select_for_update().get(pk=song_id)
                            title = song.title
                            if not self.has_change_permission(request, song):
                                raise PermissionDenied
                            if song.active:
                                results.append({"title": title, "message": "已发布，跳过（未修改）"})
                                continue
                            publish_song(song)
                            self.log_change(request, song, "批量发布歌曲")
                        results.append({"title": title, "message": "发布成功"})
                    except Song.DoesNotExist:
                        results.append({"title": title, "message": "歌曲不存在，未发布"})
                    except ValidationError as failure:
                        results.append({"title": title, "message": "未发布：" + "；".join(failure.messages)})
                    except (OSError, DatabaseError):
                        logger.exception("Batch publish failed for song %s", song_id)
                        results.append({"title": title, "message": "未发布：文件或数据库操作失败，请核对后重试。"})
        response = TemplateResponse(request, "admin/music/song/batch_publish.html", {
            **self.admin_site.each_context(request), "title": "批量发布歌曲", "opts": self.model._meta,
            "songs": list(Song.objects.filter(active=False).order_by("id")), "results": results, "error": error,
        }, status=400 if error else 200)
        response["Cache-Control"] = "private,no-store"
        return response

    def batch_import(self, request):
        from music.batch_import import create_batch, execute_batch, load_batch, recent_batches

        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        if not request.user.is_active or not request.user.is_staff or not request.user.has_perms(["music.add_song", "music.change_song"]):
            raise PermissionDenied
        batch, error = None, ""
        try:
            if request.method == "POST":
                action = request.POST.get("action")
                if action == "scan":
                    batch = create_batch(request.user.pk, analyze=request.POST.get("analyze_tags") == "yes")
                elif action == "save_candidate_edit":
                    from music.candidate_edits import save_candidate_edit
                    if not request.user.has_perms(["music.add_tag", "music.add_songtag"]):
                        raise PermissionDenied
                    batch = save_candidate_edit(request.POST.get("batch_id", ""), request.user.pk, request.POST.get("fingerprint", ""), request.POST.getlist("tag_ids"))
                    self.message_user(request, "候选标签已保存；仅新歌导入采用，未覆盖已有曲库。", messages.SUCCESS)
                elif action == "model_analyze":
                    from music.clap_candidates import analyze_batch

                    batch = analyze_batch(request.POST.get("batch_id", ""), request.user.pk, request.POST.getlist("model_selected"))
                elif action in {"minimum_analyze", "minimum_analyze_chunk"}:
                    from music.clap_candidates import analyze_batch

                    batch = analyze_batch(request.POST.get("batch_id", ""), request.user.pk, request.POST.getlist("model_selected"), minimum=True)
                    if action == "minimum_analyze_chunk":
                        selected = set(request.POST.getlist("model_selected"))
                        response = JsonResponse({"items": [{"sha256": item["sha256"], "analysis": item.get("minimum_analysis", {})} for item in batch["items"] if item.get("sha256") in selected]})
                        response["Cache-Control"] = "private,no-store"
                        return response
                elif action == "import_publish" and request.POST.get("confirm_import") == "yes":
                    batch = execute_batch(request.POST.get("batch_id", ""), request.user.pk, accept_model_tags=True, publish=True)
                elif action == "import" and request.POST.get("confirm_import") == "yes":
                    accept_high_tags = request.POST.get("accept_high_tags") == "yes"
                    accept_model_tags = request.POST.get("accept_model_tags") == "yes"
                    if (accept_high_tags or accept_model_tags) and not request.user.has_perms(["music.add_tag", "music.add_songtag"]):
                        raise PermissionDenied
                    batch = execute_batch(request.POST.get("batch_id", ""), request.user.pk, accept_high_tags=accept_high_tags, accept_model_tags=accept_model_tags)
                else:
                    raise ValueError("请明确确认创建草稿并复制音频")
                return HttpResponseRedirect(reverse("admin:music_song_batch_import") + "?batch_id=" + batch["batch_id"])
            if request.GET.get("batch_id"):
                batch = load_batch(request.GET["batch_id"], request.user.pk)
        except (OSError, ValueError, RuntimeError, ValidationError, DatabaseError) as failure:
            error = "批次暂不可用或操作未完成。请核对目录、批次归属、明确确认和服务状态；已成功项保留，可重试，不会自动发布。"
            if isinstance(failure, ValueError):
                error = str(failure)
            if request.method == "POST" and request.POST.get("action") == "minimum_analyze_chunk":
                response = JsonResponse({"error": error}, status=400)
                response["Cache-Control"] = "private,no-store"
                return response
        editor, tag_groups = None, []
        if batch:
            from music.candidate_edits import LIMITS, edited_candidates
            from music.minimum_candidates import confirmed_candidates
            available = list(Tag.objects.filter(active=True).order_by("kind", "name", "id"))
            for item in batch["items"]:
                item["effective_candidates"] = item.get("minimum_analysis", {}).get("candidates", [])
                if item.get("candidate_edit"):
                    try:
                        item["effective_candidates"] = edited_candidates(item, request.user.pk)
                    except ValueError:
                        item["candidate_edit_error"] = "人工候选已失效，请重新选择；导入时将拒绝该项。"
                if item.get("sha256") == request.GET.get("edit"):
                    try:
                        confirmed_candidates(item)
                        editor = item
                    except ValueError:
                        error = "该歌曲尚无有效模型候选，请先完成分析。"
            if editor:
                chosen = {(tag["kind"], tag["name"]) for tag in editor["effective_candidates"]}
                tag_groups = [dict(label=label, limit=LIMITS[kind], options=[dict(id=tag.pk, name=tag.name, selected=(tag.kind, tag.name) in chosen) for tag in available if tag.kind == kind]) for kind, label in Tag.KIND_CHOICES]
        response = TemplateResponse(request, "admin/music/song/batch_import.html", {
            **self.admin_site.each_context(request), "title": "批量扫描与导入音乐", "opts": self.model._meta,
            "batch": batch, "error": error,
            "editor": editor, "tag_groups": tag_groups,
            "recent_batches": recent_batches(request.user.pk),
            "can_apply_tags": request.user.has_perms(["music.add_tag", "music.add_songtag"]),
        }, status=400 if error else 200)
        response["Cache-Control"] = "private,no-store"
        return response

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
    change_list_template = "admin/music/tag/change_list.html"
    list_display = ("name", "kind", "active")
    list_filter = ("kind", "active")
    search_fields = ("name",)
    list_per_page = 30

    def get_urls(self):
        return [path("library/", self.admin_site.admin_view(self.library), name="music_tag_library")] + super().get_urls()

    def library(self, request):
        if request.method not in {"GET", "POST"}:
            return HttpResponseNotAllowed(["GET", "POST"])
        allowed = any(request.user.has_perm(permission) for permission in ("music.view_tag", "music.change_tag", "music.change_song"))
        if not request.user.is_active or not request.user.is_staff or not allowed:
            raise PermissionDenied
        can_import = request.user.has_perm("music.add_tag")
        error = ""
        if request.method == "POST":
            if not can_import:
                raise PermissionDenied
            try:
                if request.POST.get("confirm_library") != "yes":
                    raise ValidationError("请确认仅补充标签选项，不自动修改歌曲")
                result = import_library(request.POST.getlist("selected"))
            except ValidationError as failure:
                error = "；".join(failure.messages)
            except DatabaseError:
                error = "标签保存失败，本次新建已回滚，请检查数据库状态。"
            else:
                self.message_user(request, f"新增{result['created']}个标签选项，跳过{result['skipped']}个既有标签；未修改歌曲标签或发布状态。返回歌曲编辑页刷新后即可选择。", messages.SUCCESS)
                return HttpResponseRedirect(reverse("admin:music_tag_library"))
        try:
            groups, custom_tags = library_groups()
        except DatabaseError:
            groups, custom_tags = [], []
            error = "标签暂不可用，请检查数据库状态。"
        return TemplateResponse(request, "admin/music/tag/library.html", {
            **self.admin_site.each_context(request), "title": "常用标签选择指南", "opts": self.model._meta,
            "groups": groups, "custom_tags": custom_tags, "can_import": can_import, "error": error,
        }, status=400 if error and request.method == "POST" else 200)
