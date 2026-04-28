#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f compose/docker-compose.yml --profile local-grafana --profile inspector down --remove-orphans "$@"
