"""
CAPTCHA recognition via remote LLM (llama.cpp server).

Sends a screenshot to the LLM and parses the structured response
to identify CAPTCHA type, category, and correct image positions.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("cloakbrowser.captcha.recognizer")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SERVER = "http://192.168.2.60:8001"
DEFAULT_MODEL = "qwen3.5-35b-a3b"
REQUEST_TIMEOUT = 120  # seconds

# ---------------------------------------------------------------------------
# Prompt — asks the LLM to return structured JSON for drag-grid CAPTCHAs
# ---------------------------------------------------------------------------

CAPTCHA_PROMPT = """You are analyzing a CAPTCHA challenge screenshot. This is typically a drag-and-drop image verification CAPTCHA used by Chinese websites.

Analyze this image carefully and return a JSON object with the following structure:

{
  "is_captcha": true,
  "captcha_type": "drag_grid",
  "category_text": "the category description shown at the top (e.g. '属于动物的')",
  "category_keyword": "the key category word (e.g. '动物', '交通信号灯', '汽车')",
  "grid_rows": 3,
  "grid_cols": 3,
  "correct_cells": [[row, col], ...],
  "incorrect_cells": [[row, col], ...],
  "has_submit_button": true,
  "has_refresh_button": true,
  "extra_notes": ""
}

Important:
- row and col are 0-indexed (0,0 is top-left)
- "correct_cells" lists cells that MATCH the category description
- "incorrect_cells" lists cells that do NOT match
- Check ALL cells — correct + incorrect should cover all 9 positions
- If this is NOT a CAPTCHA at all, set "is_captcha": false and explain in extra_notes
- Only return the JSON object, no other text

Return ONLY the JSON, no markdown code blocks, no explanation."""


def image_to_base64(image_path: str | Path) -> str:
    """Read image file and return base64 data URL with correct MIME type."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime};base64,{data}"


def _send_to_llm(
    image_path: str | Path,
    prompt: str = CAPTCHA_PROMPT,
    server: str = DEFAULT_SERVER,
    model: str = DEFAULT_MODEL,
) -> str:
    """Send image to llama.cpp server and return raw response text."""
    data_url = image_to_base64(image_path)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
        "stream": False,
    }

    req = urllib.request.Request(
        f"{server}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM server returned HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach LLM server at {server}: {e}") from e


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from LLM response text.

    Handles responses wrapped in markdown code blocks (including truncated),
    or with extra text before/after the JSON.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` block (complete or truncated)
    # Handle: ```json\n{...}\n``` or ```json\n{... (truncated, no closing)
    if text.startswith("```"):
        # Strip opening fence
        inner = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Strip closing fence if present
        inner = re.sub(r"\n?```\s*$", "", inner)
        try:
            return json.loads(inner.strip())
        except json.JSONDecodeError:
            pass

    # Try extracting from ```json ... ``` block elsewhere
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block (greedy for complete JSON)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from LLM response:\n{text[:500]}")


class CaptchaRecognition:
    """Structured result of CAPTCHA recognition."""

    def __init__(self, raw: dict[str, Any]):
        self.is_captcha: bool = raw.get("is_captcha", False)
        self.captcha_type: str = raw.get("captcha_type", "")
        self.category_text: str = raw.get("category_text", "")
        self.category_keyword: str = raw.get("category_keyword", "")
        self.grid_rows: int = raw.get("grid_rows", 3)
        self.grid_cols: int = raw.get("grid_cols", 3)
        self.correct_cells: list[list[int]] = raw.get("correct_cells", [])
        self.incorrect_cells: list[list[int]] = raw.get("incorrect_cells", [])
        self.has_submit_button: bool = raw.get("has_submit_button", True)
        self.has_refresh_button: bool = raw.get("has_refresh_button", True)
        self.extra_notes: str = raw.get("extra_notes", "")

    @property
    def correct_count(self) -> int:
        return len(self.correct_cells)

    def __repr__(self) -> str:
        return (
            f"CaptchaRecognition(is_captcha={self.is_captcha}, "
            f"type={self.captcha_type}, "
            f"category={self.category_keyword!r}, "
            f"correct={self.correct_cells})"
        )


def recognize_captcha(
    image_path: str | Path,
    server: str = DEFAULT_SERVER,
    model: str = DEFAULT_MODEL,
) -> CaptchaRecognition:
    """Recognize a CAPTCHA from an image using remote LLM.

    Args:
        image_path: Path to screenshot image file.
        server: llama.cpp server URL (default: http://192.168.2.60:8001).
        model: Model name on the server (default: qwen3.5-35b-a3b).

    Returns:
        CaptchaRecognition with parsed CAPTCHA data.

    Raises:
        RuntimeError: If the LLM server is unreachable or returns an error.
        ValueError: If the LLM response cannot be parsed as JSON.
    """
    logger.info(f"Recognizing CAPTCHA from {image_path} via {server}")
    raw_response = _send_to_llm(image_path, server=server, model=model)
    parsed = _extract_json(raw_response)
    recognition = CaptchaRecognition(parsed)
    logger.info(f"Recognition result: {recognition}")
    return recognition
