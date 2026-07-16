"""Structural validation of public/'s hand-authored catalog + manifests.

No network, no geo-builder dependency — pure JSON/shape checks intended to catch
authoring mistakes (bad bbox, a manifestUrl pointing nowhere, a premature "url"
field) fast, in CI, without needing a live Overpass build. Run: pytest tests/ci/test_catalog.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PUBLIC_DIR = REPO_ROOT / "public"
CATALOG_PATH = PUBLIC_DIR / "catalog.json"


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _areas(catalog_payload: dict) -> list[dict]:
    return catalog_payload["areas"]


def _manifest_path(manifest_url: str) -> Path:
    return (CATALOG_PATH.parent / manifest_url.removeprefix("./")).resolve()


def _catalog_areas() -> list[dict]:
    if not CATALOG_PATH.exists():
        return []
    payload = _load_json(CATALOG_PATH)
    if not isinstance(payload, dict):
        return []
    return [area for area in payload.get("areas", []) if isinstance(area, dict)]


def _area_manifest_paths() -> list[Path]:
    """One path per unique area manifest referenced by the catalog."""
    paths: list[Path] = []
    for area in _catalog_areas():
        manifest_url = area.get("manifestUrl")
        if not isinstance(manifest_url, str):
            continue
        manifest_path = _manifest_path(manifest_url)
        if manifest_path not in paths:
            paths.append(manifest_path)
    return paths


@pytest.fixture
def catalog_payload() -> dict:
    if not CATALOG_PATH.exists():
        pytest.fail(f"{CATALOG_PATH.relative_to(REPO_ROOT)} not found")
    payload = _load_json(CATALOG_PATH)
    assert isinstance(payload, dict), f"{CATALOG_PATH.relative_to(REPO_ROOT)} must contain a JSON object"
    return payload


def test_catalog_has_areas(catalog_payload: dict) -> None:
    areas = catalog_payload.get("areas")
    assert isinstance(areas, list), "'areas' must be an array"
    assert len(areas) > 0, "'areas' must not be empty"


def test_area_ids_are_unique(catalog_payload: dict) -> None:
    ids = [a.get("id") for a in _areas(catalog_payload)]
    assert len(ids) == len(set(ids)), f"duplicate area ids: {ids}"


@pytest.mark.parametrize("area", _catalog_areas(), ids=lambda a: a.get("id"))
def test_area_has_required_fields(area: dict) -> None:
    area_id = area.get("id")
    assert isinstance(area_id, str) and area_id, "'id' must be a non-empty string"
    assert isinstance(area.get("name"), str) and area.get("name"), f"{area_id}: 'name' must be a non-empty string"
    for key in ("minRadiusPx", "maxRadiusPx", "liveMapRadiusPx"):
        assert isinstance(area.get(key), (int, float)), f"{area_id}: '{key}' must be a number"


@pytest.mark.parametrize("area", _catalog_areas(), ids=lambda a: a.get("id"))
def test_area_bbox_shape(area: dict) -> None:
    area_id = area.get("id")
    bbox = area.get("bbox")
    assert isinstance(bbox, list) and len(bbox) == 4, f"{area_id}: 'bbox' must be an array of 4 numbers"
    assert all(isinstance(v, (int, float)) for v in bbox), f"{area_id}: bbox values must be numbers"
    west, south, east, north = bbox
    assert west < east, f"{area_id}: bbox west ({west}) must be < east ({east})"
    assert south < north, f"{area_id}: bbox south ({south}) must be < north ({north})"


@pytest.mark.parametrize("area", _catalog_areas(), ids=lambda a: a.get("id"))
def test_area_manifest_url_resolves(area: dict) -> None:
    area_id = area.get("id")
    manifest_url = area.get("manifestUrl")
    assert isinstance(manifest_url, str) and manifest_url, f"{area_id}: 'manifestUrl' must be a non-empty string"
    assert _manifest_path(manifest_url).exists(), f"{area_id}: manifestUrl '{manifest_url}' does not resolve to an existing file"


@pytest.mark.parametrize("area", _catalog_areas(), ids=lambda a: a.get("id"))
def test_area_group_shape(area: dict) -> None:
    area_id = area.get("id")
    if "group" not in area:
        return
    group = area["group"]
    assert isinstance(group, list), f"{area_id}: 'group' must be an array if present"
    assert all(isinstance(g, str) and g for g in group), f"{area_id}: 'group' entries must be non-empty strings"


@pytest.fixture(params=_area_manifest_paths(), ids=lambda p: p.parent.name)
def manifest_payload(request: pytest.FixtureRequest) -> dict:
    path: Path = request.param
    if not path.exists():
        pytest.fail(f"{path.relative_to(REPO_ROOT)} not found")
    payload = _load_json(path)
    assert isinstance(payload, dict), f"{path.relative_to(REPO_ROOT)} must contain a JSON object"
    return payload


def test_manifest_has_layers(manifest_payload: dict) -> None:
    assert isinstance(manifest_payload.get("layers"), list), "'layers' must be an array"


def test_manifest_layers_have_required_keys(manifest_payload: dict) -> None:
    for i, layer in enumerate(manifest_payload["layers"]):
        assert isinstance(layer, dict), f"layers[{i}] must be an object"
        for key in ("id", "name", "type", "visible", "style"):
            assert key in layer, f"layers[{i}] (id={layer.get('id')!r}) missing required key '{key}'"


def test_manifest_layers_have_no_premature_url(manifest_payload: dict) -> None:
    for layer in manifest_payload["layers"]:
        assert "url" not in layer, (
            f"layer {layer.get('id')!r} has a 'url' — 'url' must not be pre-populated on any "
            "hand-authored layer, geo-builder adds it once the file actually exists "
            "(see CLAUDE.md Hard Architecture Rules)"
        )


def test_manifest_aggregation_and_deduping_are_objects(manifest_payload: dict) -> None:
    for key in ("aggregation", "deduping"):
        if key in manifest_payload:
            assert isinstance(manifest_payload[key], dict), f"'{key}' must be an object"
