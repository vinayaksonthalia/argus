"""Render hand-sketched illustration HTML files to PNG at 2x."""
import sys, os
from pathlib import Path
from playwright.sync_api import sync_playwright

SRC = os.path.dirname(os.path.abspath(__file__))

def render(pairs):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 840}, device_scale_factor=2)
        page = ctx.new_page()
        for html, out in pairs:
            print("rendering", html, flush=True)
            page.goto(Path(html).resolve().as_uri(), wait_until="load")
            page.wait_for_function("window.__sketchDone === true", timeout=15000)
            page.wait_for_timeout(300)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            page.screenshot(path=out)
            print("OK", out, flush=True)
        browser.close()

if __name__ == "__main__":
    args = sys.argv[1:]
    pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    render(pairs)
