#!/usr/bin/env python3
"""
Browser control utility for connecting to Chrome via CDP (Chrome DevTools Protocol).

Usage:
    from browser import Browser

    async with Browser() as b:
        await b.goto("https://example.com")
        await b.screenshot("screenshot.png")
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING, Literal

# Activate the virtual environment
venv_path = Path.home() / ".local/browser-venv"
if venv_path.exists():
    sys.path.insert(0, str(venv_path / "lib" / "python3.11" / "site-packages"))

from playwright.async_api import async_playwright  # noqa: E402  # type: ignore[import-not-found]

if TYPE_CHECKING:
    from playwright.async_api import Browser as PWBrowser, Page  # noqa: E402  # type: ignore[import-not-found]


WaitUntilType = Literal["commit", "domcontentloaded", "load", "networkidle"]


class Browser:
    """Browser control via Chrome DevTools Protocol."""

    DEFAULT_CDP_URL = "http://host.docker.internal:9222"

    def __init__(self, cdp_url: str | None = None):
        self.cdp_url = cdp_url or os.environ.get("CHROME_CDP_URL", self.DEFAULT_CDP_URL)
        self._playwright = None
        self._browser: PWBrowser | None = None
        self._page: Page | None = None
        self._console_messages: list[dict] = []

    def _require_page(self) -> Page:
        """Get the current page, raising if not connected."""
        if self._page is None:
            raise RuntimeError("Not connected to browser. Call connect() first.")
        return self._page

    def _require_browser(self) -> PWBrowser:
        """Get the browser, raising if not connected."""
        if self._browser is None:
            raise RuntimeError("Not connected to browser. Call connect() first.")
        return self._browser

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    def _get_ws_url(self) -> str | None:
        """Fetch WebSocket URL from Chrome, using localhost Host header to bypass security check."""
        url = f"{self.cdp_url}/json/version"
        req = urllib.request.Request(url, headers={"Host": "localhost"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                ws_url = data.get("webSocketDebuggerUrl")
                if ws_url:
                    # Replace localhost/127.0.0.1 with actual host address
                    # Chrome returns ws://localhost:PORT/... but we need ws://host.docker.internal:PORT/...
                    from urllib.parse import urlparse
                    cdp_parsed = urlparse(self.cdp_url)
                    ws_url = ws_url.replace("ws://localhost", f"ws://{cdp_parsed.hostname}")
                    ws_url = ws_url.replace("ws://127.0.0.1", f"ws://{cdp_parsed.hostname}")
                    # Also fix port if Chrome didn't include it
                    if cdp_parsed.port and f":{cdp_parsed.port}" not in ws_url:
                        ws_url = ws_url.replace(
                            f"ws://{cdp_parsed.hostname}/",
                            f"ws://{cdp_parsed.hostname}:{cdp_parsed.port}/"
                        )
                return ws_url
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Chrome at {self.cdp_url}: {e}") from e

    async def connect(self):
        """Connect to Chrome via CDP."""
        self._playwright = await async_playwright().start()

        # Get WebSocket URL with localhost Host header to bypass Chrome's security check
        ws_url = self._get_ws_url()
        if not ws_url:
            raise ConnectionError("Could not get WebSocket URL from Chrome")

        self._browser = await self._playwright.chromium.connect_over_cdp(ws_url)

        # Get the first context or create one
        browser = self._require_browser()
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()

        # Get the first page or create one
        pages = context.pages
        if pages:
            self._page = pages[0]
        else:
            self._page = await context.new_page()

        # Set up console message capture
        page = self._require_page()
        page.on("console", lambda msg: self._console_messages.append({
            "type": msg.type,
            "text": msg.text,
            "timestamp": datetime.now().isoformat()
        }))

        return self

    async def disconnect(self):
        """Disconnect from Chrome."""
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self) -> Page:
        """Create a new page/tab."""
        browser = self._require_browser()
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        self._page = await context.new_page()

        # Set up console capture for new page
        page = self._require_page()
        page.on("console", lambda msg: self._console_messages.append({
            "type": msg.type,
            "text": msg.text,
            "timestamp": datetime.now().isoformat()
        }))

        return page

    @property
    def page(self) -> Page | None:
        """Get the current page."""
        return self._page

    async def goto(self, url: str, wait_until: WaitUntilType = "domcontentloaded") -> dict:
        """Navigate to a URL."""
        page = self._require_page()
        await page.goto(url, wait_until=wait_until)
        return {"url": page.url, "title": await page.title()}

    async def screenshot(self, path: str | None = None, full_page: bool = False) -> str:
        """Take a screenshot. Returns the path to the saved file."""
        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"/workspaces/screenshot_{timestamp}.png"

        page = self._require_page()
        await page.screenshot(path=path, full_page=full_page)
        return path

    async def click(self, selector: str):
        """Click an element by selector."""
        page = self._require_page()
        await page.click(selector)

    async def fill(self, selector: str, text: str):
        """Fill a form field."""
        page = self._require_page()
        await page.fill(selector, text)

    async def type(self, selector: str, text: str, delay: int = 50):
        """Type text character by character (useful for simulating real typing)."""
        page = self._require_page()
        await page.type(selector, text, delay=delay)

    async def press(self, key: str):
        """Press a key (e.g., 'Enter', 'Tab', 'Escape')."""
        page = self._require_page()
        await page.keyboard.press(key)

    async def wait_for(self, selector: str, timeout: int = 30000):
        """Wait for an element to appear."""
        page = self._require_page()
        await page.wait_for_selector(selector, timeout=timeout)

    async def get_text(self, selector: str) -> str | None:
        """Get text content of an element."""
        page = self._require_page()
        return await page.text_content(selector)

    async def get_html(self, selector: str = "body") -> str:
        """Get HTML content of an element."""
        page = self._require_page()
        return await page.inner_html(selector)

    async def evaluate(self, expression: str):
        """Execute JavaScript in the page context."""
        page = self._require_page()
        return await page.evaluate(expression)

    async def get_console_logs(self, clear: bool = False) -> list:
        """Get captured console messages."""
        logs = self._console_messages.copy()
        if clear:
            self._console_messages.clear()
        return logs

    async def clear_console_logs(self):
        """Clear captured console messages."""
        self._console_messages.clear()

    async def get_page_info(self) -> dict:
        """Get current page information."""
        page = self._require_page()
        return {
            "url": page.url,
            "title": await page.title(),
            "viewport": page.viewport_size
        }

    async def scroll(self, x: int = 0, y: int = 0):
        """Scroll the page."""
        page = self._require_page()
        await page.evaluate(f"window.scrollTo({x}, {y})")

    async def scroll_to_bottom(self):
        """Scroll to the bottom of the page."""
        page = self._require_page()
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    async def get_all_links(self) -> list:
        """Get all links on the page."""
        page = self._require_page()
        return await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({href: a.href, text: a.textContent.trim()}))
        """)

    async def wait_for_network_idle(self, timeout: int = 30000):
        """Wait for network to be idle (no requests for 500ms)."""
        page = self._require_page()
        await page.wait_for_load_state("networkidle", timeout=timeout)


# CLI interface
async def main():
    """CLI interface for browser control."""
    import argparse

    parser = argparse.ArgumentParser(description="Browser control via CDP")
    parser.add_argument("--cdp", default=Browser.DEFAULT_CDP_URL, help="CDP endpoint URL")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # goto command
    goto_parser = subparsers.add_parser("goto", help="Navigate to URL")
    goto_parser.add_argument("url", help="URL to navigate to")

    # screenshot command
    ss_parser = subparsers.add_parser("screenshot", help="Take screenshot")
    ss_parser.add_argument("--output", "-o", help="Output path")
    ss_parser.add_argument("--full-page", "-f", action="store_true", help="Full page screenshot")

    # click command
    click_parser = subparsers.add_parser("click", help="Click an element")
    click_parser.add_argument("selector", help="CSS selector")

    # fill command
    fill_parser = subparsers.add_parser("fill", help="Fill a form field")
    fill_parser.add_argument("selector", help="CSS selector")
    fill_parser.add_argument("text", help="Text to fill")

    # console command
    subparsers.add_parser("console", help="Get console logs")

    # info command
    subparsers.add_parser("info", help="Get page info")

    # test command
    subparsers.add_parser("test", help="Test connection to Chrome")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        async with Browser(cdp_url=args.cdp) as browser:
            if args.command == "test":
                info = await browser.get_page_info()
                print("Connected to Chrome successfully!")
                print(f"Current page: {info['url']}")
                print(f"Title: {info['title']}")

            elif args.command == "goto":
                result = await browser.goto(args.url)
                print(f"Navigated to: {result['url']}")
                print(f"Title: {result['title']}")

            elif args.command == "screenshot":
                path = await browser.screenshot(args.output, args.full_page)
                print(f"Screenshot saved to: {path}")

            elif args.command == "click":
                await browser.click(args.selector)
                print(f"Clicked: {args.selector}")

            elif args.command == "fill":
                await browser.fill(args.selector, args.text)
                print(f"Filled {args.selector} with text")

            elif args.command == "console":
                logs = await browser.get_console_logs()
                print(json.dumps(logs, indent=2))

            elif args.command == "info":
                info = await browser.get_page_info()
                print(json.dumps(info, indent=2))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
