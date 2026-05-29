#!/usr/bin/env python3
"""
CAPTCHA fingerprint diagnostic.
Launches browser with current config, navigates to doubao.com,
captures fingerprint signals and network events to diagnose
why CAPTCHA images fail to load.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "CloakBrowser")

from cloakbrowser import launch_persistent_context
from captcha import solve_captcha


CONFIG_TOML = "config.toml"


def main():
    import tomllib

    config = tomllib.loads(Path(CONFIG_TOML).read_text())

    # Build same launch args as run_doubao.py
    fingerprint = config["fingerprint"]
    webrtc_ip_mode = str(fingerprint["webrtc_ip_mode"])
    args = [
        f"--fingerprint={fingerprint['seed']}",
        f"--fingerprint-platform={fingerprint['platform']}",
        f"--fingerprint-brand={fingerprint['brand']}",
        f"--fingerprint-brand-version={fingerprint['brand_version']}",
        f"--fingerprint-platform-version={fingerprint['platform_version']}",
        f"--fingerprint-gpu-vendor={fingerprint['gpu_vendor']}",
        f"--fingerprint-gpu-renderer={fingerprint['gpu_renderer']}",
        f"--fingerprint-hardware-concurrency={fingerprint['hardware_concurrency']}",
        f"--fingerprint-device-memory={fingerprint['device_memory']}",
        f"--fingerprint-screen-width={fingerprint['screen_width']}",
        f"--fingerprint-screen-height={fingerprint['screen_height']}",
        f"--fingerprint-timezone={fingerprint['timezone']}",
        f"--fingerprint-locale={fingerprint['locale']}",
        f"--fingerprint-storage-quota={fingerprint['storage_quota_mb']}",
        f"--fingerprint-webrtc-ip={webrtc_ip_mode}",
    ]

    proxy_cfg = config["proxy"]
    proxy = f"http://{proxy_cfg['username']}:{proxy_cfg['password']}@{proxy_cfg['server'].replace('http://', '')}"

    print("=" * 60)
    print("CAPTCHA Fingerprint Diagnostic")
    print("=" * 60)

    ctx = launch_persistent_context(
        "./.runtime/diag-profile",
        proxy=proxy,
        headless=False,
        humanize=True,
        stealth_args=False,
        args=args,
    )
    page = ctx.new_page()

    # Collect console messages
    console_logs = []

    def on_console(msg):
        console_logs.append(f"[{msg.type}] {msg.text}")

    page.on("console", on_console)

    # Collect failed requests
    failed_requests = []

    def on_request_failed(request):
        failed_requests.append(
            {
                "url": request.url,
                "failure": request.failure,
            }
        )

    page.on("requestfailed", on_request_failed)

    print("\n--- Navigating to doubao.com ---")
    page.goto("https://www.doubao.com", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        print("Page load timeout — continuing")

    time.sleep(3)

    # === Check fingerprint signals ===
    print("\n--- Browser Fingerprint Check ---")
    fp = page.evaluate("""
        () => {
            return {
                webdriver: navigator.webdriver,
                userAgent: navigator.userAgent,
                platform: navigator.platform,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
                languages: navigator.languages,
                plugins: Array.from(navigator.plugins).map(p => p.name),
                maxTouchPoints: navigator.maxTouchPoints,
                vendor: navigator.vendor,
                cookieEnabled: navigator.cookieEnabled,
                doNotTrack: navigator.doNotTrack,
                screen: { w: screen.width, h: screen.height, availW: screen.availWidth, availH: screen.availHeight, colorDepth: screen.colorDepth },
                windowChrome: typeof window.chrome,
                windowChromeRuntime: !!(window.chrome && window.chrome.runtime),
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            };
        }
    """)
    print(json.dumps(fp, indent=2, ensure_ascii=False))

    # === Check for CAPTCHA-specific DOM elements ===
    print("\n--- CAPTCHA DOM Check ---")
    captcha_info = page.evaluate("""
        () => {
            const result = {};
            // Check various CAPTCHA selectors
            const selectors = [
                '.tcaptcha-transform-container',
                '#tcaptcha_transform_dy',
                '[class*="captcha"]',
                '[class*="verify"]',
                '[class*="shield"]',
                '[id*="captcha"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const rect = el.getBoundingClientRect();
                    result[sel] = {
                        visible: rect.width > 0 && rect.height > 0,
                        x: rect.x, y: rect.y, w: rect.width, h: rect.height,
                        childImgCount: el.querySelectorAll('img').length,
                    };
                }
            }
            // Check iframes
            const iframes = document.querySelectorAll('iframe');
            result.iframeCount = iframes.length;
            result.iframeSrcs = Array.from(iframes).map(f => f.src).filter(s => s);
            return result;
        }
    """)
    print(json.dumps(captcha_info, indent=2, ensure_ascii=False))

    # === Screenshot ===
    ss_path = ".runtime/diag-screenshot.png"
    page.screenshot(path=ss_path, full_page=False)
    print(f"\nScreenshot saved: {ss_path}")

    # === Console errors ===
    print(f"\n--- Console Messages ({len(console_logs)} total) ---")
    errors = [m for m in console_logs if "error" in m.lower() or "fail" in m.lower() or "warn" in m.lower()]
    for m in errors[-20:]:
        print(f"  {m[:200]}")

    # === Failed requests (CAPTCHA-related) ===
    print(f"\n--- Failed Requests ({len(failed_requests)} total) ---")
    captcha_fails = [
        r
        for r in failed_requests
        if any(k in r["url"].lower() for k in ["captcha", "tcaptcha", "verify", "shield", "gtimg"])
    ]
    for r in captcha_fails:
        print(f"  {r['url'][:120]}")
        print(f"    failure: {r['failure']}")

    ctx.close()
    print("\nDone. Review screenshot and logs above.")


if __name__ == "__main__":
    main()
