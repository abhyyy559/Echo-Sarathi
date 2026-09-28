"""Playwright screenshots for the Review-II deck. Usage: python scripts/review2_shots.py"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "review-2-assets"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://localhost:3000"


def shot(page, name: str) -> None:
    path = OUT / name
    page.screenshot(path=str(path))
    print(f"saved {path.name}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill('input[type="email"]', "demo@example.com")
        page.fill('input[type="password"]', "demo1234")
        page.click('button[type="submit"]')
        page.wait_for_url(BASE + "/", timeout=15000)
        page.wait_for_timeout(1500)

        page.goto(f"{BASE}/", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot(page, "01-overview.png")

        page.goto(f"{BASE}/agents", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot(page, "02-agents.png")

        page.goto(f"{BASE}/campaigns/2", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shot(page, "03-campaign-contacts.png")

        page.goto(f"{BASE}/playground", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shot(page, "04-playground.png")

        page.goto(f"{BASE}/calls/15", wait_until="networkidle")
        page.wait_for_timeout(1500)
        shot(page, "05-call-detail.png")

        page.goto(f"{BASE}/calls", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot(page, "06-call-history.png")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
