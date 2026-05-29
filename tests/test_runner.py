"""Tests for runner logic (non-browser, pure functions)."""

from __future__ import annotations

from config import (
    SessionPaths,
    build_selector_config,
    build_session_paths,
    get_locator_config,
    get_runtime_config,
)
from runner import is_noise_text


class TestIsNoiseText:
    def test_detects_noise_token(self) -> None:
        assert is_noise_text("下载电脑版请点击", ["下载电脑版", "登录"])

    def test_no_noise(self) -> None:
        assert not is_noise_text("这是豆包的回复内容", ["下载电脑版", "登录"])

    def test_partial_match(self) -> None:
        assert is_noise_text("登录后查看更多", ["登录"])


class TestGetRuntimeConfig:
    def test_all_keys_present(self, sample_config: dict) -> None:
        rc = get_runtime_config(sample_config)
        assert rc["min_reply_wait_seconds"] == 30
        assert rc["page_load_timeout_ms"] == 15000
        assert rc["element_visible_timeout_ms"] == 1000
        assert rc["response_min_text_length"] == 4
        assert rc["max_response_excerpt_length"] == 1000


class TestGetLocatorConfig:
    def test_returns_lists(self, sample_config: dict) -> None:
        lc = get_locator_config(sample_config)
        assert isinstance(lc["input_selectors"], list)
        assert isinstance(lc["submit_button_selectors"], list)
        assert isinstance(lc["response_candidate_selectors"], list)
        assert isinstance(lc["noise_tokens"], list)


class TestBuildSelectorConfig:
    def test_empty_selectors(self, sample_config: dict) -> None:
        sel = build_selector_config(sample_config)
        assert sel.input_selector == ""
        assert sel.submit_selector == ""
        assert sel.response_selector == ""

    def test_custom_selectors(self, sample_config: dict) -> None:
        cfg = {**sample_config}
        cfg["dialog"] = {
            "prompt": "hello",
            "input_selector": "#my-input",
            "submit_selector": "#my-btn",
            "response_selector": ".response",
        }
        sel = build_selector_config(cfg)
        assert sel.input_selector == "#my-input"
        assert sel.submit_selector == "#my-btn"
        assert sel.response_selector == ".response"


class TestBuildSessionPaths:
    def test_single_worker_flat(self, sample_config: dict, tmp_dir) -> None:
        cfg = {**sample_config}
        cfg["session"]["base_dir"] = str(tmp_dir)
        paths = build_session_paths(cfg, worker_index=0, workers=1)
        assert isinstance(paths, SessionPaths)
        assert paths.session_dir.exists()
        assert paths.profile_dir.name == "profile"
        # Flat layout: session_dir is directly under base_dir
        assert paths.session_dir.parent == tmp_dir

    def test_multi_worker_nested(self, sample_config: dict, tmp_dir) -> None:
        cfg = {**sample_config}
        cfg["session"]["base_dir"] = str(tmp_dir)
        paths = build_session_paths(cfg, worker_index=3, workers=5)
        assert paths.session_dir.name == "worker-3"
        # Nested: sessions/<session_id>/worker-3/
        assert paths.session_dir.parent.name != "worker-3"

    def test_session_id_override(self, sample_config: dict, tmp_dir) -> None:
        cfg = {**sample_config}
        cfg["session"]["base_dir"] = str(tmp_dir)
        paths = build_session_paths(cfg, session_id_override="my-session")
        assert paths.session_id == "my-session"
        assert paths.session_dir.name == "my-session"
