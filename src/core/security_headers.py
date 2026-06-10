from __future__ import annotations

from fastapi import Request, Response


API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data: https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


def _content_security_policy(path: str) -> str:
    if path in {"/docs", "/redoc"} or path.startswith("/docs/") or path.startswith("/redoc/"):
        return DOCS_CSP
    return API_CSP


def apply_security_headers(request: Request, response: Response) -> None:
    """Apply browser defense headers to every backend response."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    )
    response.headers.setdefault("Content-Security-Policy", _content_security_policy(request.url.path))


async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    apply_security_headers(request, response)
    return response
