#!/usr/bin/env bash
# Restores public/ to input-only shape after a geo-builder designer (--edit) session.
# Thin wrapper around scripts/clean_public.py, mirroring build.sh's naming, so there's a
# one-command way to run it manually right after a designer session -- before committing
# and before build.sh/build.cmd would otherwise run it for you automatically. Needed for
# more than the documented first-launch pull: adding a *new* area in designer mode has
# also been observed writing real url/layers/csv straight into that area's public/
# manifest even under --noninvasive (see docs/CLI.md). Run from anywhere; paths are
# resolved relative to this script's location.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python "$SCRIPT_DIR/scripts/clean_public.py"
