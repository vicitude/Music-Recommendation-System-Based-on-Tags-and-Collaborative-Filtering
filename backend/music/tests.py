import json
import random
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from rest_framework.test import APIClient

from music.api.serializers import SongSerializer
from music.models import Favorite, Playlist, PlaylistSong, Song, SongTag, Tag, User, UserTag


class BasicApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "Lunar!Melody-7392 "
        cls.user = User.objects.create_user(username="listener", password=cls.password)
        cls.other = User.objects.create_user(username="another", password=cls.password)
        cls.tags = [Tag.objects.create(name=f"Tag {number}", kind="STYLE") for number in range(6)]
        cls.song = Song.objects.create(
            title="Morning Light", artist="Study Artist", duration_ms=100000,
            mime="audio/wav", active=True, source_name="TEST_METADATA_ONLY",
            source_url="https://example.org/source", license_name="UNVERIFIED_TEST_METADATA",
            license_url="https://example.org/license",
        )
        SongTag.objects.create(song=cls.song, tag=cls.tags[0])
        cls.playlist = Playlist.objects.create(user=cls.user, name="Private mix")
        cls.openapi = json.loads((settings.BASE_DIR.parent / "specs/music/system/openapi.yaml").read_text(encoding="utf-8"))

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]

    def write(self, method, path, data=None, client=None, token=None):
        client = client or self.client
        body = "" if data is None else json.dumps(data)
        return client.generic(
            method, path, body, content_type="application/json",
            HTTP_X_CSRFTOKEN=token or self.token,
        )

    def sign_in(self, user=None):
        self.client.force_login(user or self.user)

    def assert_error(self, response, status, code, details=None):
        self.assertEqual(response.status_code, status, response.content)
        body = response.json()
        self.assertEqual(body["error_code"], code)
        self.assertEqual(body["request_id"], response["X-Request-ID"])
        UUID(body["request_id"])
        self.assertEqual(response["X-Spec-Version"], "v0.1.0")
        self.assertEqual(body["details"], sorted(set(body["details"])))
        if details is not None:
            self.assertEqual(body["details"], details)
        self.assert_schema(response, "Error")

    def assert_schema(self, response, schema_name):
        validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{schema_name}", "components": self.openapi["components"]},
            format_checker=FormatChecker(),
        )
        validator.validate(response.json())

    def test_tc_m_001_register_login_and_logout(self):
        credentials = {"username": "  New_Listener  ", "password": self.password}
        response = self.write("POST", "/api/v1/auth/register/", credentials)
        self.assertEqual(response.status_code, 201)
        self.assert_schema(response, "User")
        registered = User.objects.get(username="new_listener")
        self.assertTrue(registered.check_password(self.password))
        self.assertFalse(registered.is_staff)
        self.assertEqual(registered.origin, "REAL")
        self.assertNotIn("sessionid", self.client.cookies)
        response = self.write("POST", "/api/v1/auth/login/", credentials)
        self.assertEqual(response.status_code, 200)
        self.assertIn("sessionid", self.client.cookies)
        self.assertTrue(self.client.cookies["sessionid"]["httponly"])
        response = self.client.get("/api/v1/me/")
        self.assert_schema(response, "User")
        self.assertEqual(response.json()["username"], "new_listener")
        self.assert_error(self.write("POST", "/api/v1/auth/logout/"), 403, "CSRF_FAILED")
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.assertEqual(self.write("POST", "/api/v1/auth/logout/").status_code, 204)
        self.assert_error(self.client.get("/api/v1/me/"), 401, "AUTH_REQUIRED")

    def test_duplicate_username_is_case_insensitive(self):
        response = self.write("POST", "/api/v1/auth/register/", {"username": " LISTENER ", "password": self.password})
        self.assert_error(response, 409, "USERNAME_TAKEN", ["username"])

    def test_auth_failures_do_not_disclose_user_existence(self):
        bodies = []
        for username in ["listener", "does_not_exist"]:
            response = self.write("POST", "/api/v1/auth/login/", {"username": username, "password": "incorrect"})
            self.assert_error(response, 401, "AUTH_FAILED")
            bodies.append({key: value for key, value in response.json().items() if key != "request_id"})
        self.assertEqual(bodies[0], bodies[1])

    def test_password_whitespace_is_preserved(self):
        response = self.write("POST", "/api/v1/auth/login/", {"username": "listener", "password": self.password.rstrip()})
        self.assert_error(response, 401, "AUTH_FAILED")

    def test_registration_rejects_invalid_types_and_extra_fields(self):
        invalid = [
            {"username": 1234, "password": self.password},
            {"username": "valid_name", "password": 12345678901},
            {"username": "valid_name", "password": self.password, "is_staff": True},
            {"username": "非英文", "password": self.password},
            {"username": "valid_name", "password": "1234567890"},
            [], None,
        ]
        original = User.objects.count()
        for data in invalid:
            with self.subTest(data_type=type(data).__name__):
                self.assert_error(self.write("POST", "/api/v1/auth/register/", data), 400, "VALIDATION_ERROR")
        self.assertEqual(User.objects.count(), original)

    def test_csrf_precedes_auth_on_existing_write_routes(self):
        routes = [
            ("POST", "/api/v1/auth/logout/"), ("PUT", "/api/v1/me/interests/"),
            ("PUT", f"/api/v1/favorites/{self.song.id}/"), ("POST", "/api/v1/playlists/"),
        ]
        for method, path in routes:
            with self.subTest(path=path):
                response = self.client.generic(method, path, "{}", content_type="application/json")
                self.assert_error(response, 403, "CSRF_FAILED")
                self.assert_error(self.write(method, path, {}), 401, "AUTH_REQUIRED")

    def test_inactive_account_loses_session_access(self):
        self.sign_in()
        User.objects.filter(id=self.user.id).update(is_active=False)
        self.assert_error(self.client.get("/api/v1/me/"), 401, "AUTH_REQUIRED")

    def test_api_method_and_route_errors_are_json(self):
        response = self.client.get("/api/v1/auth/register/")
        self.assert_error(response, 405, "VALIDATION_ERROR", ["method"])
        self.assertIn("POST", response["Allow"])
        self.assert_error(self.client.get("/api/v1/songs/not_an_integer/"), 404, "NOT_FOUND")

    def test_options_returns_allowed_methods_without_writing(self):
        response = self.client.options("/api/v1/playlists/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("POST", response["Allow"])
        self.assertEqual(Playlist.objects.count(), 1)

    def test_authenticated_write_still_requires_csrf(self):
        self.sign_in()
        response = self.client.post("/api/v1/playlists/", {"name": "Unauthorized"}, format="json")
        self.assert_error(response, 403, "CSRF_FAILED")
        self.assertEqual(Playlist.objects.count(), 1)

    def test_protected_reads_require_login(self):
        for path in ["/api/v1/me/", "/api/v1/me/interests/", "/api/v1/favorites/", "/api/v1/playlists/", f"/api/v1/playlists/{self.playlist.id}/"]:
            self.assert_error(self.client.get(path), 401, "AUTH_REQUIRED")

    def test_bad_json_content_type_and_body_limit(self):
        self.sign_in()
        path = "/api/v1/playlists/"
        response = self.client.post(path, "name=hello", content_type="text/plain", HTTP_X_CSRFTOKEN=self.token)
        self.assert_error(response, 415, "VALIDATION_ERROR", ["content_type"])
        response = self.client.post(path, '{"name":', content_type="application/json", HTTP_X_CSRFTOKEN=self.token)
        self.assert_error(response, 400, "VALIDATION_ERROR", ["request"])
        response = self.write("POST", path, {"name": "a" * 65536})
        self.assert_error(response, 400, "VALIDATION_ERROR", ["request"])
        response = self.write("POST", path, {"name": "a" * (3 * 1024 * 1024)})
        self.assert_error(response, 400, "VALIDATION_ERROR", ["request"])
        self.assert_error(self.write("POST", path), 400, "VALIDATION_ERROR", ["request"])

    def test_tc_m_003_interest_selection_and_skip(self):
        self.sign_in()
        tag_ids = [tag.id for tag in self.tags[:3]][::-1]
        response = self.write("PUT", "/api/v1/me/interests/", {"tag_ids": tag_ids})
        self.assertEqual(response.status_code, 200)
        self.assert_schema(response, "Interests")
        self.assertEqual(response.json()["tag_ids"], sorted(tag_ids))
        response = self.write("PUT", "/api/v1/me/interests/", {"tag_ids": []})
        self.assertEqual(response.json(), {"tag_ids": [], "onboarding_completed": True})

    def test_pt_m_007_interest_replacement_and_invalid_rollback(self):
        self.sign_in()
        generator = random.Random(42)
        active_ids = [tag.id for tag in self.tags]
        for _ in range(15):
            selection = generator.sample(active_ids, generator.choice([0, 3, 4, 5]))
            for repetition in range(2):
                response = self.write("PUT", "/api/v1/me/interests/", {"tag_ids": selection})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["tag_ids"], sorted(selection))
            self.assertEqual(UserTag.objects.filter(user=self.user).count(), len(selection))
        before = list(UserTag.objects.filter(user=self.user).order_by("tag_id").values_list("tag_id", flat=True))
        for selection in [[active_ids[0]], [active_ids[0]] * 3, [True, active_ids[1], active_ids[2]], [1.0, 2, 3], ["1", 2, 3], [99991, 99992, 99993]]:
            response = self.write("PUT", "/api/v1/me/interests/", {"tag_ids": selection})
            self.assert_error(response, 400, "VALIDATION_ERROR", ["tag_ids"])
            after = list(UserTag.objects.filter(user=self.user).order_by("tag_id").values_list("tag_id", flat=True))
            self.assertEqual(before, after)

    def test_inactive_tag_is_hidden_without_changing_onboarding(self):
        self.sign_in()
        self.write("PUT", "/api/v1/me/interests/", {"tag_ids": [tag.id for tag in self.tags[:3]]})
        Tag.objects.filter(id=self.tags[0].id).update(active=False)
        response = self.client.get("/api/v1/me/interests/")
        self.assertEqual(response.json()["tag_ids"], [tag.id for tag in self.tags[1:3]])
        self.assertTrue(response.json()["onboarding_completed"])
        self.assertEqual(UserTag.objects.filter(user=self.user).count(), 3)

    def test_song_search_tag_filter_and_order(self):
        response = self.client.get(f"/api/v1/songs/?q=morning&tag_id={self.tags[0].id}")
        self.assertEqual(response.status_code, 200)
        self.assert_schema(response, "SongPage")
        self.assertEqual([song["id"] for song in response.json()["results"]], [self.song.id])
        self.assertFalse(response.json()["results"][0]["playable"])
        self.assertIsNone(response.json()["results"][0]["stream_url"])
        self.assertEqual(self.client.get("/api/v1/songs/?q=not_present").json()["count"], 0)

    def test_tc_m_014_empty_library_pagination(self):
        Song.objects.update(active=False)
        response = self.client.get("/api/v1/songs/?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        self.assertEqual(response.json()["count"], 0)
        self.assert_error(self.client.get("/api/v1/songs/?page=2"), 404, "NOT_FOUND", ["page"])

    def test_invalid_query_parameters(self):
        for query in ["page=0", "page=1.0", "page_size=101", "page=1&page=2", "unknown=1", "tag_id=0", "tag_id=9999", "q=" + "a" * 101]:
            with self.subTest(query=query[:35]):
                self.assert_error(self.client.get("/api/v1/songs/?" + query), 400, "VALIDATION_ERROR")

    def test_tags_only_show_active_in_kind_order(self):
        mood = Tag.objects.create(name="Mood", kind="MOOD")
        scene = Tag.objects.create(name="Scene", kind="SCENE")
        Tag.objects.filter(id=self.tags[0].id).update(active=False)
        response = self.client.get("/api/v1/tags/")
        self.assertEqual([tag["id"] for tag in response.json()], [tag.id for tag in self.tags[1:]] + [mood.id, scene.id])
        self.assert_error(self.client.get("/api/v1/tags/?kind="), 400, "VALIDATION_ERROR", ["kind"])

    def test_pt_m_005_cross_user_playlist_access_is_denied(self):
        self.sign_in(self.other)
        path = f"/api/v1/playlists/{self.playlist.id}/"
        for method, url, data in [
            ("GET", path, None), ("PATCH", path, {"name": "Changed"}), ("DELETE", path, None),
            ("PUT", path + f"songs/{self.song.id}/", None), ("DELETE", path + f"songs/{self.song.id}/", None),
        ]:
            response = self.client.get(url) if method == "GET" else self.write(method, url, data)
            self.assert_error(response, 404, "NOT_FOUND")
        self.playlist.refresh_from_db()
        self.assertEqual(self.playlist.name, "Private mix")
        self.assertEqual(PlaylistSong.objects.count(), 0)

    def test_pt_m_010_relationship_retries_preserve_created_at(self):
        self.sign_in()
        favorite_path = f"/api/v1/favorites/{self.song.id}/"
        member_path = f"/api/v1/playlists/{self.playlist.id}/songs/{self.song.id}/"
        for path in [favorite_path, member_path]:
            self.assertEqual(self.write("PUT", path).status_code, 204)
        favorite_time = Favorite.objects.get(user=self.user, song=self.song).created_at
        member_time = PlaylistSong.objects.get(playlist=self.playlist, song=self.song).created_at
        for repetition in range(10):
            for path in [favorite_path, member_path]:
                self.assertEqual(self.write("PUT", path).status_code, 204)
        self.assertEqual(Favorite.objects.count(), 1)
        self.assertEqual(PlaylistSong.objects.count(), 1)
        self.assertEqual(Favorite.objects.get().created_at, favorite_time)
        self.assertEqual(PlaylistSong.objects.get().created_at, member_time)
        Song.objects.filter(id=self.song.id).update(active=False)
        for repetition in range(2):
            for path in [favorite_path, member_path]:
                self.assertEqual(self.write("DELETE", path).status_code, 204)
        self.assertEqual(Favorite.objects.count(), 0)
        self.assertEqual(PlaylistSong.objects.count(), 0)

    def test_tc_m_015_unpublished_songs_hidden_but_memberships_remain(self):
        self.sign_in()
        PlaylistSong.objects.create(playlist=self.playlist, song=self.song)
        Favorite.objects.create(user=self.user, song=self.song)
        Song.objects.filter(id=self.song.id).update(active=False)
        response = self.client.get(f"/api/v1/playlists/{self.playlist.id}/")
        self.assert_schema(response, "PlaylistDetail")
        self.assertEqual(response.json()["songs"], [])
        self.assertEqual(self.client.get("/api/v1/favorites/").json()["count"], 0)
        self.assertEqual(PlaylistSong.objects.count(), 1)
        self.assertEqual(Favorite.objects.count(), 1)

    def test_playlist_crud_and_strict_name_input(self):
        self.sign_in()
        for data in [{"name": 123}, {"name": " "}, {"name": "a" * 61}, {"name": "mix", "user_id": self.other.id}]:
            self.assert_error(self.write("POST", "/api/v1/playlists/", data), 400, "VALIDATION_ERROR")
        response = self.write("POST", "/api/v1/playlists/", {"name": " New mix "})
        self.assertEqual(response.status_code, 201)
        self.assert_schema(response, "Playlist")
        path = f'/api/v1/playlists/{response.json()["id"]}/'
        response = self.write("PATCH", path, {"name": "Renamed"})
        self.assertEqual(response.json()["name"], "Renamed")
        self.assertEqual(self.write("DELETE", path).status_code, 204)
        self.assert_error(self.client.get(path), 404, "NOT_FOUND")

    def test_playlist_limit_is_enforced(self):
        self.sign_in()
        Playlist.objects.bulk_create([Playlist(user=self.user, name=f"Mix {number}") for number in range(99)])
        self.assert_error(self.write("POST", "/api/v1/playlists/", {"name": "Overflow"}), 409, "LIMIT_REACHED")
        self.assertEqual(Playlist.objects.filter(user=self.user).count(), 100)

    def test_full_playlist_allows_retry_but_rejects_new_membership(self):
        self.sign_in()
        songs = [Song(
            title=f"Test {number}", artist="Metadata only", duration_ms=1000, mime="audio/wav", active=True,
            source_name="TEST", source_url="https://example.org", license_name="UNVERIFIED",
            license_url="https://example.org/license",
        ) for number in range(500)]
        Song.objects.bulk_create(songs)
        PlaylistSong.objects.bulk_create([PlaylistSong(playlist=self.playlist, song=song) for song in songs])
        prefix = f"/api/v1/playlists/{self.playlist.id}/songs/"
        self.assertEqual(self.write("PUT", prefix + f"{songs[0].id}/").status_code, 204)
        self.assert_error(self.write("PUT", prefix + f"{self.song.id}/"), 409, "LIMIT_REACHED")
        self.assertEqual(PlaylistSong.objects.filter(playlist=self.playlist).count(), 500)

    def test_failed_interest_replacement_rolls_back(self):
        self.sign_in()
        selection = [tag.id for tag in self.tags[:3]]
        self.write("PUT", "/api/v1/me/interests/", {"tag_ids": selection})
        with patch("music.services.UserTag.objects.bulk_create", side_effect=RuntimeError("private error")):
            with self.assertLogs("music.api.errors", level="ERROR"):
                response = self.write("PUT", "/api/v1/me/interests/", {"tag_ids": [tag.id for tag in self.tags[3:]]})
        self.assert_error(response, 500, "INTERNAL_ERROR")
        self.assertNotIn("private error", response.content.decode())
        self.assertEqual(list(UserTag.objects.filter(user=self.user).order_by("tag_id").values_list("tag_id", flat=True)), selection)

    @override_settings(MEDIA_ROOT=settings.BASE_DIR.parent / "media")
    def test_media_flag_rejects_missing_or_outside_paths(self):
        self.song.playback_allowed = True
        self.song.checked_at = timezone.now()
        for file_path in ["missing.wav", "../outside.wav", str(settings.BASE_DIR / "manage.py")]:
            self.song.file_path = file_path
            data = SongSerializer(self.song).data
            self.assertFalse(data["playable"])
            self.assertIsNone(data["stream_url"])
        self.song.file_path = "songs/verified.wav"
        with patch.object(Path, "is_file", return_value=True):
            self.assertTrue(SongSerializer(self.song).data["playable"])
