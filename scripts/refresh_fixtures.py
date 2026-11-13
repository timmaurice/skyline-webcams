"""Refresh tests/fixtures/ from the live site.

    python scripts/refresh_fixtures.py             # rewrite every fixture
    python scripts/refresh_fixtures.py place.html  # only these
    python scripts/refresh_fixtures.py --check     # change nothing, say what moved

Run it when the canary (scripts/canary.py, .github/workflows/canary.yml) reports
that the site's markup has changed and the parser has been adjusted to it: the
tests then run against the pages as they are now. Review the diff before
committing - it is the site's change, line by line - and run the suite.

Needs network access and beautifulsoup4 and aiohttp (requirements_test.txt).
The files are formatted with prettier afterwards if it is installed, as
`npm run check-format` wants them that way.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys

from bs4 import BeautifulSoup

from live_site import FIXTURES, PAGES, FetchError, fetch, make_session, selectors, trim


async def main(names: list[str], check: bool) -> int:
    unknown = [name for name in names if name not in PAGES]
    if unknown:
        print(f"unknown fixture(s): {', '.join(unknown)}; known: {', '.join(PAGES)}")
        return 2

    status = 0
    written: list[str] = []
    async with make_session() as session:
        for name in names or PAGES:
            try:
                live = await fetch(session, PAGES[name])
            except FetchError as err:
                print(f"{name}: not fetched - {err}")
                status = 1
                continue

            old = (FIXTURES / name).read_text(encoding="utf-8")
            gone = sorted(selectors(old) - selectors(live))
            # Only what is gone says something: the live page has more than a
            # trimmed fixture by design (ads, scripts, the footer).
            print(f"{name}: {len(gone)} of the old fixture's selectors gone")
            for selector in gone:
                print(f"    - {selector}")

            soup = BeautifulSoup(live, "html.parser")
            is_offline = soup.select_one(".player.off, .badge-off") is not None
            if name == "camera_offline.html" and not is_offline:
                print(
                    f"{name}: that webcam is broadcasting right now, so its page is "
                    "no offline fixture - kept as it was. Point PAGES at a webcam "
                    "that is offline, or try again later."
                )
                status = 1
                continue
            if name == "camera.html" and is_offline:
                print(f"{name}: that webcam is offline right now - kept as it was.")
                status = 1
                continue

            if not check:
                (FIXTURES / name).write_text(trim(live), encoding="utf-8")
                written.append(name)

    if written:
        prettier = shutil.which("npx")
        if prettier:
            subprocess.run(
                [
                    prettier,
                    "--no-install",
                    "prettier",
                    "--write",
                    *(str(FIXTURES / n) for n in written),
                ],
                check=False,
            )
        else:
            print("npx not found: run `npx prettier --write tests/fixtures` yourself")
        print(f"wrote: {', '.join(written)}")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", help="fixture files (default: all)")
    parser.add_argument("--check", action="store_true", help="only report")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.names, args.check)))
