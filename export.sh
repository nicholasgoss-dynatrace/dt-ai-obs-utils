#!/bin/bash
# Creates a clean customer distribution tarball from the current committed state.
# Excludes: git history, .env (secrets), __pycache__, virtualenvs.
#
# Usage:
#   ./export.sh               — outputs dt-ai-obs-test-<date>.tar.gz in the current directory
#   ./export.sh /path/to/dir  — outputs to a specific directory

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="dt-ai-obs-test"
TIMESTAMP="$(date +%Y%m%d)"
OUTPUT_DIR="${1:-${REPO_ROOT}/..}"
OUTPUT_FILE="${OUTPUT_DIR}/${REPO_NAME}-${TIMESTAMP}.tar.gz"

cd "$REPO_ROOT"

# Verify we're in a git repo with committed content
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "ERROR: Not a git repository. Run from the dt-ai-obs-test directory."
    exit 1
fi

echo "Exporting committed files (no git history)..."
git archive --format=tar.gz --prefix="${REPO_NAME}/" HEAD -o "$OUTPUT_FILE"

echo ""
echo "✓ Created: ${OUTPUT_FILE}"
echo ""
echo "Contents:"
tar -tzf "$OUTPUT_FILE" | sed 's/^/  /'
echo ""
echo "Share ${REPO_NAME}-${TIMESTAMP}.tar.gz with your customer."
echo "They can extract it with: tar -xzf ${REPO_NAME}-${TIMESTAMP}.tar.gz"
