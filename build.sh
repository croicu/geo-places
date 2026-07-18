#!/usr/bin/env bash
# Installs geo-builder and builds the deploy-ready output for every area into out/.
# Invoked by ci.yaml (validation) and cd.yaml (publish — wrangler deploys out/ directly,
# nothing here is ever committed). Run from anywhere; paths are resolved relative to
# this script's location.
#
# public/ is hand-authored input ONLY: public/catalog.json (id/name/bbox/optional group
# per area) + public/areas/<id>/manifest.json (layer/acquisition defs, no "url" field yet).
# Never generated into — this script runs scripts/clean_public.py before every build to
# guarantee it (see that script's docstring for why: designer mode pollutes public/ with
# real url/geojson/head-file data on first launch). geo-builder reads the *whole* catalog
# from --in in one call and acquires data for every area that needs it — there is no
# per-area loop. tasks_path is only used for __poi__/__void__ style lookup, so it points
# at the shared template.json at repo root rather than any one area's manifest.
#
# There is one catalog, period — geo-builder dropped the debug-catalog-file concept
# entirely (see tasks/area_grouping.md, geo-builder commit f9ff202): a per-area "group"
# field (e.g. ["debug"]) is now how areas like redmond are tagged, filtered client-side by
# geo-browser, not by building a different catalog file. Every area in public/catalog.json
# ships and is always built here, regardless of group.
#
# geo-builder writes its own native shape directly to out/ (--out out/): catalog.head.json,
# catalog.json, and per area: areas/<id>/manifest.json (now with "url" populated),
# areas/<id>/<id>.csv, areas/<id>/layers/*.geojson. This script then: (1) copies
# catalog.json from public/ into out/, and (2) strips geo-builder's catalog.head.json and
# per-area .csv files, which aren't part of the deploy contract. out/ is gitignored and
# rebuilt fresh every run — nothing under it is ever committed.
#
# geo-builder loads settings.json/settings.local.json from the CWD — this script cd's to
# REPO_ROOT before invoking it so those are picked up. This repo's build/ directory is
# reserved exclusively for geo-builder's own debug output: geo-builder hardcodes debug
# snapshots to ./build/ relative to CWD and wipes that directory on every debug run
# (settings.local.json's debug:true). This script therefore lives at repo root, not
# under build/ — putting anything we care about under build/ WILL eventually get deleted.
#
# GEO_PLACES_CATALOG_DIR / GEO_PLACES_TASKS_PATH override the catalog/template used —
# ci.yaml points these at ci-fixtures/ (a tiny synthetic area with provider: fake, no
# network) for routine validation. cd.yaml leaves them unset, using the real public/
# catalog against live Overpass.
#
# GEO_PLACES_INCREMENTAL (set only by cd.yaml) switches --in from public/ directly to a
# scratch directory assembled by scripts/prepare_incremental_build.py: areas that haven't
# changed since the last deploy are seeded from croicu/geo-places-baseline (already-acquired,
# so geo-builder's --rebuild skips them — see tasks/baseline-artifact-spec.md for that repo);
# only changed areas come from public/ raw. Cloudflare Pages is never read during the build,
# only written to at the end — see tasks/incremental_publish.md for the full design. Unset
# (ci.yaml, any plain local run): behaves exactly as before this feature existed — no script,
# no network, --in = public/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
cd "$REPO_ROOT"

GEO_BUILDER_REF="${GEO_BUILDER_REF:-main}"
CATALOG_DIR="${GEO_PLACES_CATALOG_DIR:-$REPO_ROOT/public}"
TASKS_PATH="${GEO_PLACES_TASKS_PATH:-$REPO_ROOT/template.json}"
DEPLOY_OUT="$REPO_ROOT/out"

rm -rf "$DEPLOY_OUT"

# Prefer a sibling geo-builder checkout's own venv (local dev: already has geo-builder
# installed editable, no need to pip install a copy from GitHub every run). Falls back
# to installing into whatever `python`/`pip` resolve to (CI: actions/setup-python's
# runner-owned Python, which doesn't need a venv to avoid permission errors).
SIBLING_VENV_DIR="$REPO_ROOT/../geo-builder/.venv"
if [ -x "$SIBLING_VENV_DIR/Scripts/python.exe" ]; then
  PYTHON="$SIBLING_VENV_DIR/Scripts/python.exe"
elif [ -x "$SIBLING_VENV_DIR/bin/python" ]; then
  PYTHON="$SIBLING_VENV_DIR/bin/python"
else
  PYTHON="python"
fi

if [ "$PYTHON" = "python" ]; then
  echo "Installing geo-builder@${GEO_BUILDER_REF}"
  pip install --quiet "git+https://github.com/croicu/geo-builder.git@${GEO_BUILDER_REF}"
else
  echo "Using geo-builder venv at ${SIBLING_VENV_DIR} (skipping install)"
fi

# geo-builder's designer mode (--edit) pulls existing built artifacts into --in on
# first launch, writing "url" fields, layers/*.geojson, and catalog.head*.json straight
# into public/ — always restore it to input-only shape before building, regardless of
# what a previous designer session (or a forgotten manual cleanup) left behind.
"$PYTHON" "$REPO_ROOT/scripts/clean_public.py"

if [ ! -f "$CATALOG_DIR/catalog.json" ]; then
  echo "No catalog found at ${CATALOG_DIR}/catalog.json" >&2
  exit 1
fi

if [ ! -f "$TASKS_PATH" ]; then
  echo "No template found at ${TASKS_PATH}" >&2
  exit 1
fi

BUILD_IN="$CATALOG_DIR"
REBUILD_ARGS=()
STATE_OUT=""

if [ "${GEO_PLACES_INCREMENTAL:-}" = "1" ]; then
  SCRATCH_DIR="$(mktemp -d)"
  STATE_OUT="$(mktemp)"
  REBUILD_OUT="$(mktemp)"
  trap 'rm -rf "$SCRATCH_DIR" "$STATE_OUT" "$REBUILD_OUT"' EXIT

  PREPARE_ARGS=(
    --public-dir "$CATALOG_DIR"
    --template-path "$TASKS_PATH"
    --settings-path "$REPO_ROOT/settings.json"
    --scratch-dir "$SCRATCH_DIR"
    --state-out "$STATE_OUT"
    --rebuild-out "$REBUILD_OUT"
    --baseline-url "${GEO_PLACES_BASELINE_URL:-https://raw.githubusercontent.com/croicu/geo-places-baseline/main}"
  )
  if [ -n "${GEO_PLACES_REBUILD_AREAS:-}" ]; then
    PREPARE_ARGS+=(--areas "$GEO_PLACES_REBUILD_AREAS")
  fi

  echo "Assembling incremental --in from ${GEO_PLACES_BASELINE_URL:-https://raw.githubusercontent.com/croicu/geo-places-baseline/main}"
  "$PYTHON" "$REPO_ROOT/scripts/prepare_incremental_build.py" "${PREPARE_ARGS[@]}"

  BUILD_IN="$SCRATCH_DIR"
  while IFS= read -r area_id; do
    [ -n "$area_id" ] && REBUILD_ARGS+=(--rebuild "$area_id")
  done < "$REBUILD_OUT"
fi

echo "Building catalog (tasks_path=${TASKS_PATH})"
"$PYTHON" -m geo_builder.cli "$TASKS_PATH" --in "$BUILD_IN" --out "$DEPLOY_OUT" "${REBUILD_ARGS[@]}"

cp "$CATALOG_DIR/catalog.json" "$DEPLOY_OUT/catalog.json"

if [ -n "$STATE_OUT" ]; then
  cp "$STATE_OUT" "$DEPLOY_OUT/build-state.json"
fi

# Strip geo-builder's own head file and per-area CSVs — not part of the deploy contract.
rm -f "$DEPLOY_OUT/catalog.head.json"
for area_dir in "$DEPLOY_OUT"/areas/*/; do
  [ -d "$area_dir" ] || continue
  id="$(basename "$area_dir")"
  rm -f "$area_dir/${id}.csv"
done

produced=$(find "$DEPLOY_OUT/areas" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
if [ "$produced" -eq 0 ]; then
  echo "geo-builder produced no area output" >&2
  exit 1
fi

echo "Build complete (${produced} areas) -> ${DEPLOY_OUT}"
