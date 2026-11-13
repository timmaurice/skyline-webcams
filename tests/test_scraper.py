"""The browse scraper against the pages of the redesigned site.

The redesign of skylinewebcams.com in autumn 2026 dropped the mega menu, the
`subcategories` block and the `tcam` names the scraper looked for, and the
browse flow came back with nothing to choose from. The fixtures under
fixtures/ are the pages as served on 2026-11-13, trimmed to a few entries per
list and stripped of scripts, ads and styling:

- countries.html: /en/webcam.html, the country directory
- country.html: /en/webcam/italia.html, a country with regions
- region.html: /en/webcam/italia/veneto.html, a region with places
- place.html: /en/webcam/italia/veneto/venezia.html, a place with webcams
- camera.html: a webcam's page, broadcasting (Venice - St Mark's Square)
- camera_offline.html: a webcam's page, offline (Rome - Pantheon)

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import pathlib

import aiohttp
import pytest

from custom_components.skylinewebcams.scraper import (
    SkylineWebcamsParseError,
    SkylineWebcamsScraper,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
BASE = "https://www.skylinewebcams.com"


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Serves one page, whatever is asked for, and records what was."""

    def __init__(self, text: str = "", status: int = 200, error=None) -> None:
        self.text = text
        self.status = status
        self.error = error
        self.requested: list[str] = []

    def get(self, url, headers=None):
        self.requested.append(url)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status, self.text)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def scraper_for(text: str, language: str = "en") -> SkylineWebcamsScraper:
    return SkylineWebcamsScraper(FakeSession(text), language)


async def test_the_directory_lists_continents_and_their_countries():
    scraper = scraper_for(fixture("countries.html"))

    structure = await scraper.get_structure()

    assert scraper.session.requested == [f"{BASE}/en/webcam.html"]
    assert list(structure) == ["Americas", "Europe", "Africa", "Asia", "Oceania"]
    assert structure["Europe"] == [
        {"name": "Albania", "url": f"{BASE}/en/webcam/albania.html"},
        {"name": "Austria", "url": f"{BASE}/en/webcam/austria.html"},
        {
            "name": "Bosnia and Herzegovina",
            "url": f"{BASE}/en/webcam/bosnia-and-herzegovina.html",
        },
    ]
    # The TOP Live Cams further down the page are no countries.
    assert all(
        "/webcam/" in c["url"] and c["url"].count("/") == 5
        for countries in structure.values()
        for c in countries
    )


async def test_the_directory_is_asked_for_in_the_chosen_language():
    scraper = scraper_for(fixture("countries.html"), language="de")

    await scraper.get_structure()

    assert scraper.session.requested == [f"{BASE}/de/webcam.html"]


async def test_a_country_lists_its_regions_not_its_webcams():
    page = await scraper_for(fixture("country.html")).get_locations_or_cameras(
        f"{BASE}/en/webcam/italia.html"
    )

    assert page == {
        "type": "list",
        "items": [
            {"name": "Abruzzo", "url": f"{BASE}/en/webcam/italia/abruzzo.html"},
            {
                "name": "Aosta Valley",
                "url": f"{BASE}/en/webcam/italia/valle-daosta.html",
            },
            {"name": "Apulia", "url": f"{BASE}/en/webcam/italia/puglia.html"},
            {"name": "Basilicata", "url": f"{BASE}/en/webcam/italia/basilicata.html"},
        ],
    }


async def test_a_region_lists_its_places_without_the_way_back():
    url = f"{BASE}/en/webcam/italia/veneto.html"
    page = await scraper_for(fixture("region.html")).get_locations_or_cameras(url)

    assert page["type"] == "list"
    assert [item["name"] for item in page["items"]] == ["Belluno", "Padua", "Treviso"]
    assert f"{BASE}/en/webcam/italia.html" not in [i["url"] for i in page["items"]]


async def test_a_place_lists_its_webcams():
    url = f"{BASE}/en/webcam/italia/veneto/venezia.html"
    page = await scraper_for(fixture("place.html")).get_locations_or_cameras(url)

    assert page == {
        "type": "list",
        "items": [
            {
                "name": "Piazza San Marco - Venice",
                "url": f"{BASE}/en/webcam/italia/veneto/venezia/piazza-san-marco.html",
            },
            {
                "name": "Venice - Rialto Bridge",
                "url": f"{BASE}/en/webcam/italia/veneto/venezia/rialto-canal-grande.html",
            },
            {
                "name": "Venice - Grand Canal",
                "url": f"{BASE}/en/webcam/italia/veneto/venezia/canal-grande.html",
            },
        ],
    }


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("camera.html", "Piazza San Marco - Venice Live cam"),
        # No player on it, only the OFFLINE badge - and nearby webcams below,
        # which must not turn it into a list.
        ("camera_offline.html", "Rome - Pantheon Live cam"),
    ],
)
async def test_a_webcams_page_is_a_camera(name, title):
    url = f"{BASE}/en/webcam/some/where.html"
    page = await scraper_for(fixture(name)).get_locations_or_cameras(url)

    assert page == {"type": "camera", "name": title, "url": url}


async def test_an_empty_list_is_a_list():
    """The list is there and empty: nothing to choose, not a broken page."""
    text = (
        '<html><body><section class="section"><h1>Nowhere</h1>'
        '<div class="cams"></div></section></body></html>'
    )
    page = await scraper_for(text).get_locations_or_cameras(f"{BASE}/en/x.html")

    assert page == {"type": "list", "items": []}


# What the scraper looked for before the redesign: none of it is there now.
OLD_LAYOUT = """
<html><body>
<div class="dropdown-menu mega-dropdown-menu"><div class="col-sm-6">
  <div class="continent europe"><strong>EUROPE</strong></div>
  <a href="/en/webcam/italia.html">Italy</a>
</div></div>
<div class="row list"><a href="/en/webcam/x.html"><p class="tcam">X</p></a></div>
</body></html>
"""


@pytest.mark.parametrize(
    "text", [OLD_LAYOUT, "<html><body><h1>Something else</h1></body></html>"]
)
async def test_a_page_the_scraper_does_not_know_is_a_parse_error(text):
    with pytest.raises(SkylineWebcamsParseError):
        await scraper_for(text).get_structure()
    with pytest.raises(SkylineWebcamsParseError):
        await scraper_for(text).get_locations_or_cameras(f"{BASE}/en/x.html")


@pytest.mark.parametrize(
    "session",
    [
        FakeSession(status=503),
        FakeSession(error=aiohttp.ClientError("boom")),
    ],
    ids=["error-status", "network-error"],
)
async def test_a_page_that_does_not_load_is_no_parse_error(session):
    scraper = SkylineWebcamsScraper(session)

    assert await scraper.get_structure() == {}
    assert await scraper.get_locations_or_cameras(f"{BASE}/en/x.html") == {
        "type": "error"
    }
