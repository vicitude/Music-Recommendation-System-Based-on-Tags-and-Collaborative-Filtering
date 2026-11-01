import json
import logging

from django.conf import settings
from django.http import JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response


with (settings.BASE_DIR.parent / "specs/music/system/error-catalog.json").open(encoding="utf-8") as catalog_file:
    CATALOG = json.load(catalog_file)

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, error_code: str, details: list[str] | None = None) -> None:
        self.error_code = error_code
        self.definition = CATALOG["errors"][error_code]
        self.details = sorted(set(details or []) & set(CATALOG["detail_fields"]))
        super().__init__(self.definition["message"])

    def body(self, request_id: str) -> dict:
        return {
            "error_code": self.error_code,
            "message": self.definition["message"],
            "details": self.details,
            "request_id": request_id,
        }


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return JsonResponse(ApiError("CSRF_FAILED").body(request.request_id), status=403)
    from django.views.csrf import csrf_failure as django_csrf_failure

    return django_csrf_failure(request, reason=reason)


def exception_handler(error, context):
    response_status = None
    if isinstance(error, exceptions.MethodNotAllowed):
        error, response_status = ApiError("VALIDATION_ERROR", ["method"]), 405
    elif isinstance(error, exceptions.UnsupportedMediaType):
        error, response_status = ApiError("VALIDATION_ERROR", ["content_type"]), 415
    elif isinstance(error, exceptions.ParseError):
        error = ApiError("VALIDATION_ERROR", ["request"])
    elif isinstance(error, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        error = ApiError("AUTH_REQUIRED")
    elif isinstance(error, exceptions.PermissionDenied):
        error = ApiError("PERMISSION_DENIED")
    elif isinstance(error, exceptions.NotFound):
        error = ApiError("NOT_FOUND")
    if not isinstance(error, ApiError):
        logger.error("Unhandled API exception", exc_info=(type(error), error, error.__traceback__))
        error = ApiError("INTERNAL_ERROR")
    return Response(
        error.body(context["request"].request_id),
        status=response_status or error.definition["http_statuses"][0],
        headers={"Retry-After": str(error.retry_after)} if error.error_code == "RATE_LIMITED" and hasattr(error, "retry_after") else None,
    )
