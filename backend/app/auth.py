"""The sign-in gate.

PLACEHOLDER, DELIBERATELY. These are fixed demo accounts with plaintext
passphrases and a signed-but-not-expiring cookie. It is enough to put a door on
the product and to shape the screen, and it is NOT authentication: there is no
user store, no password hashing, no rotation, no lockout, no audit trail. Before
this is used for a real examination it must be replaced by the directory
integration, and the accounts below deleted.

What it does do honestly: the cookie is signed with a per-installation secret,
so it cannot be forged by editing it in the browser, and the comparison is
constant-time so the passphrase cannot be guessed by timing the response.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse

from .settings import get_settings

COOKIE = "camview_session"

PRODUCT = "CamView"
PRODUCT_CODE = "IV-CAMVIEW"
TAGLINE = "Examination surveillance intelligence — alerts, evidence and compliance reporting."

# username -> (passphrase, role). Replace wholesale at integration.
DEMO_USERS: dict[str, tuple[str, str]] = {
    "admin":    ("innovatiview", "Administrator"),
    "operator": ("camview2026", "Operations"),
    "viewer":   ("viewonly", "Read only"),
}

# paths reachable without a session
# The product ring at "/" is the public front door; everything behind it
# (including /exams) still requires a session.
OPEN_PREFIXES = ("/login", "/logout", "/static", "/brand", "/healthz", "/favicon")
OPEN_EXACT = ("/",)


def _secret() -> bytes:
    """A per-installation secret, generated once and kept beside the database.
    Regenerating it simply signs everyone out, which is the correct failure."""
    path = Path(get_settings().data_dir) / ".session_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()


def issue(username: str) -> str:
    sig = hmac.new(_secret(), username.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{username}:{sig}"


def identify(request: Request) -> str | None:
    """The signed-in username, or None. Returns None rather than raising so a
    caller can decide between redirecting and rendering a signed-out view."""
    raw = request.cookies.get(COOKIE, "")
    if ":" not in raw:
        return None
    username, sig = raw.rsplit(":", 1)
    expected = hmac.new(_secret(), username.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected) or username not in DEMO_USERS:
        return None
    return username


def check(username: str, password: str) -> bool:
    entry = DEMO_USERS.get(username)
    if entry is None:
        # still compare, so a wrong username costs the same time as a wrong
        # passphrase and cannot be distinguished by response timing
        hmac.compare_digest(password, "\0" * 16)
        return False
    return hmac.compare_digest(password, entry[0])


def role(username: str | None) -> str:
    return DEMO_USERS.get(username or "", ("", "—"))[1]


def initials(username: str | None) -> str:
    return (username or "??")[:2].upper()


async def gate(request: Request, call_next):
    """Redirect anything that is not open and not signed in to the gate."""
    path = request.url.path
    if path in OPEN_EXACT or path.startswith(OPEN_PREFIXES) or identify(request):
        return await call_next(request)
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={nxt}", status_code=303)
