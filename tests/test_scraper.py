import asyncio
import aiohttp
import sys
import os

sys.path.append(os.getcwd())
from custom_components.skylinewebcams.scraper import SkylineWebcamsScraper


async def main():
    async with aiohttp.ClientSession() as session:
        scraper = SkylineWebcamsScraper(session)

        print("--- Fetching Structure (Continents/Countries) ---")
        # For testing, we can inject a mock if needed, but let's try live
        # (or better, parse the local example.html to avoid network hits)

        # Parse local example.html for structure
        with open("example.html", "r") as f:
            html = f.read()

        # We need to monkeypath _get_soup to return local html for the base_url
        from bs4 import BeautifulSoup

        async def mock_get_soup(url):
            if url == scraper.base_url:
                print("Using local example.html")
                return BeautifulSoup(html, "html.parser")
            # Fallback to real fetch for other URLs if needed (but we probably shouldn't scrape generic pages in test)
            print(f"Fetching real url: {url}")
            return await scraper._get_soup(url)  # Call original logic?

        # Swap method
        original_get_soup = scraper._get_soup
        scraper._get_soup = mock_get_soup

        structure = await scraper.get_structure()
        for continent, countries in structure.items():
            print(f"\n{continent}:")
            for c in countries[:3]:  # Show first 3
                print(f" - {c['name']} ({c['url']})")

        print("\n--- Testing Camera List (Simulated) ---")
        # In example.html, there is a "TOP LIVE CAMS" section.
        # Let's see if get_locations_or_cameras(base_url) finds them in example.html
        cams_result = await scraper.get_locations_or_cameras(scraper.base_url)
        if cams_result["type"] == "list":
            cams = cams_result["items"]
            print(f"Found {len(cams)} items on page:")
            for cam in cams[:5]:
                print(f" - {cam['name']} ({cam['url']})")
        else:
            print(f"Unexpected result type: {cams_result['type']}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
