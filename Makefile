# PocketLinux developer entry points
PY ?= python3
PLX := $(PY) -m plx

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nPocketLinux targets:\n\n"} /^[a-zA-Z0-9_.-]+:.*?##/ {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2} /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)}' $(MAKEFILE_LIST)
	@echo ""

.PHONY: test
test: ## Run the test suite
	$(PY) -m pytest $(ARGS)

.PHONY: lint
lint: ## Lint + format check
	$(PY) -m ruff check plx tests
	$(PY) -m ruff format --check plx tests

.PHONY: fmt
fmt: ## Auto-format
	$(PY) -m ruff check --fix plx tests
	$(PY) -m ruff format plx tests

.PHONY: check
check: lint test ## Lint + tests

.PHONY: doctor
doctor: ## Run plx doctor on this machine
	$(PLX) doctor

.PHONY: demo
demo: ## Offline demo of the CLI surface
	$(PLX) version && $(PLX) info && $(PLX) doctor --json

.PHONY: clean
clean: ## Remove caches and build artefacts
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
