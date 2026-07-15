#!/bin/sh
# install_deps.sh — download and install dompdf v3.1.5 (pure PHP, platform-independent)
# Run once after installing the moodle-pdf-generation skill.
#
# dompdf's GitHub release zip includes vendor/ (all dependencies) — no composer needed.
# Pure PHP: requires only dom, gd, mbstring extensions (standard in any Moodle install).

set -e

DOMPDF_VERSION="3.1.5"
DOMPDF_URL="https://github.com/dompdf/dompdf/releases/download/v${DOMPDF_VERSION}/dompdf-${DOMPDF_VERSION}.zip"
HERMES_HOME="${HERMES_HOME:-/var/www/moodledata/.hermes}"
DOMPDF_DIR="${HERMES_HOME}/lib/dompdf"

if [ -f "${DOMPDF_DIR}/vendor/autoload.php" ]; then
    echo "dompdf ${DOMPDF_VERSION} already installed at ${DOMPDF_DIR}"
    exit 0
fi

echo "Installing dompdf ${DOMPDF_VERSION} to ${DOMPDF_DIR}..."

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

curl -sL "$DOMPDF_URL" -o "${TMPDIR}/dompdf.zip"

# Verify the download is a valid zip
if ! unzip -tq "${TMPDIR}/dompdf.zip" >/dev/null 2>&1; then
    echo "ERROR: Downloaded file is not a valid zip. URL: $DOMPDF_URL" >&2
    exit 1
fi

unzip -q "${TMPDIR}/dompdf.zip" -d "${TMPDIR}/dompdf-extract"

# The release zip extracts to dompdf-${VERSION}/
EXTRACTED_DIR="${TMPDIR}/dompdf-extract/dompdf-${DOMPDF_VERSION}"
if [ ! -d "$EXTRACTED_DIR" ]; then
    # Some releases extract to just dompdf/
    EXTRACTED_DIR="${TMPDIR}/dompdf-extract/dompdf"
fi
if [ ! -d "$EXTRACTED_DIR" ]; then
    echo "ERROR: Could not find dompdf directory in extracted zip" >&2
    ls "${TMPDIR}/dompdf-extract/" >&2
    exit 1
fi

mkdir -p "$DOMPDF_DIR"
cp -r "${EXTRACTED_DIR}/." "$DOMPDF_DIR/"

# Verify
if [ -f "${DOMPDF_DIR}/vendor/autoload.php" ]; then
    echo "dompdf ${DOMPDF_VERSION} installed successfully."
    echo "  autoload: ${DOMPDF_DIR}/vendor/autoload.php"
else
    echo "ERROR: vendor/autoload.php not found after extraction" >&2
    exit 1
fi
