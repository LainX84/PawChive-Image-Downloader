"""Optional session cookies, stored only in the OS credential store.

PawChive content is public, so this is an advanced, optional feature. Cookies
are never written to settings files or logs. If no secure credential store is
available, storing is refused instead of falling back to plain text.
"""

from __future__ import annotations

import logging
import re
import threading

import keyring
import keyring.errors
from keyring.backends import fail

from ..version import APP_ID

log = logging.getLogger(__name__)

_KEY = "session-cookies"
_COOKIE_PAIR_RE = re.compile(r"^\s*([!#$%&'*+\-.^_`|~0-9A-Za-z]+)\s*=\s*(.*?)\s*$")


class CredentialStoreUnavailable(RuntimeError):
    pass


def parse_cookie_text(text: str, domain_suffix: str = "pawchive.pw") -> dict[str, str]:
    """Accept either ``name=value; name2=value2`` or a Netscape ``cookies.txt``."""
    cookies: dict[str, str] = {}
    lines = [line for line in (text or "").splitlines() if line.strip()]
    netscape = any(line.count("\t") >= 6 for line in lines if not line.startswith("#"))
    if netscape:
        for line in lines:
            if line.startswith("#") and not line.startswith("#HttpOnly_"):
                continue
            fields = line.removeprefix("#HttpOnly_").split("\t")
            if len(fields) < 7:
                continue
            domain, name, value = fields[0].lstrip("."), fields[5], fields[6]
            if domain == domain_suffix or domain.endswith("." + domain_suffix):
                cookies[name] = value
        return cookies
    for chunk in re.split(r"[;\n]", text or ""):
        m = _COOKIE_PAIR_RE.match(chunk)
        if m and m.group(1).lower() not in {"path", "domain", "expires", "max-age", "secure", "httponly", "samesite"}:
            cookies[m.group(1)] = m.group(2)
    return cookies


class SessionStore:
    def __init__(self, service_name: str = APP_ID) -> None:
        self.service_name = service_name
        # Re-entrant: keyring may log while we hold the lock, and logging
        # consults secret_values() through the redaction filter.
        self._lock = threading.RLock()
        self._cache: str | None = None
        self._loaded = False
        self.expired = False

    @staticmethod
    def secure_store_available() -> bool:
        backend = keyring.get_keyring()
        return not isinstance(backend, fail.Keyring) and getattr(backend, "priority", 1) > 0

    def load(self) -> None:
        """Read the stored session once (call at startup, outside logging)."""
        with self._lock:
            self._load()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            self._cache = keyring.get_password(self.service_name, _KEY)
        except keyring.errors.KeyringError as exc:
            log.info("No session in the credential store (%s)", exc.__class__.__name__)
            self._cache = None

    def cookie_header(self) -> str | None:
        with self._lock:
            self._load()
            return self._cache or None

    def has_session(self) -> bool:
        return bool(self.cookie_header())

    def set_cookies(self, text: str) -> int:
        """Parse and store cookies. Returns the number of cookies stored."""
        cookies = parse_cookie_text(text)
        if not cookies:
            raise ValueError("No cookies for pawchive.pw were found in the text.")
        if not self.secure_store_available():
            raise CredentialStoreUnavailable(
                "No secure credential store is available on this system, so cookies cannot be saved safely."
            )
        header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        with self._lock:
            keyring.set_password(self.service_name, _KEY, header)
            self._cache = header
            self._loaded = True
            self.expired = False
        log.info("Session cookies updated (%d cookies)", len(cookies))
        return len(cookies)

    def clear(self) -> None:
        with self._lock:
            try:
                keyring.delete_password(self.service_name, _KEY)
            except keyring.errors.PasswordDeleteError:
                pass
            except keyring.errors.KeyringError as exc:
                log.warning("Could not clear credential store entry: %s", exc.__class__.__name__)
            self._cache = None
            self._loaded = True
            self.expired = False
        log.info("Session cookies cleared")

    def secret_values(self) -> list[str]:
        """Values that the log redaction filter must mask.

        Uses only the in-memory copy: it is called for every log record and
        must never touch the credential store.
        """
        header = self._cache
        if not header:
            return []
        values = [header]
        for pair in header.split(";"):
            if "=" in pair:
                value = pair.split("=", 1)[1].strip()
                if len(value) >= 6:
                    values.append(value)
        return values
