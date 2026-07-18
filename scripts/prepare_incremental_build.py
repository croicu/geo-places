#!/usr/bin/env python3
"""Assemble a scratch --in directory for an incremental geo-builder build.

Seeds every catalog area that hasn't changed with its previously-deployed,
already-acquired manifest + geojson (fetched from croicu/geo-places-baseline,
a separate repo that mirrors out/ after every successful deploy — see
tasks/baseline-artifact-spec.md), and every area that HAS changed with its raw
hand-authored public/ manifest — so a subsequent `geo-builder ... --rebuild
<changed ids>` only hits Overpass for the areas that actually need it. This
keeps Cloudflare Pages a pure deploy sink: nothing in the pre-deployment build
phase reads from it. See tasks/incremental_publish.md for the full design.
There is a single public/catalog.json (no more debug catalog — see
tasks/area_grouping.md); a "debug" area is just an ordinary catalog entry
tagged with a "group", built and deployed like everything else.

"Changed" is decided by comparing a per-area fingerprint (git blob hash of the
manifest + a hash of that area's own public/catalog.json entry, since bbox
lives there and not in the manifest) against a baseline fingerprint published
alongside the previous deploy at {baseline_url}/build-state.json. A missing
baseline (first run, or a fresh site) means every area is treated as changed.
A change to template.json or settings.json (aggregation/acquisition-adjacent
shared inputs) forces every area into the rebuild set, since otherwise such a
change would never propagate anywhere.

Usage:
    python scripts/prepare_incremental_build.py \
        --public-dir public --scratch-dir <dir> --state-out <path> \
        --rebuild-out <path> [--areas prague,berlin] [--baseline-url URL]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_REBUILD_ALL = "all"
_GLOBAL_KEY = "_global"


class PrepareError(Exception):
    pass


def fetch_url(url: str) -> bytes:
    # A descriptive User-Agent is good practice for any GitHub-hosted endpoint
    # (raw.githubusercontent.com included) and costs nothing to keep sending.
    request = urllib.request.Request(url, headers={"User-Agent": "geo-places-incremental-build/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def git_hash_object(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def child_path(parent: Path, relative_path: str) -> Path:
    return parent / relative_path.removeprefix("./")


def join_url(base: str, *relative_parts: str) -> str:
    url = base.rstrip("/")
    for part in relative_parts:
        url += "/" + part.removeprefix("./").lstrip("/")
    return url


def area_fingerprint(area_entry: dict, manifest_path: Path) -> str:
    entry = {k: v for k, v in area_entry.items() if k != "manifestUrl"}
    manifest_hash = git_hash_object(manifest_path)
    return hashlib.sha256(f"{manifest_hash}|{canonical_json(entry)}".encode("utf-8")).hexdigest()


def global_fingerprint(template_path: Path, settings_path: Path) -> str:
    template_hash = git_hash_object(template_path)
    settings_hash = git_hash_object(settings_path)
    return hashlib.sha256(f"{template_hash}|{settings_hash}".encode("utf-8")).hexdigest()


def compute_current_fingerprints(catalog: dict, public_dir: Path, template_path: Path, settings_path: Path) -> dict[str, str]:
    fingerprints: dict[str, str] = {_GLOBAL_KEY: global_fingerprint(template_path, settings_path)}
    for area in catalog.get("areas", []):
        manifest_path = child_path(public_dir, area["manifestUrl"])
        fingerprints[area["id"]] = area_fingerprint(area, manifest_path)
    return fingerprints


def fetch_previous_state(baseline_url: str) -> dict:
    url = join_url(baseline_url, "build-state.json")
    try:
        raw = fetch_url(url)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}
        raise PrepareError(f"failed to fetch previous build state from {url}: {error}") from error
    except urllib.error.URLError as error:
        raise PrepareError(f"failed to fetch previous build state from {url}: {error}") from error
    return json.loads(raw.decode("utf-8"))


def resolve_rebuild_set(
    explicit_areas: list[str] | None,
    current: dict[str, str],
    baseline: dict[str, str],
    catalog_ids: list[str],
) -> list[str]:
    if explicit_areas is not None:
        if explicit_areas == [_REBUILD_ALL]:
            return list(catalog_ids)
        unknown = [area_id for area_id in explicit_areas if area_id not in catalog_ids]
        if unknown:
            raise PrepareError(f"--areas area(s) not found in public/catalog.json: {', '.join(unknown)}")
        return list(explicit_areas)

    if current.get(_GLOBAL_KEY) != baseline.get(_GLOBAL_KEY):
        return list(catalog_ids)

    return [area_id for area_id in catalog_ids if current.get(area_id) != baseline.get(area_id)]


def fetch_area_into(area_id: str, manifest_url: str, baseline_url: str, dest_manifest: Path) -> None:
    manifest_remote_url = join_url(baseline_url, manifest_url)
    try:
        manifest_bytes = fetch_url(manifest_remote_url)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise PrepareError(
            f"failed to fetch baseline manifest for area '{area_id}' from {manifest_remote_url}: {error}"
        ) from error

    dest_manifest.parent.mkdir(parents=True, exist_ok=True)
    dest_manifest.write_bytes(manifest_bytes)

    manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
    area_base = manifest_url.removeprefix("./").rsplit("/", 1)[0]

    for layer in manifest_payload.get("layers", []):
        layer_url = layer.get("url")
        if not layer_url:
            continue
        layer_remote_url = join_url(baseline_url, area_base, layer_url)
        dest_layer = child_path(dest_manifest.parent, layer_url)
        try:
            layer_bytes = fetch_url(layer_remote_url)
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            raise PrepareError(
                f"failed to fetch baseline layer '{layer_url}' for area '{area_id}' from {layer_remote_url}: {error}"
            ) from error
        dest_layer.parent.mkdir(parents=True, exist_ok=True)
        dest_layer.write_bytes(layer_bytes)


def assemble_scratch(
    catalog: dict,
    public_dir: Path,
    scratch_dir: Path,
    baseline_url: str,
    rebuild_set: set[str],
) -> None:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_dir / "catalog.json", scratch_dir / "catalog.json")

    for area in catalog.get("areas", []):
        area_id = area["id"]
        manifest_url = area["manifestUrl"]
        dest_manifest = child_path(scratch_dir, manifest_url)

        if area_id in rebuild_set:
            dest_manifest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child_path(public_dir, manifest_url), dest_manifest)
        else:
            fetch_area_into(area_id, manifest_url, baseline_url, dest_manifest)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", type=Path, default=REPO_ROOT / "public")
    parser.add_argument("--template-path", type=Path, default=REPO_ROOT / "template.json")
    parser.add_argument("--settings-path", type=Path, default=REPO_ROOT / "settings.json")
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--state-out", type=Path, required=True)
    parser.add_argument("--rebuild-out", type=Path, required=True)
    parser.add_argument("--baseline-url", default="https://raw.githubusercontent.com/croicu/geo-places-baseline/main")
    parser.add_argument("--areas", default=None, help="comma-separated area ids to force-rebuild, or 'all'")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    explicit_areas: list[str] | None = None
    if args.areas:
        explicit_areas = [a.strip() for a in args.areas.split(",") if a.strip()]

    try:
        catalog = load_json(args.public_dir / "catalog.json")
        catalog_ids = [area["id"] for area in catalog.get("areas", [])]

        current = compute_current_fingerprints(catalog, args.public_dir, args.template_path, args.settings_path)
        baseline = fetch_previous_state(args.baseline_url)

        rebuild_list = resolve_rebuild_set(explicit_areas, current, baseline, catalog_ids)
        rebuild_set = set(rebuild_list)

        assemble_scratch(catalog, args.public_dir, args.scratch_dir, args.baseline_url, rebuild_set)

        new_state = current
        args.state_out.parent.mkdir(parents=True, exist_ok=True)
        with args.state_out.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(new_state, f, indent=2)
            f.write("\n")

        args.rebuild_out.parent.mkdir(parents=True, exist_ok=True)
        with args.rebuild_out.open("w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(rebuild_list) + ("\n" if rebuild_list else ""))
    except PrepareError as error:
        print(f"prepare_incremental_build.py: error: {error}", file=sys.stderr)
        return 1

    carried_through = [area_id for area_id in catalog_ids if area_id not in rebuild_set]
    print(f"prepare_incremental_build.py: rebuilding {rebuild_list or '[]'}, carrying through {carried_through or '[]'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
