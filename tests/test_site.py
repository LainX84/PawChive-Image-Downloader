"""URL parsing, API parsing and HTTP error handling."""

from __future__ import annotations

from html.parser import HTMLParser

import httpx
import pytest
import respx

from conftest import BASE, load_fixture, FIXTURES
from pawchive_downloader.site.api import PawChiveApi, parse_post
from pawchive_downloader.site.errors import (
    AccessBlocked, AuthRequired, InvalidUrl, NotFound, RateLimited, SiteStructureChanged, UnsupportedUrl,
)
from pawchive_downloader.site.http import HttpClient, parse_retry_after
from pawchive_downloader.site.urls import PostUrl, ProfileUrl, parse_url


# ------------------------------------------------------------------ URLs
def test_parse_profile_and_post_urls():
    assert parse_url("https://pawchive.pw/patreon/user/82443765") == ProfileUrl("patreon", "82443765")
    assert parse_url("pawchive.pw/patreon/user/82443765?o=50") == ProfileUrl("patreon", "82443765")
    assert parse_url("https://www.pawchive.pw/fanbox/user/123/post/456/") == PostUrl("fanbox", "123", "456")


@pytest.mark.parametrize("bad", ["", "https://example.com/patreon/user/1", "https://pawchive.pw/posts",
                                 "https://pawchive.org/patreon/user/1", "ftp://pawchive.pw/patreon/user/1"])
def test_invalid_urls(bad):
    with pytest.raises(InvalidUrl):
        parse_url(bad)


def test_discord_is_unsupported():
    with pytest.raises(UnsupportedUrl):
        parse_url("https://pawchive.pw/discord/server/123")


# ------------------------------------------------------------- parsing
def test_parse_posts_fixture():
    posts = [parse_post(p, BASE) for p in load_fixture("posts_page.json")]
    first, empty, previews = posts
    # main file repeated in attachments is de-duplicated; the .7z extra is kept
    assert [f.name for f in first.files] == ["page35.png", "extras.7z"]
    assert [f.kind for f in first.files] == ["image", "archive"]
    assert first.files[0].url.startswith("https://n1.pawchive.pw/data/2")
    assert first.files[0].url.endswith("?f=page35.png")
    assert empty.is_empty and not empty.skipped_paths
    assert previews.has_full is False and len(previews.files) == 2


def test_original_url_matches_html_link_not_thumbnail():
    """Scenario I (static part): the API-derived URL is the one behind the
    preview's link, never the thumbnail shown in the page."""

    class Links(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.hrefs: list[str] = []
            self.imgs: list[str] = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "a" and "fileThumb" in (a.get("class") or ""):
                self.hrefs.append(a["href"])
            if tag == "img":
                self.imgs.append(a["src"])

    parser = Links()
    parser.feed((FIXTURES / "post_page.html").read_text())
    post = parse_post(load_fixture("posts_page.json")[0], BASE)
    assert post.files[0].url == parser.hrefs[0]
    assert all("/thumbnail/" in src for src in parser.imgs)
    assert post.files[0].url not in parser.imgs


def test_structure_change_is_reported():
    with pytest.raises(SiteStructureChanged):
        parse_post({"title": "no id"}, BASE)
    bad = load_fixture("posts_page.json")[0]
    bad["file"] = {"name": "x.png", "path": "/thumbnail/data/aa/bb/x.png", "server": "https://img.pawchive.pw"}
    bad["attachments"] = []
    post = parse_post(bad, BASE)
    assert post.is_empty and post.skipped_paths  # not silently treated as "empty"


def test_foreign_file_server_rejected():
    data = load_fixture("posts_page.json")[0]
    data["attachments"] = []
    data["file"]["server"] = "https://evil.example.com"
    assert parse_post(data, BASE).skipped_paths


# ------------------------------------------------------------------ HTTP
def _client() -> HttpClient:
    return HttpClient(BASE, "test", request_delay=0.0)


@respx.mock
def test_rate_limit_and_retry_after():
    respx.get(f"{BASE}/api/v1/patreon/user/1/profile").mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(RateLimited) as info:
        PawChiveApi(_client(), BASE).get_profile("patreon", "1")
    assert info.value.retry_after == 120


@respx.mock
def test_forbidden_and_challenge_are_blocked():
    respx.get(f"{BASE}/api/v1/patreon/user/1/profile").mock(return_value=httpx.Response(403, text="Just a moment..."))
    with pytest.raises(AccessBlocked):
        PawChiveApi(_client(), BASE).get_profile("patreon", "1")
    respx.get(f"{BASE}/api/v1/patreon/user/2/profile").mock(
        return_value=httpx.Response(200, text="<html>Just a moment...</html>", headers={"content-type": "text/html"}))
    with pytest.raises(AccessBlocked):
        PawChiveApi(_client(), BASE).get_profile("patreon", "2")


@respx.mock
def test_unauthorized_and_not_found():
    respx.get(f"{BASE}/api/v1/patreon/user/1/profile").mock(return_value=httpx.Response(401))
    respx.get(f"{BASE}/api/v1/patreon/user/2/profile").mock(return_value=httpx.Response(404, json={"error": "x"}))
    api = PawChiveApi(_client(), BASE)
    with pytest.raises(AuthRequired):
        api.get_profile("patreon", "1")
    with pytest.raises(NotFound):
        api.get_profile("patreon", "2")


@respx.mock
def test_cookies_only_sent_to_pawchive():
    route = respx.get(f"{BASE}/api/v1/patreon/user/1/profile").mock(
        return_value=httpx.Response(200, json=load_fixture("profile.json") | {"id": "1"}))
    client = HttpClient(BASE, "test", request_delay=0.0, cookie_provider=lambda: "session=abc")
    PawChiveApi(client, BASE).get_profile("patreon", "1")
    assert route.calls[0].request.headers["Cookie"] == "session=abc"
    assert client._headers_for("https://example.com/x") == {}


def test_pagination_offsets():
    calls = []

    class Client:
        def get_json(self, url, params=None):
            calls.append((params or {}).get("o", 0))
            base = load_fixture("posts_page.json")[0]
            count = 50 if len(calls) < 3 else 7
            return [dict(base, id=str(len(calls) * 1000 + i)) for i in range(count)]

    pages = list(PawChiveApi(Client(), BASE).iter_post_pages("patreon", "82443765"))  # type: ignore[arg-type]
    assert calls == [0, 50, 100] and [len(p) for p in pages] == [50, 50, 7]


def test_retry_after_http_date():
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480 - 60) == pytest.approx(60, abs=1)
    assert parse_retry_after(None) is None
