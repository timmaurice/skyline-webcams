"""What ends up in the HACS zip, and what the manifests declare.

The release workflow zips the integration folder with two exclusions, so debug
notes, a 2.4 MB screenshot and the test suite were downloaded by every HACS
user. These check the folder and the exclusion list together.
"""

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = REPO / "custom_components" / "skylinewebcams"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

# Everything a user needs at runtime: the integration itself, its translations
# and the bundled card. The brand images belong to the HA brands repository,
# not to a user's config folder.
SHIPPABLE_SUFFIXES = {".py", ".json", ".js"}


def zip_excludes() -> list[str]:
    """The -x patterns the release workflow passes to zip."""
    text = RELEASE_WORKFLOW.read_text()
    match = re.search(r"zip -r \.\./\.\./skylinewebcams\.zip \.(.*?)\n\n", text, re.S)
    assert match, "could not find the zip step in the release workflow"
    return re.findall(r'"([^"]+)"', match.group(1))


def matches(pattern: str, path: str) -> bool:
    """Apply one zip -x pattern the way zip does.

    zip lets * cross directory separators, which fnmatch does not, so the
    pattern is translated by hand.
    """
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, path) is not None


def packaged_files() -> list[str]:
    """Paths, relative to the integration folder, that survive the exclusions."""
    excludes = zip_excludes()
    files = []
    for path in sorted(COMPONENT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(COMPONENT).as_posix()
        if any(matches(pattern, relative) for pattern in excludes):
            continue
        files.append(relative)
    return files


def test_no_debug_artefacts_in_the_integration_folder():
    """A 2.4 MB screenshot and the debug notes are documentation, not code."""
    stray = [
        path.relative_to(REPO).as_posix()
        for path in COMPONENT.rglob("*")
        if path.is_file()
        and (path.suffix == ".md" or path.name == "debug.png" or "tests" in path.parts)
    ]
    assert stray == []


def test_the_zip_would_not_ship_tests_or_docs():
    packaged = packaged_files()

    assert packaged, "the exclusion list swallowed the whole integration"
    assert not [name for name in packaged if name.endswith(".md")]
    assert not [name for name in packaged if "tests/" in name]
    assert not [name for name in packaged if "__pycache__" in name]
    assert "manifest.json" in packaged
    assert "camera.py" in packaged
    assert "skyline-webcams-card.js" in packaged


def test_only_runtime_file_types_are_packaged():
    unexpected = [
        name
        for name in packaged_files()
        if pathlib.Path(name).suffix not in SHIPPABLE_SUFFIXES
    ]
    assert unexpected == []


def test_hacs_declares_a_minimum_core_version():
    hacs = json.loads((REPO / "hacs.json").read_text())
    assert "homeassistant" in hacs


def test_the_manifest_declares_its_type_and_loggers():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["integration_type"] == "service"
    assert manifest["loggers"] == ["bs4"]
