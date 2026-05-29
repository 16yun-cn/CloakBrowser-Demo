"""Shared test fixtures."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def sample_config() -> dict[str, Any]:
    """Minimal valid config dict for unit tests."""
    return {
        "target": {"url": "https://www.doubao.com"},
        "proxy": {
            "server": "http://127.0.0.1:6152",
            "username": "user",
            "password": "pass",
            "enabled": "true",
        },
        "session": {
            "base_dir": "./.runtime/sessions",
            "session_name": "",
            "profile_template_dir": "",
            "headless": False,
            "humanize": True,
            "navigation_timeout_ms": 90000,
            "response_timeout_ms": 120000,
        },
        "dialog": {
            "prompt": "你好",
            "input_selector": "",
            "submit_selector": "",
            "response_selector": "",
        },
        "runtime": {
            "min_reply_wait_seconds": 30,
            "page_load_timeout_ms": 15000,
            "element_visible_timeout_ms": 1000,
            "submit_visible_timeout_ms": 10000,
            "submit_retry_visible_timeout_ms": 1500,
            "submit_state_timeout_ms": 3000,
            "submit_state_poll_interval_ms": 200,
            "response_poll_interval_ms": 1000,
            "max_selector_matches": 20,
            "max_button_matches": 50,
            "send_button_min_x_ratio": 0.6,
            "send_button_y_tolerance_px": 40,
            "response_min_x": 280,
            "response_min_y": 60,
            "response_max_y": 760,
            "response_min_text_length": 4,
            "max_response_excerpt_length": 1000,
        },
        "locators": {
            "input_selectors": ["textarea"],
            "submit_button_selectors": ["button:has-text('发送')"],
            "response_candidate_selectors": ["main p"],
            "noise_tokens": ["下载电脑版"],
        },
        "captcha": {
            "enabled": True,
            "llm_server": "http://192.168.2.60:8001",
            "llm_model": "qwen3.5-35b-a3b",
            "max_retries": 3,
            "bypass_proxy": True,
        },
        "fingerprint": {
            "seed": 42069,
            "platform": "macos",
            "brand": "Chrome",
            "brand_version": "146",
            "platform_version": "15.0.0",
            "gpu_vendor": "Intel Inc.",
            "gpu_renderer": "Intel Iris OpenGL Engine",
            "hardware_concurrency": 8,
            "device_memory": 8,
            "screen_width": 1440,
            "screen_height": 900,
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
            "storage_quota_mb": 5000,
            "webrtc_ip_mode": "auto",
            "noise": "false",
        },
        "artifacts": {
            "before_send_filename": "doubao-before.png",
            "after_reply_filename": "doubao-after.png",
            "run_report_filename": "doubao-run.json",
        },
    }


@pytest.fixture
def tmp_dir() -> Path:
    """Temporary directory that auto-cleans."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
