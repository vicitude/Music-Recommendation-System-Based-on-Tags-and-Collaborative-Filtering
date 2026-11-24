import json
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from music.models import Behavior, Rating, Song, SongTag, Tag, User


class HistoryApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="history_owner")
        cls.other = User.objects.create_user(username="history_other")
        cls.now = timezone.now().replace(microsecond=0)
        cls.songs = [Song.objects.create(
            title=f"History {number}", artist="History artist", duration_ms=100000,
            mime="audio/wav", active=True, file_path="private/history.wav",
            source_name="TEST_METADATA_ONLY", source_url="https://example.org/source",
            license_name="UNVERIFIED_TEST_METADATA", license_url="https://example.org/license",
        ) for number in range(23)]
        cls.openapi = json.loads(
            (settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8")
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.user)

    def event(self, song, *, user=None, when=None, kind=Behavior.PLAY):
        return Behavior.objects.create(
            event_id=uuid4(), listening_session_id=uuid4(), user=user or self.user,
            song=song, kind=kind, occurred_at=when or self.now,
            position_ms=0, listened_ms=0, effective_ms=0, origin=(user or self.user).origin,
        )

    def history(self, query=""):
        return self.client.get("/api/v1/me/history/" + query)

    def test_anonymous_and_inactive_rejected(self):
        self.client.logout()
        response = self.history()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error_code"], "AUTH_REQUIRED")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.force_login(self.user)
        self.assertEqual(self.history().status_code, 401)

    def test_only_owned_play_events_contribute(self):
        self.event(self.songs[0], when=self.now - timedelta(days=2))
        self.event(self.songs[0], user=self.other, when=self.now + timedelta(days=1))
        self.event(self.songs[1], user=self.other)
        self.event(self.songs[2], kind=Behavior.COMPLETE)
        self.event(self.songs[3], kind=Behavior.SKIP)
        self.event(self.songs[0], kind=Behavior.COMPLETE)
        response = self.history()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        item = response.json()["items"][0]
        self.assertEqual(item["song"]["id"], self.songs[0].id)
        self.assertEqual(item["last_played_at"], (self.now - timedelta(days=2)).isoformat().replace("+00:00", "Z"))

    def test_deduplicated_latest_play_and_stable_song_id_order(self):
        self.event(self.songs[3], when=self.now + timedelta(hours=1))
        self.event(self.songs[0], when=self.now - timedelta(days=1))
        self.event(self.songs[0])
        self.event(self.songs[1])
        self.event(self.songs[2], when=self.now - timedelta(hours=1))
        for _ in range(2):
            body = self.history().json()
            self.assertEqual(body["total"], 4)
            self.assertEqual([item["song"]["id"] for item in body["items"]],
                             [self.songs[3].id] + [song.id for song in self.songs[:3]])
            self.assertEqual(body["items"][1]["last_played_at"], self.now.isoformat().replace("+00:00", "Z"))

    def test_only_accepted_play_is_visible_and_retry_does_not_duplicate(self):
        payload = {
            "event_id": str(uuid4()), "listening_session_id": str(uuid4()),
            "song_id": self.songs[0].id, "kind": "PLAY", "position_ms": 1, "listened_ms": 0,
        }
        rejected = self.client.post("/api/v1/behaviors/", payload, format="json")
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(Behavior.objects.exists())
        self.assertEqual(self.history().json()["items"], [])
        payload["position_ms"] = 0
        self.assertEqual(self.client.post("/api/v1/behaviors/", payload, format="json").status_code, 201)
        before = self.history().json()
        self.assertEqual(before["total"], 1)
        self.assertEqual(self.client.post("/api/v1/behaviors/", payload, format="json").status_code, 200)
        self.assertEqual(Behavior.objects.count(), 1)
        self.assertEqual(self.history().json(), before)

    def test_fixed_twenty_pagination(self):
        for song in self.songs:
            self.event(song)
        body = self.history().json()
        self.assertEqual((body["total"], body["page"], body["page_size"], len(body["items"])), (23, 1, 20, 20))
        second = self.history("?page=2").json()
        self.assertEqual([item["song"]["id"] for item in second["items"]], [song.id for song in self.songs[20:]])
        self.assertEqual((second["page"], second["page_size"], second["total"]), (2, 20, 23))
        self.assertEqual(self.history("?page=3").status_code, 404)

    def test_empty_first_page_and_out_of_range(self):
        self.assertEqual(self.history().json(), {"items": [], "total": 0, "page": 1, "page_size": 20})
        response = self.history("?page=2")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error_code"], "NOT_FOUND")

    def test_invalid_and_unsupported_query_parameters(self):
        for query in ("page=0", "page=-1", "page=abc", "page=1.5", "page=", "page_size=0",
                      "page_size=20", "page_size=1", "page_size=101", "page_size=abc",
                      "page=1&page=2", "page_size=1&page_size=2",
                      "user_id=1", "page=" + "9" * 21):
            with self.subTest(query=query):
                response = self.history("?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error_code"], "VALIDATION_ERROR")

    def test_unpublished_filtered_before_count_and_pagination(self):
        self.event(self.songs[0])
        self.songs[0].active = False
        self.songs[0].save(update_fields=["active"])
        self.event(self.songs[1], when=self.now - timedelta(days=1))
        body = self.history().json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["song"]["id"], self.songs[1].id)
        self.assertEqual(self.history("?page=2").status_code, 404)

    def test_full_public_song_contract_and_private_fields_absent(self):
        self.event(self.songs[0])
        tag = Tag.objects.create(name="History style", kind="STYLE")
        hidden_tag = Tag.objects.create(name="Hidden style", kind="STYLE", active=False)
        SongTag.objects.create(song=self.songs[0], tag=tag)
        SongTag.objects.create(song=self.songs[0], tag=hidden_tag)
        Rating.objects.create(user=self.user, song=self.songs[0], score=4)
        Rating.objects.create(user=self.other, song=self.songs[0], score=1)
        response = self.history()
        self.assertEqual(response.status_code, 200)
        Draft202012Validator(
            {"$ref": "#/components/schemas/HistoryPage", "components": self.openapi["components"]},
            format_checker=FormatChecker(),
        ).validate(response.json())
        song = response.json()["items"][0]["song"]
        self.assertEqual(song, self.client.get(f"/api/v1/songs/{self.songs[0].id}/").json())
        self.assertEqual(song["current_rating"], 4)
        self.assertEqual([entry["id"] for entry in song["tags"]], [tag.id])
        self.assertNotIn("file_path", song)
        self.assertNotIn("private/history.wav", response.content.decode())

    def test_get_is_read_only_and_writes_are_rejected(self):
        self.event(self.songs[0])
        before = {model._meta.label: list(model.objects.order_by("pk").values())
                  for model in connection_models()}
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.history().status_code, 200)
            self.assertEqual(self.history().status_code, 200)
        writes = [entry["sql"] for entry in queries if entry["sql"].lstrip().split()[0].upper()
                  in {"INSERT", "UPDATE", "DELETE", "REPLACE"}]
        self.assertEqual(writes, [])
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)("/api/v1/me/history/", {}, format="json").status_code, 405)
        after = {model._meta.label: list(model.objects.order_by("pk").values())
                 for model in connection_models()}
        self.assertEqual(after, before)


def connection_models():
    from django.apps import apps

    return apps.get_app_config("music").get_models()
