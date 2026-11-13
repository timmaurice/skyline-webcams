"""Scraper for SkylineWebcams."""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

_LOGGER = logging.getLogger(__name__)

# What marks a webcam's own page. #live holds the player of a webcam that is
# broadcasting; an offline webcam's page has no #live, only the player box with
# the OFFLINE badge in it, so the layout around the player counts as well.
# #webcam is from the layout before the 2026 redesign.
CAMERA_PAGE_SELECTOR = "#live, #webcam, div.cam-main, div.thumb.player"


class SkylineWebcamsParseError(Exception):
    """A page loaded, but nothing on it is where the scraper looks.

    Not the same as a page that lists nothing: that one has the list, it is
    just empty. This one most likely means the site changed its markup, and
    the user should hear that rather than get an empty list.
    """


class SkylineWebcamsScraper:
    """Class to scrape SkylineWebcams pages."""

    def __init__(self, session, language="en", hass=None):
        """Initialize the scraper.

        `hass` is optional only so the scraper stays usable without it; when it
        is there the HTML is parsed in an executor instead of on the loop.
        """
        self.session = session
        self.language = language
        self.hass = hass
        self.base_url = "https://www.skylinewebcams.com"

    async def _get_soup(self, url: str) -> BeautifulSoup | None:
        """Fetch page and return BeautifulSoup object."""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            async with self.session.get(url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error("Failed to fetch %s: %s", url, response.status)
                    return None
                text = await response.text()
                return await self._parse(text)
        except Exception as err:
            _LOGGER.error("Error fetching %s: %s", url, err)
            return None

    async def _parse(self, text: str) -> BeautifulSoup:
        """Parse HTML off the event loop where possible.

        html.parser on a directory page of a few hundred kilobytes is slow
        enough to stall the loop while a config flow is open.
        """
        if self.hass is None:
            return BeautifulSoup(text, "html.parser")
        return await self.hass.async_add_executor_job(
            BeautifulSoup, text, "html.parser"
        )

    def _absolute(self, href: str) -> str:
        return urljoin(self.base_url + "/", href)

    async def get_structure(self) -> dict:
        """Get the continents and their countries from the country directory.

        The directory is /<language>/webcam.html. Each continent is a
        `div.menu` inside `div.continents`, named by its `h2.menu-nm`, with
        the countries as plain links in its `div.menu-list`.

        Returns {} when the page cannot be fetched, and raises
        SkylineWebcamsParseError when it can but holds no continent.
        """
        url = f"{self.base_url}/{self.language}/webcam.html"
        soup = await self._get_soup(url)
        if not soup:
            return {}

        structure: dict[str, list[dict[str, str]]] = {}
        for menu in soup.select("div.continents div.menu"):
            heading = menu.find(class_="menu-nm")
            if heading is None:
                continue
            continent = heading.get_text(strip=True).title()
            countries = [
                {"name": name, "url": self._absolute(link["href"])}
                for link in menu.select(".menu-list a[href]")
                if (name := link.get_text(strip=True)) and "/webcam/" in link["href"]
            ]
            if continent and countries:
                structure[continent] = countries

        if not structure:
            _LOGGER.error("Found no continents on %s, has the page changed?", url)
            raise SkylineWebcamsParseError(url)
        return structure

    async def get_locations_or_cameras(self, url: str) -> dict:
        """
        Fetch a page and return:
        - {"type": "camera", "name": title, "url": url} for a webcam's page
        - {"type": "list", "items": [...]} for a country, region or place
        - {"type": "error"} when the page cannot be fetched

        A page that is neither raises SkylineWebcamsParseError.
        """
        soup = await self._get_soup(url)
        if not soup:
            return {"type": "error"}
        return self.parse_page(soup, url)

    def parse_page(self, soup: BeautifulSoup, url: str) -> dict:
        """Tell a webcam's page from a list, and read the list.

        A list page has its heading in a `section`, followed by `nav.chips` -
        the sub-regions, plus a `.back` chip to the parent - and `div.cams`,
        every webcam below this level, each named by its `.cam-title` link.
        Sub-regions come first: offering the 900 webcams of a country in one
        list would make the regions pointless.
        """
        if soup.select_one(CAMERA_PAGE_SELECTOR) is not None:
            h1_tag = soup.find("h1")
            title = h1_tag.get_text(" ", strip=True) if h1_tag else ""
            return {"type": "camera", "name": title or "Skyline Webcam", "url": url}

        # The section the heading is in, so that lists further down the page
        # - nearby webcams, trending ones - are not taken for this one.
        h1_tag = soup.find("h1")
        scope: Tag = (h1_tag and h1_tag.find_parent("section")) or soup
        chips = scope.select_one("nav.chips")
        cams = scope.select_one("div.cams")
        if chips is None and cams is None:
            _LOGGER.error("Found neither regions nor webcams on %s", url)
            raise SkylineWebcamsParseError(url)

        regions = self._regions(chips, url) if chips is not None else []
        if regions:
            return {"type": "list", "items": regions}
        return {
            "type": "list",
            "items": self._cameras(cams) if cams is not None else [],
        }

    def _regions(self, chips: Tag, url: str) -> list[dict[str, str]]:
        """The chips that lead further down, not the one back up."""
        depth = self._absolute(url).rstrip("/").count("/")
        items: list[dict[str, str]] = []
        for link in chips.select("a[href]"):
            if "back" in (link.get("class") or []):
                continue
            href = self._absolute(link["href"])
            name = link.get_text(strip=True)
            if name and href.rstrip("/").count("/") > depth:
                items.append({"name": name, "url": href})
        return items

    def _cameras(self, cams: Tag) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for title in cams.select(".cam-title"):
            link = title if title.name == "a" else title.find_parent("a")
            if link is None or not link.get("href"):
                continue
            href = self._absolute(link["href"])
            name = title.get_text(strip=True)
            if name and href not in seen:
                seen.add(href)
                items.append({"name": name, "url": href})
        return items
