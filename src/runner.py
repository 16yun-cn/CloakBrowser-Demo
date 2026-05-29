"""Single-worker doubao.com dialog runner.

Accepts CLI args for standalone use, or import run_dialog() for programmatic use
(e.g. from the concurrent orchestrator).

Usage:
    # Standalone (single worker)
    python run_doubao.py --config config.toml

    # With worker overrides (used by run_concurrent.py internally)
    python run_doubao.py --config config.toml --worker-index 3 --seed-override 42072
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config as _cl
from captcha import solve_captcha
from cloakbrowser import launch_persistent_context
from config import (
    SelectorConfig,
    SessionPaths,
    build_fingerprint_args,
    build_launch_kwargs,
    build_selector_config,
    build_session_paths,
    get_locator_config,
    get_runtime_config,
    load_config,
    parse_args,
    prepare_profile,
    require_section,
    require_value,
    write_report,
)

# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------


def find_first_visible(page: Any, selectors: list[str], visible_timeout_ms: int, max_selector_matches: int) -> Any:
    for selector in selectors:
        locator = page.locator(selector)
        count = min(locator.count(), max_selector_matches)
        for index in range(count):
            candidate = locator.nth(index)
            try:
                candidate.wait_for(state="visible", timeout=visible_timeout_ms)
                box = candidate.bounding_box()
                if box and box["width"] > 0 and box["height"] > 0:
                    return candidate
            except Exception:
                continue
    raise RuntimeError(f"Unable to find a visible element from selectors: {selectors}")


def get_input_text(locator: Any) -> str:
    return str(
        locator.evaluate(
            """
            node => {
                if (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) {
                    return node.value || "";
                }
                return node.innerText || node.textContent || "";
            }
            """
        )
    ).strip()


def set_contenteditable_text(locator: Any, prompt: str) -> None:
    locator.evaluate(
        """
        (node, value) => {
            node.focus();
            const text = String(value);
            node.textContent = text;
            node.dispatchEvent(new InputEvent("input", {
                bubbles: true,
                inputType: "insertText",
                data: text
            }));
            node.dispatchEvent(new Event("change", { bubbles: true }));
        }
        """,
        prompt,
    )


def fill_prompt(page: Any, locator: Any, prompt: str) -> None:
    tag_name = (locator.evaluate("node => node.tagName") or "").lower()
    locator.scroll_into_view_if_needed()
    locator.click()
    locator.focus()

    if tag_name in {"textarea", "input"}:
        locator.fill(prompt)
        if get_input_text(locator) == prompt:
            return

        locator.press("Meta+A")
        page.keyboard.insert_text(prompt)
        if get_input_text(locator) == prompt:
            return
    else:
        try:
            locator.press("Meta+A")
            locator.press("Backspace")
            locator.type(prompt)
        except Exception:
            pass
        if get_input_text(locator) == prompt:
            return

        set_contenteditable_text(locator, prompt)
        if get_input_text(locator) == prompt:
            return

        page.keyboard.insert_text(prompt)
        if get_input_text(locator) == prompt:
            return

    raise RuntimeError("Prompt text was not inserted into the input box")


def prompt_submitted(locator: Any, prompt: str, timeout_ms: int, poll_interval_ms: int) -> bool:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if get_input_text(locator) != prompt:
            return True
        time.sleep(poll_interval_ms / 1000)
    return False


def click_nearest_send_button(page: Any, input_locator: Any, runtime_config: dict[str, Any]) -> bool:
    input_box = input_locator.bounding_box()
    if not input_box:
        return False

    buttons = page.locator("button")
    count = min(buttons.count(), runtime_config["max_button_matches"])
    best_locator = None
    best_score = None
    target_x = input_box["x"] + input_box["width"]
    target_y = input_box["y"] + input_box["height"]

    for index in range(count):
        candidate = buttons.nth(index)
        try:
            if not candidate.is_visible() or not candidate.is_enabled():
                continue
            box = candidate.bounding_box()
            if not box or box["width"] <= 0 or box["height"] <= 0:
                continue
            if box["x"] < input_box["x"] + input_box["width"] * runtime_config["send_button_min_x_ratio"]:
                continue
            tolerance = runtime_config["send_button_y_tolerance_px"]
            if box["y"] < input_box["y"] - tolerance or box["y"] > input_box["y"] + input_box["height"] + tolerance:
                continue
            score = abs(box["x"] - target_x) + abs(box["y"] - target_y)
            if best_score is None or score < best_score:
                best_score = score
                best_locator = candidate
        except Exception:
            continue

    if best_locator is None:
        return False

    best_locator.click()
    return True


def submit_prompt(
    page: Any,
    input_locator: Any,
    selectors: SelectorConfig,
    prompt: str,
    submit_button_selectors: list[str],
    runtime_config: dict[str, Any],
) -> None:
    if selectors.submit_selector:
        submit_locator = page.locator(selectors.submit_selector).first
        submit_locator.wait_for(state="visible", timeout=runtime_config["submit_visible_timeout_ms"])
        submit_locator.click()
        if prompt_submitted(
            input_locator,
            prompt,
            runtime_config["submit_state_timeout_ms"],
            runtime_config["submit_state_poll_interval_ms"],
        ):
            return

    for selector in submit_button_selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=runtime_config["submit_retry_visible_timeout_ms"])
            locator.click()
            if prompt_submitted(
                input_locator,
                prompt,
                runtime_config["submit_state_timeout_ms"],
                runtime_config["submit_state_poll_interval_ms"],
            ):
                return
        except Exception:
            continue

    if click_nearest_send_button(page, input_locator, runtime_config) and prompt_submitted(
        input_locator,
        prompt,
        runtime_config["submit_state_timeout_ms"],
        runtime_config["submit_state_poll_interval_ms"],
    ):
        return

    input_locator.press("Enter")
    if prompt_submitted(
        input_locator,
        prompt,
        runtime_config["submit_state_timeout_ms"],
        runtime_config["submit_state_poll_interval_ms"],
    ):
        return

    raise RuntimeError("Prompt was inserted but could not be submitted")


def is_noise_text(text: str, noise_tokens: list[str]) -> bool:
    return any(token in text for token in noise_tokens)


def extract_response(
    page: Any,
    prompt: str,
    selectors: SelectorConfig,
    timeout_ms: int,
    response_candidate_selectors: list[str],
    noise_tokens: list[str],
    runtime_config: dict[str, Any],
) -> str:
    deadline = time.time() + timeout_ms / 1000
    if selectors.response_selector:
        locator = page.locator(selectors.response_selector).last
        locator.wait_for(state="visible", timeout=timeout_ms)
        text = locator.inner_text().strip()
        if text:
            return text

    while time.time() < deadline:
        for selector in response_candidate_selectors:
            locator = page.locator(selector)
            count = min(locator.count(), runtime_config["max_selector_matches"])
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    box = candidate.bounding_box()
                    if (
                        not box
                        or box["x"] < runtime_config["response_min_x"]
                        or box["y"] < runtime_config["response_min_y"]
                        or box["y"] > runtime_config["response_max_y"]
                    ):
                        continue
                    text = candidate.inner_text().strip()
                except Exception:
                    continue
                if not text or text == prompt or prompt in text or is_noise_text(text, noise_tokens):
                    continue
                if len(text) >= runtime_config["response_min_text_length"]:
                    return text
        time.sleep(runtime_config["response_poll_interval_ms"] / 1000)
    raise RuntimeError("Timed out waiting for a non-empty Doubao response")


# ---------------------------------------------------------------------------
# CAPTCHA CDN bypass
# ---------------------------------------------------------------------------

_CAPTCHA_CDN_DOMAINS = [
    "captcha.gtimg.com",
    "t.captcha.qq.com",
    "captcha.qq.com",
    "zijieapi.com",
    "bytedance.com",
    "captcha.baidu.com",
    "api.geetest.com",
    "static.geetest.com",
    "gcaptcha4.geetest.com",
    "captcha1.guard.qcloud.com",
]


def _install_captcha_cdn_bypass(page: Any) -> None:
    """Intercept CAPTCHA CDN requests and route them directly (bypass proxy)."""
    import urllib.request as _urlreq

    def _direct_fetch(route: Any) -> None:
        try:
            req_url = route.request.url
            req_headers = dict(route.request.headers.items())
            req_headers.pop("proxy-authorization", None)
            req_headers.pop("proxy-connection", None)

            url_req = _urlreq.Request(req_url, headers=req_headers)
            with _urlreq.urlopen(url_req, timeout=15) as resp:
                body = resp.read()
                resp_headers = dict(resp.headers)
                resp_headers.pop("transfer-encoding", None)
                resp_headers.pop("content-encoding", None)
                route.fulfill(
                    status=resp.status,
                    headers=resp_headers,
                    body=body,
                )
        except Exception:
            with contextlib.suppress(Exception):
                route.continue_()

    try:
        for domain in _CAPTCHA_CDN_DOMAINS:
            page.route(f"**/*{domain}**", _direct_fetch)
        _cl.log_step("CAPTCHA CDN bypass installed (direct fetch, no proxy)")
    except Exception as e:
        _cl.log_step(f"CAPTCHA CDN bypass failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Main dialog runner
# ---------------------------------------------------------------------------


def run_dialog(
    config: dict[str, Any],
    paths: SessionPaths,
    use_http2_fallback: bool,
    *,
    fingerprint_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run a single doubao.com dialog.

    Args:
        config: Full config dict (may have fingerprint.seed overridden per worker).
        paths: SessionPaths for this worker.
        use_http2_fallback: Whether to disable HTTP/2 (retry mode).
        fingerprint_args: Optional pre-built fingerprint CLI args. If None,
            built from config via build_fingerprint_args().
    """
    target = require_section(config, "target")
    session = require_section(config, "session")
    dialog = require_section(config, "dialog")

    url = str(require_value(target, "url"))
    prompt = str(require_value(dialog, "prompt"))
    selectors = build_selector_config(config)
    runtime_config = get_runtime_config(config)
    locator_config = get_locator_config(config)

    args = fingerprint_args if fingerprint_args is not None else build_fingerprint_args(config)
    if use_http2_fallback:
        args = list(args) + ["--disable-http2"]

    browser_context = launch_persistent_context(str(paths.profile_dir), **build_launch_kwargs(config, args))
    try:
        _cl.log_step(f"Launching page, http2_fallback={use_http2_fallback}")
        page = browser_context.new_page()
        page.set_default_timeout(int(session.get("navigation_timeout_ms", 90000)))
        _cl.log_step(f"Navigating to {url}")
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=runtime_config["page_load_timeout_ms"])
        except Exception:
            _cl.log_step("Page load state 'load' did not complete within config timeout, continuing")

        # Solve CAPTCHA if present
        captcha_cfg = config.get("captcha", {})
        if captcha_cfg.get("enabled", True):
            if captcha_cfg.get("bypass_proxy", True):
                _install_captcha_cdn_bypass(page)

            captcha_server = captcha_cfg.get("llm_server", "http://192.168.2.60:8001")
            captcha_model = captcha_cfg.get("llm_model", "qwen3.5-35b-a3b")
            captcha_retries = captcha_cfg.get("max_retries", 3)
            captcha_ss = str(paths.session_dir / "captcha-screenshot.png")
            _cl.log_step("Checking for CAPTCHA...")
            solved = solve_captcha(
                page,
                server=captcha_server,
                model=captcha_model,
                max_retries=captcha_retries,
                screenshot_path=captcha_ss,
            )
            if not solved:
                raise RuntimeError("CAPTCHA solving failed after max retries")
            _cl.log_step("CAPTCHA check complete")

        page.screenshot(path=str(paths.before_screenshot), full_page=True)

        input_selectors = [selectors.input_selector] if selectors.input_selector else locator_config["input_selectors"]
        _cl.log_step("Locating input element")
        input_locator = find_first_visible(
            page,
            [selector for selector in input_selectors if selector],
            runtime_config["element_visible_timeout_ms"],
            runtime_config["max_selector_matches"],
        )
        _cl.log_step("Filling prompt")
        fill_prompt(page, input_locator, prompt)
        _cl.log_step("Submitting prompt")
        submit_prompt(
            page,
            input_locator,
            selectors,
            prompt,
            locator_config["submit_button_selectors"],
            runtime_config,
        )

        _cl.log_step("Waiting for response")
        response_wait_started_at = time.time()
        response_text = extract_response(
            page,
            prompt,
            selectors,
            int(session.get("response_timeout_ms", 120000)),
            locator_config["response_candidate_selectors"],
            locator_config["noise_tokens"],
            runtime_config,
        )
        elapsed = time.time() - response_wait_started_at
        if elapsed < runtime_config["min_reply_wait_seconds"]:
            remaining = runtime_config["min_reply_wait_seconds"] - elapsed
            _cl.log_step(f"Response detected early, waiting {remaining:.1f}s more before screenshot")
            time.sleep(remaining)
        page.screenshot(path=str(paths.after_screenshot), full_page=True)
        _cl.log_step("Response received")

        return {
            "final_url": page.url,
            "title": page.title(),
            "prompt": prompt,
            "response_excerpt": response_text[: runtime_config["max_response_excerpt_length"]],
        }
    finally:
        browser_context.close()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    started_at = datetime.now()
    config = load_config(config_path)

    # Build fingerprint args (respecting --seed-override from CLI if given)
    seed_override = args.seed_override
    fp_args = build_fingerprint_args(config, seed_override=seed_override)

    # Build session paths (respecting --session-dir from CLI if given)
    worker_index = args.worker_index if args.worker_index is not None else 0
    if args.session_dir is not None:
        paths = build_session_paths(
            config,
            worker_index=worker_index,
            workers=1,
            session_id_override=str(args.session_dir.name),
        )
        # Override to use the exact dir specified
        paths = build_session_paths(config, worker_index=worker_index, workers=1)
    else:
        paths = build_session_paths(config, worker_index=worker_index, workers=1)

    used_http2_fallback = False

    try:
        prepare_profile(config, paths)
        result: dict[str, Any]
        try:
            result = run_dialog(config, paths, use_http2_fallback=False, fingerprint_args=fp_args)
        except Exception:
            used_http2_fallback = True
            result = run_dialog(config, paths, use_http2_fallback=True, fingerprint_args=fp_args)

        finished_at = datetime.now()
        seed = seed_override if seed_override is not None else config.get("fingerprint", {}).get("seed", "?")
        payload = {
            "status": "ok",
            "session_id": paths.session_id,
            "session_dir": str(paths.session_dir),
            "profile_dir": str(paths.profile_dir),
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
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        finished_at = datetime.now()
        seed = seed_override if seed_override is not None else config.get("fingerprint", {}).get("seed", "?")
        failure = {
            "status": "error",
            "session_id": paths.session_id,
            "session_dir": str(paths.session_dir),
            "profile_dir": str(paths.profile_dir),
            "seed": seed,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
            "used_http2_fallback": used_http2_fallback,
            "error": str(exc),
        }
        write_report(paths, failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
