import json
from datetime import timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from music.models import Rating, Song, User


class RatingApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="rating_user", password="test-password-123")
        cls.other = User.objects.create_user(username="rating_other", password="test-password-123")
        cls.song = Song.objects.create(
            title="Rating test", artist="TEST_ONLY", duration_ms=10000, mime="audio/wav",
            file_path="songs/rating.wav", active=True, playback_allowed=True,
            source_name="TEST_ONLY", source_url="https://example.org/source",
            license_name="TEST_ONLY", license_url="https://example.org/license",
        )

    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        self.client.force_login(self.user)

    def write(self, method, path, payload=None, client=None, token=None):
        return (client or self.client).generic(
            method, path, "" if payload is None else json.dumps(payload),
            content_type="application/json", HTTP_X_CSRFTOKEN=token or self.token,
        )

    def test_rating_create_update_read_delete(self):
        url = f"/api/v1/songs/{self.song.id}/rating/"
        self.assertEqual(self.client.get(url).json(), {"score": None})
        self.assertEqual(self.write("PUT", url, {"score": 4}).json(), {"score": 4})
        self.assertEqual(self.write("PUT", url, {"score": 2}).json(), {"score": 2})
        self.assertEqual(Rating.objects.filter(user=self.user, song=self.song).count(), 1)
        self.assertEqual(self.client.get(f"/api/v1/songs/{self.song.id}/").json()["current_rating"], 2)
        self.assertEqual(self.write("DELETE", url).status_code, 204)
        self.assertEqual(self.client.get(url).json(), {"score": None})

    def test_score_is_strict_and_unknown_fields_rejected(self):
        url = f"/api/v1/songs/{self.song.id}/rating/"
        for payload in ({"score": 0}, {"score": 6}, {"score": True}, {"score": 3.5}, {"score": 4, "extra": 1}):
            response = self.write("PUT", url, payload)
            self.assertEqual(response.status_code, 400, payload)
            self.assertEqual(response.json()["error_code"], "VALIDATION_ERROR")

    def test_rating_is_private_and_song_must_be_active(self):
        url = f"/api/v1/songs/{self.song.id}/rating/"
        self.write("PUT", url, {"score": 5})
        other_client = APIClient(enforce_csrf_checks=True)
        other_token = other_client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        other_client.force_login(self.other)
        self.assertEqual(other_client.get(url).json(), {"score": None})
        Song.objects.filter(id=self.song.id).update(active=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.write("PUT", url, {"score": 5}).status_code, 404)
