#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../integrations/phoenix"
docker info >/dev/null
for category in base web crypto pwn reverse forensics misc; do
  docker build -t "phoenix-tools-${category}:0.1.0" -f "images/${category}/Dockerfile" .
done
