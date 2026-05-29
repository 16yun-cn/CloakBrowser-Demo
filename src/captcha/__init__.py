"""
CAPTCHA solver — detection, recognition, and execution.

Orchestrates:
  1. Detect CAPTCHA on page (DOM-based)
  2. Wait for CAPTCHA images to actually load
  3. If images fail, refresh and re-wait
  4. Screenshot only after images confirmed loaded
  5. Send to LLM for recognition
  6. Execute humanized drag operations

Usage:
    from captcha import solve_captcha

    page = browser.new_page()
    page.goto("https://example.com")

    solved = solve_captcha(page)
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from .drag_captcha import (
    _click_refresh,
    _has_image_load_error,
    detect_captcha,
    solve_drag_captcha,
    wait_for_captcha_images,
)
from .recognizer import (
    DEFAULT_MODEL,
    DEFAULT_SERVER,
    CaptchaRecognition,
    recognize_captcha,
)

logger = logging.getLogger("captcha")

# How long to wait for CAPTCHA images to load after each refresh
IMAGE_LOAD_TIMEOUT_MS = 15000
# How many refresh attempts before giving up on this CAPTCHA
MAX_REFRESH_PER_CAPTCHA = 4


def solve_captcha(
    page: Any,
    *,
    server: str = DEFAULT_SERVER,
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
    screenshot_path: str | Path | None = None,
) -> bool:
    """Detect and solve a CAPTCHA on the page.

    Full pipeline with image-load retry:
      1. Check if CAPTCHA is present (DOM detection)
      2. Wait for grid images to load; if fail → refresh → re-wait
      3. Screenshot (only after images confirmed loaded)
      4. Send to LLM for recognition
      5. Execute humanized drag operations
      6. Click submit

    Args:
        page: Playwright Page object (humanize=True recommended).
        server: llama.cpp server URL.
        model: LLM model name.
        max_retries: Maximum CAPTCHA-level retries (new CAPTCHA each time).
        screenshot_path: Optional path to save screenshot for debugging.

    Returns:
        True if CAPTCHA was solved (or wasn't present), False if all attempts failed.
    """
    for attempt in range(max_retries):
        # Step 1: Detect CAPTCHA container
        if not detect_captcha(page):
            logger.info("No CAPTCHA detected — page is clean")
            return True

        logger.info(f"CAPTCHA detected — solving (attempt {attempt + 1}/{max_retries})")

        # Step 2: Wait for images to load, refresh if they fail
        images_ok = _ensure_images_loaded(page)
        if not images_ok:
            # Try refreshing to get a new CAPTCHA with working images
            for refresh_i in range(MAX_REFRESH_PER_CAPTCHA):
                logger.info(f"Images failed — refreshing CAPTCHA ({refresh_i + 1}/{MAX_REFRESH_PER_CAPTCHA})")
                _click_refresh(page)
                time.sleep(2.0)  # wait for CAPTCHA to re-render
                if not detect_captcha(page):
                    logger.warning("CAPTCHA disappeared after refresh")
                    break
                if _ensure_images_loaded(page):
                    images_ok = True
                    break

        if not images_ok:
            logger.error("CAPTCHA images consistently fail to load — skipping this attempt")
            if attempt < max_retries - 1:
                # Try clicking a different location or refreshing the whole page
                _click_refresh(page)
                time.sleep(2.0)
            continue

        # Step 3: Screenshot (images confirmed loaded)
        ss_path = screenshot_path
        if ss_path is None:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                ss_path = tmp.name

        try:
            page.screenshot(path=str(ss_path), full_page=False)
            logger.info(f"CAPTCHA screenshot saved: {ss_path}")
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return False

        # Step 4: Recognize via LLM
        try:
            recognition = recognize_captcha(ss_path, server=server, model=model)
        except Exception as e:
            logger.error(f"LLM recognition failed: {e}")
            _cleanup_temp(ss_path, screenshot_path)
            if attempt < max_retries - 1:
                _click_refresh(page)
                time.sleep(2.0)
            continue

        if not recognition.is_captcha:
            logger.info("LLM says this is not a CAPTCHA — page is clean")
            _cleanup_temp(ss_path, screenshot_path)
            return True

        # Step 4b: Check if LLM saw a broken CAPTCHA (no correct cells = likely load failure)
        if not recognition.correct_cells:
            logger.warning("LLM returned 0 correct cells — CAPTCHA images may be broken in screenshot")
            _cleanup_temp(ss_path, screenshot_path)
            if attempt < max_retries - 1:
                _click_refresh(page)
                time.sleep(2.0)
            continue

        # Step 5: Execute solving
        try:
            solved = solve_drag_captcha(page, recognition, max_retries=1)
            if solved:
                time.sleep(1.5)
                if not detect_captcha(page):
                    logger.info("CAPTCHA fully resolved!")
                    _cleanup_temp(ss_path, screenshot_path)
                    return True
                logger.warning("CAPTCHA seems solved but still detected — may be a new challenge")
            else:
                logger.warning("Solve execution failed")
        except Exception as e:
            logger.error(f"Solve execution failed: {e}")

        # Step 6: Refresh for next attempt
        _cleanup_temp(ss_path, screenshot_path)
        if attempt < max_retries - 1:
            _click_refresh(page)
            time.sleep(2.0)

    logger.error(f"Failed to solve CAPTCHA after {max_retries} attempts")
    return False


def _ensure_images_loaded(page: Any) -> bool:
    """Wait for CAPTCHA images to load. Returns True if images are ready."""
    # Also check if there's an explicit error state
    if _has_image_load_error(page):
        logger.warning("CAPTCHA shows image load error — need refresh")
        return False

    ok = wait_for_captcha_images(page, timeout_ms=IMAGE_LOAD_TIMEOUT_MS)
    if not ok:
        logger.warning("CAPTCHA images did not load in time")
    return ok


def _cleanup_temp(path: str | Path, original: str | Path | None) -> None:
    """Remove temp screenshot if it wasn't explicitly requested."""
    if original is not None:
        return
    import contextlib

    with contextlib.suppress(Exception):
        Path(path).unlink(missing_ok=True)


__all__ = [
    "solve_captcha",
    "detect_captcha",
    "recognize_captcha",
    "solve_drag_captcha",
    "CaptchaRecognition",
]
