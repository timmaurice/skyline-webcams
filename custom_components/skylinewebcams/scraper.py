"""Scraper for SkylineWebcams."""

from __future__ import annotations

import logging
from bs4 import BeautifulSoup
import re

_LOGGER = logging.getLogger(__name__)


class SkylineWebcamsScraper:
    """Class to scrape SkylineWebcams pages."""

    def __init__(self, session, language="en"):
        """Initialize the scraper."""
        self.session = session
        self.language = language
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
                return BeautifulSoup(text, "html.parser")
        except Exception as err:
            _LOGGER.error("Error fetching %s: %s", url, err)
            return None

    async def get_structure(self) -> dict:
        """Get the full structure of continents and countries from the homepage."""
        # Use language-specific homepage
        homepage_url = f"{self.base_url}/{self.language}.html"
        soup = await self._get_soup(homepage_url)
        if not soup:
            return {}

        structure = {}

        # The menu is within <div class="dropdown-menu mega-dropdown-menu">
        # Continents are in <div class="continent ..."><strong>...</strong></div>

        mega_menu = soup.find("div", class_="mega-dropdown-menu")
        if not mega_menu:
            return {}

        # Find all continent divs
        continent_divs = mega_menu.find_all("div", class_="continent")

        for cont_div in continent_divs:
            continent_name = cont_div.get_text(strip=True).title()
            structure[continent_name] = []

            # Countries are in sibling divs or parent->siblings
            # Structure in example.html:
            # <div class="col-sm-6 col-md-3">
            #   <div class="continent americas">...</div>
            #   <div class="row">
            #      <div class="col-xs-12 col-md-6"><a href="...">Argentina</a>...</div>

            # Go up to the column container
            col_container = cont_div.find_parent("div", class_=re.compile(r"col-"))
            if not col_container:
                continue

            # Find all links in this container
            # Careful not to pick up other things, mostly <a> tags in this block are countries
            links = col_container.find_all("a", href=True)
            for link in links:
                name = link.get_text(strip=True)
                url = link["href"]
                if not url.startswith("http"):
                    url = (
                        self.base_url + url
                        if url.startswith("/")
                        else f"{self.base_url}/{url}"
                    )

                # Filter out garbage
                if "webcam" in url:
                    structure[continent_name].append({"name": name, "url": url})

        return structure

    async def get_locations_or_cameras(self, url: str) -> dict:
        """
        Fetch a page and return:
        - {"type": "camera", "name": title} if it's a camera page
        - {"type": "list", "items": [...]} if it contains a list of items
        """
        soup = await self._get_soup(url)
        if not soup:
            return {"type": "error"}

        # Check if this IS a camera page
        # It usually has a player div or specific meta tags
        # example.html has <div id="live" class="embed-responsive-item"></div>
        if soup.find("div", id="live") or soup.find("div", id="webcam"):
            # It is a camera
            h1_tag = soup.find("h1")
            title = h1_tag.string.strip() if h1_tag else "Skyline Webcam"
            return {"type": "camera", "name": title, "url": url}

        # Otherwise, scrape for items (Regions or Cameras)
        items = []

        # Strategy 1: Look for "subcategories". These are likely Regions (e.g., Crete, Attica).
        # This prevents picking up cameras when we should be picking a region first.
        subcats = soup.find("div", class_="subcategories")
        if subcats:
            links = subcats.find_all("a", href=True)
            for link in links:
                name = link.get_text(strip=True)
                href = link["href"]
                if not href.startswith("http"):
                    href = (
                        self.base_url + href
                        if href.startswith("/")
                        else f"{self.base_url}/{href}"
                    )
                items.append({"name": name, "url": href})

            return {"type": "list", "items": items}

        # Strategy 2: If no subcategories, look for the main list of cameras/regions.
        # The main list is usually in a div with class "list" (or "row list").
        # We search for the container to avoid sidebar items.

        list_div = soup.find("div", class_="list")
        if list_div:
            # First, try to find region tags (they have class "tag" and "btn-primary")
            # These are used on country pages to show regions
            region_links = list_div.find_all("a", class_="tag")
            if region_links:
                # Found region tags, filter out parent/back links
                # Parent links go up the hierarchy (fewer path segments)
                current_depth = url.rstrip("/").count("/")

                for link in region_links:
                    href = link["href"]
                    # Make href absolute for comparison
                    if not href.startswith("http"):
                        full_href = (
                            self.base_url + href
                            if href.startswith("/")
                            else f"{self.base_url}/{href}"
                        )
                    else:
                        full_href = href

                    # Check if this link goes deeper (child) or up (parent)
                    link_depth = full_href.rstrip("/").count("/")

                    # Only include links that go deeper (children/regions)
                    if link_depth > current_depth:
                        name = link.get_text(strip=True)
                        if name:
                            items.append({"name": name, "url": full_href})

                # If we found valid region links, return them
                if items:
                    return {"type": "list", "items": items}

            # No region tags found (or all were parent links), so this is a region page with cameras
            # Inside the list div, cameras are usually in <a> tags.
            # We can use the presence of "tcam" class inside the link or just all links if structured well.
            # Based on analysis, items are like <a ...><p class="tcam">Name</p></a>

            # Find all children of list_div in order
            for child in list_div.children:
                # Check if this is the "from the web" separator
                if child.name == "div" and child.find("h2"):
                    h2_text = child.find("h2").get_text(strip=True).lower()
                    if "from the web" in h2_text:
                        # Stop here - everything after this is external webcams
                        break

                # Process links
                if child.name == "a" and child.get("href"):
                    link = child
                    # Filter out garbage inside the list if any
                    tcam = link.find(class_="tcam")
                    name = ""
                    if tcam:
                        name = tcam.get_text(strip=True)
                    else:
                        # Fallback if tcam not found but it's a link in the list
                        name = link.get_text(strip=True)

                    href = link["href"]
                    if not href.startswith("http"):
                        href = (
                            self.base_url + href
                            if href.startswith("/")
                            else f"{self.base_url}/{href}"
                        )

                    if name:  # Only add if we found a name
                        items.append({"name": name, "url": href})

            return {"type": "list", "items": items}

        # Fallback Strategy: Old behavior (find anything with class "tcam")
        # But try to exclude specific containers if possible?
        # For now, if we didn't find "subcategories" or "list", maybe the page structure is different.

        cam_links = soup.find_all("a", href=True)
        for link in cam_links:
            # Check if it has a tcam inside
            tcam = link.find(class_="tcam")
            if tcam:
                # Check if this link is inside a "mega-dropdown" or "sidebar" and skip it
                if link.find_parent(class_="mega-dropdown-menu") or link.find_parent(
                    id="sidebar"
                ):
                    continue

                name = tcam.get_text(strip=True)
                href = link["href"]
                if not href.startswith("http"):
                    href = (
                        self.base_url + href
                        if href.startswith("/")
                        else f"{self.base_url}/{href}"
                    )

                items.append({"name": name, "url": href})

        return {"type": "list", "items": items}
