#!/bin/sh
# Translate env vars → mcp-grafana CLI flags.
#
# Why: upstream supports both env-driven and flag-driven config, but several
# knobs are flag-only (transport, address, TLS files, enabled-tools, debug).
# Centralising the translation here keeps docker-compose.yml and Kubernetes
# manifests free of repetitive `--flag $(VAR)` plumbing.
#
# POSIX sh (dash-compatible). No bashisms.

set -eu

# Append "$1" to the args list only when "$2" is non-empty.
append_if_set() {
  flag=$1
  value=$2
  if [ -n "$value" ]; then
    set -- "$@" "$flag" "$value"
    # shellcheck disable=SC2124
    APPEND_ARGS="$APPEND_ARGS $flag $value"
  fi
}

ARGS=""

# Transport
ARGS="$ARGS -t ${MCP_TRANSPORT:-streamable-http}"

# Listener address (sse / streamable-http only — harmless to pass otherwise)
[ -n "${MCP_ADDRESS:-}" ] && ARGS="$ARGS --address ${MCP_ADDRESS}"
[ -n "${MCP_BASE_PATH:-}" ] && ARGS="$ARGS --base-path ${MCP_BASE_PATH}"
[ -n "${MCP_ENDPOINT_PATH:-}" ] && ARGS="$ARGS --endpoint-path ${MCP_ENDPOINT_PATH}"

# Logging
[ -n "${MCP_LOG_LEVEL:-}" ] && ARGS="$ARGS --log-level ${MCP_LOG_LEVEL}"
[ "${MCP_DEBUG:-false}" = "true" ] && ARGS="$ARGS --debug"

# Metrics
[ "${MCP_METRICS:-false}" = "true" ] && ARGS="$ARGS --metrics"
[ -n "${MCP_METRICS_ADDRESS:-}" ] && ARGS="$ARGS --metrics-address ${MCP_METRICS_ADDRESS}"

# Sessions / Loki guardrails
[ -n "${MCP_SESSION_IDLE_TIMEOUT_MINUTES:-}" ] && \
  ARGS="$ARGS --session-idle-timeout-minutes ${MCP_SESSION_IDLE_TIMEOUT_MINUTES}"
[ -n "${MCP_MAX_LOKI_LOG_LIMIT:-}" ] && \
  ARGS="$ARGS --max-loki-log-limit ${MCP_MAX_LOKI_LOG_LIMIT}"

# Tool categories
[ -n "${MCP_ENABLED_TOOLS:-}" ] && ARGS="$ARGS --enabled-tools ${MCP_ENABLED_TOOLS}"
[ "${MCP_DISABLE_WRITE:-false}" = "true" ] && ARGS="$ARGS --disable-write"

# Client TLS (Grafana connection)
[ -n "${MCP_TLS_CERT_FILE:-}" ] && ARGS="$ARGS --tls-cert-file ${MCP_TLS_CERT_FILE}"
[ -n "${MCP_TLS_KEY_FILE:-}" ] && ARGS="$ARGS --tls-key-file ${MCP_TLS_KEY_FILE}"
[ -n "${MCP_TLS_CA_FILE:-}" ] && ARGS="$ARGS --tls-ca-file ${MCP_TLS_CA_FILE}"
[ "${MCP_TLS_SKIP_VERIFY:-false}" = "true" ] && ARGS="$ARGS --tls-skip-verify"

# Server TLS (streamable-http listener)
[ -n "${MCP_SERVER_TLS_CERT_FILE:-}" ] && \
  ARGS="$ARGS --server.tls-cert-file ${MCP_SERVER_TLS_CERT_FILE}"
[ -n "${MCP_SERVER_TLS_KEY_FILE:-}" ] && \
  ARGS="$ARGS --server.tls-key-file ${MCP_SERVER_TLS_KEY_FILE}"

# Never log the token. Print everything else for ops debugging.
if [ "${MCP_DEBUG:-false}" = "true" ]; then
  echo "[entrypoint] mcp-grafana $ARGS  (extra args: $*)" >&2
fi

# Allow callers to append/override by passing args after the image.
# shellcheck disable=SC2086
exec /app/mcp-grafana $ARGS "$@"
