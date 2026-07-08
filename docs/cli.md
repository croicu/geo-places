# CLI Reference

## Synopsis

```text
geo-builder <tasks_path> [--in <dir>] [--out <dir>] [--edit]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `tasks_path` | required | Path to the template JSON file (e.g. `template.json`). Always required. |
| `--in <dir>` | `./in` | Working directory for service artifacts. Auto-created if absent. |
| `--out <dir>` | `./out` | Output directory for built artifacts. |
| `--edit` | off | Open the designer WebView instead of running a build. |

## Modes

### Build mode (no `--edit`)

Runs the processing pipeline and writes artifacts to `--out`.

1. Loads `settings.json` and `settings.local.json` from the current directory.
2. Loads the template file at `tasks_path`.
3. Reads `--in` as the seed catalog for an incremental build. If `--in` is absent or contains no valid catalog, starts from scratch.
4. Runs the build pipeline (acquisition → deduping → aggregation).
5. On success, writes all artifacts to `--out`. Output is never written when errors are present.
6. On error, prints each error to stderr prefixed with `geo-builder: error:` and exits with code `1`.

```bash
geo-builder template.json                          # scratch build to ./out
geo-builder template.json --in ./in --out ./out    # incremental build
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
| `logLevel` | `"error"` | Minimum log level printed to stdout during a designer session. One of: `verbose`, `info`, `warning`, `error`, `critical`. |
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

3. **`--in` on ephemeral CI runners.** Confirmed — no action needed. An absent or empty `--in` triggers a from-scratch build with no seed catalog required.

4. **Debug output path collision.** Confirmed hardcoded to `./build/` (not configurable). **No action needed for CI** as long as `debug: false` is kept — but this is no longer hypothetical: with `settings.local.json`'s `debug: true` active locally, a debug run from repo root deleted geo-places' own `build/build.sh`/`build.cmd` (they lived under `build/` at the time) mid-run, along with everything else under `build/`. geo-places worked around it by moving its scripts and scratch `--out` to repo root (`build.sh`/`build.cmd`) / `./out`, keeping `build/` exclusively for geo-builder's own debug output. Still worth making the snapshot path configurable (or at least warn before wiping a non-empty, non-geo-builder-owned directory) so other consumers don't hit the same data loss.

5. **Atomic failure.** Partially atomic — no action needed under normal conditions. `save_catalog()` begins by deleting and recreating `--out` in full, then writes all files. A pipeline error that occurs *before* `save_catalog` is called leaves `--out` entirely untouched. A rare OS-level error occurring *during* the write (after the directory wipe) could leave `--out` in a partial state, but this is not a realistic CI failure mode.

6. **Console-script entry point.** **Resolved.** `[project.scripts]` has been added to `pyproject.toml` — `geo-builder` is now an installable binary after `pip install -e .`. CI scripts can use the bare `geo-builder` command.

7. **Any `--in` catalog load failure silently falls back to an empty catalog, exit code 0, no error message.** `main()` wraps `load_catalog()` in a bare `except GeoError: executor = Builder()` — a missing catalog file, a missing per-area manifest, a layer `url` pointing at a nonexistent geojson file, or (intentionally, per geo-places' own `catalog.debug.json`/`catalog.json` split) a debug-mode catalog filename that happens not to exist, all produce the *same* outcome: a "successful" build (exit 0) that silently processes zero areas. geo-places hit this more than once while iterating on its own catalog setup, each time with no error output pointing at the real cause — only directly calling `load_catalog()` in isolation surfaced the actual `CatalogError`. **Request:** at minimum, log the swallowed `GeoError` (e.g. to stderr at `warning` level) before falling back to an empty catalog, so a silently-empty build is diagnosable from CI output instead of requiring a Python REPL to investigate.
