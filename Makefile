# grafana-mcp — operator entrypoints.
#
# Conventions:
#   - Every target is idempotent and has a documented teardown.
#   - Defaults assume Docker Compose; `ENGINE=podman` swaps to Podman.
#   - K8s targets render only by default; apply requires CONFIRM=yes.

SHELL          := /bin/bash
.SHELLFLAGS    := -eu -o pipefail -c

IMAGE          ?= grafana-mcp:dev
MCP_GRAFANA_VERSION ?= 0.12.1
COMPOSE_FILE   ?= compose/docker-compose.yml
PODMAN_FILE    ?= compose/podman-compose.yml
ENGINE         ?= docker
ENV            ?= dev
PYTEST_ARGS    ?= -ra

ENV_FILE       ?= .env
# --env-file is required: Compose looks for .env next to the compose file by
# default, not at the repo root. Passing it explicitly keeps host-port and
# version overrides honoured no matter where `make` is invoked from.
ifeq ($(ENGINE),podman)
  COMPOSE      := podman compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
else
  COMPOSE      := docker compose --env-file $(ENV_FILE) -f $(COMPOSE_FILE)
endif

.DEFAULT_GOAL := help

## help: list targets
help:
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}' $(MAKEFILE_LIST)

## build: build the local image
build: ## build the wrapper image
	docker build \
	  --build-arg MCP_GRAFANA_VERSION=$(MCP_GRAFANA_VERSION) \
	  -t $(IMAGE) -f docker/Dockerfile .

## run: docker compose up -d (core service only)
run: ## start the MCP server with Compose
	$(COMPOSE) up -d grafana-mcp

## run-full: bring up MCP + local Grafana + Inspector
run-full:
	$(COMPOSE) --profile local-grafana --profile inspector up -d

## stop: docker compose down
stop:
	$(COMPOSE) down --remove-orphans

## logs: tail the server logs
logs:
	$(COMPOSE) logs -f grafana-mcp

## shell: shell into the running container
shell:
	$(COMPOSE) exec grafana-mcp /bin/sh || docker exec -it $$(docker ps -qf name=grafana-mcp) /bin/sh

## inspector: launch MCP Inspector pointed at the running server
inspector:
	./scripts/run-inspector.sh

## smoke: end-to-end smoke test (compose up → /healthz → tools/list → down)
smoke:
	./scripts/smoke-test.sh

## test: lint + functional + API tests against compose stack
test: lint test-functional test-api

## test-functional: pytest functional/
test-functional:
	cd tests && python3 -m pytest functional $(PYTEST_ARGS) --junitxml=../reports/junit-functional.xml

## test-api: pytest api/
test-api:
	cd tests && python3 -m pytest api $(PYTEST_ARGS) --junitxml=../reports/junit-api.xml

## test-aks-dryrun: server-side dry-run apply for the chosen overlay
test-aks-dryrun:
	kubectl kustomize k8s/overlays/$(ENV) | kubectl apply --dry-run=server -f -

## lint: best-effort lint (skips tools that are not installed)
lint:
	@command -v shellcheck >/dev/null && shellcheck docker/entrypoint.sh scripts/*.sh tests/fixtures/*.sh || echo "shellcheck not installed — skipping"
	@command -v yamllint  >/dev/null && yamllint -s compose/ k8s/ || echo "yamllint not installed — skipping"
	@command -v markdownlint >/dev/null && markdownlint '**/*.md' --ignore node_modules || echo "markdownlint not installed — skipping"
	@kubectl kustomize k8s/overlays/$(ENV) >/dev/null && echo "kustomize render ok ($(ENV))"
	@command -v kubeconform >/dev/null && kubectl kustomize k8s/overlays/$(ENV) | kubeconform -strict -summary || echo "kubeconform not installed — skipping"

## k8s-render: print the rendered manifest set for an overlay
k8s-render:
	kubectl kustomize k8s/overlays/$(ENV)

## k8s-diff: server-side diff against the cluster
k8s-diff:
	kubectl kustomize k8s/overlays/$(ENV) | kubectl diff -f - || true

## k8s-apply-dev: apply dev overlay
k8s-apply-dev:
	kubectl kustomize k8s/overlays/dev | kubectl apply -f -

## k8s-apply-staging: apply staging overlay
k8s-apply-staging:
	kubectl kustomize k8s/overlays/staging | kubectl apply -f -

## k8s-apply-prod: apply prod overlay (CONFIRM=yes required)
k8s-apply-prod:
	@if [ "$(CONFIRM)" != "yes" ]; then echo "Refusing: set CONFIRM=yes"; exit 1; fi
	kubectl kustomize k8s/overlays/prod | kubectl apply -f -

## clean: prune local containers, images, and report files
clean:
	-$(COMPOSE) down -v --remove-orphans
	-docker rmi $(IMAGE) 2>/dev/null || true
	-rm -rf reports/

.PHONY: help build run run-full stop logs shell inspector smoke test test-functional test-api test-aks-dryrun lint k8s-render k8s-diff k8s-apply-dev k8s-apply-staging k8s-apply-prod clean
