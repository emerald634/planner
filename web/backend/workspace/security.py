"""Session-bound CSRF for login/logout/all mutations; no new authentication."""

import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.dependencies import ACCESS_TOKEN_COOKIE


def install_security(app, origin, secret, *, secure=True):
    if len(secret) < 32:
        raise ValueError("Persistent CSRF secret >=32 bytes required")
    cookie = "__Host-workspace_csrf" if secure else "workspace_csrf"
    host = urlsplit(origin).netloc

    def signature(session, nonce):
        return hmac.new(secret, (session + ":" + nonce).encode(), hashlib.sha256).hexdigest()

    @app.middleware("http")
    async def boundary(request, call_next):
        if (
            request.headers.get("host") != host
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "Недопустимый источник запроса."}, 403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            nonce = request.cookies.get(cookie, "")
            token = request.headers.get("x-csrf-token", "")
            if (
                request.headers.get("origin") != origin
                or not re.fullmatch(r"[A-Za-z0-9_-]{32}", nonce)
                or not hmac.compare_digest(
                    token, signature(request.cookies.get(ACCESS_TOKEN_COOKIE, ""), nonce)
                )
            ):
                return JSONResponse(
                    {"detail": "Обновите страницу: проверка безопасности не пройдена."}, 403
                )
            # Bound JSON request size BEFORE FastAPI parses it, including chunked bodies.
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 512_000:
                    return JSONResponse({"detail": "Слишком большой запрос."}, 413)
                body.extend(chunk)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'"
                ),
            }
        )
        return response

    @app.get("/api/v1/auth/csrf")
    def csrf(request: Request):
        nonce = request.cookies.get(cookie, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", nonce):
            nonce = secrets.token_urlsafe(24)
        response = JSONResponse(
            {"csrf": signature(request.cookies.get(ACCESS_TOKEN_COOKIE, ""), nonce)}
        )
        response.set_cookie(
            cookie, nonce, secure=secure, httponly=True, samesite="strict", path="/"
        )
        return response
