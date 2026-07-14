# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`geo-places` is a static data repository — no rendering code, no UI. It holds hand-authored area manifests; the generated GeoJSON layer data that `geo-browser` consumes at runtime is built fresh on every deploy and never committed.

It has no *rendering* relationship to TypeScript, Vite, or Leaflet — those live in `geo-browser`. This repo's only job is: **manifest in, deploy-ready static files out, published directly to Cloudflare Pages.** The one narrow exception: `vite.config.js` + `package.json` exist purely as a local dev static file server for `out/` (`npm run dev`, port 5174) so `geo-browser`'s own dev server has something to fetch from locally instead of `geo-places.croicu.com`, mirroring the real two-origin production topology. No bundling, no framework, no `.ts`/`.tsx`/`.vue` files, no build step of its own — `out/` is served as-is. Don't grow this into an actual frontend; that still belongs in `geo-browser`.

The `geo-builder` CLI (a separate repo, installed via pip) is the only tool that produces generated output here. This repo does not contain builder source code — it consumes the builder as a dependency.

## Commands

```bash
# Install the builder CLI (pin to a tag for reproducible builds)
pip install git+https://github.com/croicu/geo-builder.git@v1.0.0

# Build the deploy-ready output for every area into out/ — must be run from repo root
./build.sh          # or build.cmd on Windows

# Serve out/ locally on http://localhost:5174 (CORS enabled) — requires build.sh to have run first
npm run dev

# Restore public/ to input-only shape after a geo-builder designer (--edit) session —
# build.sh/build.cmd already run this automatically before every build
python scripts/clean_public.py
```

> `geo-builder` reads the **whole catalog** from `--in` in a single call and acquires data for every area that needs it — there's no per-area invocation. `build.sh` points `--in` at `public/` (read-only; safe) and `--out` directly at `out/`. geo-builder's native output already matches the deploy shape almost exactly (`out/areas/{id}/manifest.json` with `url` populated, `out/areas/{id}/layers/*.geojson`) — `build.sh` only needs to clean up afterward: copy both `catalog.json` and `catalog.debug.json` from `public/` into `out/` (a single run only produces whichever one the active `debug` flag resolved to, never both), and strip geo-builder's `catalog.head*.json` and per-area `.csv` files, which aren't part of the deploy contract. `out/` is gitignored and rebuilt fresh every run — nothing under it is ever committed; `cd.yaml` deploys it directly to Cloudflare Pages via wrangler. See `docs/CLI.md` for the full CLI reference and `build.sh` for the cleanup step. `geo-builder` also loads `settings.json`/`settings.local.json` from the current working directory, so `build.sh`/`build.cmd` must be run with CWD at repo root (they `cd` there themselves; running the underlying `geo-builder`/`python -m geo_builder.cli` command directly requires doing this yourself).

## Current Product Shape

`public/` is hand-authored input **only** — never generated into. `out/` is the generated deploy artifact — gitignored, rebuilt fresh every run, never committed:

```text
build.sh, build.cmd         ← this repo's build scripts (repo root, NOT inside build/ — see Hard Architecture Rules)
settings.json                ← hand-authored, checked in: geo-builder config (Overpass URL, logLevel, providers.fake.dataPath)
settings.local.json          ← hand-authored, gitignored: local overrides (e.g. debug: true)
template.json                ← hand-authored: shared __poi__/__void__ style template (tasks_path arg)
package.json, vite.config.js  ← local-dev-only static server for out/ (npm run dev) — see Project section, not a frontend
scripts/clean_public.py       ← restores public/ to input-only shape after a designer session; build.sh/build.cmd run it automatically (see Hard Architecture Rules)
scripts/prepare_incremental_build.py ← assembles a scratch --in for cd.yaml's incremental publish (see CI/CD section + tasks/incremental_publish.md)
tests/ci/test_catalog.py        ← pytest, no-network structural validation of public/'s catalog + manifests (ci.yaml)
tests/ci/test_incremental_build.py ← pytest, no-network unit tests for prepare_incremental_build.py's fingerprinting/diffing logic (ci.yaml)
tests/data/                     ← synthetic area (catalog.json, catalog.debug.json, areas/citest/) + tests/data/providers/fake.json (canned Overpass response) — mirrors geo-builder's own tests/data/providers/fake.json convention. ci.yaml builds this, not public/, to avoid live Overpass on every push
build/                        ← reserved exclusively for geo-builder's own debug output; never ours (see Hard Architecture Rules)
public/                        ← hand-authored input only, committed
  catalog.json                  ← full: all real areas, used when debug is false
  catalog.debug.json             ← dedicated small debug-only area (currently redmond, not in catalog.json): used when debug is true, for fast local iteration
  areas/
    prague/
      manifest.json                ← layers, style, acquisition filters (no "url" yet)
    berlin/
      manifest.json
out/                            ← generated deploy artifact, gitignored, never committed
  catalog.json                    ← copied through from public/ (always present regardless of debug flag)
  catalog.debug.json               ← copied through from public/ (always present regardless of debug flag)
  build-state.json                 ← cd.yaml only: per-area source fingerprints from this run, published so the next incremental deploy can diff against it (see CI/CD section)
  areas/
    prague/
      manifest.json                  ← same filename as the input, "url" now populated
      layers/
        1.geojson
        2.geojson
    berlin/
      manifest.json
      layers/
```

`public/catalog.json` is **not** the same thing as `catalog.default.json`. `catalog.default.json` is geo-browser's served master registry and does **not** live in this repo. `public/catalog.json` is geo-builder's own build-input catalog (bbox/id/name per area) — it lives here because `geo-builder` requires it to know what to build. Don't confuse the two.

Pipeline:

```text
public/catalog.json + public/areas/*/manifest.json (hand-authored: bbox, layers, acquisition filters)
  → geo-builder CLI (single call, reads the whole catalog from --in, writes natively to --out out/)
    → Overpass API query per area/layer that lacks data
      → out/catalog*.json + out/areas/*/manifest.json + out/areas/*/layers/*.geojson (gitignored, never committed)
        → wrangler pages deploy (cd.yaml, on a v* tag push)
          → Cloudflare Pages serves geo-places.croicu.com
```

`geo-browser` never talks to Overpass or Nominatim directly. It only ever fetches static files this repo publishes.

## Hard Architecture Rules

- `public/catalog.json`, `public/catalog.debug.json`, and `public/areas/*/manifest.json` are the only hand-edited inputs. Never hand-edit anything under `out/` — always regenerated by `geo-builder`, and gitignored anyway.
- No layer in a hand-authored `manifest.json` — data layers with an `acquisition` block, `__void__` layers, or any other generated-layer type — may carry a `url` field until `geo-builder` has actually produced that file. `url` is something `geo-builder` adds to its output, not something to pre-populate — a hand-authored `url` pointing at a nonexistent file makes the entire catalog fail to load (silently, as an empty catalog — see `docs/CLI.md`). `scripts/clean_public.py` strips `url` from every layer, not just acquisition ones.
- `geo-builder` is the single writer of generated files, writing natively into `out/` (its own `manifest.json`/`layers/` naming already matches what we want, no renaming needed). `build.sh` / `build.cmd` only copy both catalog files through from `public/` and strip `catalog.head*.json` + per-area `.csv` files afterward. If output looks wrong, fix the manifest or the builder — not the generated JSON.
- **Never put anything we care about inside `build/`.** `geo-builder` hardcodes debug-mode snapshot output to `./build/` relative to CWD and **wipes that directory** (`shutil.rmtree` then recreate) at the start of every debug run — this isn't configurable on geo-builder's side (see `docs/CLI.md`). This already destroyed this repo's build scripts once when they lived at `build/build.sh` with `settings.local.json`'s `debug: true` active; that's why the scripts live at repo root (`build.sh`/`build.cmd`) and the generated output lives at `./out` (repo root), not under `build/`. `build/` and `out/` are both gitignored and treated as fully disposable.
- **`public/catalog.debug.json` is intentional, not stale data.** When `debug: true` (local `settings.local.json` only — gitignored, never present in CI), `geo-builder` resolves the catalog filename to `catalog.debug.json` instead of `catalog.json`. This is a deliberate fast-iteration mechanism: `catalog.debug.json` holds a single dedicated debug-only area (currently `redmond`) so local debug builds skip the cost of acquiring all 5 ship areas. `redmond` is deliberately **not** one of `catalog.json`'s ship areas — `build.sh` always seeds `--in` from the clean `public/` (never from a previous `--out`), so there's no incremental caching between a debug build and a full build; if the debug area overlapped a ship area, iterating locally and then sanity-checking a full build would query Overpass twice for the same area. CI/CD never has `debug: true`, so `ci.yaml`/`cd.yaml` always build the full `catalog.json`. Keep both files' area lists reasonably in sync in shape (layer structure, no premature `url`) — don't delete `catalog.debug.json` thinking it's leftover cruft, and don't "fix" the area mismatch by making it overlap a ship area.
- `catalog.default.json` does not live in this repo — it's generated and maintained in `geo-browser`. Do not confuse it with `public/catalog.json` (see Current Product Shape above).
- **`geo-builder`'s designer mode (`--edit`) will pollute `public/` if you point `--in` at it.** On first launch, if `--in` has no head file, designer mode pulls existing built artifacts from `settings.json`'s `designUrl` straight into `--in` — writing real `url` fields, `layers/*.geojson`, and `catalog.head*.json` (sometimes with an absolute production `catalogUrl`, which only resolves correctly on Windows by a pathlib quirk and would likely break catalog loading on the Linux runners `cd.yaml` actually deploys from) directly into `public/`. This is expected `geo-builder` behavior today, not a bug to route around locally — a `--noninvasive` flag has been requested from the geo-builder team (see `docs/CLI.md`'s "New request: `--noninvasive` flag for designer mode") that would skip the pull entirely and make this a non-issue; until that lands, the fix is cleanup. `scripts/clean_public.py` strips all of this back out (keeping structural edits), and `build.sh`/`build.cmd` run it automatically before every build so a forgotten manual cleanup can't silently break a deploy. Run it manually after a designer session too, before committing: `python scripts/clean_public.py`. `.gitignore` also excludes `public/areas/*/layers/`, `public/areas/*/*.csv`, and `public/catalog.head*.json` as a second layer of defense.
- No frontend/rendering code belongs in this repo. If a task involves Leaflet, TypeScript, or the PWA shell, it belongs in `geo-browser`, not here.
- No live API calls happen at serve time. Overpass calls happen only when `geo-builder` runs (locally or in CI) — never at request time from a visitor's browser.
- **Generated output (`out/`) is never committed to git.** It's rebuilt fresh in `cd.yaml` on every tag push and deployed directly to Cloudflare Pages via `wrangler pages deploy out`. There is no "commit generated files, let Cloudflare auto-deploy on push" step in this repo's model — don't reintroduce one.

## Naming Rules

Directories under `public/areas/` (and correspondingly `out/areas/` after a build) are lowercase, hyphenated if multi-word, and match the `id` used in `public/catalog.json`:

```text
public/areas/naples/
public/areas/redmond/
public/areas/prague/
```

Files within an area directory — same filename (`manifest.json`) whether hand-authored or generated, distinguished by which top-level directory it's under:

```text
public/areas/<id>/manifest.json   ← hand-authored, committed, no "url" field
out/areas/<id>/manifest.json       ← generated, gitignored, "url" populated
out/areas/<id>/layers/              ← generated, gitignored
```

## Vocabulary

Use these terms consistently (shared with `geo-browser`'s vocabulary — do not diverge):

```text
Area      = one city/region, one directory under public/areas/ (and out/areas/ after a build)
Manifest  = one area's layer/style/acquisition definitions — same filename (manifest.json)
              hand-authored (public/, no "url") or generated (out/, "url" populated)
Layers    = the generated GeoJSON feature data for one area, out/areas/<id>/layers/*.geojson
Catalog   = ambiguous term, disambiguate by name:
              public/catalog.json = geo-builder's build-input catalog (id/name/bbox); lives here
              catalog.default.json = geo-browser's served master registry; lives in geo-browser
```

Do not reintroduce `project` or `dataset` as vocabulary for "area." The ecosystem settled on `area`.

## Manifest & Catalog Format

`public/catalog.json` — one entry per area, drives what `geo-builder` builds:

```json
{
  "version": "1.0",
  "createdAt": "2026-05-20 02:29:29.216307+00:00",
  "areas": [
    {
      "id": "naples",
      "name": "Naples",
      "bbox": [14.20, 40.82, 14.30, 40.88],
      "minRadiusPx": 32,
      "maxRadiusPx": 512,
      "liveMapRadiusPx": 640,
      "manifestUrl": "./areas/naples/manifest.json"
    }
  ]
}
```

`bbox` is `[west, south, east, north]` (`[minLon, minLat, maxLon, maxLat]`), same coordinate order convention as GeoJSON, per `geo-browser`'s CLAUDE.md (`[longitude, latitude]`). Every area referenced here **must** have a matching `manifestUrl` file on disk — a missing one fails the entire catalog load (see `docs/CLI.md`).

`public/areas/<id>/manifest.json` — hand-authored layer/style/acquisition definitions for one area:

```json
{
  "version": 1,
  "layers": [
    {
      "id": "1",
      "name": "Parks",
      "type": "circle",
      "visible": true,
      "style": { "opacity": 0.3, "radiusScale": 1.0, "surface": true, "color": "#007f00" },
      "acquisition": { "provider": "overpass", "filters": { "leisure": ["park"] } }
    }
  ],
  "aggregation": {},
  "deduping": {}
}
```

No `url` field on layers that haven't been built yet (see Hard Architecture Rules above).

**Provider selection is per-layer, not a CLI flag or global setting.** Each layer's `acquisition.provider` (`"overpass"` or `"fake"`) hardcodes which provider that layer uses — `settings.json`'s `providers` block only holds *config for* each provider (`overpass.url`, `fake.dataPath`), it doesn't select between them. `public/`'s real areas all use `"overpass"`; `tests/data/areas/citest/manifest.json` (the `ci.yaml` fixture) uses `"fake"`. There is deliberately no environment-variable or CLI-flag override for this in `geo-builder` — switching providers means switching which catalog/manifest set `--in` points at (`GEO_PLACES_CATALOG_DIR` in `build.sh`), not flipping a setting. Don't add a provider CLI flag to `geo-builder` to "simplify" this — the per-layer approach keeps `geo-builder` itself unaware that geo-places uses two different catalogs for two different purposes.

## CI/CD

Two GitHub Actions workflows:

- **`ci.yaml`** — runs on push (non-`main` branches) and PRs into `main`. Two steps, both network-free: (1) `pytest tests/ci/test_catalog.py` structurally validates `public/`'s real catalog + manifests (bbox shape, `manifestUrl` resolves, no premature `url`, etc.) — this is what actually catches mistakes in the data being changed; (2) `build.sh` with `GEO_PLACES_CATALOG_DIR`/`GEO_PLACES_TASKS_PATH` pointed at `tests/data/` instead of `public/`, exercising the real build pipeline (install → catalog load → acquisition → aggregation → dedupe → save) against a synthetic single-area catalog whose layer uses `"provider": "fake"` (replays `tests/data/providers/fake.json` instead of hitting Overpass). Doesn't deploy or commit anything. The check name required by branch protection on `main` is `build` (the job name).
- **`cd.yaml`** — runs on `v*` tag push, or manually via `workflow_dispatch` (optional `areas` input: comma-separated ids, or `all`). Sets `GEO_PLACES_INCREMENTAL=1` and `GEO_PLACES_REBUILD_AREAS=<the areas input>`, then runs `build.sh`, then deploys `out/` directly to Cloudflare Pages via `cloudflare/wrangler-action` (`wrangler pages deploy out --project-name=geo-places`). No git commit involved at all — the build output never touches git history. This is the only workflow that hits live Overpass, and (per the incremental mechanism below) only for the area(s) that actually need it.
>
> **Incremental publish** (see `tasks/incremental_publish.md` for the full design writeup). `GEO_PLACES_INCREMENTAL=1` makes `build.sh` call `scripts/prepare_incremental_build.py` before invoking `geo-builder`, instead of pointing `--in` straight at `public/`:
> 1. It fingerprints every area in `public/catalog.json` (git blob hash of that area's `manifest.json`, combined with a hash of that area's own `catalog.json` entry, since `bbox` lives there and not in the manifest) plus a global fingerprint of `template.json` + `settings.json`.
> 2. It fetches `{production_url}/build-state.json` (default production URL: `https://geo-places.croicu.com`) — the fingerprints published by the *previous* deploy. Missing (first run) → every area is treated as changed. A changed global fingerprint → every area is treated as changed (a shared style/config change must propagate everywhere, not silently apply nowhere).
> 3. It assembles a scratch `--in`: areas whose fingerprint changed (or the explicit `areas` input, which overrides the diff entirely) are seeded from the raw `public/areas/<id>/manifest.json`; every other area is seeded by fetching its already-built manifest + `layers/*.geojson` straight from the live production site.
> 4. `build.sh` then invokes `geo-builder ... --rebuild <id> --rebuild <id> ...` with exactly the changed-area ids — geo-builder acquires only those from Overpass and hard-fails (exit 1, nothing written to `--out`) if any other loaded area turns out to have no data, or if a `--rebuild` id doesn't exist in the catalog. See `docs/CLI.md`'s `--rebuild` section (requested and implemented via [geo-builder#32](https://github.com/croicu/geo-builder/issues/32)).
> 5. A fresh `build-state.json` (this run's fingerprints) is written to `out/build-state.json` so it publishes alongside the deploy and becomes the next run's baseline.
>
> Unset `GEO_PLACES_INCREMENTAL` (the default — `ci.yaml`, or any plain local `./build.sh`/`build.cmd` run): behaves exactly as before this feature existed, no script, no network fetch, `--in` = `public/` directly, full rebuild every time.

> Pin the `geo-builder` install to a tag, not `@main`, so CI runs are reproducible and don't silently pick up unreleased builder changes. Set via the `GEO_BUILDER_REF` env var that `build.sh` / `build.cmd` read. Note CI's `settings.local.json` won't exist (gitignored), so `debug` is always `false` there — the `build/` wipe hazard is a local-only concern.
>
> `main` has branch protection: PRs required (no direct push), the `build` status check must pass, no mandatory review count (personal-account repos can't do per-user bypass of required reviews — see git history around the lockdown). Make changes on a branch (e.g. `working`) and open a PR. The repo is **public** (flipped from private) — GitHub's free tier doesn't support branch protection on private repos at all (classic protection and rulesets both refuse with a 403). No secrets are exposed by this; `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` remain protected repo secrets regardless of visibility.

## Testing Rules

This repo has no application logic to unit test — it is data plus CI orchestration. `tests/ci/test_catalog.py` is the lightweight schema check (pytest, run by `ci.yaml`): validates every `public/*.json` catalog's areas have a well-formed `bbox`, matching `manifestUrl` file, and that manifests don't carry premature `url` fields. `tests/ci/test_incremental_build.py` covers `scripts/prepare_incremental_build.py`'s fingerprinting/diffing/assembly logic in isolation (network calls monkeypatched) — see CI/CD section. Extend these rather than adding a heavier test framework if more validation is needed.

## Next Likely Work

Good next branches:

1. ~~Decide whether `geo-builder` should gain a `geo-build` console-script entry point, or `python -m geo_builder.cli` stays the permanent invocation.~~ Resolved: `geo-builder` is now an installable console script — see `docs/CLI.md`.
2. ~~Confirm final `manifest.json`/catalog schema against what `geo-builder` actually consumes.~~ Resolved via direct testing against a real geo-builder build — see Current Product Shape and Manifest & Catalog Format above.
3. ~~Decide whether `layers.json` generation should fail CI loudly on Overpass/Nominatim errors, or fall back to stale committed data.~~ Resolved: build mode already fails loud (exit `1`, no `--out` artifacts written on error) — see `docs/CLI.md`. Moot anyway now: generated output is never committed, so there's no "stale committed data" to fall back to.
4. ~~Follow up with the geo-builder team on the open items filed in `docs/CLI.md`'s "geo-places usage contract" section — in particular, the silent-empty-catalog failure mode when `--in` fails to load (currently swallowed with no error message).~~ Resolved: geo-builder fixed the silent-fallback behavior; `--in` is now required in build mode (exit 1 if absent) rather than silently defaulting to an empty catalog.
5. ~~Confirm the `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets are actually configured on this repo for `cd.yaml`'s wrangler deploy step to work.~~ Resolved: `v0.1.2` deployed successfully, `geo-places.croicu.com` confirmed serving the real built `catalog.json` and area manifests.
6. ~~Use the mock/fake Overpass provider (`geo_builder.providers.fake`) to cut network cost.~~ Resolved for CI — `ci.yaml` now builds `tests/data/` (provider: fake) instead of live Overpass, see CI/CD above. Still open: `catalog.debug.json`'s local fast-iteration build (`redmond`) still hits real Overpass; switching it to `provider: fake` too is a possible follow-up but would need its manifest layers rewritten to use the fake provider, which changes what a "debug build" actually exercises.
7. `cd.yaml`'s v0.1.2 run flagged `actions/checkout@v4`, `actions/setup-python@v5`, and `cloudflare/wrangler-action@v3` as targeting the deprecated Node 20 runtime (currently auto-forced onto Node 24 by GitHub, not yet a hard failure). Bump to newer action versions when convenient.
8. ~~Follow up with the geo-builder team on the `--noninvasive` flag requested in `docs/CLI.md` (designer mode currently pulls real acquired data into `--in`, which `scripts/clean_public.py` works around locally).~~ Resolved: `--noninvasive` has landed in geo-builder's `main` — see `docs/CLI.md`'s "New request: `--noninvasive` flag for designer mode". `.vscode/launch.json`'s "geo-build (Edit)" config now passes it. Not yet in a tagged release, so CI/CD (pinned via `GEO_BUILDER_REF`) still relies on `scripts/clean_public.py` until a new tag is cut. The two follow-on bugs from that same request are also resolved: `pull.py` now always normalizes `catalogUrl` to a relative local path, and `assetsUrl` in `settings.json` is confirmed to have a real (different) job — the `assetsBase` query param on `designUrl` — rather than being inert; the pull origin itself is still derived from `designUrl`'s own origin, by design.
9. ~~Deploy time/reliability will degrade as more cities are added — see [issue #6](https://github.com/croicu/geo-places/issues/6).~~ Addressed: `cd.yaml` now builds incrementally (`GEO_PLACES_INCREMENTAL=1`) — only the area(s) whose committed source actually changed hit Overpass; every other area is carried through from the live production site untouched. See the CI/CD section above and `tasks/incremental_publish.md` for the full design, and `docs/CLI.md`'s `--rebuild` section for the geo-builder-side flag this depends on ([geo-builder#32](https://github.com/croicu/geo-builder/issues/32)). A full rebuild is still available on demand via `workflow_dispatch`'s `areas: all` input. Not yet exercised against a real live deploy — first real tag push after this lands is the actual end-to-end verification.

Keep branches narrow.
