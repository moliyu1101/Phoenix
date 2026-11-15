#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { printf 'Docker CLI is required.\n' >&2; exit 1; }
docker info >/dev/null
exec bash scripts/build-sandboxes.sh
