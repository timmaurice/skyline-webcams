"""The canary's exit status: 0 fine, 1 markup changed, 2 site out of reach.

A rate limit (429) or a server error is the site being out of reach, not its
markup changing. The scraper turns any error status into "no page", so without
a check of its own the canary reported a 429 as a changed markup.
"""

from __future__ import annotations

import sys
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import canary  # noqa: E402
import live_site  # noqa: E402


class _Response:
    def __init__(self, status: int, text: str = "") -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _Session:
    """Answers every request with one status, or raises."""

    def __init__(self, status: int = 200, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.requests: list[str] = []

    def get(self, url: str, **kwargs) -> _Response:
        self.requests.append(url)
        if self.error is not None:
            raise self.error
        return _Response(self.status, "<html></html>")

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *exc) -> None:
        return None


async def _main_with(monkeypatch, session: _Session) -> int:
    monkeypatch.setattr(canary, "make_session", lambda: session)
    return await canary.main()


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_rate_limit_and_server_errors_mean_unreachable(
    monkeypatch, capsys, status
):
    session = _Session(status)
    assert await _main_with(monkeypatch, session) == 2
    assert "could not reach the site" in capsys.readouterr().out
    # It stops at the first answer instead of hammering a rate limited site.
    assert len(session.requests) == 1


async def test_a_network_error_means_unreachable(monkeypatch):
    session = _Session(error=aiohttp.ClientConnectionError("down"))
    assert await _main_with(monkeypatch, session) == 2


async def test_a_missing_page_means_the_markup_changed(monkeypatch, capsys):
    assert await _main_with(monkeypatch, _Session(404)) == 1
    assert "not with the page" in capsys.readouterr().out


async def test_a_page_the_parser_finds_nothing_in_fails_with_1(monkeypatch):
    # 200 with an empty page: reached the site, found nothing.
    assert await _main_with(monkeypatch, _Session(200)) == 1


async def test_the_live_pages_are_fetched_once_each(monkeypatch):
    session = _Session(200)
    await _main_with(monkeypatch, session)
    assert sorted(session.requests) == sorted(
        live_site.BASE + path for path in live_site.PAGES.values()
    )
