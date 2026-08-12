#!/usr/bin/env bash
#
# Install this repository's local-only protections against committing voter data.
#
# Git does not track hooks or filter configuration, so both live in .git/ and
# have to be installed once per clone. Run:
#
#     bash scripts/install-hooks.sh

set -eo pipefail

root=$(git rev-parse --show-toplevel)
hooks=$(git rev-parse --git-path hooks)

mkdir -p "$hooks"
cp "$root/scripts/pre-commit" "$hooks/pre-commit"
chmod +x "$hooks/pre-commit"
echo "Installed $hooks/pre-commit"

if [ -x "$root/.venv/bin/nbstripout" ]; then
    (cd "$root" && .venv/bin/nbstripout --install --attributes .gitattributes)
    echo "Installed the nbstripout clean filter (see .gitattributes)"
else
    echo "WARNING: no .venv/bin/nbstripout, so the clean filter was NOT installed." >&2
    echo "         Run: uv pip install -e \".[dev]\" && bash scripts/install-hooks.sh" >&2
fi
