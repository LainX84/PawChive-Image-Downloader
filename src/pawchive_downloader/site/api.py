"""Typed access to the PawChive JSON API (``/api/v1``).

Every response is validated. Missing or malformed fields raise
:class:`SiteStructureChanged` with a message that says what changed, so a
frontend update produces a clear error instead of silent misbehaviour.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .errors import NotFound, SiteStructureChanged
from .http import HttpClient
from .models import Creator, Post, RemoteFile
from .urls import is_site_host

log = logging.getLogger(__name__)

PAGE_SIZE = 50
# Original file paths end with the SHA-256 of the content (verified 2026-11).
_HASH_PATH_RE = re.compile(r"^/(?:[^/]+/)*(?P<sha>[0-9a-f]{64})\.(?P<ext>[A-Za-z0-9]{1,8})$")


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _require(obj: dict[str, Any], key: str, kind: type | tuple[type, ...], context: str) -> Any:
    if key not in obj:
        raise SiteStructureChanged(f"{context}: field {key!r} is missing")
    value = obj[key]
    if not isinstance(value, kind):
        raise SiteStructureChanged(f"{context}: field {key!r} has unexpected type {type(value).__name__}")
    return value


def parse_creator(data: Any, service: str, creator_id: str) -> Creator:
    if not isinstance(data, dict):
        raise SiteStructureChanged("creator profile is not an object")
    ctx = f"profile {service}/{creator_id}"
    name = _require(data, "name", str, ctx)
    returned_id = str(_require(data, "id", (str, int), ctx))
    if returned_id != str(creator_id):
        raise SiteStructureChanged(f"{ctx}: API returned a different creator id {returned_id!r}")
    return Creator(
        service=str(data.get("service") or service),
        creator_id=returned_id,
        name=name.strip() or returned_id,
        public_id=data.get("public_id") if isinstance(data.get("public_id"), str) else None,
        updated=data.get("updated") if isinstance(data.get("updated"), str) else None,
    )


def parse_remote_file(entry: Any, position: int, base_url: str, context: str) -> RemoteFile | None:
    """Return a :class:`RemoteFile`, ``None`` for an empty entry, or raise."""
    if entry in (None, {}, []):
        return None
    if not isinstance(entry, dict):
        raise SiteStructureChanged(f"{context}: file entry is not an object")
    path = entry.get("path")
    if not path:
        return None
    if not isinstance(path, str):
        raise SiteStructureChanged(f"{context}: file path is not a string")
    server = entry.get("server")
    if not isinstance(server, str) or not server.startswith("https://"):
        raise SiteStructureChanged(f"{context}: file {path!r} has no usable 'server' field")
    if not is_site_host(urlsplit(server).hostname, base_url):
        raise SiteStructureChanged(f"{context}: file server {server!r} is outside the PawChive domain")
    if "/thumbnail/" in path:
        raise SiteStructureChanged(f"{context}: API returned a thumbnail path instead of an original")
    match = _HASH_PATH_RE.match(path)
    if not match:
        raise SiteStructureChanged(f"{context}: file path {path!r} does not end with a SHA-256 name")
    name = entry.get("name") if isinstance(entry.get("name"), str) and entry.get("name").strip() else f"{match['sha']}.{match['ext']}"
    return RemoteFile(
        name=name.strip(),
        path=path,
        server=server.rstrip("/"),
        sha256=match["sha"],
        extension=match["ext"].lower(),
        position=position,
    )


def parse_post(data: Any, base_url: str) -> Post:
    if not isinstance(data, dict):
        raise SiteStructureChanged("post is not an object")
    post_id = str(_require(data, "id", (str, int), "post"))
    ctx = f"post {post_id}"
    creator_id = str(_require(data, "user", (str, int), ctx))
    service = _require(data, "service", str, ctx)
    title = data.get("title")
    if title is None:
        title = ""
    if not isinstance(title, str):
        raise SiteStructureChanged(f"{ctx}: title is not a string")
    attachments = data.get("attachments", [])
    if attachments is None:
        attachments = []
    if not isinstance(attachments, list):
        raise SiteStructureChanged(f"{ctx}: attachments is not a list")
    has_full = data.get("has_full", True)
    if not isinstance(has_full, bool):
        raise SiteStructureChanged(f"{ctx}: has_full is not a boolean")

    files: list[RemoteFile] = []
    seen: set[str] = set()
    skipped: list[str] = []
    entries = [data.get("file")] + list(attachments)
    position = 0
    for entry in entries:
        try:
            remote = parse_remote_file(entry, position, base_url, ctx)
        except SiteStructureChanged as exc:
            log.warning("%s", exc)
            skipped.append(str(exc))
            continue
        if remote is None:
            continue
        # The main file is frequently repeated in the attachments.
        if remote.sha256 in seen:
            continue
        seen.add(remote.sha256)
        files.append(remote)
        position += 1

    # Re-number so positions are contiguous after de-duplication.
    files = [
        RemoteFile(f.name, f.path, f.server, f.sha256, f.extension, i) for i, f in enumerate(files)
    ]
    return Post(
        post_id=post_id,
        creator_id=creator_id,
        service=service,
        title=title,
        published=_parse_time(data.get("published")) or _parse_time(data.get("added")),
        edited=_parse_time(data.get("edited")),
        has_full=has_full,
        files=files,
        skipped_paths=skipped,
        raw=data,
    )


class PawChiveApi:
    """Endpoint wrappers. All methods may raise errors from :mod:`.errors`."""

    def __init__(self, client: HttpClient, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.api_root = f"{self.base_url}/api/v1"

    def get_profile(self, service: str, creator_id: str) -> Creator:
        data = self.client.get_json(f"{self.api_root}/{service}/user/{creator_id}/profile")
        return parse_creator(data, service, creator_id)

    def list_posts(self, service: str, creator_id: str, offset: int = 0) -> list[Post]:
        if offset % PAGE_SIZE:
            raise ValueError("offset must be a multiple of 50")
        params = {"o": offset} if offset else None
        try:
            data = self.client.get_json(f"{self.api_root}/{service}/user/{creator_id}/posts", params=params)
        except NotFound:
            if offset:
                return []  # past the last page on some deployments
            raise
        if not isinstance(data, list):
            raise SiteStructureChanged(f"post list for {service}/{creator_id} is not a list")
        return [parse_post(item, self.base_url) for item in data]

    def iter_post_pages(self, service: str, creator_id: str, start: int = 0) -> Iterator[list[Post]]:
        offset = start
        while True:
            page = self.list_posts(service, creator_id, offset)
            if not page:
                return
            yield page
            if len(page) < PAGE_SIZE:
                return
            offset += PAGE_SIZE

    def get_post(self, service: str, creator_id: str, post_id: str) -> Post:
        data = self.client.get_json(f"{self.api_root}/{service}/user/{creator_id}/post/{post_id}")
        # Some Kemono forks wrap the post: {"post": {...}}
        if isinstance(data, dict) and "post" in data and isinstance(data["post"], dict):
            data = data["post"]
        return parse_post(data, self.base_url)
