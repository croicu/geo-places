#!/usr/bin/env python3
"""Restore public/ to its input-only state after a geo-builder designer session.

geo-builder's designer mode (--edit, --in public/) pulls existing built artifacts
from the configured designUrl on first launch when --in has no head file — this
writes real "url" fields, layers/*.geojson, and catalog.head*.json files straight
into public/, which is supposed to be hand-authored input only (see CLAUDE.md
Hard Architecture Rules). Left in place, this breaks two things:

  1. tests/ci/test_catalog.py's no-premature-url check.
  2. geo-builder's has_data_layers check would then skip re-acquisition on the
     next build, silently breaking the "always rebuild fresh from Overpass on
     deploy" invariant cd.yaml depends on.
  3. A stray catalog.head*.json with an absolute production catalogUrl (rather
     than a relative one) only resolves correctly by a Windows-specific pathlib
     quirk — it would very likely break catalog loading entirely on the Linux
     runners cd.yaml actually deploys from.

The same pull also carries over VoidWorker's per-source-layer "__void__{id}__"
variants (see geo-builder's src/geo_builder/workers/void.py) — these are always
discarded and rebuilt from scratch on every run from whatever "heatmap"/"circle"
layers exist, never read back from the input manifest. Only the bare "__void__"
layer is real hand-authored input (style + optional geometry.radius override).

Any designer save (even editing a single area's bbox) also round-trips every
OTHER area's catalog.json entry through geo-builder's Area dataclass, which
unconditionally serializes "group": [] for areas that never had a group set
(dataclasses.asdict() always emits every field). "Omitted" and "[]" mean the
same thing (ungrouped, see tasks/area_grouping.md), but the spurious diff on
unrelated areas is a real problem for scripts/prepare_incremental_build.py's
content-hash fingerprinting — it would misclassify every untouched area as
changed. Strip empty "group" arrays back to omitted so an edit to one area
doesn't bump every other area's fingerprint.

Run this after any designer session, before committing or building:
    python scripts/clean_public.py
build.sh / build.cmd also run this automatically before every build, so a
forgotten manual run doesn't silently break a real deploy.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "public"
_VOID_TYPE = "__void__"
_VOID_BARE_ID = "__void__"


def clean_manifest(manifest_path: Path) -> bool:
    """Strip "url" from every layer and drop generated void variants. Returns True if changed."""
    with manifest_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    layers = payload.get("layers", [])
    kept_layers = [
        layer
        for layer in layers
        if not (isinstance(layer, dict) and layer.get("type") == _VOID_TYPE and layer.get("id") != _VOID_BARE_ID)
    ]

    changed = len(kept_layers) != len(layers)
    for layer in kept_layers:
        if isinstance(layer, dict) and "url" in layer:
            del layer["url"]
            changed = True

    if changed:
        payload["layers"] = kept_layers
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

    return changed


def clean_catalog(catalog_path: Path) -> bool:
    """Strip empty "group": [] back to omitted on every area. Returns True if changed."""
    with catalog_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    changed = False
    for area in payload.get("areas", []):
        if isinstance(area, dict) and area.get("group") == []:
            del area["group"]
            changed = True

    if changed:
        with catalog_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")

    return changed


def main() -> int:
    if not PUBLIC_DIR.exists():
        print(f"clean_public.py: {PUBLIC_DIR} not found, nothing to do")
        return 0

    changed_files: list[Path] = []
    removed_layers_dirs: list[Path] = []
    removed_files: list[Path] = []

    catalog_path = PUBLIC_DIR / "catalog.json"
    if catalog_path.exists() and clean_catalog(catalog_path):
        changed_files.append(catalog_path)

    for manifest_path in sorted(PUBLIC_DIR.glob("areas/*/manifest.json")):
        if clean_manifest(manifest_path):
            changed_files.append(manifest_path)

        for generated_dir_name in ("layers", "void"):
            generated_dir = manifest_path.parent / generated_dir_name
            if generated_dir.exists():
                shutil.rmtree(generated_dir)
                removed_layers_dirs.append(generated_dir)

        for csv_path in manifest_path.parent.glob("*.csv"):
            csv_path.unlink()
            removed_files.append(csv_path)

    head_path = PUBLIC_DIR / "catalog.head.json"
    if head_path.exists():
        head_path.unlink()
        removed_files.append(head_path)

    if not (changed_files or removed_layers_dirs or removed_files):
        print("clean_public.py: public/ already clean")
        return 0

    for p in changed_files:
        print(f"clean_public.py: cleaned {p.relative_to(REPO_ROOT)}")
    for p in removed_layers_dirs:
        print(f"clean_public.py: removed {p.relative_to(REPO_ROOT)}")
    for p in removed_files:
        print(f"clean_public.py: removed {p.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
