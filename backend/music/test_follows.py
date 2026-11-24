import importlib
import json
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import CASCADE, PROTECT, ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.test import APIClient

from music import follows
from music.api.errors import ApiError
from music.models import Comment, Follow, Song, User


class FollowApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="follow_source", email="secret@example.org")
        cls.target = User.objects.create_user(username="follow_target", is_staff=True)
        cls.other = User.objects.create_user(username="follow_other")
        cls.inactive = User.objects.create_user(username="follow_inactive", is_active=False)
        cls.openapi = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.client.force_login(self.user)
        self.url = f"/api/v1/users/{self.target.pk}/"

    def write(self, method="PUT", user_id=None, body="", token=True, query="", content_type="application/json"):
        headers = {"HTTP_X_CSRFTOKEN": self.token} if token else {}
        return self.client.generic(method, f"/api/v1/users/{user_id or self.target.pk}/follow/{query}", body,
                                   content_type=content_type, **headers)

    def assert_error(self, response, status, code, details=None):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error_code"], code)
        self.assertEqual(response["Cache-Control"], "private,no-store")
        if details is not None:
            self.assertEqual(response.json()["details"], details)

    def validate_schema(self, schema, value):
        Draft202012Validator({"$ref": f"#/components/schemas/{schema}", "components": self.openapi["components"]}).validate(value)

    def test_summary_exact_fields_and_self(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": self.target.pk, "username": self.target.username,
                         "following_count": 0, "follower_count": 0, "is_following": False, "is_self": False})
        self.validate_schema("UserSummary", response.json())
        self.assertTrue(self.client.get(f"/api/v1/users/{self.user.pk}/").json()["is_self"])

    def test_follow_idempotent_and_authoritative(self):
        first = self.write()
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["is_following"])
        self.assertEqual(first.json()["follower_count"], 1)
        created_at = Follow.objects.get().created_at
        self.assertEqual(self.write().json(), first.json())
        self.assertEqual(Follow.objects.get().created_at, created_at)
        self.assertEqual(self.client.get(self.url).json(), first.json())

    def test_unfollow_idempotent(self):
        self.write()
        response = self.write("DELETE")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_following"])
        self.assertEqual(response.json()["follower_count"], 0)
        self.assertEqual(self.write("DELETE").json(), response.json())
        self.assertFalse(Follow.objects.exists())

    def test_directions_independent(self):
        Follow.objects.create(source=self.target, target=self.user)
        self.assertFalse(self.client.get(self.url).json()["is_following"])
        self.write()
        self.assertEqual(Follow.objects.count(), 2)
        self.write("DELETE")
        self.assertTrue(Follow.objects.filter(source=self.target, target=self.user).exists())

    def test_self_rejected_for_both_methods(self):
        for method in ("PUT", "DELETE"):
            self.assert_error(self.write(method, self.user.pk), 400, "VALIDATION_ERROR", ["id"])
        self.assertFalse(Follow.objects.exists())

    def test_missing_and_inactive_indistinguishable(self):
        for user_id in (999999, self.inactive.pk):
            for suffix in ("", "following/", "followers/"):
                self.assert_error(self.client.get(f"/api/v1/users/{user_id}/{suffix}"), 404, "NOT_FOUND", [])
            for method in ("PUT", "DELETE"):
                self.assert_error(self.write(method, user_id), 404, "NOT_FOUND", [])

    def test_anonymous_requires_login_all_endpoints(self):
        self.client.logout()
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        for suffix in ("", "following/", "followers/"):
            self.assert_error(self.client.get(self.url + suffix), 401, "AUTH_REQUIRED")
        for method in ("PUT", "DELETE"):
            self.assert_error(self.write(method), 401, "AUTH_REQUIRED")

    def test_inactive_session_rejected(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assert_error(self.client.get(self.url), 401, "AUTH_REQUIRED")
        self.assert_error(self.write(), 401, "AUTH_REQUIRED")

    def test_csrf_required_for_both_methods(self):
        for method in ("PUT", "DELETE"):
            self.assert_error(self.write(method, token=False), 403, "CSRF_FAILED")
        self.assertFalse(Follow.objects.exists())

    def test_no_body_and_json_content_type(self):
        for method in ("PUT", "DELETE"):
            for body in ("{}", "null", '{"source":999}', "{"):
                self.assert_error(self.write(method, body=body), 400, "VALIDATION_ERROR", ["request"])
            self.assert_error(self.write(method, content_type="text/plain"), 415, "VALIDATION_ERROR")
        for suffix in ("", "following/", "followers/"):
            self.assert_error(self.client.generic("GET", self.url + suffix, "{}", content_type="application/json"),
                              400, "VALIDATION_ERROR", ["request"])

    def test_unknown_and_duplicate_query_rejected(self):
        for query in ("?source=1", "?page=1", "?page=1&page=2"):
            self.assert_error(self.write(query=query), 400, "VALIDATION_ERROR")
            self.assert_error(self.client.get(self.url + query), 400, "VALIDATION_ERROR")
        for suffix in ("following/", "followers/"):
            for query in ("?page_size=2", "?page=1&page=2", "?email=x"):
                self.assert_error(self.client.get(self.url + suffix + query), 400, "VALIDATION_ERROR")

    def test_empty_first_page_and_out_of_range(self):
        for suffix in ("following/", "followers/"):
            response = self.client.get(self.url + suffix)
            self.assertEqual(response.json(), {"count": 0, "page": 1, "page_size": 20, "results": []})
            self.validate_schema("UserRelationPage", response.json())
            self.assert_error(self.client.get(self.url + suffix + "?page=2"), 404, "NOT_FOUND", ["page"])

    def test_invalid_pages(self):
        for page in ("0", "-1", "abc", "1.5", "", "9" * 21):
            self.assert_error(self.client.get(self.url + "following/?page=" + page), 400, "VALIDATION_ERROR", ["page"])

    def test_pagination_stable_ties_and_fixed_size(self):
        members = [User.objects.create_user(username=f"page_{number}") for number in range(23)]
        for member in members:
            Follow.objects.create(source=self.target, target=member)
        Follow.objects.update(created_at=timezone.now())
        first = self.client.get(self.url + "following/").json()
        second = self.client.get(self.url + "following/?page=2").json()
        self.assertEqual((first["count"], first["page_size"], len(first["results"]), len(second["results"])), (23, 20, 20, 3))
        self.assertEqual([member["id"] for member in first["results"] + second["results"]], [member.pk for member in reversed(members)])
        self.validate_schema("UserRelationPage", first)

    def test_lists_viewer_flags_and_privacy(self):
        Follow.objects.create(source=self.user, target=self.target)
        Follow.objects.create(source=self.other, target=self.target)
        Follow.objects.create(source=self.user, target=self.other)
        response = self.client.get(self.url + "followers/").json()
        self.assertEqual(response["results"], [
            {"id": self.other.pk, "username": self.other.username, "is_following": True, "is_self": False},
            {"id": self.user.pk, "username": self.user.username, "is_following": False, "is_self": True},
        ])
        self.validate_schema("UserRelationPage", response)
        self.assertNotIn("secret@example.org", json.dumps(response))

    def test_inactive_edges_hidden_and_restored(self):
        Follow.objects.create(source=self.target, target=self.other)
        Follow.objects.create(source=self.other, target=self.target)
        User.objects.filter(pk=self.other.pk).update(is_active=False)
        body = self.client.get(self.url).json()
        self.assertEqual((body["following_count"], body["follower_count"]), (0, 0))
        for suffix in ("following/", "followers/"):
            self.assertEqual(self.client.get(self.url + suffix).json()["count"], 0)
        self.assertEqual(Follow.objects.count(), 2)
        User.objects.filter(pk=self.other.pk).update(is_active=True)
        body = self.client.get(self.url).json()
        self.assertEqual((body["following_count"], body["follower_count"]), (1, 1))

    def test_cache_control_for_success_and_errors(self):
        for suffix in ("", "following/", "followers/"):
            self.assertEqual(self.client.get(self.url + suffix)["Cache-Control"], "private,no-store")
        self.assertEqual(self.write()["Cache-Control"], "private,no-store")
        self.assertEqual(self.write("DELETE")["Cache-Control"], "private,no-store")
        self.assert_error(self.client.post(self.url, {}, format="json", HTTP_X_CSRFTOKEN=self.token), 405, "VALIDATION_ERROR")
        self.assert_error(self.client.get("/api/v1/users/not-an-id/"), 404, "NOT_FOUND")

    def test_constraints_unique_and_no_self(self):
        Follow.objects.create(source=self.user, target=self.target)
        for target in (self.target, self.user):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Follow.objects.create(source=self.user, target=target)
        self.assertEqual(Follow.objects.count(), 1)

    def test_new_cascade_does_not_change_comment_protection(self):
        Follow.objects.create(source=self.user, target=self.other)
        self.other.delete()
        self.assertFalse(Follow.objects.exists())
        self.assertIs(Follow._meta.get_field("source").remote_field.on_delete, CASCADE)
        self.assertIs(Follow._meta.get_field("target").remote_field.on_delete, CASCADE)
        self.assertIs(Comment._meta.get_field("user").remote_field.on_delete, PROTECT)
        song = Song.objects.create(title="test", artist="test", duration_ms=1, mime="audio/wav")
        Comment.objects.create(user=self.user, song=song, content="protected")
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_music_data_unchanged_and_reads_no_writes(self):
        models = [model for model in apps.get_app_config("music").get_models() if model is not Follow]
        before = {model._meta.label: list(model.objects.order_by("pk").values()) for model in models}
        self.write()
        with CaptureQueriesContext(connection) as queries:
            for suffix in ("", "following/", "followers/"):
                self.assertEqual(self.client.get(self.url + suffix).status_code, 200)
        self.assertFalse(any(entry["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"} for entry in queries))
        self.write("DELETE")
        self.assertEqual(before, {model._meta.label: list(model.objects.order_by("pk").values()) for model in models})

    def test_transaction_rechecks_stale_source_and_target(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(ApiError) as error:
            follows.change_follow(self.user, self.target.pk, True)
        self.assertEqual(error.exception.error_code, "AUTH_REQUIRED")
        User.objects.filter(pk=self.user.pk).update(is_active=True)
        User.objects.filter(pk=self.target.pk).update(is_active=False)
        with self.assertRaises(ApiError) as error:
            follows.change_follow(self.user, self.target.pk, True)
        self.assertEqual(error.exception.error_code, "NOT_FOUND")
        self.assertFalse(Follow.objects.exists())

    def test_unrelated_integrity_failure_not_silenced(self):
        with patch("music.follows.Follow.objects.get_or_create", side_effect=IntegrityError("test-only")):
            with self.assertRaises(IntegrityError):
                follows.change_follow(self.user, self.target.pk, True)
        self.assertFalse(Follow.objects.exists())

    def test_migration_and_indexes(self):
        migration = importlib.import_module("music.migrations.0005_follow").Migration
        self.assertIn(("music", "0004_comment"), migration.dependencies)
        self.assertEqual([type(operation).__name__ for operation in migration.operations], ["CreateModel"])
        self.assertEqual(Follow._meta.db_table, "music_follow")
        self.assertEqual([index.fields for index in Follow._meta.indexes],
                         [["source", "-created_at", "-id"], ["target", "-created_at", "-id"]])
