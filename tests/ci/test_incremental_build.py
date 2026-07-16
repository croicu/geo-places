"""Unit tests for scripts/prepare_incremental_build.py's pure logic.

No network: fetch_url is monkeypatched wherever a "previous deploy" response is
needed. Fingerprinting uses `git hash-object`, which works on any file on disk
regardless of repo tracking, so these use plain tmp_path fixtures rather than a
real git checkout. Run: pytest tests/ci/test_incremental_build.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import prepare_incremental_build as pib  # noqa: E402


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f)


@pytest.fixture
def public_dir(tmp_path: Path) -> Path:
    public = tmp_path / "public"
    catalog = {
        "version": "1.0",
        "areas": [
            {
                "id": "prague",
                "name": "Prague",
                "bbox": [14.0, 50.0, 14.1, 50.1],
                "minRadiusPx": 32,
                "maxRadiusPx": 512,
                "liveMapRadiusPx": 640,
                "manifestUrl": "./areas/prague/manifest.json",
            },
            {
                "id": "berlin",
                "name": "Berlin",
                "bbox": [13.0, 52.0, 13.1, 52.1],
                "minRadiusPx": 32,
                "maxRadiusPx": 512,
                "liveMapRadiusPx": 640,
                "manifestUrl": "./areas/berlin/manifest.json",
            },
        ],
    }
    _write_json(public / "catalog.json", catalog)
    _write_json(public / "areas/prague/manifest.json", {"version": 1, "layers": [], "aggregation": {}, "deduping": {}})
    _write_json(public / "areas/berlin/manifest.json", {"version": 1, "layers": [], "aggregation": {}, "deduping": {}})
    _write_json(tmp_path / "template.json", {"layers": []})
    _write_json(tmp_path / "settings.json", {"settings": {}, "providers": {}})
    return public


def _fingerprints(public_dir: Path, tmp_path: Path) -> dict[str, str]:
    catalog = pib.load_json(public_dir / "catalog.json")
    return pib.compute_current_fingerprints(catalog, public_dir, tmp_path / "template.json", tmp_path / "settings.json")


def test_identical_fingerprints_yield_empty_rebuild_set(public_dir: Path, tmp_path: Path) -> None:
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(None, current, current, ["prague", "berlin"])
    assert rebuild == []


def test_changed_manifest_rebuilds_only_that_area(public_dir: Path, tmp_path: Path) -> None:
    baseline = _fingerprints(public_dir, tmp_path)
    _write_json(public_dir / "areas/prague/manifest.json", {"version": 1, "layers": [{"id": "1"}], "aggregation": {}, "deduping": {}})
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(None, current, baseline, ["prague", "berlin"])
    assert rebuild == ["prague"]


def test_changed_bbox_rebuilds_only_that_area(public_dir: Path, tmp_path: Path) -> None:
    baseline = _fingerprints(public_dir, tmp_path)
    catalog_path = public_dir / "catalog.json"
    catalog = pib.load_json(catalog_path)
    catalog["areas"][1]["bbox"] = [13.0, 52.0, 13.2, 52.2]
    _write_json(catalog_path, catalog)
    current = pib.compute_current_fingerprints(catalog, public_dir, tmp_path / "template.json", tmp_path / "settings.json")
    rebuild = pib.resolve_rebuild_set(None, current, baseline, ["prague", "berlin"])
    assert rebuild == ["berlin"]


def test_changed_template_forces_full_rebuild(public_dir: Path, tmp_path: Path) -> None:
    baseline = _fingerprints(public_dir, tmp_path)
    _write_json(tmp_path / "template.json", {"layers": [{"id": "__poi__"}]})
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(None, current, baseline, ["prague", "berlin"])
    assert set(rebuild) == {"prague", "berlin"}


def test_missing_baseline_rebuilds_everything(public_dir: Path, tmp_path: Path) -> None:
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(None, current, {}, ["prague", "berlin"])
    assert set(rebuild) == {"prague", "berlin"}


def test_explicit_areas_override_diff(public_dir: Path, tmp_path: Path) -> None:
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(["berlin"], current, current, ["prague", "berlin"])
    assert rebuild == ["berlin"]


def test_explicit_all_expands_to_every_catalog_area(public_dir: Path, tmp_path: Path) -> None:
    current = _fingerprints(public_dir, tmp_path)
    rebuild = pib.resolve_rebuild_set(["all"], current, current, ["prague", "berlin"])
    assert set(rebuild) == {"prague", "berlin"}


def test_explicit_unknown_area_id_raises(public_dir: Path, tmp_path: Path) -> None:
    current = _fingerprints(public_dir, tmp_path)
    with pytest.raises(pib.PrepareError, match="nonexistent"):
        pib.resolve_rebuild_set(["nonexistent"], current, current, ["prague", "berlin"])


def test_fetch_previous_state_missing_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def fake_fetch(url: str) -> bytes:
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    monkeypatch.setattr(pib, "fetch_url", fake_fetch)
    assert pib.fetch_previous_state("https://example.test") == {}


def test_fetch_previous_state_non_404_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def fake_fetch(url: str) -> bytes:
        raise urllib.error.HTTPError(url, 500, "server error", None, None)

    monkeypatch.setattr(pib, "fetch_url", fake_fetch)
    with pytest.raises(pib.PrepareError):
        pib.fetch_previous_state("https://example.test")


def test_assemble_scratch_copies_rebuild_areas_and_fetches_others(
    public_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    berlin_manifest = {
        "version": 1,
        "layers": [{"id": "1", "name": "Parks", "type": "circle", "visible": True, "style": {}, "url": "./layers/1.geojson"}],
        "aggregation": {},
        "deduping": {},
    }
    served = {
        "areas/berlin/manifest.json": json.dumps(berlin_manifest).encode("utf-8"),
        "areas/berlin/layers/1.geojson": b'{"type":"FeatureCollection","features":[]}',
    }

    def fake_fetch(url: str) -> bytes:
        for suffix, payload in served.items():
            if url.endswith(suffix):
                return payload
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(pib, "fetch_url", fake_fetch)

    catalog = pib.load_json(public_dir / "catalog.json")
    scratch = tmp_path / "scratch"
    pib.assemble_scratch(catalog, public_dir, scratch, "https://example.test", {"prague"})

    assert (scratch / "catalog.json").exists()
    assert (scratch / "areas/prague/manifest.json").exists()
    assert (scratch / "areas/berlin/manifest.json").exists()
    assert (scratch / "areas/berlin/layers/1.geojson").exists()


def test_assemble_scratch_hard_fails_on_fetch_error(public_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def fake_fetch(url: str) -> bytes:
        raise urllib.error.HTTPError(url, 404, "not found", None, None)

    monkeypatch.setattr(pib, "fetch_url", fake_fetch)

    catalog = pib.load_json(public_dir / "catalog.json")
    scratch = tmp_path / "scratch"
    with pytest.raises(pib.PrepareError):
        pib.assemble_scratch(catalog, public_dir, scratch, "https://example.test", {"prague"})
