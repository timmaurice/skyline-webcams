"""What the canary and the fixture refresh share: the pages, and fetching them.

The pages are the ones tests/fixtures/ holds a trimmed copy of. Everything here
runs against the live site and needs network access; the unit tests never
import this module.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))

BASE = "https://www.skylinewebcams.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# fixture file -> the live page it is a trimmed copy of. The two webcam pages
# are single webcams, so they can go away or change state: the offline one is
# only a good fixture while the webcam really is offline (the refresh says so).
PAGES = {
    "countries.html": "/en/webcam.html",
    "country.html": "/en/webcam/italia.html",
    "region.html": "/en/webcam/italia/veneto.html",
    "place.html": "/en/webcam/italia/veneto/venezia.html",
    "camera.html": "/en/webcam/italia/veneto/venezia/piazza-san-marco.html",
    "camera_offline.html": "/en/webcam/italia/lazio/roma/pantheon.html",
}

# The scraper and the camera read the page through these; a fixture keeps them
# and nothing else.
_DROP = (
    "script",
    "style",
    "noscript",
    "iframe",
    "ins",
    "link",
    "svg",
    "footer",
    "form",
)
KEEP_PER_LIST = 2
KEEP_CHIPS = 4
KEEP_LINKS = 3


class FetchError(Exception):
    """The site did not give us a page - not the same as a page that changed."""


def make_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": USER_AGENT, "Referer": f"{BASE}/"},
        timeout=aiohttp.ClientTimeout(total=30),
    )


async def fetch(session: aiohttp.ClientSession, path_or_url: str) -> str:
    url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise FetchError(f"{url} answered {response.status}")
            return await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise FetchError(f"{url}: {err!r}") from err


def trim(html: str) -> str:
    """The page as a fixture: only what the integration reads, a few entries.

    Scripts, styles, ads and the footer go; so do all but a few entries of
    every list. The stream of a broadcasting webcam is in a script, so a
    trimmed webcam page has none - that is by design, tests add it back.
    """
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
    for tag in soup.find_all(_DROP):
        tag.decompose()
    head = soup.find("head")
    if head is not None:
        for tag in head.find_all(True):
            if tag.name == "title":
                continue
            if tag.name == "meta" and tag.get("property") in ("og:image", "og:url"):
                continue
            tag.decompose()
    for aside in soup.select("aside.aside-ads"):
        aside.clear()
    for noise in soup.select("div.adbox, header .tools"):
        noise.decompose()
    for logo in soup.select("header a.logo"):
        logo.clear()
    for cams in soup.select("div.cams"):
        for cam in cams.find_all("div", class_="cam", recursive=False)[KEEP_PER_LIST:]:
            cam.decompose()
    for chips in soup.select("nav.chips"):
        links = [a for a in chips.find_all("a") if "back" not in (a.get("class") or [])]
        for link in links[KEEP_CHIPS:]:
            link.decompose()
    for menu in soup.select(".menu-list"):
        for link in menu.find_all("a")[KEEP_LINKS:]:
            link.decompose()
    # Sections that ended up with nothing in them.
    for section in soup.select("section"):
        if not section.get_text(strip=True) and section.find("img") is None:
            section.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr in ("style", "onclick", "data-ad", "nonce") or attr.startswith(
                "data-"
            ):
                del tag[attr]
    text = soup.prettify()
    return re.sub(r"\n{3,}", "\n\n", text)


def selectors(html: str) -> set[str]:
    """The tag.class combinations a page is built from.

    A comparison of these tells a trimmed copy from the live page without
    caring about how many entries either one has, or what they say.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(("script", "style", "noscript", "svg")):
        tag.decompose()
    found = set()
    for tag in soup.find_all(True):
        classes = ".".join(sorted(tag.get("class") or []))
        found.add(f"{tag.name}.{classes}" if classes else tag.name)
    return found
