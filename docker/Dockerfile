# Thin wrapper over the upstream Grafana MCP image.
#
# The upstream image already runs as a non-root user and ships the binary at
# /app/mcp-grafana. We layer:
#   1. an entrypoint that translates env vars → CLI flags (cleaner UX than
#      passing every flag through docker run)
#   2. a HEALTHCHECK so orchestrators can gate readiness on /healthz
#
# Pinned tag is recorded in CHANGELOG.md and bumped via PR — never use a
# floating tag in production.

ARG MCP_GRAFANA_VERSION=0.12.1
FROM grafana/mcp-grafana:${MCP_GRAFANA_VERSION}

# Upstream is debian-slim and ships without curl/wget. We install curl so
# both Docker's HEALTHCHECK and operator debugging work without docker-cp
# heroics. Alpine variant could replace this, but pinning to the standard
# upstream tag keeps us aligned with grafana/mcp-grafana's release matrix.
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
USER 65532

EXPOSE 8000

# /healthz only responds on sse / streamable-http transports; the entrypoint
# defaults to streamable-http so this is the intended runtime contract.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz | grep -q '^ok$' || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
