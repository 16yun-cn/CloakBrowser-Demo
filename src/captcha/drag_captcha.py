"""
Drag-and-drop grid CAPTCHA solver.

Handles the common Chinese CAPTCHA pattern:
- Modal overlay with a 3×3 image grid
- Category title at top (e.g. "属于动物的")
- Drop target area with "拖拽到这里"
- Submit and Refresh buttons

Uses Playwright's bounding_box() for element positioning and
page.mouse for humanized drag operations.

When humanize=True is active on the page, mouse operations
automatically use Bézier curves for natural movement.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .recognizer import CaptchaRecognition

logger = logging.getLogger("cloakbrowser.captcha.drag_captcha")

# ---------------------------------------------------------------------------
# Common CAPTCHA container selectors (tried in order)
# ---------------------------------------------------------------------------

CAPTCHA_CONTAINER_SELECTORS = [
    # Tencent CAPTCHA
    ".tcaptcha-transform-container",
    "#tcaptcha_transform_dy",
    ".tcaptcha-transform",
    # Generic CAPTCHA patterns
    "[class*='captcha']",
    "[id*='captcha']",
    "[class*='verification']",
    "[id*='verification']",
    # Modal overlays that might contain CAPTCHA
    "[class*='modal'] [class*='captcha']",
    "[class*='dialog'] [class*='captcha']",
    # Doubao / ByteDance specific
    "[class*='verify']",
    "[class*='shield']",
]

# CAPTCHA iframe selectors
CAPTCHA_IFRAME_SELECTORS = [
    "iframe[src*='captcha']",
    "iframe[src*='tcaptcha']",
    "iframe[id*='tcaptcha']",
    "iframe[src*='verify']",
    "iframe[src*='shield']",
]

# ---------------------------------------------------------------------------
# Drop target selectors
# ---------------------------------------------------------------------------

DROP_TARGET_SELECTORS = [
    "[class*='drag-target']",
    "[class*='drop-zone']",
    "[class*='dropzone']",
    "[class*='drag_area']",
    "[class*='target-area']",
    ".tcaptcha-drag-target",
    "[class*='slider']",
]

# ---------------------------------------------------------------------------
# Submit / Refresh button selectors
# ---------------------------------------------------------------------------

SUBMIT_BUTTON_SELECTORS = [
    "button:has-text('提交')",
    "button:has-text('确定')",
    "button:has-text('Submit')",
    "button:has-text('Confirm')",
    "[class*='submit'] button",
    "[class*='submit-btn']",
]

REFRESH_BUTTON_SELECTORS = [
    "button:has-text('刷新')",
    "[class*='refresh']",
    "[aria-label*='刷新']",
    "[aria-label*='refresh' i]",
]


def _find_element(page_or_frame: Any, selectors: list[str]) -> Any | None:
    """Find first visible element matching any of the selectors."""
    for selector in selectors:
        try:
            locator = page_or_frame.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue
    return None


def _find_captcha_frame(page: Any) -> Any | None:
    """Find iframe containing CAPTCHA and return its frame object."""
    for selector in CAPTCHA_IFRAME_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                frame = locator.content_frame()
                if frame:
                    logger.info(f"Found CAPTCHA iframe: {selector}")
                    return frame
        except Exception:
            continue

    # Also check all frames for CAPTCHA content
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            for sel in CAPTCHA_CONTAINER_SELECTORS:
                el = frame.locator(sel).first
                if el.count() > 0:
                    logger.info(f"Found CAPTCHA in frame: {frame.url}")
                    return frame
        except Exception:
            continue

    return None


def _get_search_root(page: Any) -> tuple[Any, Any]:
    """Get the correct page/frame root for CAPTCHA search.

    Returns (frame, container_locator) where frame is the Playwright frame
    containing the CAPTCHA (or main page) and container_locator is the
    CAPTCHA container element within that frame.
    """
    # Check for CAPTCHA iframe first
    captcha_frame = _find_captcha_frame(page)
    if captcha_frame:
        container = _find_element(captcha_frame, CAPTCHA_CONTAINER_SELECTORS)
        if container:
            return captcha_frame, container

    # Main page
    container = _find_element(page, CAPTCHA_CONTAINER_SELECTORS)
    if container:
        return page, container

    # Fallback: body
    return page, page.locator("body")


def _find_all_images_in_container(page_or_frame: Any, container_locator: Any) -> list[dict[str, float]]:
    """Find all img elements inside the container and return their bounding boxes.

    Returns list of {x, y, width, height} in viewport coordinates, sorted
    by position (top-to-bottom, left-to-right).
    """
    result = page_or_frame.evaluate(
        """
        (container) => {
            const imgs = container.querySelectorAll('img');
            const boxes = [];
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (rect.width > 20 && rect.height > 20) {  // ignore tiny icons
                    boxes.push({
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                    });
                }
            }
            // Sort by position: top-to-bottom, then left-to-right
            boxes.sort((a, b) => {
                const rowDiff = a.y - b.y;
                if (Math.abs(rowDiff) > 10) return rowDiff;
                return a.x - b.x;
            });
            return boxes;
        }
        """,
        container_locator.element_handle(),
    )
    return result


def _get_grid_cells(
    page_or_frame: Any,
    container_locator: Any,
    rows: int,
    cols: int,
) -> list[dict[str, float]]:
    """Calculate grid cell centers based on image positions inside container.

    Tries to use actual img element positions first. Falls back to equal
    division of container bounds.

    Returns list of {x, y} center points for each cell, in row-major order.
    """
    imgs = _find_all_images_in_container(page_or_frame, container_locator)
    if imgs and len(imgs) == rows * cols:
        logger.info(f"Found {len(imgs)} image elements in container")
        cells = []
        for img in imgs:
            cells.append(
                {
                    "x": img["x"] + img["width"] / 2,
                    "y": img["y"] + img["height"] / 2,
                }
            )
        return cells

    # Fallback: equal division
    logger.info("No image elements found, using grid division")
    box = container_locator.bounding_box()
    if not box:
        raise RuntimeError("Cannot determine container bounding box")

    cell_w = box["width"] / cols
    cell_h = box["height"] / rows
    cells = []
    for r in range(rows):
        for c in range(cols):
            cells.append(
                {
                    "x": box["x"] + (c + 0.5) * cell_w,
                    "y": box["y"] + (r + 0.5) * cell_h,
                }
            )
    return cells


def _get_drop_target(page_or_frame: Any, container_locator: Any) -> dict[str, float] | None:
    """Find the drop target area and return its center coordinates."""
    # Try JS-based detection of the "drag here" zone
    result = page_or_frame.evaluate(
        """
        (container) => {
            const candidates = container.querySelectorAll(
                '[class*="drag"], [class*="drop"], [class*="target"], ' +
                '[class*="receiver"], [class*="zone"], [class*="area"]'
            );
            for (const el of candidates) {
                const text = (el.textContent || '').trim();
                if (text.includes('拖拽') || text.includes('drag') ||
                    text.includes('drop') || text.includes('拖动') ||
                    text.includes('放置')) {
                    const rect = el.getBoundingClientRect();
                    return {
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                    };
                }
            }
            return null;
        }
        """,
        container_locator.element_handle(),
    )
    if result:
        logger.info(f"Found drop target via JS: {result}")
        return result

    # Try selector-based approach
    drop_el = _find_element(page_or_frame, DROP_TARGET_SELECTORS)
    if drop_el:
        box = drop_el.bounding_box()
        if box:
            return {"x": box["x"] + box["width"] / 2, "y": box["y"] + box["height"] / 2}

    return None


def _execute_drag(
    page: Any,
    from_x: float,
    from_y: float,
    to_x: float,
    to_y: float,
    steps: int = 30,
) -> None:
    """Execute a humanized drag from source to target position.

    Uses page.mouse which is patched by humanize for Bézier curves.
    """
    # Move to source
    page.mouse.move(from_x, from_y)
    time.sleep(0.05)

    # Press down
    page.mouse.down()

    # Drag to target with intermediate steps for smooth humanized curve
    page.mouse.move(to_x, to_y, steps=steps)

    # Small pause before release (human-like)
    time.sleep(0.08)

    # Release
    page.mouse.up()


def wait_for_captcha_images(
    page: Any,
    timeout_ms: int = 10000,
    poll_interval_ms: int = 500,
) -> bool:
    """Wait for CAPTCHA grid images to fully load (naturalWidth > 0).

    Polls the DOM for img elements inside the CAPTCHA container.
    Returns True when at least 9 loaded images (3×3 grid) are found.
    Returns False on timeout.

    Also returns False early if "图片加载失败" error text detected.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        frame, container = _get_search_root(page)

        # Check for error state first
        error_text = frame.evaluate(
            """(container) => {
                const text = (container.textContent || '');
                return text.includes('图片加载失败') || text.includes('加载失败');
            }""",
            container.element_handle(),
        )
        if error_text:
            logger.warning("CAPTCHA images failed to load (error text detected)")
            return False

        # Count loaded images
        loaded_count = frame.evaluate(
            """(container) => {
                const imgs = container.querySelectorAll('img');
                let count = 0;
                for (const img of imgs) {
                    if (img.naturalWidth > 20 && img.naturalHeight > 20) {
                        count++;
                    }
                }
                return count;
            }""",
            container.element_handle(),
        )
        logger.info(f"CAPTCHA loaded images: {loaded_count}/9")
        if loaded_count >= 9:
            return True

        time.sleep(poll_interval_ms / 1000)

    logger.warning(f"Timed out waiting for CAPTCHA images after {timeout_ms}ms")
    return False


def _has_image_load_error(page: Any) -> bool:
    """Check if CAPTCHA shows image load error on page."""
    try:
        frame, container = _get_search_root(page)
        return frame.evaluate(
            """(container) => {
                const text = (container.textContent || '');
                return text.includes('图片加载失败') || text.includes('加载失败');
            }""",
            container.element_handle(),
        )
    except Exception:
        return False


def _click_refresh(page: Any) -> bool:
    """Click CAPTCHA refresh button. Returns True if clicked."""
    for selector in REFRESH_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                logger.info("Clicked CAPTCHA refresh button")
                return True
        except Exception:
            continue

    # Fallback: try clicking any element containing refresh icon/text
    try:
        refresh_el = page.locator("[class*='refresh'], [class*='reload'], span:has-text('刷新')").first
        if refresh_el.count() > 0 and refresh_el.is_visible():
            refresh_el.click()
            logger.info("Clicked refresh via fallback selector")
            return True
    except Exception:
        pass

    logger.warning("Could not find refresh button")
    return False


def solve_drag_captcha(
    page: Any,
    recognition: CaptchaRecognition,
    max_retries: int = 2,
) -> bool:
    """Solve a drag-and-drop grid CAPTCHA on the page.

    Args:
        page: Playwright Page object (should have humanize=True active).
        recognition: Parsed CAPTCHA recognition result.
        max_retries: Max retry attempts if solving fails.

    Returns:
        True if CAPTCHA was solved successfully, False otherwise.
    """
    if not recognition.is_captcha:
        logger.info("Not a CAPTCHA — nothing to solve")
        return True

    if recognition.captcha_type != "drag_grid":
        logger.warning(f"Unsupported CAPTCHA type: {recognition.captcha_type}")
        return False

    if not recognition.correct_cells:
        logger.warning("No correct cells identified by LLM")
        return False

    for attempt in range(max_retries):
        logger.info(
            f"Solving drag CAPTCHA — attempt {attempt + 1}/{max_retries}, "
            f"category={recognition.category_keyword!r}, "
            f"correct cells={recognition.correct_cells}"
        )

        try:
            # Step 1: Find CAPTCHA root (main page or iframe)
            frame, container = _get_search_root(page)
            logger.info(f"CAPTCHA found in {'iframe' if frame != page else 'main page'}")

            # Step 2: Calculate grid cell positions
            cells = _get_grid_cells(frame, container, recognition.grid_rows, recognition.grid_cols)
            if len(cells) != recognition.grid_rows * recognition.grid_cols:
                logger.warning(
                    f"Grid cell count mismatch: expected {recognition.grid_rows * recognition.grid_cols}, "
                    f"got {len(cells)}"
                )
                cells = _get_grid_cells(page, page.locator("body"), recognition.grid_rows, recognition.grid_cols)

            # Step 3: Find drop target
            drop_target = _get_drop_target(frame, container)
            if not drop_target:
                # Fallback: center-bottom of container
                box = container.bounding_box() or frame.locator("body").bounding_box()
                if box:
                    drop_target = {
                        "x": box["x"] + box["width"] / 2,
                        "y": box["y"] + box["height"] * 0.9,
                    }
                    logger.info(f"Using fallback drop target: {drop_target}")
                else:
                    logger.error("Cannot determine drop target")
                    return False

            # Step 4: Drag each correct cell to drop target
            for cell_idx in recognition.correct_cells:
                row, col = cell_idx[0], cell_idx[1]
                flat_idx = row * recognition.grid_cols + col

                if flat_idx >= len(cells):
                    logger.warning(f"Cell index {flat_idx} out of range (have {len(cells)} cells)")
                    continue

                cell = cells[flat_idx]
                logger.info(
                    f"Dragging cell ({row},{col}) from ({cell['x']:.0f},{cell['y']:.0f}) "
                    f"to ({drop_target['x']:.0f},{drop_target['y']:.0f})"
                )

                _execute_drag(page, cell["x"], cell["y"], drop_target["x"], drop_target["y"])

                # Brief pause between drags
                time.sleep(0.3)

            # Step 5: Click submit button
            submit_btn = _find_element(page, SUBMIT_BUTTON_SELECTORS)
            if submit_btn:
                logger.info("Clicking submit button")
                submit_btn.click()
            else:
                logger.warning("Submit button not found")

            # Step 6: Verify CAPTCHA is gone
            time.sleep(1.0)
            remaining = _find_element(page, CAPTCHA_CONTAINER_SELECTORS)
            if not remaining or not remaining.is_visible():
                logger.info("CAPTCHA solved successfully!")
                return True

            logger.warning("CAPTCHA still visible after solve attempt, may need retry")

        except Exception as e:
            logger.error(f"Solve attempt {attempt + 1} failed: {e}")

    return False


def detect_captcha(page: Any) -> bool:
    """Check if a CAPTCHA is present on the page.

    Returns True if a CAPTCHA element is detected in the DOM.
    """
    for selector in CAPTCHA_CONTAINER_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                logger.info(f"CAPTCHA detected via selector: {selector}")
                return True
        except Exception:
            continue

    # Also check iframes
    captcha_frame = _find_captcha_frame(page)
    if captcha_frame:
        logger.info("CAPTCHA detected inside iframe")
        return True

    logger.info("No CAPTCHA detected on page")
    return False
