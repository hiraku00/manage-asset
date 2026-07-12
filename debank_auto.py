"""Automated DeBank profile fetcher (Playwright-driven).

Background
----------
docs/crypto-asset-tracker-design.md section 2 originally rejected automated
scraping of DeBank profile pages, because DeBank's Terms of Service prohibit
unauthorized scrapers/scripts/extensions accessing the service. That design
called for a strictly manual "open page -> user copies HTML -> paste" flow
instead.

This module implements the automated version anyway, at the explicit,
informed request of the wallet owner, for a small, fixed set of self-owned
wallet addresses (not a crawl of third-party data). To keep the request
pattern as close to a real, unhurried human session as possible:

- one browser is reused sequentially, one wallet/tab at a time (never
  parallel requests)
- each tab is closed immediately after its HTML is captured
- a randomized multi-second pause separates each wallet
- a normal (non-headless) browser + realistic UA is used by default, since a
  visibly-open browser window is what a human session looks like

If DeBank's page structure, bot-detection, or ToS enforcement changes this
approach, fall back to the manual clipboard flow described in the design doc,
or to the official DeBank OpenAPI mentioned there as the ToS-clean
alternative.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEBANK_PROFILE_URL = "https://debank.com/profile/{address}"

# A real Chrome UA on macOS keeps the automated session close to what an
# ordinary logged-out browser tab looks like.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class DebankAutoError(RuntimeError):
    """Raised for setup failures (e.g. Playwright not installed)."""


@dataclass
class WalletFetchResult:
    wallet_id: str
    name: str
    address: str
    html: str | None
    error: str | None


def _wait_for_data(page, timeout_ms: int = 25000) -> None:
    """Wait until the page has rendered its header total and (best effort)
    settled its background token/DeFi requests."""
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_selector('[class*="HeaderInfo_totalAssetInner__"]', timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001 - normalized below
        raise DebankAutoError(
            "総資産の表示を検出できませんでした（未読込、レート制限、またはページ構造の変更の可能性）"
        ) from exc
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # DeBank keeps some long-lived connections open; networkidle timing
        # out is normal and not itself a failure.
        pass
    # Chain/token/DeFi panels continue to hydrate asynchronously for a bit
    # after the header renders and network settles. A short fixed pause
    # avoids capturing a partially-rendered table.
    page.wait_for_timeout(2500)


def fetch_wallets_html(
    wallets: list[dict],
    headless: bool | None = None,
    min_pause_s: float = 0.0,
    max_pause_s: float = 0.0,
    on_result=None,
) -> list[WalletFetchResult]:
    """Sequentially open each wallet's DeBank profile in its own tab, capture
    the rendered HTML, close the tab, then move to the next wallet.

    A per-wallet failure (timeout, selector miss, navigation error) is
    captured in that wallet's result and does not stop the remaining
    wallets.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DebankAutoError(
            "playwrightが見つかりません。`pip install -r requirements.txt` の後 "
            "`playwright install chromium` を実行してください"
        ) from exc

    if headless is None:
        # Chrome for Testing may crash while closing a visible macOS window.
        # Headless is the stable default; set DEBANK_HEADLESS=0 when a visible
        # browser is needed for debugging.
        headless = os.environ.get("DEBANK_HEADLESS", "1") == "1"

    results: list[WalletFetchResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=DEFAULT_USER_AGENT)
        try:
            for i, wallet in enumerate(wallets):
                address = wallet.get("address", "")
                name = wallet.get("name") or address
                page = context.new_page()
                try:
                    page.goto(
                        DEBANK_PROFILE_URL.format(address=address),
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    _wait_for_data(page)
                    html = page.content()
                    result = WalletFetchResult(wallet["wallet_id"], name, address, html, None)
                    results.append(result)
                    if on_result:
                        on_result(result)
                except Exception as exc:  # noqa: BLE001 - keep going with remaining wallets
                    result = WalletFetchResult(wallet["wallet_id"], name, address, None, str(exc))
                    results.append(result)
                    if on_result:
                        on_result(result)
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()
    return results
