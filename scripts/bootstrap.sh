#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-full}"
case "$mode" in full|--backend-only) ;; *) printf 'Usage: bash scripts/bootstrap.sh [--backend-only]\n' >&2; exit 2;; esac
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
[ -f config.yaml ] || cp config.example.yaml config.yaml
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
if [ "$mode" = full ]; then
  command -v node >/dev/null || { printf 'Node.js 20+ is required for the Phoenix frontend.\n' >&2; exit 1; }
  node -e 'if (Number(process.versions.node.split(".")[0]) < 20) process.exit(1)'
  command -v npm >/dev/null
  (cd frontend && npm ci --no-audit --no-fund)
fi
printf '\nConfigured. Fill .env and config.yaml before live model runs.\n'
printf 'Full UI: bash scripts/start.sh --dev\nBackend only: bash scripts/start.sh --backend-only\n'
printf 'Production: bash scripts/build-ui.sh && bash scripts/start.sh\n'
printf 'No-cost scripted swarm check: .venv/bin/python -m phoenix swarm-demo\n'
