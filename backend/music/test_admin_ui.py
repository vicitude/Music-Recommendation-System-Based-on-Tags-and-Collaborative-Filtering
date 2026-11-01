from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.views import serve
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from music.models import Song, User


class AdminInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "TestOnly!Studio-8374"
        cls.admin = User.objects.create_superuser(username="studio_admin", password=cls.password)
        cls.listener = User.objects.create_user(username="studio_listener", password=cls.password)

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def login_form(self):
        response = self.client.get("/admin/login/", HTTP_HOST="127.0.0.1:8000")
        self.assertEqual(response.status_code, 200)
        return response, response.cookies["csrftoken"].value

    def admin_login(self, token, origin="http://127.0.0.1:5173", username="studio_admin"):
        payload = {"username": username, "password": self.password, "next": "/admin/"}
        if token is not None:
            payload["csrfmiddlewaretoken"] = token
        return self.client.post("/admin/login/", payload, HTTP_HOST="127.0.0.1:8000", HTTP_ORIGIN=origin)

    def test_adm_m_001_trusted_proxy_origin_logs_in_with_real_csrf(self):
        self.assertEqual(settings.CSRF_TRUSTED_ORIGINS, ["http://127.0.0.1:5173"])
        _, token = self.login_form()
        response = self.admin_login(token)
        self.assertRedirects(response, "/admin/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.id)

    def test_adm_m_002_trusted_origin_still_rejects_missing_token(self):
        self.login_form()
        self.assertEqual(self.admin_login(None).status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_adm_m_003_unknown_origins_rejected_even_with_token(self):
        _, token = self.login_form()
        for origin in ("https://evil.example", "http://127.0.0.1:5174", "http://localhost:5173"):
            with self.subTest(origin=origin):
                self.assertEqual(self.admin_login(token, origin=origin).status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_adm_m_004_api_proxy_uses_same_csrf_protection(self):
        token = self.client.get("/api/v1/auth/csrf/").json()["csrf_token"]
        credentials = {"username": "studio_listener", "password": self.password}
        denied = self.client.post("/api/v1/auth/login/", credentials, content_type="application/json", HTTP_ORIGIN="http://127.0.0.1:5173", HTTP_HOST="127.0.0.1:8000")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error_code"], "CSRF_FAILED")
        response = self.client.post("/api/v1/auth/login/", credentials, content_type="application/json", HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="http://127.0.0.1:5173", HTTP_HOST="127.0.0.1:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.listener.id)

    def test_adm_m_005_branded_login_preserves_fields_errors_and_escape(self):
        response, token = self.login_form()
        self.assertTemplateUsed(response, "admin/login.html")
        for text in ("登录内容管理台", "csrfmiddlewaretoken", 'name="username"', 'name="password"', "/static/music/admin.css", "不是数据库账户"):
            self.assertContains(response, text)
        self.assertNotContains(response, self.password)
        response = self.admin_login(token, username='<script>alert("x")</script>')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "errornote")
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertNotContains(response, self.password)

    def test_adm_m_006_dashboard_shows_only_authorized_entries(self):
        self.client.force_login(self.admin)
        response = self.client.get("/admin/")
        self.assertTemplateUsed(response, "admin/index.html")
        for text in ("管理入口", "一首歌的上架路径", "我的近期操作", "/admin/music/song/", "/admin/music/tag/"):
            self.assertContains(response, text)
        limited = User.objects.create_user(username="limited_staff", is_staff=True)
        self.client.force_login(limited)
        response = self.client.get("/admin/")
        self.assertContains(response, "当前账号暂无可管理内容")
        self.assertNotContains(response, "/admin/music/song/")
        self.client.force_login(self.listener)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_adm_m_007_lists_and_grouped_forms_render_without_changing_data(self):
        self.client.force_login(self.admin)
        for path in ("/admin/music/song/", "/admin/music/tag/", "/admin/music/user/"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/music/admin.css")
        response = self.client.get("/admin/music/song/add/")
        for text in ("歌曲信息", "音频与预览", "来源与许可", "核验与发布", "rights_confirmed", "preview_confirmed", "csrfmiddlewaretoken"):
            self.assertContains(response, text)
        self.assertContains(response, "multipart/form-data")
        self.assertEqual(Song.objects.count(), 0)

    def test_adm_m_008_local_static_exists_and_trust_is_not_a_csrf_bypass(self):
        self.assertIsNotNone(finders.find("music/admin.css"))
        response = serve(RequestFactory().get("/static/music/admin.css"), "music/admin.css", insecure=True)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"studio-login-layout", b"".join(response.streaming_content))
        finally:
            response.close()
        with override_settings(CSRF_TRUSTED_ORIGINS=[]):
            _, token = self.login_form()
            self.assertEqual(self.admin_login(token).status_code, 403)
        self.assertEqual(self.client.get("/admin/music/song/").status_code, 302)


class AdminLayoutTests(SimpleTestCase):
    def test_adm_m_009_dashboard_width_overrides_legacy_dashboard_selector(self):
        from pathlib import Path
        import re

        css = Path(finders.find("music/admin.css")).read_text(encoding="utf-8")
        match = re.search(r"\.music-dashboard #content\s*\{([^}]+)\}", css)
        self.assertIsNotNone(match)
        declarations = dict(item.strip().split(":", 1) for item in match[1].split(";") if item.strip())
        for name, value in {"width": "100%", "max-width": "1680px", "box-sizing": "border-box", "margin": "0 auto"}.items():
            self.assertEqual(declarations[name].strip(), value)
        self.assertIn(".music-dashboard .main > .content { min-width: 0; width: 100%; }", css)
        self.assertIn("@media (max-width: 1100px)", css)
        self.assertIn("@media (max-width: 767px)", css)

    def test_adm_m_010_custom_styles_follow_framework_styles_and_bust_cache(self):
        response = self.client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("/static/music/admin.css?v=20261030-2", html)
        self.assertLess(html.index("/static/admin/css/base.css"), html.index("/static/music/admin.css"))
        self.assertLess(html.index("/static/admin/css/responsive.css"), html.index("/static/music/admin.css"))
