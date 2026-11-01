from uuid import uuid4

from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone

from music.api.errors import ApiError


class ApiRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid4())
        request.now = timezone.now()
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            if response.status_code == 404 and not response.get("Content-Type", "").startswith("application/json"):
                response = JsonResponse(ApiError("NOT_FOUND").body(request.request_id), status=404)
            response["X-Spec-Version"] = "v0.1.0"
            response["X-Request-ID"] = request.request_id
            if request.path.startswith("/api/v1/recommendations/daily/"):
                response["Cache-Control"] = "private,no-store"
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.path.startswith("/api/") or request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return None
        view_class = getattr(view_func, "cls", None)
        if view_class is not None and request.method.lower() not in view_class.http_method_names:
            return None
        return CsrfViewMiddleware(self.get_response).process_view(request, self.csrf_target, (), {})

    @staticmethod
    def csrf_target(request):
        return None
