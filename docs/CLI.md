# CLI Reference

## Synopsis

```text
geo-builder <tasks_path> [--in <dir>] [--out <dir>] [--edit]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `tasks_path` | required | Path to the template JSON file (e.g. `template.json`). Always required. |
| `--in <dir>` | required in build mode; `./in` in designer mode | Working directory for service artifacts. Auto-created if absent. |
| `--out <dir>` | `./out` | Output directory for built artifacts. |
| `--edit` | off | Open the designer WebView instead of running a build. |

## Modes

### Build mode (no `--edit`)

Runs the processing pipeline and writes artifacts to `--out`.

1. Loads `settings.json` and `settings.local.json` from the current directory.
2. Loads the template file at `tasks_path`.
3. `--in` is required. Reads it as the seed catalog for an incremental build. If it contains no valid catalog, starts from scratch.
4. Runs the build pipeline (acquisition → deduping → aggregation).
5. On success, writes all artifacts to `--out`. Output is never written when errors are present.
6. On error, prints each error to stderr prefixed with `geo-builder: error:` and exits with code `1`.

```bash
geo-builder template.json --in ./in               # scratch build to ./out
geo-builder template.json --in ./in --out ./out   # incremental build with explicit out
```

### Designer mode (`--edit`)

Opens the geo-browser WebView. Requires `designUrl` in `settings.json`.

1. Loads settings and template as above.
2. Reads `--in` to pre-load the in-memory catalog (areas, layers, styles).
3. **First launch** — if `--in` contains no head file, pulls all artifacts from the service at `designUrl` into `--in` before the WebView starts.
4. **Subsequent launches** — serves directly from `--in` and `--out`; no network pull. Use the refresh action in the UI to re-pull from the service.
5. Appends query parameters to `designUrl` before navigating:
   - `debug=1` — when `debug` is `true`
   - `center=<value>` — from `map.center` in settings (if present)
   - `zoom=<value>` — from `map.zoom` in settings (if present)
6. Window geometry (position and size) is saved to `settings.local.json` on close and restored on the next launch.

```bash
geo-builder template.json --edit                           # designer with defaults
geo-builder template.json --in ./in --out ./out --edit     # designer with explicit paths
```

## Configuration files

Configuration is loaded from two files in the **current working directory** each time the CLI is invoked.

### `settings.json`

Stable settings checked into the repository.

```json
{
  "settings": {
    "debug": false,
    "logLevel": "error",
    "designUrl": "http://localhost:5173/?design=1",
    "devTools": false,
    "map": {
      "center": "47.726,-122.106",
      "zoom": 10
    }
  },
  "providers": {
    "overpass": {
      "url": "https://overpass-api.de/api/interpreter"
    }
  }
}
```

| Key | Default | Description |
|---|---|---|
| `debug` | `false` | Enables debug mode: full exception tracebacks, per-task snapshots under `./build/`, and `debug=1` appended to `designUrl`. |
| `logLevel` | `"error"` | Minimum log level printed to stdout. Applies in both build mode and designer mode. One of: `verbose`, `info`, `warning`, `error`, `critical`. |
| `designUrl` | — | URL of the geo-browser app. Required for `--edit`. |
| `devTools` | `false` | Auto-opens DevTools when the WebView starts. |
| `map.center` | — | Initial map center passed to the designer as `center=<value>`. |
| `map.zoom` | — | Initial map zoom passed to the designer as `zoom=<value>`. |
| `providers` | `{}` | Provider-specific configuration (e.g. Overpass API URL). |

### `settings.local.json`

Local overrides — gitignored. Loaded after `settings.json`; any key present here wins. Primarily used for per-machine settings and to persist window geometry.

```json
{
  "settings": {
    "debug": true,
    "logLevel": "verbose",
    "window": {
      "left": 100,
      "top": 50,
      "width": 1400,
      "height": 900
    }
  }
}
```

Window geometry (`left`, `top`, `width`, `height`) is written back to this file automatically when the designer window closes.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | One or more errors. Details printed to stderr. |

In build mode with `debug: true`, unhandled exceptions propagate as Python tracebacks instead of being caught and printed as `geo-builder: error:` messages.

## Debug output

When `debug: true`, the build pipeline writes a snapshot after each worker step:

```text
./build/{task_type}/{counter:03d}/
    catalog.json        — catalog snapshot (no embedded GeoJSON)
    {layer_id}.geojson  — layers added or modified by this step
    {layer_id}.csv      — lon/lat + feature properties for each GeoJSON
```

The counter is global across all task types and reflects execution order. Only layers that were new or had their feature count change appear as GeoJSON/CSV files.

## geo-places usage contract (proposal)

geo-places (this repo) builds one area per manifest, non-interactively, in CI. This section states what geo-places needs from the CLI, based on the current behavior documented above, and flags the points that need confirmation before CI depends on it. Intended to be submitted to the geo-builder team as a request/checklist, not a description of already-agreed behavior.

### Invocation

```bash
geo-builder areas/<area>/manifest.json --in build/.scratch --out areas/<area>
```

- `--edit` is never passed in CI — build mode's existing headless behavior (no GUI, no prompts) is exactly what's needed. Please keep build mode free of any interactive fallback, including when required data is missing (fail with an exit-1 error instead).
- geo-places calls this file `manifest.json`; the naming above calls it `tasks_path` / "template". Assuming these are the same concept under different vocabulary in each repo — please flag if they're expected to diverge.

### Answers / resolutions

1. **Output artifact names.** There is no `layers.json`. The exact file set written to `--out` by a successful build is:

   ```text
   {out}/catalog.head.json
   {out}/catalog.json
   {out}/areas/{areaId}/manifest.json      ← per-area layer list (equivalent of layers.json)
   {out}/areas/{areaId}/{areaId}.csv
   {out}/areas/{areaId}/layers/{id}.geojson  ← one file per layer
   ```

   The per-area `manifest.json` is the layer catalogue for that area — it contains every layer's `id`, `name`, `type`, style, and the relative `url` pointing to its `.geojson` file. **Action for geo-places:** if a `layers.json` at a fixed path is required, generate it in geo-places' own CI step from the manifest.

2. **`settings.json` requirement.** Optional — no action needed. All fields have working defaults, and `OverpassProvider` falls back to `https://overpass-api.de/api/interpreter` when no `providers.overpass.url` is configured. Build mode works with no `settings.json` present at all.

3. **`--in` on ephemeral CI runners.** `--in` is now required in build mode (exit 1 if absent). On ephemeral runners, pass `--in` pointing to an empty or pre-populated directory. An empty directory triggers a from-scratch build with no seed catalog required.

4. **Debug output path collision.** Confirmed hardcoded to `./build/` (not configurable). **No action needed for CI** as long as `debug: false` is kept. Making the path configurable is a future enhancement; worth filing a geo-builder issue if it becomes a problem.

5. **Atomic failure.** Partially atomic — no action needed under normal conditions. `save_catalog()` begins by deleting and recreating `--out` in full, then writes all files. A pipeline error that occurs *before* `save_catalog` is called leaves `--out` entirely untouched. A rare OS-level error occurring *during* the write (after the directory wipe) could leave `--out` in a partial state, but this is not a realistic CI failure mode.

6. **Console-script entry point.** **Resolved.** `[project.scripts]` has been added to `pyproject.toml` — `geo-builder` is now an installable binary after `pip install -e .`. CI scripts can use the bare `geo-builder` command.

### New request: `--noninvasive` flag for designer mode

**Status: resolved in geo-builder `main`** (2026-07-10) — `--edit --noninvasive` skips the first-launch pull into `--in` as requested below. Not yet in a tagged release: `build.sh`/`build.cmd` pin CI/CD's `geo-builder` install via `GEO_BUILDER_REF` to a tag for reproducibility (see CLAUDE.md), so that path won't pick this up until a new tag is cut. Local designer sessions launched via `.vscode/launch.json`'s "geo-build (Edit)" config run straight against the sibling `geo-builder` checkout's venv (no version pin), so they already get it — that config now passes `--noninvasive`. `scripts/clean_public.py` stays in place as defense-in-depth (also cleans up automatically if `--noninvasive` is ever forgotten on a given run) and because it's still needed for direct CLI invocations against a tagged release.

**Problem.** geo-places uses designer mode (`--edit --in public/`) to make structural catalog/manifest edits (bbox, layer styles, filters) directly in `public/`, which must stay hand-authored-input-only — no `url` fields, no `layers/*.geojson`, no `catalog.head*.json` (see `CLAUDE.md`'s Hard Architecture Rules in geo-places). But per the documented "First launch" behavior above, if `--in` has no head file, designer mode pulls real acquired artifacts (`url` fields, `layers/*.geojson`, `catalog.head*.json`) straight into `--in`. Traced through `designer/host.py`'s `launch()`: the pull origin is derived from `designUrl`'s own origin, not a separate data-source setting, and `_pull()` writes everything — including `catalogUrl` — verbatim to `--in`.

This has real consequences for geo-places specifically:
- It broke `tests/ci/test_catalog.py`'s no-premature-`url` check.
- Since acquired layers now have real `geojson` data loaded, `has_data_layers` would skip re-acquisition on the next build, silently breaking the "always rebuild fresh from Overpass on deploy" invariant `cd.yaml` depends on.
- One pulled `catalog.head.json` had an **absolute** `catalogUrl` (`https://geo-places.croicu.com/catalog.json`) rather than a relative one. This only resolved correctly by a Windows-specific `pathlib` join quirk (`Path("public") / "https://…"` happened to collapse to `public/catalog.json`) — it would almost certainly resolve to a broken path on Linux, which is what `cd.yaml` actually deploys from.

geo-places worked around all of this locally with a defense-in-depth script (`scripts/clean_public.py`, run automatically before every build) that strips `url` fields, deletes `layers/`, and deletes stray `catalog.head*.json` from `public/` — but this is a workaround, not a fix, and depends on remembering to run it (or trusting `build.sh` to).

**Requested fix — new opt-in flag:**

```bash
geo-builder template.json --in public --edit --noninvasive
```

When `--noninvasive` is passed (only meaningful together with `--edit`):

- **Skip the "first launch" pull into `--in` entirely** — regardless of whether `--in` has a head file. `--in` is loaded and used exactly as it already is (structural manifests only, whatever `load_catalog` finds), with no network pull writing into it.
- Everything that *already* only writes structural data back to `--in` should keep working exactly as today — this is most of what a geo-places-style editing session needs:
  - Bbox edits (`SET_AREA_BBOX` → `save_catalog_meta(catalog, in_dir, ...)`) — writes `catalog.json`/head only, never touches area manifests' `url`/geojson.
  - Style/filter/layer-list edits (`PUT_AREA_JSON` → `area.apply_manifest(data.manifest, in_dir)`) — as long as the manifest round-tripped through the UI never contained a `url` field to begin with (guaranteed if the initial pull never ran), this stays clean automatically.
- Real builds (`Builder(...).run()`, triggered by bbox/style changes needing re-acquisition) continue to write full acquired data to `--out` only, same as today — `--noninvasive` doesn't change build/acquisition behavior, only what touches `--in`.
- Not requesting a change to default (non-`--noninvasive`) behavior — this needs to be strictly opt-in so nothing about the existing "pull real data for a full interactive preview" workflow changes for other designer-mode use cases.

**Also worth fixing regardless of the flag above** (both are real bugs independent of this feature request):
1. `pull.py`'s head-file handling should always write a **relative** local `catalogUrl` (e.g. `"./catalog.json"`), never persist whatever absolute URL the service happened to return.
2. `assetsUrl` in `settings.json` (added speculatively on the geo-places side) is currently **not read anywhere** in `geo-builder` — the pull origin is always derived from `designUrl`'s own origin instead. Either wire up a real separate data-source setting, or document clearly that `designUrl`'s origin is what's actually used, so users don't assume `assetsUrl` does something it doesn't.
