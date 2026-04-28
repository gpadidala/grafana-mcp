#!/usr/bin/env bash
# Render a Kustomize overlay to stdout. `kubectl kustomize` is used because
# it ships with the kubectl binary the operator already has.
#
# Usage: scripts/render-manifests.sh <dev|staging|prod>

set -euo pipefail
ENV="${1:?usage: $0 <dev|staging|prod>}"
cd "$(dirname "$0")/.."
kubectl kustomize "k8s/overlays/${ENV}"
