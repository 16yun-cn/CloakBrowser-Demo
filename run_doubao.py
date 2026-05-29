from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib

from cloakbrowser import launch_persistent_context
from captcha import solve_captcha


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


def log_step(message: str) -> None:
    print(f"[run_doubao] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml")
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


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


def validate_filename(name: str, key: str) -> str:
    if not name:
        raise ConfigError(f"Missing required config value: {key}")
    pure = Path(name)
    if pure.name != name or "/" in name or "\\" in name:
        raise ConfigError(f"{key} must be a file name, not a path: {name}")
    return name


def build_session_paths(config: dict[str, Any]) -> SessionPaths:
    session = require_section(config, "session")
    artifacts = require_section(config, "artifacts")

    base_dir = Path(str(require_value(session, "base_dir")))
    session_name = str(session.get("session_name", "")).strip()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_id = f"{session_name}-{timestamp}" if session_name else timestamp

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


def build_selector_config(config: dict[str, Any]) -> SelectorConfig:
    dialog = require_section(config, "dialog")
    return SelectorConfig(
        input_selector=str(dialog.get("input_selector", "")).strip(),
        submit_selector=str(dialog.get("submit_selector", "")).strip(),
        response_selector=str(dialog.get("response_selector", "")).strip(),
    )


def build_fingerprint_args(config: dict[str, Any]) -> list[str]:
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


# Domains used by Chinese CAPTCHA CDNs — requests to these bypass the proxy
_CAPTCHA_CDN_DOMAINS = [
    # Tencent CAPTCHA
    "captcha.gtimg.com",
    "t.captcha.qq.com",
    "captcha.qq.com",
    # ByteDance/Doubao verification services (config, image serving)
    "zijieapi.com",
    "bytedance.com",
    # Baidu CAPTCHA
    "captcha.baidu.com",
    # Geetest
    "api.geetest.com",
    "static.geetest.com",
    "gcaptcha4.geetest.com",
    # QCloud
    "captcha1.guard.qcloud.com",
]


def _install_captcha_cdn_bypass(page: Any) -> None:
    """Intercept CAPTCHA CDN requests and route them directly (bypass proxy).

    CAPTCHA image CDNs often throttle or block datacenter/proxy IPs.
    This intercepts matching requests, fetches them directly from Python
    (no proxy), and fulfills the browser request with the direct response.
    """
    import urllib.request as _urlreq

    def _direct_fetch(route: Any) -> None:
        """Fetch the request directly from Python, bypassing browser proxy."""
        try:
            req_url = route.request.url
            req_headers = {k: v for k, v in route.request.headers.items()}
            # Remove headers that might cause issues on direct request
            req_headers.pop("proxy-authorization", None)
            req_headers.pop("proxy-connection", None)

            url_req = _urlreq.Request(req_url, headers=req_headers)
            with _urlreq.urlopen(url_req, timeout=15) as resp:
                body = resp.read()
                resp_headers = dict(resp.headers)
                # Remove transfer-encoding — Playwright handles it
                resp_headers.pop("transfer-encoding", None)
                resp_headers.pop("content-encoding", None)
                route.fulfill(
                    status=resp.status,
                    headers=resp_headers,
                    body=body,
                )
        except Exception:
            # Fall back to normal proxy routing
            try:
                route.continue_()
            except Exception:
                pass

    try:
        for domain in _CAPTCHA_CDN_DOMAINS:
            page.route(f"**/*{domain}**", _direct_fetch)
        log_step("CAPTCHA CDN bypass installed (direct fetch, no proxy)")
    except Exception as e:
        log_step(f"CAPTCHA CDN bypass failed (non-fatal): {e}")


def run_dialog(config: dict[str, Any], paths: SessionPaths, use_http2_fallback: bool) -> dict[str, Any]:
    target = require_section(config, "target")
    session = require_section(config, "session")
    dialog = require_section(config, "dialog")

    url = str(require_value(target, "url"))
    prompt = str(require_value(dialog, "prompt"))
    selectors = build_selector_config(config)
    runtime_config = get_runtime_config(config)
    locator_config = get_locator_config(config)
    args = build_fingerprint_args(config)
    if use_http2_fallback:
        args.append("--disable-http2")

    browser_context = launch_persistent_context(str(paths.profile_dir), **build_launch_kwargs(config, args))
    try:
        log_step(f"Launching page, http2_fallback={use_http2_fallback}")
        page = browser_context.new_page()
        page.set_default_timeout(int(session.get("navigation_timeout_ms", 90000)))
        log_step(f"Navigating to {url}")
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("load", timeout=runtime_config["page_load_timeout_ms"])
        except Exception:
            log_step("Page load state 'load' did not complete within config timeout, continuing")

        # Solve CAPTCHA if present
        captcha_cfg = config.get("captcha", {})
        if captcha_cfg.get("enabled", True):
            # Bypass proxy for CAPTCHA CDN domains — CAPTCHA image CDNs often
            # block or throttle proxy IPs. Route these requests directly.
            if captcha_cfg.get("bypass_proxy", True):
                _install_captcha_cdn_bypass(page)

            captcha_server = captcha_cfg.get("llm_server", "http://192.168.2.60:8001")
            captcha_model = captcha_cfg.get("llm_model", "qwen3.5-35b-a3b")
            captcha_retries = captcha_cfg.get("max_retries", 3)
            captcha_ss = str(paths.session_dir / "captcha-screenshot.png")
            log_step("Checking for CAPTCHA...")
            solved = solve_captcha(
                page,
                server=captcha_server,
                model=captcha_model,
                max_retries=captcha_retries,
                screenshot_path=captcha_ss,
            )
            if not solved:
                raise RuntimeError("CAPTCHA solving failed after max retries")
            log_step("CAPTCHA check complete")

        page.screenshot(path=str(paths.before_screenshot), full_page=True)

        input_selectors = [selectors.input_selector] if selectors.input_selector else locator_config["input_selectors"]
        log_step("Locating input element")
        input_locator = find_first_visible(
            page,
            [selector for selector in input_selectors if selector],
            runtime_config["element_visible_timeout_ms"],
            runtime_config["max_selector_matches"],
        )
        log_step("Filling prompt")
        fill_prompt(page, input_locator, prompt)
        log_step("Submitting prompt")
        submit_prompt(
            page,
            input_locator,
            selectors,
            prompt,
            locator_config["submit_button_selectors"],
            runtime_config,
        )

        log_step("Waiting for response")
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
            log_step(f"Response detected early, waiting {remaining:.1f}s more before screenshot")
            time.sleep(remaining)
        page.screenshot(path=str(paths.after_screenshot), full_page=True)
        log_step("Response received")

        return {
            "final_url": page.url,
            "title": page.title(),
            "prompt": prompt,
            "response_excerpt": response_text[: runtime_config["max_response_excerpt_length"]],
        }
    finally:
        browser_context.close()


def write_report(paths: SessionPaths, payload: dict[str, Any]) -> None:
    paths.run_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    started_at = datetime.now()
    config = load_config(config_path)
    paths = build_session_paths(config)
    used_http2_fallback = False

    try:
        prepare_profile(config, paths)
        result: dict[str, Any]
        try:
            result = run_dialog(config, paths, use_http2_fallback=False)
        except Exception:
            used_http2_fallback = True
            result = run_dialog(config, paths, use_http2_fallback=True)

        finished_at = datetime.now()
        payload = {
            "status": "ok",
            "session_id": paths.session_id,
            "session_dir": str(paths.session_dir),
            "profile_dir": str(paths.profile_dir),
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
        failure = {
            "status": "error",
            "session_id": paths.session_id,
            "session_dir": str(paths.session_dir),
            "profile_dir": str(paths.profile_dir),
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
