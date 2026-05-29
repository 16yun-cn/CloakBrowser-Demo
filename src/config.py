"""Configuration loading and validation shared across run_doubao and run_concurrent."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SelectorConfig:
    input_selector: str
    submit_selector: str
    response_selector: str


@dataclass
class SessionPaths:
    session_dir: Path
    profile_dir: Path
    before_screenshot: Path
    after_screenshot: Path
    run_report: Path
    session_id: str


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Logging (simple — rich overrides this in concurrent mode)
# ---------------------------------------------------------------------------


def log_step(message: str) -> None:
    print(f"[run_doubao] {message}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--worker-index", type=int, default=None)
    parser.add_argument("--seed-override", type=int, default=None)
    parser.add_argument("--session-dir", type=Path, default=None)
    return parser.parse_args()


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


# ---------------------------------------------------------------------------
# Section / value accessors
# ---------------------------------------------------------------------------


def require_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"Missing [{name}] section")
    return section


def require_value(section: dict[str, Any], key: str) -> Any:
    value = section.get(key)
    if value in (None, ""):
        raise ConfigError(f"Missing required config value: {key}")
    return value


def require_int(section: dict[str, Any], key: str) -> int:
    value = require_value(section, key)
    if not isinstance(value, int):
        raise ConfigError(f"Config value must be an integer: {key}")
    return value


def require_float(section: dict[str, Any], key: str) -> float:
    value = require_value(section, key)
    if not isinstance(value, (int, float)):
        raise ConfigError(f"Config value must be a number: {key}")
    return float(value)


def require_list(section: dict[str, Any], key: str) -> list[Any]:
    value = require_value(section, key)
    if not isinstance(value, list):
        raise ConfigError(f"Config value must be a list: {key}")
    return value


# ---------------------------------------------------------------------------
# Config sub-section builders
# ---------------------------------------------------------------------------


def get_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    runtime = require_section(config, "runtime")
    return {
        "min_reply_wait_seconds": require_float(runtime, "min_reply_wait_seconds"),
        "page_load_timeout_ms": require_int(runtime, "page_load_timeout_ms"),
        "element_visible_timeout_ms": require_int(runtime, "element_visible_timeout_ms"),
        "submit_visible_timeout_ms": require_int(runtime, "submit_visible_timeout_ms"),
        "submit_retry_visible_timeout_ms": require_int(runtime, "submit_retry_visible_timeout_ms"),
        "submit_state_timeout_ms": require_int(runtime, "submit_state_timeout_ms"),
        "submit_state_poll_interval_ms": require_int(runtime, "submit_state_poll_interval_ms"),
        "response_poll_interval_ms": require_int(runtime, "response_poll_interval_ms"),
        "max_selector_matches": require_int(runtime, "max_selector_matches"),
        "max_button_matches": require_int(runtime, "max_button_matches"),
        "send_button_min_x_ratio": require_float(runtime, "send_button_min_x_ratio"),
        "send_button_y_tolerance_px": require_int(runtime, "send_button_y_tolerance_px"),
        "response_min_x": require_int(runtime, "response_min_x"),
        "response_min_y": require_int(runtime, "response_min_y"),
        "response_max_y": require_int(runtime, "response_max_y"),
        "response_min_text_length": require_int(runtime, "response_min_text_length"),
        "max_response_excerpt_length": require_int(runtime, "max_response_excerpt_length"),
    }


def get_locator_config(config: dict[str, Any]) -> dict[str, list[str]]:
    locators = require_section(config, "locators")
    return {
        "input_selectors": [str(item) for item in require_list(locators, "input_selectors")],
        "submit_button_selectors": [str(item) for item in require_list(locators, "submit_button_selectors")],
        "response_candidate_selectors": [str(item) for item in require_list(locators, "response_candidate_selectors")],
        "noise_tokens": [str(item) for item in require_list(locators, "noise_tokens")],
    }


def get_concurrency(config: dict[str, Any]) -> int:
    """Return concurrency worker count (default 1)."""
    concurrency = config.get("concurrency")
    if not isinstance(concurrency, dict):
        return 1
    workers = concurrency.get("workers", 1)
    if not isinstance(workers, int) or workers < 1:
        return 1
    return workers


# ---------------------------------------------------------------------------
# Session paths
# ---------------------------------------------------------------------------


def validate_filename(name: str, key: str) -> str:
    if not name:
        raise ConfigError(f"Missing required config value: {key}")
    pure = Path(name)
    if pure.name != name or "/" in name or "\\" in name:
        raise ConfigError(f"{key} must be a file name, not a path: {name}")
    return name


def build_session_id(config: dict[str, Any]) -> str:
    """Compute a session ID from config without creating any directories."""
    session = require_section(config, "session")
    session_name = str(session.get("session_name", "")).strip()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{session_name}-{timestamp}" if session_name else timestamp


def build_session_paths(
    config: dict[str, Any],
    *,
    worker_index: int = 0,
    workers: int = 1,
    session_id_override: str | None = None,
) -> SessionPaths:
    """Build SessionPaths, optionally nesting under worker-N/ for concurrency.

    When workers > 1, each worker gets its own sub-directory:
        sessions/<session_id>/worker-<N>/profile/
    When workers == 1 (or worker_index == 0), the flat layout is used.
    """
    session = require_section(config, "session")
    artifacts = require_section(config, "artifacts")

    base_dir = Path(str(require_value(session, "base_dir")))

    if session_id_override:
        session_id = session_id_override
    else:
        session_name = str(session.get("session_name", "")).strip()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_id = f"{session_name}-{timestamp}" if session_name else timestamp

    if workers > 1:
        session_dir = base_dir / session_id / f"worker-{worker_index}"
    else:
        session_dir = base_dir / session_id

    profile_dir = session_dir / "profile"
    session_dir.mkdir(parents=True, exist_ok=False)

    before_name = validate_filename(str(require_value(artifacts, "before_send_filename")), "before_send_filename")
    after_name = validate_filename(str(require_value(artifacts, "after_reply_filename")), "after_reply_filename")
    report_name = validate_filename(str(require_value(artifacts, "run_report_filename")), "run_report_filename")

    return SessionPaths(
        session_dir=session_dir,
        profile_dir=profile_dir,
        before_screenshot=session_dir / before_name,
        after_screenshot=session_dir / after_name,
        run_report=session_dir / report_name,
        session_id=session_id,
    )


def prepare_profile(config: dict[str, Any], paths: SessionPaths) -> None:
    session = require_section(config, "session")
    template_dir = str(session.get("profile_template_dir", "")).strip()
    if template_dir:
        source = Path(template_dir)
        if not source.exists():
            raise ConfigError(f"profile_template_dir does not exist: {source}")
        shutil.copytree(source, paths.profile_dir)
    else:
        paths.profile_dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------


def build_proxy(config: dict[str, Any]) -> str:
    proxy = require_section(config, "proxy")
    server = str(require_value(proxy, "server"))
    username = str(proxy.get("username", "")).strip()
    password = str(proxy.get("password", "")).strip()
    if not username or not password:
        return server

    if "://" not in server:
        raise ConfigError(f"proxy.server must include scheme: {server}")
    scheme, rest = server.split("://", 1)
    return f"{scheme}://{username}:{password}@{rest}"


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


def build_selector_config(config: dict[str, Any]) -> SelectorConfig:
    dialog = require_section(config, "dialog")
    return SelectorConfig(
        input_selector=str(dialog.get("input_selector", "")).strip(),
        submit_selector=str(dialog.get("submit_selector", "")).strip(),
        response_selector=str(dialog.get("response_selector", "")).strip(),
    )


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def build_fingerprint_args(
    config: dict[str, Any],
    *,
    seed_override: int | None = None,
) -> list[str]:
    """Build Chromium --fingerprint-* CLI args from config.

    Args:
        config: Full config dict.
        seed_override: If provided, use this seed instead of config's seed.
            Used by concurrent workers to give each a distinct fingerprint.
    """
    fingerprint = require_section(config, "fingerprint")
    required = [
        "seed",
        "platform",
        "brand",
        "brand_version",
        "platform_version",
        "gpu_vendor",
        "gpu_renderer",
        "hardware_concurrency",
        "device_memory",
        "screen_width",
        "screen_height",
        "timezone",
        "locale",
        "storage_quota_mb",
        "webrtc_ip_mode",
    ]
    values = {key: require_value(fingerprint, key) for key in required}

    if seed_override is not None:
        values["seed"] = seed_override

    webrtc_ip_mode = str(values["webrtc_ip_mode"])
    if webrtc_ip_mode != "auto" and "." not in webrtc_ip_mode and ":" not in webrtc_ip_mode:
        raise ConfigError("fingerprint.webrtc_ip_mode must be 'auto' or an explicit IP")

    args = [
        f"--fingerprint={values['seed']}",
        f"--fingerprint-platform={values['platform']}",
        f"--fingerprint-brand={values['brand']}",
        f"--fingerprint-brand-version={values['brand_version']}",
        f"--fingerprint-platform-version={values['platform_version']}",
        f"--fingerprint-gpu-vendor={values['gpu_vendor']}",
        f"--fingerprint-gpu-renderer={values['gpu_renderer']}",
        f"--fingerprint-hardware-concurrency={values['hardware_concurrency']}",
        f"--fingerprint-device-memory={values['device_memory']}",
        f"--fingerprint-screen-width={values['screen_width']}",
        f"--fingerprint-screen-height={values['screen_height']}",
        f"--fingerprint-timezone={values['timezone']}",
        f"--fingerprint-locale={values['locale']}",
        f"--fingerprint-storage-quota={values['storage_quota_mb']}",
        f"--fingerprint-webrtc-ip={webrtc_ip_mode}",
    ]

    # Disable noise injection — CAPTCHA systems detect canvas/WebGL/audio noise as tampering
    fingerprint_noise = fingerprint.get("noise", "false")
    if str(fingerprint_noise).lower() in ("false", "0", "no", "off"):
        args.append("--fingerprint-noise=false")

    return args


# ---------------------------------------------------------------------------
# Launch kwargs
# ---------------------------------------------------------------------------


def build_launch_kwargs(config: dict[str, Any], extra_args: list[str]) -> dict[str, Any]:
    session = require_section(config, "session")
    fingerprint = config.get("fingerprint", {})
    proxy_cfg = config.get("proxy", {})
    proxy_enabled = str(proxy_cfg.get("enabled", "true")).lower() in ("true", "1", "yes", "on")

    kwargs = {
        "headless": bool(session.get("headless", False)),
        "humanize": bool(session.get("humanize", True)),
        "stealth_args": False,
        "args": list(extra_args),
    }
    if proxy_enabled:
        kwargs["proxy"] = build_proxy(config)
    else:
        # Explicitly disable proxy — Chromium picks up system proxy env
        # vars (http_proxy, all_proxy, etc.) even when config says disabled.
        # --no-proxy-server overrides all proxy env/args.
        kwargs["args"].append("--no-proxy-server")
    # Match viewport to fingerprint screen dimensions — mismatch is a detection signal
    sw = fingerprint.get("screen_width")
    sh = fingerprint.get("screen_height")
    if sw and sh:
        kwargs["viewport"] = {"width": int(sw), "height": int(sh)}
    return kwargs


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_report(paths: SessionPaths, payload: dict[str, Any]) -> None:
    paths.run_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a dict as JSON to an arbitrary path."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
