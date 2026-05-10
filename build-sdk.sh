#!/bin/bash
# Build the qym SDK wheel + sdist and (optionally) download all transitive
# dependencies as Linux wheels, then package everything into a single tarball
# ready for USB transfer to an air-gapped Nexus.
#
# Run this on a machine with public PyPI access (e.g. your Mac).

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

SDK_DIR="${REPO_ROOT}/packages/sdk"
PYPROJECT="${SDK_DIR}/pyproject.toml"

if [[ ! -f "$PYPROJECT" ]]; then
    echo -e "${RED}Cannot find ${PYPROJECT}${NC}" >&2
    exit 1
fi

PY="$(command -v python3 || command -v python)"
if [[ -z "$PY" ]]; then
    echo -e "${RED}Python is required.${NC}" >&2
    exit 1
fi

echo -e "${GREEN}=== QYM SDK builder ===${NC}\n"

# Current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version\s*=' "$PYPROJECT" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
echo "Current SDK version: ${YELLOW}${CURRENT_VERSION}${NC}"

# Bump prompt
read -r -p "New version (blank to keep ${CURRENT_VERSION}): " NEW_VERSION
NEW_VERSION="${NEW_VERSION:-$CURRENT_VERSION}"

if [[ "$NEW_VERSION" != "$CURRENT_VERSION" ]]; then
    # Update pyproject.toml
    sed -E "s/^version[[:space:]]*=[[:space:]]*\"[^\"]+\"/version = \"${NEW_VERSION}\"/" "$PYPROJECT" > "${PYPROJECT}.tmp"
    mv "${PYPROJECT}.tmp" "$PYPROJECT"
    echo -e "${GREEN}Bumped version to ${NEW_VERSION} in ${PYPROJECT}${NC}"
fi

# Bundle deps?
read -r -p "Also bundle transitive dependencies for the air-gapped install? (Y/n): " BUNDLE_DEPS
BUNDLE_DEPS=${BUNDLE_DEPS:-y}

PYTARGET="3.9"
if [[ "$BUNDLE_DEPS" =~ ^[Yy]$ ]]; then
    read -r -p "Target Python version on the install machine [3.9]: " PYTARGET
    PYTARGET=${PYTARGET:-3.9}
fi

# Confirm
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Version:    ${NEW_VERSION}"
echo "  Bundle deps: ${BUNDLE_DEPS}"
[[ "$BUNDLE_DEPS" =~ ^[Yy]$ ]] && echo "  Target Python: ${PYTARGET}"
echo ""
read -r -p "Proceed? (Y/n): " CONFIRM
CONFIRM=${CONFIRM:-y}
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${RED}Aborted.${NC}"
    exit 1
fi

# Output paths
OUTPUT_DIR="${REPO_ROOT}/builds/qym-sdk"
BUNDLE_NAME="qym-${NEW_VERSION}-bundle"
BUNDLE_DIR="${OUTPUT_DIR}/${BUNDLE_NAME}"
TARBALL="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"

rm -rf "$BUNDLE_DIR" "$TARBALL"
mkdir -p "$BUNDLE_DIR"

# Ensure build tooling
echo -e "\n${GREEN}[1/4] Ensuring build tooling...${NC}"
"$PY" -m pip install --quiet --upgrade build

# Build wheel + sdist into bundle dir
echo -e "\n${GREEN}[2/4] Building wheel + sdist...${NC}"
"$PY" -m build "$SDK_DIR" --outdir "$BUNDLE_DIR"

# Download transitive deps
if [[ "$BUNDLE_DEPS" =~ ^[Yy]$ ]]; then
    echo -e "\n${GREEN}[3/4] Downloading Linux deps for Python ${PYTARGET}...${NC}"
    "$PY" -m pip download "qym==${NEW_VERSION}" \
        --platform manylinux2014_x86_64 \
        --python-version "$PYTARGET" \
        --only-binary=:all: \
        -d "$BUNDLE_DIR" \
        --no-deps  # qym wheel is local, deps below
    # Now download every transitive dep (no version pin to grab latest compatible)
    "$PY" -m pip download "qym==${NEW_VERSION}" \
        --platform manylinux2014_x86_64 \
        --python-version "$PYTARGET" \
        --only-binary=:all: \
        -d "$BUNDLE_DIR" \
        --find-links "$BUNDLE_DIR" \
        --index-url https://pypi.org/simple/ || {
            echo -e "${YELLOW}Note: some deps may need source distributions. Falling back...${NC}"
            "$PY" -m pip download "qym==${NEW_VERSION}" \
                -d "$BUNDLE_DIR" \
                --find-links "$BUNDLE_DIR" \
                --index-url https://pypi.org/simple/
        }
else
    echo -e "\n${GREEN}[3/4] Skipping transitive deps${NC}"
fi

# Package into a single tarball
echo -e "\n${GREEN}[4/4] Packaging bundle tarball...${NC}"
( cd "$OUTPUT_DIR" && tar czf "${BUNDLE_NAME}.tar.gz" "$BUNDLE_NAME" )

# Summary
SIZE=$(du -h "$TARBALL" | cut -f1)
FILE_COUNT=$(ls "$BUNDLE_DIR" | wc -l | tr -d ' ')
echo ""
echo -e "${GREEN}=== Done ===${NC}"
echo "Version: ${NEW_VERSION}"
echo "Files:   ${FILE_COUNT} wheel/sdist files"
echo "Bundle:  ${TARBALL} (${SIZE})"
echo ""
echo "Next steps:"
echo "  1. USB-transfer ${TARBALL} to a machine that can reach Nexus."
echo "  2. On that machine: ./upload-sdk-to-nexus.sh ${BUNDLE_NAME}.tar.gz"
