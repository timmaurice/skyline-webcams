"""The reconfigure flow: moving a webcam entry to a new URL in place.

Moving a camera used to mean deleting its entry and adding it again, which
minted a new entity id and left the history, the cards and the automations
that named the old one behind. What these tests hold on to is that a
reconfigure changes where the camera looks and nothing the user relies on:
the entity id, the device, and a title the user chose.

The flow runs through Home Assistant's flow manager against an entry that is
set up the real way (see conftest.py). The pages are served by a fake session
keyed on the URL, so the suite stays offline.
"""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.skylinewebcams import config_flow
from custom_components.skylinewebcams.const import CONF_URL, DOMAIN
from custom_components.skylinewebcams.helpers import unique_id_for_url

from .conftest import CAMERA_URL, _no_scrape, make_entry

NEW_URL = CAMERA_URL.replace("schloss-neuschwanstein", "hohenschwangau")


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
    """Serves a heading per URL; anything else is a network error."""

    def __init__(self, pages: dict[str, str | int]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url, headers=None):
        self.requested.append(url)
        page = self.pages.get(url)
        if page is None:
            raise aiohttp.ClientError(f"no route to {url}")
        if isinstance(page, int):
            return FakeResponse(page, "")
        return FakeResponse(200, f"<html><h1>{page}</h1></html>")


@pytest.fixture
def pages(monkeypatch) -> FakeSession:
    session = FakeSession({CAMERA_URL: "Neuschwanstein", NEW_URL: "Hohenschwangau"})
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: session)
    return session


@pytest.fixture
async def entry(hass, setup_entry) -> MockConfigEntry:
    """An entry as the flow writes it: titled after its page, keyed on its URL."""
    entry = make_entry(hass, unique_id=unique_id_for_url(CAMERA_URL))
    await setup_entry(entry)
    return entry


async def reconfigure(hass, entry: MockConfigEntry, url: str) -> dict:
    """Open the reconfigure form, submit `url`, and let any reload finish."""
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    with _no_scrape():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: url}
        )
        await hass.async_block_till_done()
    return result


def camera_rows(hass, entry: MockConfigEntry) -> list[er.RegistryEntry]:
    return er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)


async def test_the_form_starts_from_the_current_url(hass, entry, pages):
    result = await entry.start_reconfigure_flow(hass)

    assert result["type"] == "form"
    assert result["description_placeholders"] == {"name": "Neuschwanstein"}
    [field] = result["data_schema"].schema
    assert field.default() == CAMERA_URL


async def test_the_entry_moves_and_its_camera_stays(hass, entry, pages):
    [device_before] = dr.async_entries_for_config_entry(
        dr.async_get(hass), entry.entry_id
    )

    result = await reconfigure(hass, entry, NEW_URL)

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_URL] == NEW_URL
    assert entry.unique_id == unique_id_for_url(NEW_URL)

    # The same registry row, under the new id: same entity id, so the same
    # history. Without the move the reload would register camera.*_2 beside
    # an orphaned camera.neuschwanstein.
    [row] = camera_rows(hass, entry)
    assert row.entity_id == "camera.neuschwanstein"
    assert row.unique_id == unique_id_for_url(NEW_URL)
    assert hass.states.get("camera.neuschwanstein") is not None
    assert hass.states.get("camera.neuschwanstein_2") is None
    assert entry.runtime_data.camera.unique_id == unique_id_for_url(NEW_URL)
    assert entry.runtime_data.camera.entity_id == "camera.neuschwanstein"

    # The device is keyed on the entry id, so it is the same device; only its
    # link to the page follows the URL.
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.id == device_before.id
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.configuration_url == NEW_URL
    assert row.device_id == device.id


async def test_a_title_the_flow_chose_follows_the_page(hass, entry, pages):
    await reconfigure(hass, entry, NEW_URL)

    assert entry.title == "Hohenschwangau"
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.name == "Hohenschwangau"


async def test_a_title_the_user_chose_is_kept(hass, entry, pages):
    hass.config_entries.async_update_entry(entry, title="The castle")
    await hass.async_block_till_done()

    await reconfigure(hass, entry, NEW_URL)

    assert entry.title == "The castle"
    assert entry.data[CONF_URL] == NEW_URL


async def test_the_title_is_kept_when_the_old_page_is_gone(hass, entry, pages):
    """The old heading cannot be asked for, so the title may be the user's."""
    del pages.pages[CAMERA_URL]

    result = await reconfigure(hass, entry, NEW_URL)

    assert result["reason"] == "reconfigure_successful"
    assert entry.title == "Neuschwanstein"


async def test_the_default_title_follows_the_page(hass, entry, pages):
    hass.config_entries.async_update_entry(entry, title=config_flow.DEFAULT_TITLE)
    await hass.async_block_till_done()

    await reconfigure(hass, entry, NEW_URL)

    assert entry.title == "Hohenschwangau"


@pytest.mark.parametrize(
    "url",
    [
        CAMERA_URL,
        # Another spelling of the same camera: the German page, say.
        CAMERA_URL.replace("/en/", "/de/"),
    ],
)
async def test_the_entrys_own_camera_is_accepted(hass, entry, pages, url):
    pages.pages[CAMERA_URL.replace("/en/", "/de/")] = "Schloss Neuschwanstein"

    result = await reconfigure(hass, entry, url)

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_URL] == url
    assert entry.unique_id == unique_id_for_url(CAMERA_URL)
    [row] = camera_rows(hass, entry)
    assert row.entity_id == "camera.neuschwanstein"
    assert row.unique_id == unique_id_for_url(CAMERA_URL)


async def test_a_camera_another_entry_has_is_refused(hass, entry, pages):
    other = make_entry(
        hass, title="Hohenschwangau", url=NEW_URL, unique_id=unique_id_for_url(NEW_URL)
    )

    # The other entry's camera under another spelling of its URL.
    pages.pages[NEW_URL.replace("/en/", "/de/")] = "Hohenschwangau"

    result = await reconfigure(hass, entry, NEW_URL.replace("/en/", "/de/"))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    assert entry.data[CONF_URL] == CAMERA_URL
    assert entry.unique_id == unique_id_for_url(CAMERA_URL)
    assert other.unique_id == unique_id_for_url(NEW_URL)
    [row] = camera_rows(hass, entry)
    assert row.unique_id == unique_id_for_url(CAMERA_URL)


async def test_a_camera_row_that_is_not_the_entrys_is_refused(hass, entry, pages):
    """A YAML camera for the page, or one left behind by an earlier run.

    Taking its id over would hand the reloaded camera that row's entity id.
    """
    er.async_get(hass).async_get_or_create(
        "camera", DOMAIN, unique_id_for_url(NEW_URL), suggested_object_id="leftover"
    )

    result = await reconfigure(hass, entry, NEW_URL)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    assert entry.data[CONF_URL] == CAMERA_URL
    [row] = camera_rows(hass, entry)
    assert row.unique_id == unique_id_for_url(CAMERA_URL)


@pytest.mark.parametrize(
    ("url", "page", "error"),
    [
        # Refused before anything is fetched, as in the manual step.
        ("https://evil.example/?x=skylinewebcams.com", None, "invalid_url"),
        ("not a url", None, "invalid_url"),
        (NEW_URL, None, "cannot_connect"),
        (NEW_URL, 404, "cannot_connect"),
    ],
)
async def test_a_url_that_does_not_validate_changes_nothing(
    hass, entry, pages, url, page, error
):
    pages.pages.pop(NEW_URL)
    if page is not None:
        pages.pages[url] = page

    result = await reconfigure(hass, entry, url)

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": error}
    assert entry.data[CONF_URL] == CAMERA_URL
    assert entry.unique_id == unique_id_for_url(CAMERA_URL)
    assert entry.title == "Neuschwanstein"
    [row] = camera_rows(hass, entry)
    assert row.unique_id == unique_id_for_url(CAMERA_URL)
    if error == "invalid_url":
        assert url not in pages.requested


async def test_the_form_comes_back_after_an_error(hass, entry, pages):
    """The error is on the form, not an abort: the user can correct the URL."""
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "https://evil.example/"}
    )
    assert result["errors"] == {"base": "invalid_url"}

    with _no_scrape():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: NEW_URL}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_URL] == NEW_URL


async def test_a_deleted_entry_aborts(hass, entry, pages):
    """Core leaves a reconfigure flow open when its entry is removed."""
    result = await entry.start_reconfigure_flow(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: NEW_URL}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "unknown_entry"
