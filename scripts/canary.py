"""Canary: run the integration's parsers against the live SkylineWebcams site.

    python scripts/canary.py

The unit tests run on trimmed copies of the pages, so they stay green when the
site changes its markup. This is the check that does not: it fetches the
directory and one page of every kind (country, region, place, a broadcasting
webcam, an offline one), runs the scraper and the camera's own page reading on
them, and fails loudly when they find nothing. For the list pages it also
compares the page's markup with the fixture of it, so a change that the parser
happens to survive still shows up.

Exit status: 0 all fine, 1 the markup changed (or a parser found nothing),
2 the site could not be fetched, which says nothing about the markup.
Runs weekly in .github/workflows/canary.yml. When it fails because the markup
moved, fix the parser, then `python scripts/refresh_fixtures.py`.
"""

from __future__ import annotations

import asyncio
import sys
import types

from live_site import (
    BASE,
    FIXTURES,
    PAGES,
    FetchError,
    fetch,
    make_session,
    selectors,
)

from custom_components.skylinewebcams.camera import SkylineWebcamsCamera
from custom_components.skylinewebcams.scraper import (
    SkylineWebcamsParseError,
    SkylineWebcamsScraper,
)

# Where the live pages are looked at: the fixture pages. The webcam pages are
# single webcams; if one has gone, the canary says so rather than guessing.
LIST_PAGES = ("countries.html", "country.html", "region.html", "place.html")
CAMERA_PAGES = ("camera.html", "camera_offline.html")


class _Executor:
    """The one thing a camera asks of `hass` while it reads a page."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def fail(problem: str, failures: list[str]) -> None:
    print(f"  FAIL {problem}")
    failures.append(problem)


async def check_lists(session, scraper, failures: list[str]) -> None:
    structure = await scraper.get_structure()
    countries = sum(len(c) for c in structure.values())
    print(f"directory: {len(structure)} continents, {countries} countries")
    if len(structure) < 4 or countries < 30:
        fail(
            f"the directory lists {len(structure)} continents / {countries} "
            "countries, expected at least 4 / 30",
            failures,
        )

    for name, minimum, what in (
        ("country.html", 5, "regions"),
        ("region.html", 3, "places"),
        ("place.html", 3, "webcams"),
    ):
        url = BASE + PAGES[name]
        try:
            page = await scraper.get_locations_or_cameras(url)
        except SkylineWebcamsParseError:
            fail(f"{url}: neither {what} nor anything else found", failures)
            continue
        items = page.get("items", [])
        print(f"{name}: {page.get('type')}, {len(items)} {what}")
        if page.get("type") != "list" or len(items) < minimum:
            fail(
                f"{url} gave {page.get('type')} with {len(items)} {what}, "
                f"expected a list of at least {minimum}",
                failures,
            )
        elif not all(i["name"] and i["url"].startswith("https://") for i in items):
            fail(f"{url}: an entry without a name or link", failures)

    # The markup, as opposed to what the parser makes of it.
    for name in LIST_PAGES:
        fixture = selectors((FIXTURES / name).read_text(encoding="utf-8"))
        live = selectors(await fetch(session, PAGES[name]))
        gone = sorted(fixture - live)
        # What the live page has beyond the fixture is the trimming (ads,
        # scripts, footer), so only what is gone counts.
        print(f"{name}: markup, {len(gone)} of the fixture's selectors gone")
        for selector in gone:
            print(f"    - {selector}")
        if gone:
            fail(f"{name}: the live page no longer has {', '.join(gone)}", failures)


async def check_cameras(session, scraper, failures: list[str]) -> None:
    for name in CAMERA_PAGES:
        url = BASE + PAGES[name]
        page = await scraper.get_locations_or_cameras(url)
        if page.get("type") != "camera" or page.get("name") == "Skyline Webcam":
            fail(f"{url} is not read as a webcam page: {page}", failures)
            continue

        camera = SkylineWebcamsCamera(
            hass=types.SimpleNamespace(
                async_add_executor_job=_Executor().async_add_executor_job
            ),
            url=url,
            name=name,
            unique_id=name,
            entry_id=name,
        )
        camera._session = session
        stream = await camera._fetch_stream_url()
        attrs = camera._additional_attributes
        print(
            f"{name}: {page['name']!r}, "
            f"{'stream' if stream else 'offline' if camera.offline else 'no stream'}, "
            f"{attrs.get('country')} / {attrs.get('region')} / {attrs.get('place')}"
        )

        if not stream and not camera.offline:
            fail(f"{url} has neither a stream nor an OFFLINE marker", failures)
        for key in ("poster", "country", "region", "place"):
            if not attrs.get(key):
                fail(f"{url}: no {key} read from the page", failures)


async def main() -> int:
    failures: list[str] = []
    try:
        async with make_session() as session:
            scraper = SkylineWebcamsScraper(session)
            await check_lists(session, scraper, failures)
            await check_cameras(session, scraper, failures)
    except FetchError as err:
        print(f"\ncould not reach the site, nothing is known about its markup: {err}")
        return 2

    if failures:
        print("\nCANARY FAILED - the site's markup has most likely changed:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nFix the parser, then run scripts/refresh_fixtures.py.")
        return 1
    print("\nok: the parsers still read the live site.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
