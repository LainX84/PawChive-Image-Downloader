"""Parsing and classification of PawChive URLs pasted by the user."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .errors import InvalidUrl, UnsupportedUrl

KNOWN_SERVICES = ("patreon", "fanbox", "fantia", "gumroad", "subscribestar", "afdian", "boosty", "dlsite")

_PROFILE_RE = re.compile(r"^/(?P<service>[a-z0-9_]+)/user/(?P<creator>[A-Za-z0-9_\-.]+)/?$")
_POST_RE = re.compile(
    r"^/(?P<service>[a-z0-9_]+)/user/(?P<creator>[A-Za-z0-9_\-.]+)/post/(?P<post>[A-Za-z0-9_\-]+)/?$"
)
_DISCORD_RE = re.compile(r"^/discord/server/")


@dataclass(frozen=True)
class ProfileUrl:
    service: str
    creator_id: str


@dataclass(frozen=True)
class PostUrl:
    service: str
    creator_id: str
    post_id: str


def site_host(base_url: str) -> str:
    return (urlsplit(base_url).hostname or "").lower()


def is_site_host(host: str | None, base_url: str) -> bool:
    """True for the site host itself and its subdomains (file nodes)."""
    if not host:
        return False
    host = host.lower().rstrip(".")
    root = site_host(base_url)
    return host == root or host.endswith("." + root)


def parse_url(text: str, base_url: str = "https://pawchive.pw") -> ProfileUrl | PostUrl:
    """Classify a pasted URL.

    Raises :class:`InvalidUrl` for anything that is not a PawChive creator or
    post URL, and :class:`UnsupportedUrl` for PawChive URLs that cannot be
    archived (for example Discord servers).
    """
    raw = (text or "").strip()
    if not raw:
        raise InvalidUrl("Please paste a PawChive URL.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise InvalidUrl("Only http(s) URLs are supported.")
    host = (parts.hostname or "").lower()
    root = site_host(base_url)
    if host not in (root, "www." + root):
        raise InvalidUrl(f"This is not a {root} URL.")

    path = re.sub(r"/{2,}", "/", parts.path)
    if _DISCORD_RE.match(path):
        raise UnsupportedUrl("Discord servers are not supported: they have no galleries to archive.")
    if m := _POST_RE.match(path):
        return PostUrl(m["service"], m["creator"], m["post"])
    if m := _PROFILE_RE.match(path):
        return ProfileUrl(m["service"], m["creator"])
    raise InvalidUrl("Paste an author profile URL (…/service/user/ID) or a post URL (…/user/ID/post/ID).")


def profile_url(base_url: str, service: str, creator_id: str) -> str:
    return f"{base_url.rstrip('/')}/{service}/user/{creator_id}"


def post_url(base_url: str, service: str, creator_id: str, post_id: str) -> str:
    return f"{profile_url(base_url, service, creator_id)}/post/{post_id}"
