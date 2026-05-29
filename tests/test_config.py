"""Tests for config parsing and building."""

from __future__ import annotations

from typing import Any

import pytest

from config import (
    ConfigError,
    build_fingerprint_args,
    build_proxy,
    get_concurrency,
    require_section,
    require_value,
)


class TestRequireSection:
    def test_returns_section(self, sample_config: dict[str, Any]) -> None:
        sec = require_section(sample_config, "fingerprint")
        assert sec["seed"] == 42069

    def test_missing_section_raises(self, sample_config: dict[str, Any]) -> None:
        with pytest.raises(ConfigError, match="Missing \\[nonexistent\\]"):
            require_section(sample_config, "nonexistent")

    def test_non_dict_raises(self) -> None:
        with pytest.raises(ConfigError, match="Missing \\[bad\\]"):
            require_section({"bad": "string"}, "bad")


class TestRequireValue:
    def test_returns_value(self) -> None:
        assert require_value({"key": "val"}, "key") == "val"

    def test_none_raises(self) -> None:
        with pytest.raises(ConfigError):
            require_value({"key": None}, "key")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ConfigError):
            require_value({"key": ""}, "key")


class TestBuildProxy:
    def test_full_credentials(self, sample_config: dict[str, Any]) -> None:
        url = build_proxy(sample_config)
        assert url == "http://user:pass@127.0.0.1:6152"

    def test_no_credentials(self, sample_config: dict[str, Any]) -> None:
        cfg = {
            **sample_config,
            "proxy": {"server": "http://proxy:8080", "username": "", "password": "", "enabled": "true"},
        }
        url = build_proxy(cfg)
        assert url == "http://proxy:8080"

    def test_missing_scheme_raises(self, sample_config: dict[str, Any]) -> None:
        cfg = {**sample_config, "proxy": {"server": "host:8080", "username": "u", "password": "p", "enabled": "true"}}
        with pytest.raises(ConfigError, match="scheme"):
            build_proxy(cfg)


class TestBuildFingerprintArgs:
    def test_basic_args(self, sample_config: dict[str, Any]) -> None:
        args = build_fingerprint_args(sample_config)
        assert any(a.startswith("--fingerprint=42069") for a in args)

    def test_seed_override(self, sample_config: dict[str, Any]) -> None:
        args = build_fingerprint_args(sample_config, seed_override=99999)
        assert "--fingerprint=99999" in args
        assert "--fingerprint=42069" not in args

    def test_noise_disabled(self, sample_config: dict[str, Any]) -> None:
        args = build_fingerprint_args(sample_config)
        assert "--fingerprint-noise=false" in args

    def test_noise_enabled(self, sample_config: dict[str, Any]) -> None:
        cfg = {**sample_config}
        cfg["fingerprint"] = {**cfg["fingerprint"], "noise": "true"}
        args = build_fingerprint_args(cfg)
        assert "--fingerprint-noise=false" not in args

    def test_includes_webrtc_ip(self, sample_config: dict[str, Any]) -> None:
        args = build_fingerprint_args(sample_config)
        assert "--fingerprint-webrtc-ip=auto" in args


class TestGetConcurrency:
    def test_default_one(self) -> None:
        assert get_concurrency({}) == 1

    def test_returns_configured(self) -> None:
        assert get_concurrency({"concurrency": {"workers": 5}}) == 5

    def test_negative_clamped(self) -> None:
        assert get_concurrency({"concurrency": {"workers": -1}}) == 1

    def test_non_dict_section(self) -> None:
        assert get_concurrency({"concurrency": "bad"}) == 1
