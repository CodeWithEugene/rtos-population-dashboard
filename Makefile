# Reproducible entry points. `make help` lists targets.
# Uses uv if available (fast, isolated), else falls back to plain python.

PY := $(shell [ -d .venv ] && echo .venv/bin/python || command -v python3)
RUN := $(if $(shell command -v uv),uv run,$(PY))

.DEFAULT_GOAL := help

.PHONY: help setup pipeline dashboard test fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the environment and install dependencies (uv)
	uv venv --python 3.12
	uv pip install -e ".[dev]"

pipeline: ## Run the full data pipeline (fetch -> aggregate -> tidy outputs)
	$(RUN) python -m rtos.pipeline

dashboard: ## Launch the Streamlit dashboard
	$(RUN) streamlit run app/dashboard.py

test: ## Run the unit tests
	$(RUN) python -m pytest -q

clean: ## Remove cached raw data and processed outputs
	rm -rf data/raw data/processed
