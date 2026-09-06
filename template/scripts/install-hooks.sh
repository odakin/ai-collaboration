#!/bin/bash
# Install this repo's git hooks (idempotent; symlinks, so edits to hooks/ propagate).
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$REPO/.git/hooks"
chmod +x "$REPO/hooks/pre-commit"
ln -sf "$REPO/hooks/pre-commit" "$REPO/.git/hooks/pre-commit"
echo "installed: $REPO/.git/hooks/pre-commit -> hooks/pre-commit"
