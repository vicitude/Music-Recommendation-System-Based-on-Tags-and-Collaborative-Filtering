import importlib
import json
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import DELETION, LogEntry
from django.contrib.auth.models import Permission
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import PROTECT, ProtectedError
from django.http import HttpRequest
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.authentication import SessionAuthentication
from rest_framework.test import APIClient
from django.urls import resolve

from music.models import Comment, Song, User
from music.api.errors import ApiError
from music.api.views import createComment


class CommentApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="comment_owner", password="test-password-123")
        cls.other = User.objects.create_user(username="comment_other", email="private@example.org")
        cls.admin = User.objects.create_superuser(username="comment_admin", password="test-password-123")
        cls.song = Song.objects.create(title="Comment song", artist="TEST_ONLY", duration_ms=10000,
                                       mime="audio/wav", active=True)
        cls.openapi = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.client.force_login(self.user)
        self.url = f"/api/v1/songs/{self.song.pk}/comments/"

    def write(self, method="POST", payload=None, url=None, token=None):
        return self.client.generic(method, url or self.url, "" if payload is None else json.dumps(payload),
                                   content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token)

    def comment(self, **kwargs):
        return Comment.objects.create(user=self.user, song=self.song, content="test comment", **kwargs)

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error_code"], code)

    def validate_schema(self, schema, value):
        Draft202012Validator({"$ref": f"#/components/schemas/{schema}", "components": self.openapi["components"]},
                              format_checker=FormatChecker()).validate(value)

    def test_create_trim_multiline_and_response_contract(self):
        response = self.write(payload={"content": " \n 第一行\n  第二行 \n "})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.validate_schema("CommentItem", body)
        self.assertEqual(body["content"], "第一行\n  第二行")
        self.assertEqual(Comment.objects.get().content, body["content"])
        self.assertEqual(body["song_id"], self.song.pk)
        self.assertEqual(body["author"], {"id": self.user.pk, "username": self.user.username})
        self.assertTrue(body["can_delete"])

    def test_content_boundaries_strict_types_and_unknown_fields(self):
        for content in ("a", "字" * 500, " " + "字" * 500 + " "):
            with self.subTest(length=len(content)):
                self.assertEqual(self.write(payload={"content": content}).status_code, 201)
        for payload in ({}, [], None, {"content": ""}, {"content": " \n\t\u3000"}, {"content": "字" * 501},
                        {"content": 1}, {"content": True}, {"content": None}, {"content": []},
                        {"content": {}}, {"content": "ok", "user_id": self.other.pk},
                        {"content": "ok", "song_id": self.song.pk}, {"content": "ok", "extra": 1}):
            with self.subTest(payload=payload):
                self.assert_error(self.write(payload=payload), 400, "VALIDATION_ERROR")
        self.assertEqual(Comment.objects.count(), 3)

    def test_public_get_and_explicit_private_post(self):
        self.comment()
        self.client.logout()
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["items"][0]["can_delete"])
        self.assert_error(self.write(payload={"content": "anonymous"}), 401, "AUTH_REQUIRED")
        self.assert_error(self.write("DELETE", url=f"/api/v1/comments/{Comment.objects.get().pk}/"), 401, "AUTH_REQUIRED")
        self.assertEqual(Comment.objects.count(), 1)

    def test_inactive_session_cannot_write_or_claim_ownership(self):
        comment = self.comment()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["items"][0]["can_delete"])
        self.assert_error(self.write(payload={"content": "inactive"}), 401, "AUTH_REQUIRED")
        self.assert_error(self.write("DELETE", url=f"/api/v1/comments/{comment.pk}/"), 401, "AUTH_REQUIRED")

    def test_post_function_explicitly_rejects_inactive_authenticated_user(self):
        self.user.is_active = False
        request = HttpRequest()
        request.user = self.user
        with self.assertRaises(ApiError) as caught:
            createComment(request, self.song.pk)
        self.assertEqual(caught.exception.error_code, "AUTH_REQUIRED")

    def test_session_authentication_and_csrf_enforced(self):
        self.assertIn(SessionAuthentication, resolve(self.url).func.cls.authentication_classes)
        comment = self.comment()
        for method, url, payload in (("POST", self.url, {"content": "blocked"}),
                                     ("DELETE", f"/api/v1/comments/{comment.pk}/", None)):
            for token in (None, "invalid"):
                response = self.client.generic(method, url, "" if payload is None else json.dumps(payload),
                                               content_type="application/json", **({"HTTP_X_CSRFTOKEN": token} if token else {}))
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(self.url, HTTP_X_CSRFTOKEN="invalid").status_code, 200)
        self.assertEqual(self.write(payload={"content": "accepted"}).status_code, 201)
        self.assertEqual(self.write("DELETE", url=f"/api/v1/comments/{comment.pk}/").status_code, 204)

    def test_owner_only_admin_not_exempt_and_repeated_delete(self):
        comment = self.comment()
        url = f"/api/v1/comments/{comment.pk}/"
        for user in (self.other, self.admin):
            self.client.force_login(user)
            self.assertFalse(self.client.get(self.url).json()["items"][0]["can_delete"])
            self.assert_error(self.write("DELETE", url=url), 404, "NOT_FOUND")
        self.client.force_login(self.user)
        response = self.write("DELETE", url=url)
        self.assertEqual((response.status_code, response.content), (204, b""))
        self.assert_error(self.write("DELETE", url=url), 404, "NOT_FOUND")

    def test_unpublished_and_missing_song_get_post_delete(self):
        comment = self.comment()
        Song.objects.filter(pk=self.song.pk).update(active=False)
        for response in (self.client.get(self.url), self.write(payload={"content": "hidden"}),
                         self.write("DELETE", url=f"/api/v1/comments/{comment.pk}/"),
                         self.client.get("/api/v1/songs/999999/comments/"),
                         self.write(payload={"content": "missing"}, url="/api/v1/songs/999999/comments/")):
            self.assert_error(response, 404, "NOT_FOUND")
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_pagination_stable_ties_and_created_at_priority(self):
        comments = [self.comment() for number in range(42)]
        now = timezone.now()
        Comment.objects.update(created_at=now)
        Comment.objects.filter(pk=comments[0].pk).update(created_at=now + timedelta(seconds=1))
        expected = [comments[0].pk] + [comment.pk for comment in reversed(comments[1:])]
        actual = []
        for page in (1, 2, 3):
            response = self.client.get(self.url, {"page": page})
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.validate_schema("CommentPage", body)
            self.assertEqual((body["page"], body["page_size"], body["total"]), (page, 20, 42))
            actual.extend(item["id"] for item in body["items"])
        self.assertEqual(actual, expected)
        self.assert_error(self.client.get(self.url, {"page": 4}), 404, "NOT_FOUND")

    def test_empty_page_and_invalid_queries(self):
        self.assertEqual(self.client.get(self.url).json(), {"items": [], "total": 0, "page": 1, "page_size": 20})
        self.assert_error(self.client.get(self.url, {"page": 2}), 404, "NOT_FOUND")
        for query in ("page=0", "page=-1", "page=", "page=1.5", "page=abc", "page=1&page=2",
                      "page_size=20", "user_id=1", "page=" + "9" * 21):
            self.assert_error(self.client.get(self.url + "?" + query), 400, "VALIDATION_ERROR")

    def test_authors_only_public_fields_no_origin_or_active_filter(self):
        self.other.origin = "SIMULATED"
        self.other.is_active = False
        self.other.save(update_fields=["origin", "is_active"])
        Comment.objects.create(user=self.other, song=self.song, content="existing simulated author")
        item = self.client.get(self.url).json()["items"][0]
        self.assertEqual(item["author"], {"id": self.other.pk, "username": self.other.username})
        self.assertNotIn(self.other.email, json.dumps(item))
        self.assertEqual(set(item), {"id", "song_id", "author", "content", "created_at", "can_delete"})

    def test_no_other_business_model_writes(self):
        models = [model for model in apps.get_app_config("music").get_models() if model is not Comment]
        before = {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}
        response = self.write(payload={"content": "no algorithm feedback"})
        self.assertEqual(response.status_code, 201)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertFalse(any(entry["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"} for entry in queries))
        self.assertEqual(self.write("DELETE", url=f"/api/v1/comments/{response.json()['id']}/").status_code, 204)
        self.assertEqual(before, {model._meta.label: list(model.objects.order_by("pk").values()) for model in models})

    def test_method_and_malformed_json_rejected(self):
        self.assertEqual(self.client.put(self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.token).status_code, 405)
        self.assert_error(self.client.post(self.url, '{"content":', content_type="application/json", HTTP_X_CSRFTOKEN=self.token), 400, "VALIDATION_ERROR")

    def test_model_protection_metadata_and_index(self):
        self.comment()
        for obj in (self.song, self.user):
            with self.assertRaises(ProtectedError):
                obj.delete()
        self.assertIs(Comment._meta.get_field("user").remote_field.on_delete, PROTECT)
        self.assertIs(Comment._meta.get_field("song").remote_field.on_delete, PROTECT)
        self.assertEqual(Comment._meta.verbose_name, "歌曲评论")
        self.assertEqual(Comment._meta.db_table, "music_comment")
        self.assertEqual(Comment._meta.indexes[0].fields, ["song", "-created_at", "-id"])

    def test_spec_bindings_entity_and_migration_mapping(self):
        root = settings.BASE_DIR.parent / "specs/music/system"
        entity = json.loads((root / "entities.schema.json").read_text(encoding="utf-8"))["$defs"]["Comment"]
        plan = json.loads((root / "migration-plan.json").read_text(encoding="utf-8"))["entities"]["Comment"]
        self.assertEqual(set(entity["properties"]), {field.attname for field in Comment._meta.fields})
        self.assertEqual(set(plan["columns"]), set(entity["properties"]))
        self.assertEqual(plan["table"], Comment._meta.db_table)
        self.assertEqual(plan["columns"]["content"]["max_length"], Comment._meta.get_field("content").max_length)
        for field in ("user_id", "song_id"):
            self.assertEqual(plan["columns"][field]["on_delete"], "PROTECT")
        self.assertEqual(plan["indexes"]["ix_comment_song_created_id"], ["song_id", "-created_at", "-id"])
        bindings = json.loads((root / "api-bindings.json").read_text(encoding="utf-8"))["bindings"]
        for operation, method, route in (("listComments", "GET", "/api/v1/songs/{id}/comments/"),
                                         ("createComment", "POST", "/api/v1/songs/{id}/comments/"),
                                         ("deleteComment", "DELETE", "/api/v1/comments/{id}/")):
            binding = next(entry for entry in bindings if entry["operation_id"] == operation)
            self.assertEqual((binding["method"], binding["path"]), (method, route))
            self.assertEqual(self.openapi["paths"][route][method.lower()]["operationId"], operation)
            self.assertEqual(binding["csrf"], method != "GET")


class CommentAdminTests(TestCase):
    setUpTestData = classmethod(CommentApiTests.setUpTestData.__func__)
    comment = CommentApiTests.comment

    def setUp(self):
        CommentApiTests.setUp(self)
        self.client.force_login(self.admin)
        self.entry = self.comment()
        self.list_url = "/admin/music/comment/"
        self.change_url = f"{self.list_url}{self.entry.pk}/change/"
        self.delete_url = f"{self.list_url}{self.entry.pk}/delete/"

    def test_admin_index_and_search_and_date_filter(self):
        self.assertContains(self.client.get("/admin/"), self.list_url)
        for query in (self.user.username, self.song.title, self.entry.content):
            response = self.client.get(self.list_url, {"q": query})
            self.assertEqual(list(response.context["cl"].queryset), [self.entry])
        response = self.client.get(self.list_url, {"created_at__gte": "2099-01-01T00:00:00Z"})
        self.assertEqual(response.context["cl"].queryset.count(), 0)

    def test_readonly_view_and_add_change_posts_forbidden(self):
        self.assertEqual(self.client.get(self.change_url).status_code, 200)
        self.assertEqual(self.client.get(self.list_url + "add/").status_code, 403)
        response = self.client.post(self.change_url, {"content": "tampered", "user": self.other.pk}, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 403)
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.content, self.entry.user_id), ("test comment", self.user.pk))

    def test_delete_requires_confirmation_csrf_and_logs(self):
        self.assertEqual(self.client.get(self.delete_url).status_code, 200)
        self.assertTrue(Comment.objects.filter(pk=self.entry.pk).exists())
        self.assertEqual(self.client.post(self.delete_url, {"post": "yes"}).status_code, 403)
        response = self.client.post(self.delete_url, {"post": "yes"}, HTTP_X_CSRFTOKEN=self.token)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Comment.objects.filter(pk=self.entry.pk).exists())
        self.assertTrue(LogEntry.objects.filter(user=self.admin, object_id=str(self.entry.pk), action_flag=DELETION).exists())

    def test_staff_view_permission_does_not_grant_delete(self):
        self.other.is_staff = True
        self.other.save(update_fields=["is_staff"])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.other.user_permissions.add(Permission.objects.get(codename="view_comment"))
        self.assertEqual(self.client.get(self.change_url).status_code, 200)
        self.assertEqual(self.client.get(self.delete_url).status_code, 403)
        self.assertEqual(self.client.post(self.delete_url, {"post": "yes"}, HTTP_X_CSRFTOKEN=self.token).status_code, 403)
        self.other.user_permissions.add(Permission.objects.get(codename="delete_comment"))
        self.assertEqual(self.client.post(self.delete_url, {"post": "yes"}, HTTP_X_CSRFTOKEN=self.token).status_code, 302)


class CommentMigrationTests(TransactionTestCase):
    def test_0004_adds_only_comment_and_roundtrips_existing_data(self):
        migration = importlib.import_module("music.migrations.0004_comment").Migration
        self.assertEqual(migration.dependencies, [("music", "0003_recommendation_scene")])
        self.assertEqual(len(migration.operations), 1)
        self.assertIsInstance(migration.operations[0], migrations.CreateModel)
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([("music", "0003_recommendation_scene")])
            old_apps = executor.loader.project_state([("music", "0003_recommendation_scene")]).apps
            user = old_apps.get_model("music", "User").objects.create(username="migration_comment_user")
            song = old_apps.get_model("music", "Song").objects.create(title="preserved", artist="TEST", duration_ms=1000, mime="audio/wav")
            tables = set(connection.introspection.table_names())
            executor = MigrationExecutor(connection)
            executor.migrate([("music", "0004_comment")])
            self.assertEqual(set(connection.introspection.table_names()) - tables, {"music_comment"})
            self.assertEqual(Song.objects.get(pk=song.pk).title, "preserved")
            comment = Comment.objects.create(user_id=user.pk, song_id=song.pk, content="migrated")
            self.assertIsNotNone(comment.created_at)
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, "music_comment")
            self.assertEqual(constraints["ix_comment_song_created_id"]["columns"], ["song_id", "created_at", "id"])
            executor = MigrationExecutor(connection)
            executor.migrate([("music", "0003_recommendation_scene")])
            self.assertNotIn("music_comment", connection.introspection.table_names())
            self.assertEqual(Song.objects.get(pk=song.pk).title, "preserved")
        finally:
            MigrationExecutor(connection).migrate([("music", "0004_comment")])
