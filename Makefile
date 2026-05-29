CONFIG ?= config.toml

.PHONY: help check run run-concurrent test lint format latest report sessions clean-runtime

help:
	@printf '%s\n' \
		'make check          # Lint + test' \
		'make lint           # Ruff lint only' \
		'make format         # Ruff format' \
		'make test           # Run pytest' \
		'make run            # Run single worker' \
		'make run-concurrent # Run with concurrency' \
		'make latest         # Print newest session dir' \
		'make report         # Print newest aggregate report' \
		'make sessions       # List all session directories' \
		'make clean-runtime  # Remove generated runtime artifacts'

check: lint test

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/ scripts/

test:
	uv run pytest

run:
	uv run python -u src/runner.py --config $(CONFIG)

run-concurrent:
	uv run python -u src/orchestrator.py --config $(CONFIG)

latest:
	@find .runtime/sessions -mindepth 1 -maxdepth 2 -name 'doubao-run.json' -type f \
		| sed 's|/doubao-run.json||' | sort | tail -n 1

report:
	@latest_dir=$$(find .runtime/sessions -mindepth 1 -maxdepth 2 -name 'doubao-run.json' -type f \
		| sed 's|/doubao-run.json||' | sort | tail -n 1); \
		if [ -z "$$latest_dir" ]; then \
			echo "No session directory found."; \
			exit 1; \
		fi; \
		echo "$$latest_dir/doubao-run.json"; \
		cat "$$latest_dir/doubao-run.json"

sessions:
	@find .runtime/sessions -mindepth 1 -maxdepth 2 -name 'doubao-run.json' -type f \
		| sed 's|/doubao-run.json||' | sort

clean-runtime:
	rm -rf .runtime/sessions __pycache__
