#!/bin/sh
# install_deps.sh — install dompdf (PHP) + mathjax-full (Node.js) for PDF math rendering
# Run once after installing the moodle-pdf-generation skill.
#
# dompdf: GitHub release zip includes vendor/ (no composer needed), pure PHP.
# mathjax-full: npm package for server-side LaTeX→SVG rendering (requires Node.js).
#
# Pure PHP deps: dom, gd, mbstring (standard in any Moodle install).
# Node.js deps: node + npm (for MathJax SVG rendering; falls back to Unicode if absent).

set -e

DOMPDF_VERSION="3.1.5"
DOMPDF_URL="https://github.com/dompdf/dompdf/releases/download/v${DOMPDF_VERSION}/dompdf-${DOMPDF_VERSION}.zip"
HERMES_HOME="${HERMES_HOME:-/var/www/moodledata/.hermes}"
DOMPDF_DIR="${HERMES_HOME}/lib/dompdf"
MATHJAX_DIR="${HERMES_HOME}/lib/mathjax-svg"

# --- dompdf ---
if [ -f "${DOMPDF_DIR}/vendor/autoload.php" ]; then
    echo "dompdf ${DOMPDF_VERSION} already installed at ${DOMPDF_DIR}"
else
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
        EXTRACTED_DIR="${TMPDIR}/dompdf-extract/dompdf"
    fi
    if [ ! -d "$EXTRACTED_DIR" ]; then
        echo "ERROR: Could not find dompdf directory in extracted zip" >&2
        ls "${TMPDIR}/dompdf-extract/" >&2
        exit 1
    fi

    mkdir -p "$DOMPDF_DIR"
    cp -r "${EXTRACTED_DIR}/." "$DOMPDF_DIR/"

    if [ -f "${DOMPDF_DIR}/vendor/autoload.php" ]; then
        echo "dompdf ${DOMPDF_VERSION} installed successfully."
    else
        echo "ERROR: vendor/autoload.php not found after extraction" >&2
        exit 1
    fi
fi

# --- mathjax-full (Node.js, for LaTeX→SVG rendering) ---
if [ -f "${MATHJAX_DIR}/node_modules/mathjax-full/package.json" ]; then
    echo "mathjax-full already installed at ${MATHJAX_DIR}"
else
    if ! command -v node >/dev/null 2>&1; then
        echo "WARNING: Node.js not found — MathJax SVG rendering unavailable (Unicode fallback will be used)"
        exit 0
    fi
    echo "Installing mathjax-full to ${MATHJAX_DIR}..."
    mkdir -p "$MATHJAX_DIR"
    cd "$MATHJAX_DIR"
    npm init -y >/dev/null 2>&1
    npm install mathjax-full >/dev/null 2>&1
    if [ -f "${MATHJAX_DIR}/node_modules/mathjax-full/package.json" ]; then
        echo "mathjax-full installed successfully."
    else
        echo "WARNING: mathjax-full installation failed — Unicode fallback will be used"
    fi
fi
