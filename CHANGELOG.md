# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial scaffold targeting upstream `grafana/mcp-grafana` **0.12.1**.
- Dockerfile wrapper, env-var → CLI translation entrypoint.
- Compose v2 stack with `local-grafana` and `inspector` profiles.
- Podman variant (`compose/podman-compose.yml`).
- Pytest suite covering tool discovery, dashboards, datasources, Prometheus,
  Loki, alerting, annotations, health/metrics — 27 passing locally.
- Kustomize base + `dev` / `staging` / `prod` overlays for AKS.
- Production checklist, use-case catalogue, API reference, installation
  guide, architecture document with Mermaid diagrams.

### Pinned versions

| Component | Version |
|---|---|
| upstream `grafana/mcp-grafana` | `0.12.1` |
| Grafana OSS (compose `local-grafana` profile) | `11.6.4` |
| MCP Inspector | `@modelcontextprotocol/inspector@latest` |
| `mcp` Python SDK | `1.27.0` |
| pytest | `8.3.4` |
