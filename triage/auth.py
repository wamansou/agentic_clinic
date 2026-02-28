"""Simple password auth for external client demos."""

import hashlib
import hmac
import os
import secrets
import time

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

DEMO_USER = os.getenv("DEMO_USER", "admin")
DEMO_PASS = os.getenv("DEMO_PASS", "kvinde2026")
COOKIE_NAME = "triage_session"
COOKIE_SECRET = os.getenv("COOKIE_SECRET", secrets.token_hex(32))
COOKIE_MAX_AGE = 60 * 60 * 24  # 24 hours

EXEMPT_PATHS = {"/login", "/health"}
EXEMPT_PREFIXES = ("/static/",)


def _sign(value: str) -> str:
    """Create an HMAC signature for a cookie value."""
    return hmac.new(COOKIE_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_cookie(username: str) -> str:
    """Create a signed cookie value."""
    ts = str(int(time.time()))
    payload = f"{username}|{ts}"
    sig = _sign(payload)
    return f"{payload}|{sig}"


def _verify_cookie(cookie: str) -> str | None:
    """Verify a signed cookie. Returns username if valid, None otherwise."""
    parts = cookie.split("|")
    if len(parts) != 3:
        return None
    username, ts, sig = parts
    expected_sig = _sign(f"{username}|{ts}")
    if not hmac.compare_digest(sig, expected_sig):
        return None
    # Check expiry
    try:
        created = int(ts)
        if time.time() - created > COOKIE_MAX_AGE:
            return None
    except ValueError:
        return None
    return username


def get_current_user(request: Request) -> str | None:
    """Extract and verify the current user from session cookie."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return _verify_cookie(cookie)


def login_required(request: Request) -> str | None:
    """Check if the request is authenticated. Returns username or None."""
    path = request.url.path
    if path in EXEMPT_PATHS or any(path.startswith(p) for p in EXEMPT_PREFIXES):
        return "exempt"
    return get_current_user(request)


def handle_login(username: str, password: str, response: Response) -> bool:
    """Validate credentials and set session cookie. Returns True on success."""
    if username == DEMO_USER and password == DEMO_PASS:
        cookie_value = _make_cookie(username)
        response.set_cookie(
            COOKIE_NAME,
            cookie_value,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return True
    return False


def handle_logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(COOKIE_NAME)
