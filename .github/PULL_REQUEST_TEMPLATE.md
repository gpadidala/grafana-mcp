## Summary

<!-- 1-3 bullets. What changed and why. -->

## Test plan

- [ ] `make test` passes locally against full LGTM compose stack
- [ ] `make k8s-render ENV=prod | kubeconform -strict -summary` clean
- [ ] If image bumped: `MCP_GRAFANA_VERSION` updated in Makefile + Dockerfile + CHANGELOG
- [ ] If new datasource type: provisioning file updated + integration test added
- [ ] If touching the prod overlay: applied to staging first, observed for 24h

## Risk / blast radius

<!-- One sentence. Include "blast radius: ..." -->

## Rollback

<!-- One sentence on how to undo this if it goes wrong. -->
