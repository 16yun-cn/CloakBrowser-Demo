# Concurrency Support Plan

## Context

Currently `run_doubao.py` runs a single browser instance per invocation — it mixes config parsing, session setup, and dialog execution all in one file. The user wants to run **N concurrent browser instances**, each with a **different fingerprint** but all sharing the **same proxy**. Default concurrency: 5 workers.

This requires a refactoring: separate config loading from dialog execution, keep single-worker logic clean in `run_doubao.py`, and add a new orchestrator that spawns N processes.

## Approach

**Architecture refactoring** — split into three modules:

| Module | Role |
|--------|------|
| `config_loader.py` (new) | All config parsing, validation, path building. Shared by both runners. |
| `run_doubao.py` (refactored) | Pure single-worker dialog execution. Takes a parsed config dict + worker overrides. Can still run standalone. |
| `run_concurrent.py` (new) | Orchestrator: reads config, spawns N processes via `multiprocessing.Pool`, aggregates results. |

**Concurrency model**: `multiprocessing.Pool` — each worker is a completely independent Python process. No shared state at all (each process runs its own `run_dialog()` with its own Playwright/Chromium). Pool size = configured `workers`.

**Fingerprint variation**: Each worker gets `seed + worker_index`. All other fingerprint params remain from config.

**Logging**: Use `rich` library for colored, per-worker console output. Each worker gets a distinct color from a palette, making it trivial to see which worker is printing what.

## Files

| File | Change |
|------|--------|
| `config_loader.py` | **NEW** — extract all config parsing from `run_doubao.py` |
| `run_doubao.py` | **REFACTOR** — keep only dialog execution; import config from `config_loader.py` |
| `run_concurrent.py` | **NEW** — multi-process orchestrator with `rich` logging |
| `config.template.toml` | Add `[concurrency]` section |
| `pyproject.toml` | Add `rich` dependency |

## Reuse

| Existing Code | Current Location | Moves To |
|---------------|------------------|----------|
| `load_config()`, `require_section()`, `require_value()`, etc. | `run_doubao.py` | `config_loader.py` |
| `get_runtime_config()`, `get_locator_config()` | `run_doubao.py` | `config_loader.py` |
| `build_session_paths()`, `prepare_profile()` | `run_doubao.py` | `config_loader.py` |
| `build_proxy()`, `build_selector_config()` | `run_doubao.py` | `config_loader.py` |
| `build_fingerprint_args()`, `build_launch_kwargs()` | `run_doubao.py` | `config_loader.py` |
| `validate_filename()`, `write_report()` | `run_doubao.py` | `config_loader.py` |
| `log_step()` | `run_doubao.py` | `config_loader.py` (generic), overridden in concurrent |
| `run_dialog()` + all helpers (`fill_prompt`, `submit_prompt`, `extract_response`, `find_first_visible`, `_install_captcha_cdn_bypass`, etc.) | `run_doubao.py` | Stays in `run_doubao.py` |
| `launch_persistent_context` | `cloakbrowser/browser.py` | Called from `run_doubao.py` (unchanged) |
| `solve_captcha` | `captcha/__init__.py` | Called from `run_doubao.py` (unchanged) |

## New Config

```toml
[concurrency]
# Number of concurrent browser instances.
# Each worker uses seed + worker_index as its fingerprint seed.
# Set to 1 to run a single worker (same as running run_doubao.py directly).
workers = 5
```

## Steps

- [ ] **Step 1 — Add `rich` dependency**
  - `uv add rich`
  - This adds `rich` to `pyproject.toml` dependencies

- [ ] **Step 2 — Create `config_loader.py`**
  - Move all config parsing code from `run_doubao.py`:
    - `ConfigError`, `SelectorConfig`, `SessionPaths` dataclasses
    - `parse_args()`, `load_config()`, `require_section()`, `require_value()`, `require_int()`, `require_float()`, `require_list()`
    - `get_runtime_config()`, `get_locator_config()`
    - `validate_filename()`, `build_session_paths()`, `prepare_profile()`
    - `build_proxy()`, `build_selector_config()`
    - `build_fingerprint_args()`, `build_launch_kwargs()`
    - `write_report()`
  - Add `build_session_paths()` variant that accepts `worker_index` for sub-directory layout
  - Add `build_fingerprint_args()` variant that accepts `seed_override: int | None`
  - Add `log_step()` — a simple `print()` based logger (used by single-worker)
  - No behavioral changes — pure extraction

- [ ] **Step 3 — Refactor `run_doubao.py`**
  - Remove all config parsing code (now imported from `config_loader`)
  - Keep: `run_dialog()` and all its inline helpers (`fill_prompt`, `submit_prompt`, `extract_response`, `find_first_visible`, `click_nearest_send_button`, `get_input_text`, `set_contenteditable_text`, `prompt_submitted`, `is_noise_text`, `_install_captcha_cdn_bypass`, `_CAPTCHA_CDN_DOMAINS`)
  - Keep a `main()` that: parses CLI args, loads config, builds paths/fingerprint/proxy, calls `run_dialog()`, writes report
  - Accept these CLI args for worker overrides (used by `run_concurrent.py`):
    - `--worker-index N` — sets seed override and session sub-dir
    - `--seed-override N` — explicit seed override (optional, computed from worker-index if omitted)
    - `--session-dir /path` — explicit session dir (optional)
  - Standalone usage still works: `python run_doubao.py --config config.toml`

- [ ] **Step 4 — Add `[concurrency]` section to `config.template.toml`**
  - Add between `[session]` and `[dialog]`:
    ```toml
    [concurrency]
    # Number of concurrent browser instances.
    # Each worker uses seed + worker_index as its fingerprint seed.
    # Set to 1 to run a single worker (same as running run_doubao.py directly).
    workers = 5
    ```

- [ ] **Step 5 — Create `run_concurrent.py`**
  - Entry point for concurrent execution
  - Imports config from `config_loader.py`, dialog from `run_doubao.py`
  - `get_concurrency()` helper to read `[concurrency].workers` (default 1)
  - When `workers == 1`: run a single worker in-process (same as `run_doubao.py` directly)
  - When `workers > 1`:
    - Build base session dir
    - Define `run_one_worker(worker_index: int) -> dict` that:
      - Creates worker-specific session sub-dir `{base}/worker-{N}/`
      - Computes seed = `base_seed + worker_index`
      - Calls `run_dialog()` with overridden config
      - Catches exceptions, returns result dict
    - Use `multiprocessing.Pool(processes=workers)` with `pool.map(run_one_worker, range(workers))` or `apply_async` for streaming results
    - Collect results, write aggregate report
  - **Rich logging**:
    - Each worker gets a color from `rich.console.Console` with a style palette
    - Worker console prints: `[worker-N]` prefix in its assigned color
    - Main process shows a progress summary via `rich.progress.Progress`
    - Main process prints final aggregate summary with success/failure counts

- [ ] **Step 6 — Aggregate reporting**
  - After all workers finish, write `doubao-run.json` in the parent session dir:
    ```json
    {
      "status": "ok" | "partial" | "error",
      "session_id": "...",
      "workers_total": 5,
      "workers_ok": 4,
      "workers_failed": 1,
      "duration_seconds": 45.3,
      "workers": [
        {"worker_index": 0, "status": "ok", "session_dir": "...", "seed": 42069, "response_excerpt": "..."},
        {"worker_index": 1, "status": "error", "session_dir": "...", "seed": 42070, "error": "..."}
      ]
    }
    ```
  - Print aggregate JSON to stdout

- [ ] **Step 7 — Update `Makefile`**
  - Add `make run-concurrent` target: `uv run python -u run_concurrent.py --config $(CONFIG)`
  - `make run` still works (runs `run_doubao.py` directly for single worker)
  - Or: make `make run` point to `run_concurrent.py` by default (which handles workers=1 gracefully)

## Verification

1. **Single worker, standalone**: `uv run python run_doubao.py --config config.toml` — identical to current behavior
2. **Single worker via concurrent**: `workers = 1` in config, run `run_concurrent.py` — same result, no sub-process overhead
3. **5 workers via concurrent**: `workers = 5` — 5 browser instances launch concurrently, each with distinct seed, shared proxy. Session dir: `sessions/<ts>/worker-0/` through `worker-4/`. Colored console output per worker.
4. **Partial failure**: Kill proxy mid-run — some workers fail, aggregate JSON shows `"partial"` status with per-worker errors
5. **Ctrl+C**: Press Ctrl+C — pool terminates, all worker processes cleaned up via `pool.terminate()`
6. **Seed variation**: Verify each worker report shows a unique seed value
7. **No `[concurrency]` section**: `run_concurrent.py` gracefully defaults to 1 worker
