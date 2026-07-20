SHELL := /bin/bash
.DEFAULT_GOAL := help

UV ?= uv
PNPM ?= pnpm
SHELLCHECK ?= shellcheck
RG ?= rg
PHASE2_ENV_FILE ?= infra/compose/phase2.env
PHASE2_SECRET_GID ?= $(shell id -g)
export PHASE2_SECRET_GID
PHASE2_COMPOSE = docker compose --env-file $(PHASE2_ENV_FILE) --file compose.yaml
PHASE2_ALL_PROFILES = --profile core --profile app --profile observability --profile dev
PHASE3_ENV_FILE ?= infra/compose/phase3.env
PHASE3_SECRET_GID ?= $(shell id -g)
export PHASE3_SECRET_GID
PHASE3_COMPOSE = docker compose --env-file $(PHASE3_ENV_FILE) --file compose.phase3.yaml
PHASE3_ALL_PROFILES = --profile llama --profile nemotron --profile retriever \
	--profile stage-llama --profile stage-nemotron --profile stage-retriever
PHASE3_PYTHON_SCRIPTS = scripts/phase3_benchmark.py scripts/phase3_quality.py scripts/phase3_runtime_evidence.py scripts/phase3_scorecard.py
PHASE5_PYTHON_SCRIPTS = scripts/phase5_benchmark.py scripts/phase5_finalize_winner.py
PHASE6_PYTHON_SCRIPTS = scripts/phase6_candidate_eval.py scripts/phase6_winner_e2e.py
CHATBOT_EVAL_PYTHON_SCRIPTS = scripts/phase12_rag_eval.py scripts/load_test_rag.py

.PHONY: help require-uv require-pnpm require-shellcheck require-rg require-docker require-jq \
	preflight bootstrap lock-check secret-scan lint format format-check typecheck test build \
	smoke check phase2-secrets phase2-config phase2-images up-core up down migrate \
	phase2-status phase2-acceptance phase3-secrets phase3-config phase3-images \
	phase3-cache-llama phase3-cache-nemotron phase3-cache-retriever phase3-status \
	phase3-down phase3-acceptance phase5-eval eval eval-chatbot benchmark-chatbot

help: ## Show the repository command contract.
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

require-uv:
	@command -v "$(UV)" >/dev/null 2>&1 || { printf 'Missing required command: %s\n' "$(UV)" >&2; exit 127; }

require-pnpm:
	@command -v "$(PNPM)" >/dev/null 2>&1 || { printf 'Missing required command: %s\n' "$(PNPM)" >&2; exit 127; }

require-shellcheck:
	@command -v "$(SHELLCHECK)" >/dev/null 2>&1 || { printf 'Missing required command: %s\n' "$(SHELLCHECK)" >&2; exit 127; }

require-rg:
	@command -v "$(RG)" >/dev/null 2>&1 || { printf 'Missing required command: %s\n' "$(RG)" >&2; exit 127; }

require-docker:
	@command -v docker >/dev/null 2>&1 || { printf 'Missing required command: docker\n' >&2; exit 127; }
	@docker info >/dev/null 2>&1 || { printf 'Docker daemon is unavailable.\n' >&2; exit 1; }

require-jq:
	@command -v jq >/dev/null 2>&1 || { printf 'Missing required command: jq\n' >&2; exit 127; }

preflight: ## Capture read-only host/GPU/container inventory evidence (writes artifacts).
	./scripts/preflight.sh

bootstrap: require-uv require-pnpm ## Install exactly the reviewed Python and Node lockfiles.
	$(UV) sync --all-packages --locked
	$(PNPM) install --frozen-lockfile

lock-check: require-uv require-pnpm ## Verify lockfiles and the installed Python environment offline.
	$(UV) lock --check --offline --python 3.14
	UV_BIN="$(UV)" PYTHON_BIN=".venv/bin/python" ./scripts/python-environment-check.sh
	$(PNPM) install --frozen-lockfile --offline --lockfile-only

secret-scan: require-rg ## Reject high-confidence credentials without printing their values.
	RG_BIN="$(RG)" ./scripts/source-secret-scan.sh

lint: require-uv require-pnpm require-shellcheck ## Lint Python, TypeScript, and shell without changing source.
	$(UV) run --locked --no-sync ruff check apps packages tests scripts/phase2-persistence.py $(PHASE3_PYTHON_SCRIPTS) $(PHASE5_PYTHON_SCRIPTS) $(PHASE6_PYTHON_SCRIPTS) $(CHATBOT_EVAL_PYTHON_SCRIPTS) migrations
	$(PNPM) lint
	bash -n scripts/*.sh infra/*/*.sh
	$(SHELLCHECK) scripts/*.sh infra/*/*.sh

format: require-uv require-pnpm ## Rewrite source with the configured Python and web formatters.
	$(UV) run --locked --no-sync ruff format apps packages tests scripts/phase2-persistence.py $(PHASE3_PYTHON_SCRIPTS) $(PHASE5_PYTHON_SCRIPTS) $(PHASE6_PYTHON_SCRIPTS) $(CHATBOT_EVAL_PYTHON_SCRIPTS) migrations
	$(PNPM) format

format-check: require-uv require-pnpm ## Verify Python and web formatting without changing source.
	$(UV) run --locked --no-sync ruff format --check apps packages tests scripts/phase2-persistence.py $(PHASE3_PYTHON_SCRIPTS) $(PHASE5_PYTHON_SCRIPTS) $(PHASE6_PYTHON_SCRIPTS) $(CHATBOT_EVAL_PYTHON_SCRIPTS) migrations
	$(PNPM) format:check

typecheck: require-uv require-pnpm ## Run Python and TypeScript static type checks.
	$(UV) run --locked --no-sync mypy apps/api/app apps/worker/worker packages/contracts/src packages/rag-eval/src packages/shared-python/src scripts/phase2-persistence.py $(PHASE3_PYTHON_SCRIPTS) $(PHASE5_PYTHON_SCRIPTS) $(PHASE6_PYTHON_SCRIPTS) $(CHATBOT_EVAL_PYTHON_SCRIPTS) migrations
	$(PNPM) typecheck

test: require-uv require-pnpm ## Run all CPU-only pytest and Vitest suites.
	$(UV) run --locked --no-sync pytest
	$(PNPM) test

build: require-pnpm ## Compile the production web skeleton without starting a service.
	$(PNPM) build

smoke: require-uv require-pnpm ## Start temporary loopback skeletons and verify their public pages.
	UV_BIN="$(UV)" PNPM_BIN="$(PNPM)" ./scripts/smoke-phase1.sh

check: ## Run the complete CPU-only repository quality gate in a fixed order.
	$(MAKE) lock-check
	$(MAKE) secret-scan
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) build
	$(MAKE) smoke

phase2-secrets: ## Initialize local Compose secret files if missing (writes .secrets).
	./scripts/phase2-secrets.sh init

phase2-config: require-docker require-jq ## Validate the rendered Compose topology without starting services.
	PHASE2_ENV_FILE="$(PHASE2_ENV_FILE)" ./scripts/phase2-compose-check.sh

phase2-images: require-docker ## Stage and verify every pinned Phase 2 image for ARM64 (network on cache miss).
	PHASE2_ENV_FILE="$(PHASE2_ENV_FILE)" ./scripts/phase2-images.sh

up-core: phase2-secrets phase2-config phase2-images ## Start persistent core datastores (changes local Docker state/data).
	$(PHASE2_COMPOSE) --profile core up --detach --wait --wait-timeout 180

up: phase2-secrets phase2-config phase2-images ## Build/start Phase 2 core, app, observability, and dev profiles.
	$(PHASE2_COMPOSE) $(PHASE2_ALL_PROFILES) up --detach --build --wait --wait-timeout 300

down: require-docker ## Stop Phase 2 containers without deleting named volumes.
	$(PHASE2_COMPOSE) $(PHASE2_ALL_PROFILES) down --remove-orphans

migrate: phase2-secrets require-docker ## Apply reviewed Alembic migrations to healthy Phase 2 PostgreSQL.
	PHASE2_ENV_FILE="$(PHASE2_ENV_FILE)" ./scripts/phase2-migrate.sh

phase2-status: require-docker ## Show the current Phase 2 container and health state.
	$(PHASE2_COMPOSE) $(PHASE2_ALL_PROFILES) ps

phase2-acceptance: phase2-secrets phase2-config phase2-images ## Run destructive test sentinels, recreate containers, then clean them.
	PHASE2_ENV_FILE="$(PHASE2_ENV_FILE)" ./scripts/smoke-phase2.sh

phase3-secrets: ## Initialize/check the local NGC staging secret from Docker auth.
	@if [[ -s .secrets/phase3/ngc_api_key ]]; then \
		./scripts/phase3-secrets.sh check; \
	else \
		./scripts/phase3-secrets.sh init-from-docker-auth; \
	fi

phase3-config: require-docker require-jq ## Validate private NIM topology and immutable image pins.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/phase3-compose-check.sh

phase3-images: phase3-secrets require-docker ## Stage/verify reviewed Phase 3 ARM64 images.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/phase3-images.sh stage all

phase3-cache-llama: phase3-secrets phase3-config ## Stage the Llama model cache with temporary egress.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/phase3-cache.sh stage llama

phase3-cache-nemotron: phase3-secrets phase3-config ## Stage the Nemotron model cache with temporary egress.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/phase3-cache.sh stage nemotron

phase3-cache-retriever: phase3-secrets phase3-config ## Stage embedding/reranking caches with temporary egress.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/phase3-cache.sh stage retriever

phase3-status: require-docker ## Show Phase 3 NIM containers without exposing a host port.
	$(PHASE3_COMPOSE) $(PHASE3_ALL_PROFILES) ps

phase3-down: require-docker ## Stop Phase 3 containers while preserving model-cache volumes.
	$(PHASE3_COMPOSE) $(PHASE3_ALL_PROFILES) down --remove-orphans

phase3-acceptance: phase3-secrets phase3-config ## Run the live NIM bake-off; BGE access remains a hard gate.
	PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/smoke-phase3.sh

phase5-eval: require-uv require-docker ## Run the historical candidate grid; it never activates an alias.
	UV_BIN="$(UV)" PHASE3_ENV_FILE="$(PHASE3_ENV_FILE)" ./scripts/smoke-phase5.sh

eval: phase5-eval ## Alias for the historical candidate-grid workflow.

eval-chatbot: require-uv ## Run real offline memory/citation/ingestion regression gates.
	@mkdir -p evals/reports
	$(UV) run --locked --no-sync pytest -q \
		apps/api/tests/test_conversation_memory.py \
		apps/api/tests/test_phase6_rag.py \
		apps/api/tests/test_exact_token_counter.py \
		apps/worker/tests/test_parse_quality.py \
		--junitxml=evals/reports/chatbot-contract.xml
	@if [[ -n "$${EVAL_OBSERVATIONS:-}" && -n "$${EVAL_CONFIG_FINGERPRINT:-}" ]]; then \
		$(UV) run --locked --no-sync python scripts/phase12_rag_eval.py \
			--observations "$$EVAL_OBSERVATIONS" \
			--config-fingerprint "$$EVAL_CONFIG_FINGERPRINT"; \
	else \
		printf '%s\n' 'Retrieval scoring skipped: set EVAL_OBSERVATIONS and EVAL_CONFIG_FINGERPRINT for measured data.'; \
	fi

benchmark-chatbot: require-uv ## Benchmark the live API; requires NTC_BENCHMARK_TOKEN.
	$(UV) run --locked --no-sync python scripts/load_test_rag.py
