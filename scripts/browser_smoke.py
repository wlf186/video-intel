"""Exercise production assets in an isolated API checkout, without GPU/models."""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def check_browser(base_url, output):
    """App loads -> language/navigation interaction -> correct page, with offline docs."""
    output.mkdir(parents=True, exist_ok=True)
    origin = urlsplit(base_url).netloc
    errors, external = [], []
    with sync_playwright() as playwright:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or shutil.which(
            "chromium"
        )
        browser = playwright.chromium.launch(executable_path=executable)
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(
                    viewport={"width": width, "height": height}
                )

                def route(request_route):
                    url = request_route.request.url
                    if urlsplit(url).netloc != origin:
                        external.append(url)
                        request_route.abort()
                    else:
                        request_route.continue_()

                context.route("http**://**", route)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda msg: (
                        errors.append(msg.text) if msg.type == "error" else None
                    ),
                )
                page.goto(base_url, wait_until="domcontentloaded")
                expect(page).to_have_title("生成工作台 · Sandevistan Video")
                expect(page.locator("main")).to_be_visible()
                expect(page.locator("vite-error-overlay")).to_have_count(0)
                for language, label in [
                    ("zh", "任务库"),
                    ("en", "Library" if width < 600 else "Task library"),
                ]:
                    if width < 600:
                        page.get_by_role("button", name="菜单", exact=True).click()
                        page.locator(".menu-popover select").select_option(language)
                        page.get_by_role(
                            "button",
                            name="菜单" if language == "zh" else "Menu",
                            exact=True,
                        ).click()
                    else:
                        page.locator(".header-actions select").select_option(language)
                    page.get_by_role("button", name=label, exact=True).filter(
                        visible=True
                    ).click()
                    expect(page).to_have_title(
                        ("任务库" if language == "zh" else "Task library")
                        + " · Sandevistan Video"
                    )
                    expect(
                        page.get_by_text(
                            "正在加载任务…" if language == "zh" else "Loading tasks…",
                            exact=True,
                        )
                    ).to_have_count(0)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    ), "Horizontal overflow"
                    page.screenshot(
                        path=str(output / f"library-{width}-{language}.png"),
                        full_page=False,
                    )
                page.goto(base_url + "/docs", wait_until="domcontentloaded")
                expect(page.get_by_role("heading", level=1)).to_contain_text(
                    "Sandevistan Video"
                )
                expect(page.locator(".opblock").first).to_be_visible()
                assert page.evaluate("ui.getConfigs().validatorUrl") is None
                page.screenshot(path=str(output / f"docs-{width}.png"), full_page=False)
                context.close()
        finally:
            browser.close()
    assert not errors, errors
    assert not external, external
    print(
        "Browser plugin not available; Playwright Chromium: desktop/mobile, Chinese/English, "
        "navigation and offline Swagger passed; no console errors or external requests"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", help="Read-only checks against an existing deployment"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "video-intel-browser-smoke",
    )
    args = parser.parse_args()
    if args.base_url:
        check_browser(args.base_url.rstrip("/"), args.output)
        return
    with tempfile.TemporaryDirectory(prefix="video-intel-browser-") as folder:
        stage = Path(folder)
        for name in ["video_intel", "static", "frontend/dist"]:
            shutil.copytree(
                ROOT / name, stage / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with (stage / "api.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "video_intel.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=stage,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "PYTHONPATH": str(stage),
                    "VIDEO_INTEL_PORT": str(port),
                    "VIDEO_INTEL_BACKEND_PORT": "1",
                },
            )
            base_url = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        with urllib.request.urlopen(
                            base_url + "/openapi.json", timeout=1
                        ) as response:
                            assert (
                                json.load(response)["info"]["version"]
                                == json.loads(
                                    (ROOT / "frontend/package.json").read_text()
                                )["version"]
                            )
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Isolated API did not start")
                check_browser(base_url, args.output)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
