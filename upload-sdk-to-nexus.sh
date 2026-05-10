#!/bin/bash
# Extract a qym SDK bundle (built by build-sdk.sh) and upload all wheels +
# sdists to a Nexus PyPI hosted repo via twine.
#
# Run this on a machine that can reach Nexus (e.g. an inside server).
#
# Usage:
#   ./upload-sdk-to-nexus.sh <bundle.tar.gz>
#
# Env vars (override defaults):
#   NEXUS_URL    full upload URL, including trailing slash
#                e.g. https://nexus.estishraf.gov.sa/repository/pypi-internal/
#   NEXUS_USER   Nexus username  (or pass via prompt)
#   NEXUS_PASS   Nexus password  (or pass via prompt)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <qym-X.Y.Z-bundle.tar.gz>" >&2
    exit 2
fi

BUNDLE_TGZ="$(realpath "$1")"
if [[ ! -f "$BUNDLE_TGZ" ]]; then
    echo -e "${RED}Bundle not found: ${BUNDLE_TGZ}${NC}" >&2
    exit 1
fi

PY="$(command -v python3 || command -v python)"
if [[ -z "$PY" ]]; then
    echo -e "${RED}Python is required.${NC}" >&2
    exit 1
fi

echo -e "${GREEN}=== QYM SDK -> Nexus uploader ===${NC}\n"

# Nexus URL
DEFAULT_NEXUS_URL="${NEXUS_URL:-https://nexus.estishraf.gov.sa/repository/pypi-internal/}"
read -r -p "Nexus upload URL [${DEFAULT_NEXUS_URL}]: " NEXUS_URL_INPUT
NEXUS_URL="${NEXUS_URL_INPUT:-$DEFAULT_NEXUS_URL}"

# Strip trailing /simple/ if user pasted the index URL by mistake
NEXUS_URL="${NEXUS_URL%simple/}"
NEXUS_URL="${NEXUS_URL%simple}"
[[ "$NEXUS_URL" != */ ]] && NEXUS_URL="${NEXUS_URL}/"

# Credentials
DEFAULT_USER="${NEXUS_USER:-admin}"
read -r -p "Nexus username [${DEFAULT_USER}]: " USER_INPUT
NEXUS_USER="${USER_INPUT:-$DEFAULT_USER}"

if [[ -n "${NEXUS_PASS:-}" ]]; then
    echo "Using NEXUS_PASS from environment."
else
    read -r -s -p "Nexus password: " NEXUS_PASS
    echo
fi

if [[ -z "$NEXUS_PASS" ]]; then
    echo -e "${RED}Password cannot be empty.${NC}" >&2
    exit 1
fi

# Ensure twine
echo -e "\n${GREEN}[1/4] Ensuring twine is installed...${NC}"
"$PY" -m pip install --quiet --upgrade twine

# Extract bundle
WORK_DIR="$(mktemp -d)"
trap "rm -rf $WORK_DIR" EXIT

echo -e "\n${GREEN}[2/4] Extracting bundle...${NC}"
tar xzf "$BUNDLE_TGZ" -C "$WORK_DIR"

# The bundle root is a single directory inside
EXTRACTED_DIR="$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
if [[ -z "$EXTRACTED_DIR" ]]; then
    echo -e "${RED}Bundle structure unexpected. Expected one top-level directory.${NC}" >&2
    exit 1
fi

# List files
shopt -s nullglob
WHEELS=( "$EXTRACTED_DIR"/*.whl )
SDISTS=( "$EXTRACTED_DIR"/*.tar.gz )
shopt -u nullglob

TOTAL=$(( ${#WHEELS[@]} + ${#SDISTS[@]} ))
echo "Found ${TOTAL} files (${#WHEELS[@]} wheels, ${#SDISTS[@]} sdists):"
for f in "${WHEELS[@]}" "${SDISTS[@]}"; do
    echo "  $(basename "$f")"
done

if [[ "$TOTAL" -eq 0 ]]; then
    echo -e "${RED}No wheels or sdists found in bundle.${NC}" >&2
    exit 1
fi

echo ""
echo -e "${YELLOW}Will upload to:${NC} ${NEXUS_URL}"
read -r -p "Proceed? (Y/n): " CONFIRM
CONFIRM=${CONFIRM:-y}
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${RED}Aborted.${NC}"
    exit 1
fi

# Upload one file at a time. Nexus PyPI auth is per-request and twine's batched
# upload sometimes drops auth on subsequent files (showing as 401). Per-file
# uploads also let us continue past a single "already exists" 400 instead of
# aborting the whole batch.
echo -e "\n${GREEN}[3/4] Uploading via twine (one file at a time, with retries)...${NC}"

UPLOADED=()
SKIPPED=()
FAILED=()
ALL_FILES=( "${WHEELS[@]}" "${SDISTS[@]}" )

upload_one() {
    local file="$1"
    local name attempt rc log
    name="$(basename "$file")"
    for attempt in 1 2 3; do
        log="$(mktemp)"
        if TWINE_USERNAME="$NEXUS_USER" TWINE_PASSWORD="$NEXUS_PASS" \
            "$PY" -m twine upload --disable-progress-bar \
                --repository-url "$NEXUS_URL" \
                "$file" >"$log" 2>&1; then
            rm -f "$log"
            return 0
        fi
        rc=$?
        # Treat "file already exists" as success — Nexus returns 400 on duplicates.
        if grep -qiE '400.*already|file.*already.*exists|already.*been.*uploaded|reason: bad request' "$log"; then
            cat "$log" >&2
            rm -f "$log"
            return 2
        fi
        echo -e "${YELLOW}  attempt ${attempt} failed for ${name} (exit ${rc}); retrying...${NC}" >&2
        cat "$log" >&2
        rm -f "$log"
        sleep 2
    done
    return 1
}

for f in "${ALL_FILES[@]}"; do
    name="$(basename "$f")"
    echo -e "  → uploading ${name}"
    if upload_one "$f"; then
        UPLOADED+=( "$name" )
        echo -e "    ${GREEN}OK${NC}"
    else
        rc=$?
        if [[ "$rc" -eq 2 ]]; then
            SKIPPED+=( "$name" )
            echo -e "    ${YELLOW}already exists on Nexus, skipped${NC}"
        else
            FAILED+=( "$name" )
            echo -e "    ${RED}FAILED after retries${NC}"
        fi
    fi
done

echo ""
echo "Upload summary:"
echo "  uploaded: ${#UPLOADED[@]}"
echo "  skipped:  ${#SKIPPED[@]}  (already on Nexus)"
echo "  failed:   ${#FAILED[@]}"
if (( ${#FAILED[@]} > 0 )); then
    echo -e "${RED}Failed files:${NC}"
    for f in "${FAILED[@]}"; do echo "  - $f"; done
fi

# Verify (assumes the index URL is the upload URL with /simple/ appended)
INDEX_URL="${NEXUS_URL}simple/"
echo -e "\n${GREEN}[4/4] Verifying qym is in Nexus index...${NC}"
LISTED=$(curl -sS -u "${NEXUS_USER}:${NEXUS_PASS}" -k "${INDEX_URL}qym/" | grep -oE 'qym-[0-9][0-9.a-z\-]*' | sort -u || true)

if [[ -n "$LISTED" ]]; then
    echo -e "${GREEN}OK${NC} — index lists:"
    echo "$LISTED" | sed 's/^/  /'
else
    echo -e "${YELLOW}Could not parse index listing (auth or TLS issue?). Check manually:${NC}"
    echo "  curl -u ${NEXUS_USER}:<pass> ${INDEX_URL}qym/"
fi

echo ""
if (( ${#FAILED[@]} > 0 )); then
    echo -e "${RED}=== Done with errors (${#FAILED[@]} file(s) failed) ===${NC}"
else
    echo -e "${GREEN}=== Done ===${NC}"
fi
echo ""
echo "Users can install with:"
echo "  pip install qym --index-url ${INDEX_URL} --trusted-host $(echo "$NEXUS_URL" | awk -F/ '{print $3}')"

if (( ${#FAILED[@]} > 0 )); then
    exit 1
fi
