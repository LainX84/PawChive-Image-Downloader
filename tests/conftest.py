"""Shared fixtures: a simulated PawChive site built on respx.

Nothing in the test suite contacts the real website.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pawchive_downloader.config.settings import Settings  # noqa: E402
from pawchive_downloader.core.engine import Engine  # noqa: E402
from pawchive_downloader.site.http import HttpClient  # noqa: E402
from pawchive_downloader.storage.db import Database  # noqa: E402
from pawchive_downloader.storage.migrate import migrate  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://pawchive.pw"


def make_image(seed: int, size: int = 4096, kind: str = "png") -> bytes:
    rng = random.Random(seed)
    body = bytes(rng.getrandbits(8) for _ in range(size))
    header = {
        "png": b"\x89PNG\r\n\x1a\n",
        "jpg": b"\xff\xd8\xff\xe0",
        "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 ",
        "7z": b"7z\xbc\xaf\x27\x1c",
        "mp4": b"\x00\x00\x00\x18ftypisom",
    }[kind]
    return header + body


@dataclass
class FakeFile:
    name: str
    data: bytes
    node: str = "n1"

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def ext(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower()

    @property
    def path(self) -> str:
        # Mirrors the real layout: /<digit><h0h1>/<h2h3>/<sha>.<ext>
        return f"/1{self.sha[:2]}/{self.sha[2:4]}/{self.sha}.{self.ext}"

    def entry(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "server": f"https://{self.node}.pawchive.pw"}


@dataclass
class FakePost:
    post_id: str
    title: str
    files: list[FakeFile] = field(default_factory=list)
    has_full: bool = True
    published: str = "2026-01-01T10:00:00"
    edited: str | None = None

    def to_json(self, creator_id: str) -> dict[str, Any]:
        entries = [f.entry() for f in self.files]
        return {
            "id": self.post_id,
            "user": creator_id,
            "service": "patreon",
            "title": self.title,
            "content": "",
            "published": self.published,
            "added": self.published,
            "edited": self.edited or self.published,
            "file": entries[0] if entries else {},
            # The real site repeats the main file inside attachments.
            "attachments": entries,
            "has_full": self.has_full,
            "preview_state": "scraped" if self.has_full else "pending",
        }


class FakeSite:
    """In-memory PawChive: creators, posts (newest first) and file nodes."""

    def __init__(self) -> None:
        self.creators: dict[str, dict[str, Any]] = {}
        self.posts: dict[str, list[FakePost]] = {}
        self.files: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail_file_once: dict[str, int] = {}  # sha -> bytes to send before dropping
        self.file_status: dict[str, int] = {}  # sha -> forced status
        self.api_status: int | None = None
        self.api_headers: dict[str, str] = {}
        self.support_ranges = True

    def add_creator(self, creator_id: str, name: str, updated: str = "2026-01-01T00:00:00") -> None:
        self.creators[creator_id] = {
            "id": creator_id, "name": name, "service": "patreon", "indexed": "2026-01-01T00:00:00",
            "updated": updated, "public_id": name, "relation_id": None,
        }
        self.posts.setdefault(creator_id, [])

    def publish(self, creator_id: str, post: FakePost) -> FakePost:
        self.posts[creator_id].insert(0, post)
        for f in post.files:
            self.files[f.sha] = f.data
        self.creators[creator_id]["updated"] = f"2026-02-{len(self.posts[creator_id]):02d}T00:00:00"
        return post

    # ------------------------------------------------------------ handlers
    def _api(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.api_status:
            return httpx.Response(self.api_status, headers=self.api_headers, text="blocked")
        path = request.url.path
        if m := re.fullmatch(r"/api/v1/patreon/user/([^/]+)/profile", path):
            creator = self.creators.get(m.group(1))
            if not creator:
                return httpx.Response(404, json={"error": "Creator not found."})
            return httpx.Response(200, json=creator)
        if m := re.fullmatch(r"/api/v1/patreon/user/([^/]+)/posts", path):
            cid = m.group(1)
            if cid not in self.creators:
                return httpx.Response(404, json={"error": "not found"})
            offset = int(request.url.params.get("o", "0"))
            if offset % 50:
                return httpx.Response(400, json={"error": "offset not multiple of 50"})
            page = self.posts[cid][offset: offset + 50]
            return httpx.Response(200, json=[p.to_json(cid) for p in page])
        if m := re.fullmatch(r"/api/v1/patreon/user/([^/]+)/post/([^/]+)", path):
            for post in self.posts.get(m.group(1), []):
                if post.post_id == m.group(2):
                    return httpx.Response(200, json=post.to_json(m.group(1)))
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(404, json={"error": "not found"})

    def _file(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        m = re.search(r"/data/[^/]+/[^/]+/([0-9a-f]{64})\.", request.url.path)
        if not m or m.group(1) not in self.files:
            return httpx.Response(404, text="404 page not found")
        sha = m.group(1)
        if sha in self.file_status:
            return httpx.Response(self.file_status[sha], text="error")
        data = self.files[sha]
        ctype = "image/png" if request.url.path.endswith(".png") else "application/octet-stream"
        start = 0
        range_header = request.headers.get("Range")
        if range_header and self.support_ranges:
            start = int(re.match(r"bytes=(\d+)-", range_header).group(1))  # type: ignore[union-attr]
            if start >= len(data):
                return httpx.Response(416, headers={"Content-Range": f"bytes */{len(data)}"})
        body = data[start:]
        if sha in self.fail_file_once:
            cut = self.fail_file_once.pop(sha)
            return httpx.Response(
                200, headers={"Content-Length": str(len(data)), "Content-Type": ctype},
                stream=_FaultyStream(data[:cut]),
            )
        if start and self.support_ranges:
            return httpx.Response(206, content=body, headers={
                "Content-Range": f"bytes {start}-{len(data) - 1}/{len(data)}", "Content-Type": ctype,
                "Content-Length": str(len(body))})
        return httpx.Response(200, content=data, headers={"Content-Type": ctype, "Content-Length": str(len(data))})

    def install(self, router: respx.Router) -> None:
        router.route(host="pawchive.pw").mock(side_effect=self._api)
        router.route(host__regex=r"n\d\.pawchive\.pw").mock(side_effect=self._file)
        router.route(host="img.pawchive.pw").mock(return_value=httpx.Response(200, content=make_image(0, 100, "webp")))

    def file_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host.startswith("n")]


class _FaultyStream(httpx.SyncByteStream):
    """Sends some bytes, then drops the connection."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self):  # type: ignore[override]
        yield self.data
        raise httpx.ReadError("connection reset by peer")


@pytest.fixture
def site() -> FakeSite:
    return FakeSite()


@pytest.fixture
def router(site: FakeSite):
    with respx.mock(assert_all_called=False) as mock:
        site.install(mock)
        yield mock


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(scan_on_startup=False).resolved(tmp_path / "data")
    s.request_delay_seconds = 0.0
    from pawchive_downloader.config.paths import prepare_directories

    prepare_directories(s)
    return s


def make_engine(settings: Settings) -> Engine:
    db = Database(settings.database_path)
    migrate(db, settings.database_path.parent / "backups")
    http = HttpClient(BASE, "PawChiveImageDownloader/test", request_delay=0.0, file_request_delay=0.0)
    return Engine(settings, db, http)


@pytest.fixture
def engine(settings: Settings, router):
    eng = make_engine(settings)
    yield eng
    eng.db.close()
    eng.http.close()


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
