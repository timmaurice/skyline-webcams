"""Config flow for SkylineWebcams integration."""

from __future__ import annotations

import logging
from typing import Any
import re
import aiohttp
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_URL
from .scraper import SkylineWebcamsScraper

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
    }
)


async def validate_input(hass, data):
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    session = async_get_clientsession(hass)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with session.get(data[CONF_URL], headers=headers) as response:
            if response.status != 200:
                raise ValueError("cannot_connect")
            text = await response.text()

            # Simple check if it looks like a skyline webcam page
            if "skylinewebcams.com" not in data[CONF_URL]:
                raise ValueError("invalid_url")

            # Extract title
            soup = BeautifulSoup(text, "html.parser")
            h1_tag = soup.find("h1")
            title = h1_tag.string.strip() if h1_tag else "Skyline Webcam"

            return {"title": title}

    except aiohttp.ClientError:
        raise ValueError("cannot_connect")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SkylineWebcams."""

    VERSION = 1

    def __init__(self):
        """Initialize flow."""
        self._structure = {}
        self._selected_continent = None
        self._selected_country_url = None
        self._selected_language = "en"  # Default to English

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is not None:
            if user_input.get("action") == "Manual URL":
                return await self.async_step_manual()
            return await self.async_step_language()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="Browse"): vol.In(
                        ["Browse", "Manual URL"]
                    )
                }
            ),
        )

    async def async_step_language(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle language selection."""
        if user_input is not None:
            self._selected_language = user_input["language"]
            return await self.async_step_continent()

        # Language options based on Skylinewebcams available languages
        languages = {
            "en": "English",
            "de": "Deutsch",
            "it": "Italiano",
            "es": "Español",
            "fr": "Français",
            "pl": "Polski",
            "el": "Ελληνικά",
            "hr": "Hrvatski",
            "sl": "Slovenski",
            "ru": "Русский",
            "zh": "简体中文",
        }

        return self.async_show_form(
            step_id="language",
            data_schema=vol.Schema(
                {vol.Required("language", default="en"): vol.In(languages)}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual URL input."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except ValueError as error:
                errors["base"] = str(error)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="manual", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_continent(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle continent selection."""
        errors: dict[str, str] = {}

        # Initialize scraper and fetch structure if not already done
        if not self._structure:
            session = async_get_clientsession(self.hass)
            scraper = SkylineWebcamsScraper(session, self._selected_language)
            try:
                self._structure = await scraper.get_structure()
            except Exception:
                return self.async_abort(reason="cannot_connect")

        if not self._structure:
            return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            self._selected_continent = user_input["continent"]
            return await self.async_step_country()

        continents = list(self._structure.keys())
        return self.async_show_form(
            step_id="continent",
            data_schema=vol.Schema(
                {vol.Required("continent"): vol.In(sorted(continents))}
            ),
            errors=errors,
        )

    async def async_step_country(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle country selection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # Find the URL for the selected country name
            country_name = user_input["country"]
            countries = self._structure[self._selected_continent]
            for c in countries:
                if c["name"] == country_name:
                    self._selected_country_url = c["url"]
                    break
            return await self.async_step_browse(url=self._selected_country_url)

        # Ensure we have continents loaded (should be done)
        if (
            not self._selected_continent
            or self._selected_continent not in self._structure
        ):
            return self.async_abort(reason="unknown")

        countries_list = [
            c["name"] for c in self._structure.get(self._selected_continent, [])
        ]
        return self.async_show_form(
            step_id="country",
            data_schema=vol.Schema(
                {vol.Required("country"): vol.In(sorted(countries_list))}
            ),
            errors=errors,
        )

    async def async_step_browse(
        self, user_input: dict[str, Any] | None = None, url: str | None = None
    ) -> FlowResult:
        """Browse a URL for items or cameras."""
        errors: dict[str, str] = {}

        # If user picked something from the list
        if user_input is not None:
            selection = user_input["selection"]
            return await self.async_step_browse(url=selection)

        # If url is None and no user input, we are lost
        if url is None:
            return self.async_abort(reason="unknown")

        target_url = url
        session = async_get_clientsession(self.hass)
        scraper = SkylineWebcamsScraper(session, self._selected_language)
        try:
            result = await scraper.get_locations_or_cameras(target_url)
        except Exception:
            return self.async_abort(reason="cannot_connect")

        if result.get("type") == "error":
            return self.async_abort(reason="cannot_connect")

        if result.get("type") == "camera":
            # Direct camera hit
            return self.async_create_entry(
                title=result["name"], data={CONF_URL: result["url"]}
            )

        # It is a list
        items = result.get("items", [])
        if not items:
            # This handles cases where a page has no cameras found (scraper should return empty list)
            return self.async_abort(reason="no_items_found")

        options = {item["url"]: item["name"] for item in items}

        return self.async_show_form(
            step_id="browse",
            data_schema=vol.Schema({vol.Required("selection"): vol.In(options)}),
            errors=errors,
        )
