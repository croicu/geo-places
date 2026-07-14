# Incremental publish: only acquire changed area(s) on deploy

## Status: implemented, pending a real deploy to fully verify

1. ✅ Filed and resolved **[geo-builder#32](https://github.com/croicu/geo-builder/issues/32)** — `--rebuild <id>` (repeatable) + `--rebuild all` shipped in geo-builder, merged to `main` (commit `96852f2`). Issue closed; outcome written back into `docs/CLI.md`'s `--rebuild` section as the permanent record.
2. ✅ `scripts/prepare_incremental_build.py` — fingerprints/diffs areas, fetches carried-through areas from production, assembles the scratch `--in`. Unit-tested in `tests/ci/test_incremental_build.py` (12 cases, no network).
3. ✅ `build.sh` / `build.cmd` — `GEO_PLACES_INCREMENTAL=1` switches `--in` to the assembled scratch dir and passes the resolved `--rebuild <id>` args through to geo-builder; unset (default) is byte-for-byte unchanged from before this feature. Verified end-to-end on both scripts with a local fixture (fake "production" HTTP server + `provider: fake`): the changed area got real acquisition, the unchanged area's geojson was carried through untouched, `build-state.json` came out correct. Caught and fixed one real bug in this process — `Path.write_text` on Windows was emitting `\r\n`, which corrupted the area-id list `build.sh` reads with `read -r`.
4. ✅ `.github/workflows/cd.yaml` — added `workflow_dispatch` with an `areas` input (comma-separated ids, or `all`; empty = auto-diff), sets `GEO_PLACES_INCREMENTAL=1` unconditionally. Tag push and manual dispatch share the exact same code path.
5. ✅ `CLAUDE.md` updated (Current Product Shape, CI/CD, Testing Rules, Next Likely Work item on deploy scaling marked addressed).
6. **Not yet done, and can't be done from here:** a real deploy. Everything above is verified against a synthetic local fixture, not the actual `geo-places.croicu.com` site or live Overpass. First real tag push (or a `workflow_dispatch` run) after this merges is the real end-to-end check — confirm Overpass is only queried for the intended area(s) in the Actions log, and that `build-state.json` shows up correctly on the live site afterward.

## Context

`cd.yaml` currently rebuilds the entire ship catalog (`public/catalog.json`, all areas) against live Overpass on every tag push. [Issue #6](https://github.com/croicu/geo-places/issues/6) tracks the resulting problem: wall-clock time grows with every area added, and the build is atomic — one flaky Overpass retry failing permanently kills the whole release, with no partial output.

The fix agreed on: seed geo-builder's `--in` with the *previously deployed* output (fetched straight from the live production site) for every area that hasn't changed, and seed only the area(s) that actually changed from the hand-authored `public/areas/<id>/manifest.json`, then pass the changed-area list to geo-builder's `--rebuild` flag explicitly.

Why an explicit flag rather than relying on geo-builder's existing implicit behavior (verified this session: `Builder._tasks_from_catalog()` in `geo_builder/builder.py:70-119` already skips acquisition for an area whose manifest-in-`--in` already has `geojson` loaded, since loading a manifest with `url` populated auto-reads the referenced `.geojson` — `geo_builder/entities/geo_area.py`'s `_load_layer`, lines 128-148): that heuristic is silent and data-presence-keyed, with no way to force a refresh and no failure signal on an assembly mistake. `--rebuild` makes the selection a real, checked contract instead of a side effect — see the filed geo-builder issue for the exact requested semantics (unknown id → error, unlisted area with no data → error, `--rebuild` overrides the implicit heuristic entirely).

Scope: **ship catalog only** (`public/catalog.json`). `public/catalog.debug.json` (currently just `redmond`) is local-dev-only and is not built by CD at all today (CI/CD never has `debug: true`) — it continues to be copied through to `out/` unchanged, untouched by this change.

## Design

### 1. New script: `scripts/prepare_incremental_build.py`

Single script, stdlib-only (`json`, `hashlib`, `subprocess`, `urllib.request`, `pathlib`) — no new dependency management needed, consistent with `scripts/clean_public.py`. Responsibilities:

1. **Compute current per-area fingerprints** for every area in `public/catalog.json`:
   `fingerprint(area) = sha256(git_hash_object(public/areas/<id>/manifest.json) + canonical_json(catalog_entry_without_manifestUrl))`
   Using `git hash-object` (via `subprocess`) ties the manifest side to "the committed file version," per your instruction; the catalog-entry hash is needed too because `bbox` (acquisition-relevant) lives in `catalog.json`, not the manifest, and git-diffing the whole `catalog.json` file would be too coarse (any one area's edit would look like every area changed).
2. **Compute a global fingerprint** the same way for `template.json` + `settings.json` combined. Per your call: if this differs from the baseline, every ship area is forced into the rebuild set this run (closes the gap where a shared style/config change would otherwise never propagate to any area).
3. **Fetch the previous state** from `{production_url}/build-state.json` (default `production_url` = `https://geo-places.croicu.com`, overridable via `--production-url` / `GEO_PLACES_PRODUCTION_URL`). A 404 (first run ever, or a fresh redeploy after this feature ships) is treated as "no baseline" — every area is rebuilt, bootstrapping the mechanism. State file shape (catalog-keyed, so the ship/debug split — and any future per-trip catalog split — has a natural home without redesigning this later; only the `"catalog.json"` key is ever populated/read today):
   ```json
   { "catalog.json": { "prague": "<fingerprint>", "berlin": "<fingerprint>", "_global": "<fingerprint>" } }
   ```
4. **Determine the rebuild set:**
   - `--areas prague,berlin` (explicit, from workflow_dispatch) → use exactly that list verbatim, **overriding** the diff entirely (this is the manual "force-refresh even though nothing changed" lever). Unknown id vs. current `catalog.json` → exit 1.
   - `--areas all` → every ship area, unconditionally.
   - No `--areas` given (plain tag push) → diff current fingerprints against the fetched baseline; changed/missing → rebuild; also short-circuits to "all" if the global fingerprint changed (see point 2). Areas present in the baseline but no longer in `public/catalog.json` are simply dropped, not fetched.
5. **Assemble the scratch `--in` directory** (path passed in via `--scratch-dir`, a fresh `mktemp -d` — no new repo-local ignored folder needed, avoids adding more special-cased directories alongside `build/`/`out/`):
   - Copy `public/catalog.json` and `public/catalog.debug.json` in verbatim (source of truth for the area list/bbox/etc.).
   - For each area in the rebuild set: copy `public/areas/<id>/manifest.json` as-is.
   - For each other ship area: fetch `{production_url}/areas/<id>/manifest.json`, parse its layers, fetch every referenced `layers/*.geojson`, write everything into the scratch dir preserving relative paths — this is still required even with `--rebuild` doing the selection, since those areas must actually carry real acquired-looking data or geo-builder's own `--rebuild` contract would reject them as "unlisted area with no data." **Any fetch failure here is a hard exit 1** — no partial fallback, matching the fully-transactional-against-Cloudflare deploy model (single atomic `wrangler pages deploy`, so failing before that point is the correct behavior, not a regression).
6. **Write the new state file** (fresh fingerprints for every current ship area + the new global fingerprint) to `--state-out` — computed once, reused as both "what did we diff against" and "what do we publish as the new baseline," since nothing changes between those two moments in a single run.
7. **Print the final rebuild-set list** (or write it to a small file) so `build.sh` can pass it straight through as geo-builder's `--rebuild <ids>` argument on the actual build invocation.

### 2. `build.sh` / `build.cmd` changes

New env vars, all optional (defaults preserve **exactly today's behavior** for `ci.yaml` and any plain local `./build.sh` run — nobody except `cd.yaml` will ever set `GEO_PLACES_INCREMENTAL`):

- `GEO_PLACES_INCREMENTAL` (unset/false by default) — when true, switch on the new path below.
- `GEO_PLACES_REBUILD_AREAS` (optional) — forwarded as `--areas` to the script when set.
- `GEO_PLACES_PRODUCTION_URL` (default `https://geo-places.croicu.com`).

When `GEO_PLACES_INCREMENTAL` is true:
- `scripts/clean_public.py` still runs unconditionally first, same as today (public/ must always stay clean regardless of mode).
- Create a scratch dir via `mktemp -d`, run `prepare_incremental_build.py` to populate it, produce a new state file at a second temp path, and capture the resolved rebuild-set list it prints.
- Point geo-builder's `--in` at the **scratch dir** instead of `public/` directly, and pass `--rebuild <resolved ids>` on the same invocation.
- After a successful geo-builder run, in addition to the existing copy-through of `catalog.json`/`catalog.debug.json` from `public/` into `out/` (unchanged, still always sourced from `public/`), also copy the new state file to `out/build-state.json`.

When unset/false: behaves exactly as today, byte-for-byte — no script invocation, no network, `--in` = `public/` directly.

### 3. `.github/workflows/cd.yaml` changes

- Add `workflow_dispatch` (with an optional `areas` string input) alongside the existing `push: tags: v*` trigger.
- Set `GEO_PLACES_INCREMENTAL=1` unconditionally in the build step's `env:`.
- Set `GEO_PLACES_REBUILD_AREAS: ${{ github.event.inputs.areas }}` — empty/absent on a plain tag push (script auto-diffs), populated on a manual dispatch.
- Everything else (checkout, setup-python, `bash build.sh`, wrangler deploy) stays as-is — this is deliberately "one script, one code path": a tag push is just a dispatch run with the area list computed for you instead of typed in.

### 4. Tests

`ci.yaml` can't exercise the live-fetch path (no network, no production site to hit against a synthetic fixture) — but the pure logic (fingerprint computation determinism, diff/rebuild-set selection, the `--areas` override/`all` paths, unknown-id rejection) is fully unit-testable without network. Add `tests/ci/test_incremental_build.py`:
- Structure `prepare_incremental_build.py` so the "fetch bytes from a URL" step is one small function, easily monkeypatched in tests to serve from a local temp dir instead of a real HTTP call.
- Test: identical fingerprints → empty rebuild set; a changed manifest → that area only; a changed `bbox` in `catalog.json` (manifest untouched) → that area only; a changed `template.json` → every area; explicit `--areas` → exact override regardless of diff; unknown id in `--areas` → exit 1; missing baseline (simulated 404) → every area.

### Files touched

- New: `scripts/prepare_incremental_build.py`, `tests/ci/test_incremental_build.py`.
- Modified: `build.sh`, `build.cmd`, `.github/workflows/cd.yaml`.
- Docs: update `CLAUDE.md` (Current Product Shape, CI/CD section, Next Likely Work item on deploy scaling) to describe the new incremental mechanism and mark the relevant backlog item addressed.

## Verification

- Unit tests: `pytest tests/ci/test_incremental_build.py` and the existing `tests/ci/test_catalog.py` (must still pass unmodified — `public/` shape isn't changing).
- `ci.yaml`'s existing fixture build (`GEO_PLACES_CATALOG_DIR=tests/data`, `GEO_PLACES_INCREMENTAL` unset) must still pass unchanged — confirms the default path is untouched.
- Real end-to-end verification needs a live run against production and can't be done from here — this is on you to trigger: a `workflow_dispatch` run with a single test area (or a real tag push after a one-area manifest edit) and confirm in the Actions log that Overpass is only queried for the intended area, the resulting `out/build-state.json` is present and correct on the live site afterward, and the rest of the deployed catalog is byte-identical to before.
