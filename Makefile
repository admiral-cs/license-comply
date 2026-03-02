# Makefile for license-comply
# Run `make help` to see available commands.
#
# IMPORTANT: Use a virtual environment! Before running these commands:
#   python3 -m venv .venv
#   source .venv/bin/activate
#
# A Makefile defines "targets" — short commands that run longer shell commands.
# The syntax is:
#   target-name:  ## Description (the ## comment shows up in `make help`)
#   	command-to-run (MUST be indented with a TAB, not spaces)

.PHONY: help install dev test lint format coverage demo clean

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install license-comply (production only)
	pip install .

dev:  ## Install in development mode with all optional dependencies
	pip install -e ".[dev,ai]"

test:  ## Run the test suite
	pytest tests/ -v

lint:  ## Check code style and formatting (no changes made)
	ruff check src/ tests/
	ruff format --check src/ tests/

format:  ## Auto-format code with ruff
	ruff format src/ tests/

coverage:  ## Generate an HTML coverage report (open htmlcov/index.html to browse)
	pytest tests/ -v --cov-report=html

demo:  ## Run the tool against the demo project
	license-comply ./demo --project-type proprietary --format terminal --format markdown

clean:  ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
