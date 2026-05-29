CONFIG ?= config.toml

.PHONY: help check run latest report sessions clean-runtime

help:
	@printf '%s\n' \
		'make check         # Compile-check run_doubao.py with uv' \
		'make run           # Run the CloakBrowser demo with config.toml' \
		'make latest        # Print the newest session directory' \
		'make report        # Print the newest run report path and content' \
		'make sessions      # List all saved session directories' \
		'make clean-runtime # Remove generated runtime artifacts'

check:
	uv run python -m py_compile run_doubao.py

run:
	uv run python -u run_doubao.py --config $(CONFIG)

latest:
	@find .runtime/sessions -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1

report:
	@latest_dir=$$(find .runtime/sessions -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1); \
		if [ -z "$$latest_dir" ]; then \
			echo "No session directory found."; \
			exit 1; \
		fi; \
		echo "$$latest_dir/doubao-run.json"; \
		cat "$$latest_dir/doubao-run.json"

sessions:
	@find .runtime/sessions -mindepth 1 -maxdepth 1 -type d | sort

clean-runtime:
	rm -rf .runtime/sessions __pycache__
