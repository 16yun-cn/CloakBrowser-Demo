"""Tests for CAPTCHA recognition (mock LLM, no network)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from captcha.recognizer import (
    DEFAULT_MODEL,
    DEFAULT_SERVER,
    CaptchaRecognition,
    recognize_captcha,
)

# A realistic LLM response for a 3×3 drag-grid CAPTCHA
_VALID_LLM_RESPONSE = json.dumps(
    {
        "is_captcha": True,
        "captcha_type": "drag_grid",
        "category_text": "请选出属于动物的图片",
        "category_keyword": "动物",
        "grid_rows": 3,
        "grid_cols": 3,
        "correct_cells": [[0, 0], [0, 1], [0, 2], [1, 2], [2, 0], [2, 1]],
        "incorrect_cells": [[1, 0], [1, 1], [2, 2]],
        "has_submit_button": True,
        "has_refresh_button": True,
        "extra_notes": "",
    }
)

_NOT_CAPTCHA_RESPONSE = json.dumps(
    {
        "is_captcha": False,
        "captcha_type": "none",
        "category_text": "",
        "category_keyword": "",
        "grid_rows": 0,
        "grid_cols": 0,
        "correct_cells": [],
        "incorrect_cells": [],
        "has_submit_button": False,
        "has_refresh_button": False,
        "extra_notes": "This is a normal page, no CAPTCHA detected.",
    }
)


@pytest.fixture
def fake_image() -> Path:
    """Create a minimal 1×1 PNG file for testing."""
    # Minimal valid PNG: 1×1 white pixel
    png_data = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png_data)
        return Path(f.name)


def _mock_urlopen(llm_content: str):
    """Create a mock for urllib.request.urlopen that returns an OpenAI-style response.

    ``llm_content`` is the text the LLM would return (e.g. the CAPTCHA JSON string).
    """

    def _factory(*args, **kwargs):
        # Build a full OpenAI /v1/chat/completions response wrapper
        wrapper = {
            "choices": [{"message": {"content": llm_content}}],
        }
        mock = MagicMock()
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = json.dumps(wrapper).encode("utf-8")
        mock.status = 200
        mock.headers = {}
        return mock

    return _factory


class TestCaptchaRecognition:
    """Tests for CaptchaRecognition class."""

    def test_from_valid_dict(self) -> None:
        cr = CaptchaRecognition(json.loads(_VALID_LLM_RESPONSE))
        assert cr.is_captcha is True
        assert cr.captcha_type == "drag_grid"
        assert cr.category_keyword == "动物"
        assert cr.correct_count == 6
        assert len(cr.incorrect_cells) == 3

    def test_from_empty_dict(self) -> None:
        cr = CaptchaRecognition({})
        assert cr.is_captcha is False
        assert cr.correct_cells == []
        assert cr.incorrect_cells == []
        assert cr.correct_count == 0

    def test_repr(self) -> None:
        cr = CaptchaRecognition(json.loads(_VALID_LLM_RESPONSE))
        r = repr(cr)
        assert "CaptchaRecognition" in r
        assert "动物" in r


class TestRecognizeCaptcha:
    """Tests for recognize_captcha with mocked LLM."""

    @patch("urllib.request.urlopen")
    def test_recognizes_captcha(self, mock_urlopen, fake_image) -> None:
        mock_urlopen.side_effect = _mock_urlopen(_VALID_LLM_RESPONSE)

        result = recognize_captcha(str(fake_image), server=DEFAULT_SERVER, model=DEFAULT_MODEL)

        assert result.is_captcha is True
        assert result.captcha_type == "drag_grid"
        assert result.category_keyword == "动物"
        assert result.grid_rows == 3
        assert result.grid_cols == 3
        assert result.correct_count == 6
        assert len(result.incorrect_cells) == 3

    @patch("urllib.request.urlopen")
    def test_no_captcha(self, mock_urlopen, fake_image) -> None:
        mock_urlopen.side_effect = _mock_urlopen(_NOT_CAPTCHA_RESPONSE)

        result = recognize_captcha(str(fake_image), server=DEFAULT_SERVER, model=DEFAULT_MODEL)

        assert result.is_captcha is False
        assert result.correct_cells == []

    @patch("urllib.request.urlopen")
    def test_response_with_markdown_code_block(self, mock_urlopen, fake_image) -> None:
        """LLM sometimes wraps JSON in ```json ... ``` blocks — must strip."""
        wrapped = f"```json\n{_VALID_LLM_RESPONSE}\n```"
        mock_urlopen.side_effect = _mock_urlopen(wrapped)

        result = recognize_captcha(str(fake_image), server=DEFAULT_SERVER, model=DEFAULT_MODEL)

        assert result.is_captcha is True
        assert result.correct_count == 6
