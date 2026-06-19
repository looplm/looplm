#!/usr/bin/env bash
#
# Cut a release: bump version across all manifests, commit, tag, push.
# Usage: scripts/release.sh {patch|minor|major}
#
# Triggers CI which builds & pushes Docker images tagged X.Y.Z, X.Y, latest,
# and sha-<short> to Docker Hub on the tag push.
#
set -euo pipefail

BUMP_TYPE="${1:-}"
if [[ ! "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]]; then
  echo "Usage: $0 {patch|minor|major}" >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

# --- Safety checks --------------------------------------------------------

BRANCH="$(git symbolic-ref --short HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  echo "Error: releases must be cut from main (currently on '$BRANCH')" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree has uncommitted changes — commit or stash first" >&2
  git status --short >&2
  exit 1
fi

git fetch origin main --quiet
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [[ "$LOCAL" != "$REMOTE" ]]; then
  echo "Error: local main is not in sync with origin/main" >&2
  echo "  local:  $LOCAL" >&2
  echo "  remote: $REMOTE" >&2
  echo "  Run 'git pull --ff-only' or 'git push' as appropriate." >&2
  exit 1
fi

# --- Compute versions -----------------------------------------------------

CURRENT="$(sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' package.json | head -n1)"
if [[ -z "$CURRENT" ]]; then
  echo "Error: could not read current version from package.json" >&2
  exit 1
fi

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
case "$BUMP_TYPE" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEW="$MAJOR.$MINOR.$PATCH"
TAG="v$NEW"

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Error: tag $TAG already exists" >&2
  exit 1
fi

echo
echo "  Current: $CURRENT"
echo "  New:     $NEW"
echo "  Tag:     $TAG"
echo
read -r -p "Proceed? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[yY] ]]; then
  echo "Aborted."
  exit 1
fi

# --- Bump manifests -------------------------------------------------------

MANIFESTS=(
  "package.json"
  "apps/web/package.json"
  "apps/api/pyproject.toml"
  "connectors/pyproject.toml"
  "apps/api/app/__init__.py"
)

for f in "${MANIFESTS[@]}"; do
  case "$f" in
    *.json)
      sed -i.bak -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")$CURRENT(\")/\1$NEW\2/" "$f"
      ;;
    *.toml)
      sed -i.bak -E "s/^(version[[:space:]]*=[[:space:]]*\")$CURRENT(\")/\1$NEW\2/" "$f"
      ;;
    *.py)
      # The API serves __version__ from app/__init__.py (the package itself is
      # installed --no-root in the Docker image, so importlib.metadata can't see it).
      sed -i.bak -E "s/^(__version__[[:space:]]*=[[:space:]]*\")$CURRENT(\")/\1$NEW\2/" "$f"
      ;;
  esac
  rm -f "$f.bak"
done

# Verify all four actually changed
if ! git diff --quiet "${MANIFESTS[@]}"; then
  :
else
  echo "Error: no manifests were modified — version strings may have drifted out of sync" >&2
  git checkout -- "${MANIFESTS[@]}"
  exit 1
fi

# --- Commit, tag, push ----------------------------------------------------

git add "${MANIFESTS[@]}"
git commit -m "chore: release $TAG"
git tag -a "$TAG" -m "Release $TAG"
git push origin main
git push origin "$TAG"

echo
echo "✓ Released $TAG"
echo
echo "Watch CI:       https://github.com/looplm/looplm/actions"
echo "Docker images:  https://hub.docker.com/r/timtres/looplm-web/tags"
echo "                https://hub.docker.com/r/timtres/looplm-api/tags"
