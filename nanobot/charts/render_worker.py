"""Private render-only process. No general browser or navigation API is exposed."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path

from playwright.sync_api import Route, sync_playwright


def deny_network(route: Route) -> None:
    route.abort()


def run() -> None:
    assets = Path(__file__).parent / "assets"
    script = (assets / "chart-renderer.js").read_bytes()
    css = (assets / "chart-renderer.css").read_bytes()
    for name, contents in (("js", script), ("css", css)):
        expected = (assets / f"chart-renderer.{name}.sha256").read_text().strip()
        if hashlib.sha256(contents).hexdigest() != expected:
            raise ValueError("Unverified chart renderer bundle")
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if executable is None:
        raise ValueError("Chart-only Chromium renderer is not installed")
    width, height = int(sys.argv[1]), int(sys.argv[2])
    if not 320 <= width <= 1600 or not 240 <= height <= 1200:
        raise ValueError("Invalid export size")
    raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Invalid export input")
    scene = json.loads(raw)
    font = base64.b64encode((assets / "DejaVuSans.ttf").read_bytes()).decode("ascii")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable, headless=True,
            args=["--disable-background-networking", "--disable-extensions", "--disable-component-update",
                  "--disable-sync", "--disable-default-apps", "--host-resolver-rules=MAP * ~NOTFOUND"])
        try:
            context = browser.new_context(viewport={"width": width, "height": height},
                accept_downloads=False, service_workers="block", locale="en-US", timezone_id="UTC", device_scale_factor=1)
            context.route("**/*", deny_network)
            context.route_web_socket("**/*", lambda socket: socket.close())
            page = context.new_page()
            page.set_default_timeout(15000)
            page.set_content('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; font-src data:; img-src data:; connect-src \'none\'; frame-src \'none\'; object-src \'none\'">'
                             '<div id="chart"></div>')
            page.add_style_tag(content=f'@font-face{{font-family:NanobotChart;src:url(data:font/ttf;base64,{font})}}'
                f'html,body{{margin:0;background:#0f172a}}#chart{{width:{width}px;height:{height}px}}'
                + css.decode() + '#chart *{font-family:NanobotChart,sans-serif !important}')
            page.add_script_tag(content=script.decode())
            # A fixed function receives data, never model-authored JS.
            data_url = page.evaluate("scene => NanobotChartRender.render(scene)", scene)
            if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
                raise ValueError("Invalid chart export")
            sys.stdout.write(data_url.removeprefix("data:image/png;base64,"))
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        # Do not reflect labels or provider data in process errors.
        sys.exit(1)
