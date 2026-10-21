#!/usr/bin/env bash
# Compatibility wrapper; requires Python 3.11+. No writes on --dry-run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "${PYTHON:-python3}" "$ROOT/scripts/import_issues.py" "$@"
