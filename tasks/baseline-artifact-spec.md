# Baseline Artifact Pipeline — Specification

## Purpose

After each successful deployment of `geo-places` to Cloudflare Pages, mirror the freshly built `out/` directory into a separate repository. This snapshot serves as a stable baseline that subsequent CI builds can diff against — e.g. to detect changes, compute deltas, or skip redundant work (incremental builds).

This is an intentional exception to the "no generated files committed to git" principle used elsewhere in this system (e.g. `out/` in `geo-places`, which is never committed there). The baseline artifact has a different purpose — it is not the deploy payload itself, but a reference snapshot consumed by CI, so committing it is appropriate in this separate repo.

## Components

| Component | Value |
|---|---|
| Source repo | `croicu/geo-places` |
| Baseline repo | `croicu/geo-places-baseline` (separate repo, exists and is seeded manually — CI does not create it) |
| Branch | `main` (the only branch — no history retention beyond normal git; each run commits on top of the last) |
| Artifact | Full mirror of `out/`: `catalog.json`, `build-state.json`, and every `areas/<id>/manifest.json` + `areas/<id>/layers/*.geojson` + `areas/<id>/void/*.geojson`, laid out at the baseline repo's root exactly as under `out/` |
| Auth | Fine-grained PAT, scoped to `geo-places-baseline` only, `Contents: Read and write` |
| Secret name | `BASELINE_REPO_PAT` (stored in `geo-places` repo secrets) |

## Preconditions (one-time setup)

1. `geo-places-baseline` repo exists. ✅
2. `main` branch seeded with a full mirror of the live production `out/` tree. ✅ (done manually via an HTTP crawl of `geo-places.croicu.com`, since local `out/` was dirty relative to the last real deploy and wrangler has no command to pull deployed files back down.)
3. `BASELINE_REPO_PAT` secret is set in `geo-places` with write access to `geo-places-baseline`. ⬜ **still pending** — needs to be created manually (fine-grained PAT, `Contents: Read and write`, scoped only to `geo-places-baseline`) and added as a repo secret on `geo-places` before the new `cd.yaml` step will work.

CI does **not** handle the case where the repo or branch is missing — it assumes both are already present.

## Workflow behavior

Trigger: runs as a step in the existing `geo-places` deploy workflow (`.github/workflows/cd.yaml`), immediately after the Cloudflare Pages deploy step, and **only if that step succeeds**.

Deployment itself continues to happen from `geo-places`, as it does today — `geo-places-baseline` is a purely downstream, passive mirror written only after a successful deploy. It is never itself deployed to Cloudflare Pages and holds no Cloudflare secrets, keeping deploy-secret blast radius unchanged.

Steps (see the actual step in `cd.yaml` for the source of truth):

1. Clone `geo-places-baseline` at `main` (shallow, depth 1) using the PAT.
2. `rsync -a --delete` the just-built `out/` directory over the clone (excluding `.git`) — this is a plain directory copy of what CI just built and deployed, not a re-fetch from the live site. `--delete` keeps the mirror honest when an area or layer is removed.
3. Stage everything (`git add -A`). If there is no diff against the last commit, skip commit/push (no-op run).
4. If there is a diff, commit and push to `main` via normal fast-forward (no force push required, since history is linear and single-writer).

## Design decisions and rationale

- **Separate repo, not a branch of `geo-places`**: keeps the data-snapshot concern fully out of the source repo, consistent with the existing pattern of separating `geo-places` (data layer) from `geo-browser` (frontend) and `geo-builder` (CLI).
- **Full `out/` mirror, not just the catalog**: the stated future use is incremental builds, which need every area's manifest + layer data to diff against and reuse — not just the top-level catalog.
- **Single `main` branch, no per-run tags**: no deployment history is needed — only the latest snapshot matters as a diff target. Simplifies both the write path (fixed branch name, no discovery logic) and the read path (any consumer just fetches `origin/main`).
- **Deploy stays in `geo-places`**: `geo-places-baseline` is written *after* a successful deploy, never the other way around. Deploying from the baseline repo instead was considered and rejected — it would require duplicating `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` into a second repo and make production deploys depend on that repo being in sync, which contradicts its purpose as a passive reference snapshot.
- **`main` branch protection is irrelevant**: protection rules on `geo-places`'s `main` don't apply to a different repo, so no bypass or admin override is needed.
- **PAT over default `GITHUB_TOKEN`**: the built-in token is scoped to the repo the workflow runs in and cannot push to `geo-places-baseline`. A fine-grained PAT scoped only to the baseline repo is used instead, minimizing blast radius if leaked.
- **No-op on unchanged content**: avoids empty commits and unnecessary pushes when nothing changed between deploys.

## Known limitations / future considerations

- **PAT expiration**: fine-grained PATs expire (max 1 year). No automated rotation — expect a CI failure as the signal to rotate.
- **No history**: if a future need arises to diff against *older* baselines (not just the latest), this design doesn't support it — would require reintroducing per-run tags or branches.
- **Single writer assumption**: concurrent deploy runs could race on the push. Not currently guarded against; acceptable given this is a personal, low-concurrency project.
- **Repo size**: the mirror is ~29MB today and will grow with each new area. Git history will accumulate a full copy on every changed deploy since there's no squashing — worth revisiting if this becomes unwieldy.
