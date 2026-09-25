"""The translation files have to carry the same keys as strings.json.

Home Assistant falls back to English for a key a language lacks, so a missing
German key does not fail anywhere - it just shows English in a German UI. A key
only the German file has is dead weight nobody notices either.
"""

import json
import pathlib

import pytest

COMPONENT = (
    pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "skylinewebcams"
)
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))


def keys(tree: dict, prefix: str = "") -> set[str]:
    """Every leaf of a translation tree, as a dotted path."""
    found: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            found |= keys(value, f"{path}.")
        else:
            found.add(path)
    return found


def test_there_are_translations_to_check():
    assert [path.name for path in TRANSLATIONS] == ["de.json", "en.json"]


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda path: path.name)
def test_every_language_has_the_keys_of_strings_json(path):
    assert keys(json.loads(path.read_text())) == keys(STRINGS)


def test_english_is_strings_json():
    """en.json is what a custom integration ships in place of strings.json."""
    english = json.loads((COMPONENT / "translations" / "en.json").read_text())
    assert english == STRINGS
