#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
if [ ! -f node_modules/next/package.json ]; then
  printf 'Run npm ci in frontend first.\n' >&2
  exit 1
fi
npm run typecheck
npm run build
[ -f .next/standalone/server.js ] || { printf 'Next standalone build missing.\n' >&2; exit 1; }
mkdir -p .next/standalone/.next
rm -rf .next/standalone/public .next/standalone/.next/static
cp -R public .next/standalone/public
cp -R .next/static .next/standalone/.next/static
printf 'Production frontend ready. Run bash scripts/start.sh from the project root.\n'
