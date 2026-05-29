"""Multi-worker concurrent doubao.com dialog runner.

Spawns N independent processes (via multiprocessing.Pool), each running
run_dialog() with a distinct fingerprint seed but sharing the same proxy.

Uses rich for colored per-worker console output.

Usage:
    uv run python run_concurrent.py --config config.toml
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from config import (
    ConfigError,
    build_session_id,
    get_concurrency,
    is_seed_random,
    load_config,
    require_section,
    write_json,
)

# ---------------------------------------------------------------------------
# Worker color palette — each worker gets a distinct colour
# ---------------------------------------------------------------------------

_WORKER_COLORS = [
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
    "bright_red",
    "bright_blue",
    "cyan",
    "green",
    "yellow",
    "magenta",
    "red",
    "blue",
]


def _worker_color(index: int) -> str:
    return _WORKER_COLORS[index % len(_WORKER_COLORS)]


# Console for the main (orchestrator) process
_console = Console()


def _log_main(message: str) -> None:
    _console.print(f"[bold white][orchestrator][/bold white] {message}")


# ---------------------------------------------------------------------------
# Per-worker entry point (runs in child process via multiprocessing.Pool)
# ---------------------------------------------------------------------------


def _run_one_worker(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a single worker (called from a Pool worker process).

    Args:
        payload: Dict with keys:
            config_path: str — path to the config TOML file
            worker_index: int — 0-based worker number
            base_seed: int — base fingerprint seed from config
            session_id: str — shared parent session ID

    Returns:
        Result dict for this worker.
    """
    # Re-import inside the worker process for clean state
    from config import (
        build_fingerprint_args,
        build_session_paths,
        load_config,
        prepare_profile,
        write_report,
    )
    from runner import run_dialog

    worker_index: int = payload["worker_index"]
    config_path: str = payload["config_path"]
    base_seed: int = payload["base_seed"]
    seed_random: bool = payload.get("seed_random", False)
    session_id: str = payload["session_id"]
    workers: int = payload["workers"]
    color = _worker_color(worker_index)

    # Each worker gets its own rich Console for colored output
    console = Console(highlight=False)

    def log(message: str) -> None:
        console.print(f"[{color}][worker-{worker_index}][/{color}] {message}")

    # Redirect log_step used by run_dialog
    import config as _cl

    _cl.log_step = log

    started_at = datetime.now()

    try:
        config = load_config(Path(config_path))
        if seed_random:
            import random

            seed = random.randint(100_000, 999_999)
        else:
            seed = base_seed + worker_index
        log(f"seed={seed}")

        fp_args = build_fingerprint_args(config, seed_override=seed)
        paths = build_session_paths(config, worker_index=worker_index, workers=workers, session_id_override=session_id)
        prepare_profile(config, paths)

        used_http2_fallback = False
        try:
            result = run_dialog(config, paths, use_http2_fallback=False, fingerprint_args=fp_args)
        except Exception:
            used_http2_fallback = True
            result = run_dialog(config, paths, use_http2_fallback=True, fingerprint_args=fp_args)

        finished_at = datetime.now()
        payload = {
            "status": "ok",
            "worker_index": worker_index,
            "session_id": paths.session_id,
            "session_dir": str(paths.session_dir),
            "seed": seed,
            "artifacts": {
                "before_send_screenshot": str(paths.before_screenshot),
                "after_reply_screenshot": str(paths.after_screenshot),
                "run_report": str(paths.run_report),
            },
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
            "used_http2_fallback": used_http2_fallback,
            **result,
        }
        write_report(paths, payload)
        log(f"OK — {result.get('response_excerpt', '')[:60]}")
        return payload

    except Exception as exc:
        finished_at = datetime.now()
        # Build minimal session dir info even on early failure
        try:
            config = load_config(Path(config_path))
            paths = build_session_paths(
                config, worker_index=worker_index, workers=workers, session_id_override=session_id
            )
            session_dir = str(paths.session_dir)
        except Exception:
            session_dir = "?"

        failure = {
            "status": "error",
            "worker_index": worker_index,
            "session_id": session_id,
            "session_dir": session_dir,
            "seed": base_seed + worker_index,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
            "error": str(exc),
        }
        log(f"FAILED — {exc}")
        return failure


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    started_at = datetime.now()

    try:
        config = load_config(config_path)
    except ConfigError as e:
        _console.print(f"[bold red]Config error:[/bold red] {e}")
        return 1

    workers = get_concurrency(config)
    if workers < 1:
        workers = 1

    # Build shared parent session ID (no directories created yet — workers do that)
    session_id = build_session_id(config)
    base_dir = Path(str(require_section(config, "session").get("base_dir", "./.runtime/sessions")))
    parent_dir = base_dir / session_id

    seed_random = is_seed_random(config)
    if seed_random:
        _log_main(f"Starting {workers} worker(s), seed = random")
    else:
        base_seed = int(require_section(config, "fingerprint").get("seed", 42069))
        _log_main(f"Starting {workers} worker(s), base seed = {base_seed}")

    _log_main(f"Session: {session_id}")

    # --- Single worker path (no multiprocessing overhead) ---
    if workers == 1:
        payload = _run_one_worker(
            {
                "config_path": str(config_path),
                "worker_index": 0,
                "base_seed": base_seed if not seed_random else 0,
                "seed_random": seed_random,
                "session_id": session_id,
                "workers": 1,
            }
        )
        return 0 if payload.get("status") == "ok" else 1

    # --- Multi-worker path ---
    worker_payloads = [
        {
            "config_path": str(config_path),
            "worker_index": i,
            "base_seed": base_seed if not seed_random else 0,
            "seed_random": seed_random,
            "session_id": session_id,
            "workers": workers,
        }
        for i in range(workers)
    ]

    with multiprocessing.Pool(processes=workers) as pool:
        results = pool.map(_run_one_worker, worker_payloads)

    # --- Aggregate ---
    finished_at = datetime.now()
    total_duration = round((finished_at - started_at).total_seconds(), 3)
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    failed_count = workers - ok_count

    if failed_count == 0:
        agg_status = "ok"
    elif ok_count == 0:
        agg_status = "error"
    else:
        agg_status = "partial"

    aggregate = {
        "status": agg_status,
        "session_id": session_id,
        "workers_total": workers,
        "workers_ok": ok_count,
        "workers_failed": failed_count,
        "duration_seconds": total_duration,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "workers": results,
    }

    # Write aggregate report to parent session dir
    agg_path = parent_dir / "doubao-run.json"
    write_json(agg_path, aggregate)

    # --- Rich summary table ---
    _console.print()
    table = Table(title=f"Run Summary — {session_id}", title_style="bold white")
    table.add_column("Worker", style="dim", width=8)
    table.add_column("Status", width=8)
    table.add_column("Seed", width=8)
    table.add_column("Duration", width=10)
    table.add_column("Response / Error", width=60)

    for r in results:
        wi = r.get("worker_index", "?")
        status = r.get("status", "?")
        seed = r.get("seed", "?")
        dur = f"{r.get('duration_seconds', 0):.1f}s"
        if status == "ok":
            detail = r.get("response_excerpt", "")[:55]
            status_style = "[bold green]ok[/bold green]"
        else:
            detail = r.get("error", "")[:55]
            status_style = "[bold red]FAIL[/bold red]"

        table.add_row(
            f"[{_worker_color(wi)}]worker-{wi}[/{_worker_color(wi)}]",
            status_style,
            str(seed),
            dur,
            detail,
        )

    _console.print(table)
    _console.print(
        f"\n[bold]Aggregate:[/bold] {agg_status}  "
        f"[green]{ok_count} ok[/green]  "
        f"[red]{failed_count} failed[/red]  "
        f"total {total_duration}s"
    )
    _console.print(f"[dim]Report: {agg_path}[/dim]")

    # Also print JSON to stdout for scripting
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))

    return 0 if agg_status != "error" else 1


if __name__ == "__main__":
    # Required for multiprocessing on macOS / spawn context
    multiprocessing.set_start_method("spawn", force=True)
    raise SystemExit(main())
