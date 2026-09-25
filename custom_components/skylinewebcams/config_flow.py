"""Config flow for SkylineWebcams integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_URL
from .helpers import unique_id_for_url
from .scraper import SkylineWebcamsScraper

_LOGGER = logging.getLogger(__name__)

ALLOWED_HOST = "skylinewebcams.com"
VALIDATE_TIMEOUT_SECONDS = 15
# What validate_input names an entry whose page has no heading.
DEFAULT_TITLE = "Skyline Webcam"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
    }
)


def is_webcam_url(url: str | None) -> bool:
    """Whether a URL points at SkylineWebcams over HTTP(S).

    Checked before anything is fetched: the previous substring test ran after
    the request, so Home Assistant first fetched whatever host was typed, and
    https://evil.example/?x=skylinewebcams.com passed it afterwards.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host == ALLOWED_HOST or host.endswith("." + ALLOWED_HOST)


async def validate_input(hass, data):
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    url = data[CONF_URL]
    if not is_webcam_url(url):
        raise ValueError("invalid_url")

    session = async_get_clientsession(hass)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with asyncio.timeout(VALIDATE_TIMEOUT_SECONDS):
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise ValueError("cannot_connect")
                text = await response.text()

        # Off the loop: the pages run to hundreds of kilobytes.
        soup = await hass.async_add_executor_job(BeautifulSoup, text, "html.parser")
        h1_tag = soup.find("h1")
        # get_text, not .string: a heading with a child tag has no .string,
        # which used to raise an AttributeError and show "unknown".
        title = h1_tag.get_text(" ", strip=True) if h1_tag else ""
        return {"title": title or DEFAULT_TITLE}

    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise ValueError("cannot_connect")


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SkylineWebcams."""

    # 2: entries are keyed on the normalised id, see async_migrate_entry.
    VERSION = 2

    def __init__(self):
        """Initialize flow."""
        self._structure = {}
        self._selected_continent = None
        self._selected_country_url = None
        self._selected_language = "en"  # Default to English
        # The options of the browse form last shown. A failure further down
        # used to abort the whole flow; with these the form can come back with
        # an error on it instead.
        self._last_browse_options: dict[str, str] | None = None
        self._last_browse_url: str | None = None

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

        return self._show_language_form()

    def _show_language_form(self, errors: dict[str, str] | None = None) -> FlowResult:
        """Show the language form, optionally carrying an error.

        This is where the browse path starts, so it is where it can be picked
        up again after a failure without restarting the whole flow.
        """
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
            errors=errors or {},
        )

    def _show_browse_error(self, error: str) -> FlowResult:
        """Come back with an error on the last form instead of aborting."""
        if self._last_browse_options:
            return self.async_show_form(
                step_id="browse",
                data_schema=vol.Schema(
                    {vol.Required("selection"): vol.In(self._last_browse_options)}
                ),
                errors={"base": error},
            )
        return self._show_language_form({"base": error})

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual URL input."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(unique_id_for_url(user_input[CONF_URL]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)
            except ValueError as error:
                errors["base"] = str(error)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="manual", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Point an existing webcam entry at a different page.

        The URL lives in the entry's data, which no options flow can write, so
        a camera that moved used to mean deleting the entry and adding it
        again - a new entity id, and the history, the cards and the automations
        that named the old one left behind.

        The new URL goes through the same checks the manual step runs, and the
        entry is then updated and reloaded in place. Three things move with the
        URL, because all three are derived from it: the entry's unique id, the
        camera entity's unique id (see _async_move_camera_entity) and the
        device's configuration URL. The device itself is keyed on the entry id
        and stays as it is.
        """
        try:
            entry = self._get_reconfigure_entry()
        except config_entries.UnknownEntry:
            # Deleted while the form was open: core aborts a reauth flow when
            # its entry goes, but leaves a reconfigure flow running.
            return self.async_abort(reason="unknown_entry")

        errors: dict[str, str] = {}
        url: str = entry.data[CONF_URL]
        if user_input is not None:
            url = user_input[CONF_URL]
            try:
                info = await validate_input(self.hass, user_input)
                unique_id = unique_id_for_url(url)
                if self._another_entry_has(entry, unique_id) or (
                    self._camera_id_taken(entry, unique_id)
                ):
                    raise ValueError("already_configured")
                title = await self._async_title_after_move(entry, url, info["title"])
            except ValueError as error:
                errors["base"] = str(error)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if self.hass.config_entries.async_get_entry(entry.entry_id) is None:
                    # Deleted while the pages were being fetched.
                    return self.async_abort(reason="unknown_entry")
                # Nothing is awaited from here on, so the entity row and the
                # entry move together or not at all. No update listener to do
                # it: this reloads the entry, and the camera starts over on
                # the new page straight away.
                self._async_move_camera_entity(entry, unique_id)
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=title,
                    data_updates={CONF_URL: url},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_URL, default=url): str}),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    def _another_entry_has(
        self, entry: config_entries.ConfigEntry, unique_id: str
    ) -> bool:
        """Whether an entry other than `entry` already watches this camera.

        The entry's own camera is fine: entering its URL again, or another
        spelling of it (/de/ for /en/), is how a user reloads it or changes
        the language of its page. Ignored entries count, so that the entry
        cannot take over an id core would then hold twice. The stored URL is
        checked as well as the unique id, for an entry that has not been
        migrated onto the normalised id yet.
        """
        for other in self._async_current_entries(include_ignore=True):
            if other.entry_id == entry.entry_id:
                continue
            if other.unique_id == unique_id:
                return True
            if (other_url := other.data.get(CONF_URL)) and unique_id_for_url(
                other_url
            ) == unique_id:
                return True
        return False

    def _camera_id_taken(
        self, entry: config_entries.ConfigEntry, unique_id: str
    ) -> bool:
        """Whether a camera row that is not this entry's holds the new id.

        A YAML camera for that page, or one left behind by an earlier run.
        Moving onto it is not possible, and letting the reload take it over
        would hand this camera that row's entity id instead of its own. The
        user can delete a leftover row under Settings > Entities and try again.
        """
        if unique_id == entry.unique_id:
            return False
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(CAMERA_DOMAIN, DOMAIN, unique_id)
        if entity_id is None:
            return False
        row = registry.async_get(entity_id)
        return row is None or row.config_entry_id != entry.entry_id

    @callback
    def _async_move_camera_entity(
        self, entry: config_entries.ConfigEntry, unique_id: str
    ) -> None:
        """Carry the entry's camera entity over to the new unique id.

        The camera's unique id is the entry's, the normalised URL, and the
        entity registry keys the entity on it. Reloading the entry with a new
        one would register a second camera - `camera.<title>_2`, with no
        history - and leave the old one behind as "no longer provided". Moving
        the registry row instead keeps its entity id, its history and whatever
        the user set on it, and the reloaded camera finds the row under its new
        id. The row is moved rather than the camera given a stable id of its
        own, because the normalised URL is also what recognises a YAML camera
        and a UI entry for the same page as one camera, and what the unique id
        migration of every existing camera is built on.
        """
        if unique_id == entry.unique_id:
            return

        registry = er.async_get(self.hass)
        for row in er.async_entries_for_config_entry(registry, entry.entry_id):
            if row.domain == CAMERA_DOMAIN and row.unique_id == entry.unique_id:
                _LOGGER.debug(
                    "Moving %s from unique id %s to %s",
                    row.entity_id,
                    row.unique_id,
                    unique_id,
                )
                registry.async_update_entity(row.entity_id, new_unique_id=unique_id)

    async def _async_title_after_move(
        self, entry: config_entries.ConfigEntry, url: str, page_title: str
    ) -> str:
        """The entry's title once it watches `url`.

        A title the user chose stays. One the flow chose - the heading of the
        page it was added from, or the default for a page without one - is
        replaced by the new page's heading, or the entry of a camera that moved
        from Venice to Rome would go on being called Venice. The entry does not
        record which kind its title is, so the old page is asked for its
        heading; if it cannot be reached any more, the title is kept, which is
        the safe side to be wrong on.
        """
        if entry.title == page_title:
            return entry.title
        if entry.title == DEFAULT_TITLE:
            return page_title

        old_url = entry.data[CONF_URL]
        if old_url == url:
            # The same page: it cannot say what it was called when it was
            # added, only what it is called now, which is not the title.
            return entry.title
        try:
            old_info = await validate_input(self.hass, {CONF_URL: old_url})
        except Exception:  # noqa: BLE001 - only decides the title
            _LOGGER.debug("Keeping the title of %s: %s is gone", entry.title, old_url)
            return entry.title
        return page_title if entry.title == old_info["title"] else entry.title

    async def async_step_continent(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle continent selection."""
        errors: dict[str, str] = {}

        # Initialize scraper and fetch structure if not already done
        if not self._structure:
            session = async_get_clientsession(self.hass)
            scraper = SkylineWebcamsScraper(session, self._selected_language, self.hass)
            try:
                self._structure = await scraper.get_structure()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Failed to load the webcam directory")
                return self._show_language_form({"base": "cannot_connect"})

        if not self._structure:
            return self._show_language_form({"base": "cannot_connect"})

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
        scraper = SkylineWebcamsScraper(session, self._selected_language, self.hass)
        try:
            result = await scraper.get_locations_or_cameras(target_url)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Failed to browse %s", target_url)
            return self._show_browse_error("cannot_connect")

        if result.get("type") == "error":
            return self._show_browse_error("cannot_connect")

        if result.get("type") == "camera":
            # Direct camera hit
            await self.async_set_unique_id(unique_id_for_url(result["url"]))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=result["name"], data={CONF_URL: result["url"]}
            )

        # It is a list
        items = result.get("items", [])
        if not items:
            # A page that lists neither cameras nor sub-regions. Show the list
            # the user came from again, so another branch can be tried.
            return self._show_browse_error("no_items_found")

        options = {item["url"]: item["name"] for item in items}
        self._last_browse_options = options
        self._last_browse_url = target_url

        return self.async_show_form(
            step_id="browse",
            data_schema=vol.Schema({vol.Required("selection"): vol.In(options)}),
            errors=errors,
        )
