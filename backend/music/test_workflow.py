import io
import json
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.test import TestCase
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from music.models import Behavior, Favorite, Playlist, PlaylistSong, Song, SongTag, Tag, User


class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.base = datetime(2026, 10, 30, 4, tzinfo=timezone.utc)
        cls.tags = [Tag.objects.create(name=name, kind=kind) for name, kind in (
            ("合成风格", Tag.STYLE), ("合成情绪", Tag.MOOD), ("合成场景", Tag.SCENE),
        )]
        cls.songs = [Song.objects.create(
            title=f"SYNTHETIC_WORKFLOW_{number}", artist="TEST_ONLY_NOT_REAL_MUSIC",
            duration_ms=10000, mime="audio/wav", file_path=f"songs/workflow-{number}.wav",
            active=True, playback_allowed=True, checked_at=cls.base - timedelta(days=1),
            source_name="IN_MEMORY_SYNTHETIC_TEST", source_url="https://example.org/test-source",
            license_name="TEST_FIXTURE_NOT_A_LICENSE", license_url="https://example.org/test-license",
        ) for number in range(4)]
        Song.objects.update(created_at=cls.base - timedelta(days=1))
        SongTag.objects.bulk_create([SongTag(song=song, tag=tag) for song in cls.songs for tag in cls.tags])
        cls.api = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.now = self.base
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        clock = patch("music.api.middleware.timezone.now", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        files = patch("pathlib.Path.is_file", return_value=True)
        files.start()
        self.addCleanup(files.stop)

    def write(self, method, path, payload=None, *, client=None, token=None):
        return (client or self.client).generic(
            method, path, "" if payload is None else json.dumps(payload),
            content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token,
        )

    def schema(self, response, name, status=200):
        self.assertEqual(response.status_code, status, response.content)
        Draft202012Validator(
            {"$ref": f"#/components/schemas/{name}", "components": self.api["components"]},
            format_checker=FormatChecker(),
        ).validate(response.json())
        return response.json()

    def account(self, username="workflow_listener"):
        credentials = {"username": username, "password": "Nebula!Test-8347"}
        registered = self.schema(self.write("POST", "/api/v1/auth/register/", credentials), "User", 201)
        self.assertFalse(User.objects.get(id=registered["id"]).is_staff)
        self.schema(self.write("POST", "/api/v1/auth/login/", credentials), "User")
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.schema(self.client.get("/api/v1/me/"), "User")
        return registered["id"]

    def choose(self, ids=None):
        ids = [tag.id for tag in self.tags] if ids is None else ids
        result = self.schema(self.write("PUT", "/api/v1/me/interests/", {"tag_ids": ids}), "Interests")
        self.assertEqual(result["tag_ids"], ids)
        self.assertTrue(result["onboarding_completed"])

    def event(self, song_id, session_id, kind, elapsed=0):
        return {"event_id": str(uuid4()), "song_id": song_id, "listening_session_id": str(session_id),
                "kind": kind, "position_ms": elapsed, "listened_ms": elapsed}

    def test_wf_m_001_registered_listener_full_api_workflow(self):
        owner = self.account()
        self.choose()
        catalog = self.schema(self.client.get("/api/v1/songs/?page=1&page_size=20"), "SongPage")
        self.assertEqual(catalog["count"], 4)
        snapshot = self.schema(self.client.get("/api/v1/recommendations/daily/"), "Daily")
        self.assertEqual(snapshot["revision"], 1)
        self.assertEqual(len(snapshot["items"]), 4)
        item = snapshot["items"][0]
        self.assertEqual(item["source"], "CONTENT")
        self.assertTrue(set(item["evidence"]["tag_ids"]) <= {tag.id for tag in self.tags})
        for tag in Tag.objects.filter(id__in=item["evidence"]["tag_ids"]):
            self.assertIn(tag.name, item["explanation"])
        song_id = item["song_id"]
        detail = self.schema(self.client.get(f"/api/v1/songs/{song_id}/"), "Song")
        self.assertTrue(detail["playable"])
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00" * 160000)
        data = buffer.getvalue()
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=len(data))), patch.object(Path, "open", side_effect=lambda *args, **kwargs: io.BytesIO(data)):
            response = self.client.get(detail["stream_url"], HTTP_RANGE="bytes=0-43")
            try:
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response["Content-Range"], f"bytes 0-43/{len(data)}")
                self.assertEqual(b"".join(response.streaming_content), data[:44])
            finally:
                response.close()
        session_id = uuid4()
        self.now += timedelta(seconds=1)
        self.schema(self.write("POST", "/api/v1/behaviors/", self.event(song_id, session_id, "PLAY")), "BehaviorResponse", 201)
        self.now += timedelta(seconds=8)
        completed = self.event(song_id, session_id, "COMPLETE", 8000)
        saved = self.schema(self.write("POST", "/api/v1/behaviors/", completed), "BehaviorResponse", 201)
        repeated = self.schema(self.write("POST", "/api/v1/behaviors/", completed), "BehaviorResponse")
        self.assertEqual(saved, repeated)
        self.assertEqual(saved["effective_ms"], 8000)
        self.assertEqual(Behavior.objects.filter(user_id=owner).count(), 2)
        self.now += timedelta(seconds=1)
        self.assertEqual(self.write("PUT", f"/api/v1/favorites/{song_id}/").status_code, 204)
        favorites = self.schema(self.client.get("/api/v1/favorites/"), "SongPage")
        self.assertEqual([song["id"] for song in favorites["results"]], [song_id])
        playlist = self.schema(self.write("POST", "/api/v1/playlists/", {"name": "Workflow list"}), "Playlist", 201)
        playlist_url = f'/api/v1/playlists/{playlist["id"]}/'
        member_url = playlist_url + f"songs/{song_id}/"
        self.assertEqual(self.write("PUT", member_url).status_code, 204)
        self.assertEqual(self.write("PUT", member_url).status_code, 204)
        self.assertEqual(PlaylistSong.objects.filter(playlist_id=playlist["id"]).count(), 1)
        listed = self.schema(self.client.get(playlist_url), "PlaylistDetail")
        self.assertEqual([song["id"] for song in listed["songs"]], [song_id])
        renamed = self.schema(self.write("PATCH", playlist_url, {"name": "Renamed mix"}), "Playlist")
        self.assertEqual(renamed["name"], "Renamed mix")
        self.assertEqual(self.write("DELETE", member_url).status_code, 204)
        self.assertEqual(self.schema(self.client.get(playlist_url), "PlaylistDetail")["songs"], [])
        self.assertEqual(self.write("DELETE", playlist_url).status_code, 204)
        self.assertFalse(Playlist.objects.filter(id=playlist["id"]).exists())
        self.now += timedelta(seconds=1)
        filtered = self.schema(self.client.get("/api/v1/recommendations/daily/"), "Daily")
        self.assertNotIn(song_id, [entry["song_id"] for entry in filtered["items"]])
        limited = self.write("POST", "/api/v1/recommendations/daily/refresh/")
        self.assertEqual(self.schema(limited, "Error", 429)["error_code"], "RATE_LIMITED")
        self.assertGreater(int(limited["Retry-After"]), 0)
        self.now = self.base + timedelta(seconds=61)
        updated = self.schema(self.write("POST", "/api/v1/recommendations/daily/refresh/"), "Daily")
        self.assertEqual(updated["revision"], 2)
        self.assertNotIn(song_id, [entry["song_id"] for entry in updated["items"]])
        self.assertEqual(self.write("DELETE", f"/api/v1/favorites/{song_id}/").status_code, 204)
        self.assertFalse(Favorite.objects.filter(user_id=owner, song_id=song_id).exists())
        self.assertEqual(self.write("POST", "/api/v1/auth/logout/").status_code, 204)
        self.assertEqual(self.schema(self.client.get("/api/v1/me/"), "Error", 401)["error_code"], "AUTH_REQUIRED")
        self.assertEqual(self.client.get(detail["stream_url"]).status_code, 401)

    def test_wf_m_002_skip_interests_uses_honest_hot_fallback(self):
        self.account()
        self.choose([])
        snapshot = self.schema(self.client.get("/api/v1/recommendations/daily/"), "Daily")
        self.assertEqual(len(snapshot["items"]), 4)
        for item in snapshot["items"]:
            self.assertEqual(item["source"], "HOT")
            self.assertEqual(item["explanation"], "热门歌曲，供你探索")
            self.assertEqual(item["evidence"], {"tag_ids": [], "neighbor_count": 0})

    def test_wf_m_003_revoked_permission_removes_existing_recommendation(self):
        self.account()
        self.choose()
        snapshot = self.schema(self.client.get("/api/v1/recommendations/daily/"), "Daily")
        song_id = snapshot["items"][0]["song_id"]
        Song.objects.filter(id=song_id).update(playback_allowed=False)
        filtered = self.schema(self.client.get("/api/v1/recommendations/daily/"), "Daily")
        self.assertEqual(filtered["revision"], snapshot["revision"])
        self.assertNotIn(song_id, [item["song_id"] for item in filtered["items"]])
        detail = self.schema(self.client.get(f"/api/v1/songs/{song_id}/"), "Song")
        self.assertFalse(detail["playable"])
        self.assertIsNone(detail["stream_url"])
        self.assertEqual(self.schema(self.client.get(f"/api/v1/songs/{song_id}/stream/"), "Error", 403)["error_code"], "PERMISSION_DENIED")

    def test_wf_m_004_private_writes_and_events_remain_owner_bound(self):
        owner = self.account()
        playlist = self.schema(self.write("POST", "/api/v1/playlists/", {"name": "Owner only"}), "Playlist", 201)
        song_id = self.songs[0].id
        played = self.event(song_id, uuid4(), "PLAY")
        self.schema(self.write("POST", "/api/v1/behaviors/", played), "BehaviorResponse", 201)
        other = APIClient(enforce_csrf_checks=True)
        other_token = other.get("/api/v1/auth/csrf/").json()["csrf_token"]
        credentials = {"username": "workflow_other", "password": "Orbit!Testing-9371"}
        self.schema(self.write("POST", "/api/v1/auth/register/", credentials, client=other, token=other_token), "User", 201)
        self.schema(self.write("POST", "/api/v1/auth/login/", credentials, client=other, token=other_token), "User")
        other_token = other.get("/api/v1/auth/csrf/").json()["csrf_token"]
        url = f'/api/v1/playlists/{playlist["id"]}/'
        self.assertEqual(other.get(url).status_code, 404)
        self.assertEqual(self.write("PATCH", url, {"name": "hijack"}, client=other, token=other_token).status_code, 404)
        self.assertEqual(self.write("PUT", url + f"songs/{song_id}/", client=other, token=other_token).status_code, 404)
        collision = self.write("POST", "/api/v1/behaviors/", played, client=other, token=other_token)
        self.assertEqual(self.schema(collision, "Error", 409)["error_code"], "EVENT_CONFLICT")
        denied = other.put(f"/api/v1/favorites/{song_id}/", "", content_type="application/json")
        self.assertEqual(self.schema(denied, "Error", 403)["error_code"], "CSRF_FAILED")
        self.assertFalse(Favorite.objects.exists())
        self.assertEqual(Playlist.objects.get(id=playlist["id"]).user_id, owner)
        self.assertEqual(Behavior.objects.count(), 1)
