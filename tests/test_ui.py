import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = free_port()
    environment = {**os.environ, "PORT": str(port)}
    process = subprocess.Popen(["python3", "app.py"], cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                break
        except OSError:
            time.sleep(.1)
    else:
        process.terminate()
        raise RuntimeError("test server did not start")
    yield url
    process.terminate()
    process.wait(timeout=5)


SAMPLE_STATE = {
    "wallets": [{"wallet_id": "wallet_lido", "name": "Lido2", "address": "0x1234567890123456789012345678901234567890", "enabled": True}],
    "sources": [{"source_id": "src_binance", "display_name": "Binance", "provider": "binance", "credential_configured": True}],
    "snapshots": [{"wallet_id": "wallet_lido", "wallet_name": "Lido2", "address": "0x1234567890123456789012345678901234567890", "captured_at": "2026-07-12T10:00:00Z", "as_of_date": "2026-07-12", "total_usd": "216232.72", "fx_usdjpy": "161.87", "tokens": [{"symbol": "ETH", "amount_value": "0.02", "usd_value_display": "36.14"}], "protocols": [{"name": "Lido", "panels": [{"assets": [{"asset_symbol": "stETH", "amount_value": "119.7089", "usd_value": "216196.58"}]}]}]}],
    "exchange_snapshots": [{"source_id": "src_binance", "account_name": "Binance", "captured_at": "2026-07-12T11:00:00Z", "as_of_date": "2026-07-12", "totals": {"net_asset_usd": "12970.87"}, "positions": [{"symbol": "BTC", "net_quantity": "0.20271302", "usd_value": "12970.87"}], "quality": {"warnings": []}}],
}


def install_routes(page):
    history = {"snapshots": SAMPLE_STATE["snapshots"], "exchange_snapshots": SAMPLE_STATE["exchange_snapshots"], "runs": []}
    providers = {"providers": [{"provider": "binance", "label": "Binance Spot"}]}
    page.route("**/api/state", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(SAMPLE_STATE)))
    page.route("**/api/history", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(history)))
    page.route("**/api/providers", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(providers)))


def test_four_views_are_isolated_and_render_expected_content(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        expected = {"資産概要": "#overview", "保管場所": "#locations", "データ更新": "#update", "設定": "#settings"}
        for label, selector in expected.items():
            page.get_by_role("button", name=label, exact=True).click()
            assert page.locator(f"{selector}.active").is_visible()
            assert page.locator(".view.active").count() == 1
        browser.close()


def test_asset_table_contains_one_unit_price_column_and_defi_assets(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        assert page.locator("#assets thead th", has_text="単価").count() == 1
        assert page.locator("#assets tbody").get_by_text("stETH", exact=True).count() == 1
        assert page.locator("#assets tbody tr").first.locator("td").count() == 6
        browser.close()


def test_update_cards_have_equal_steps_and_no_initial_result_placeholder(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.get_by_role("button", name="データ更新", exact=True).click()
        boxes = page.locator(".update-steps li").evaluate_all("els => els.map(e => ({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))")
        assert len(boxes) == 4
        assert len({round(box["width"]) for box in boxes}) == 1
        assert len({round(box["height"]) for box in boxes}) == 1
        assert page.get_by_role("heading", name="個別更新").count() == 2
        colors = page.locator("#updateExchange, #updateWallet, #updateAllExchanges, #updateAllWallets").evaluate_all("els => els.map(e => getComputedStyle(e).backgroundColor)")
        assert len(set(colors)) == 1
        assert not page.locator("#importStatus").is_visible()
        assert "更新結果がここに表示されます" not in page.locator("body").inner_text()
        browser.close()


def test_exchange_bulk_update_uses_same_progress_cards_and_elapsed_seconds(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        poll_count = {"value": 0}

        def exchange_job(route):
            if route.request.method == "POST":
                route.fulfill(status=202, content_type="application/json", body=json.dumps({"run_id": "run_exchange_test", "total": 2, "status": "running"}))
                return
            poll_count["value"] += 1
            if poll_count["value"] == 1:
                payload = {"run_id": "run_exchange_test", "status": "running", "total": 2, "completed": 1, "success": 1, "failed": 0, "elapsed_seconds": 3, "results": []}
            else:
                payload = {"run_id": "run_exchange_test", "status": "completed", "total": 2, "completed": 2, "success": 1, "failed": 1, "elapsed_seconds": 5, "results": [{"name": "Binance", "status": "success"}, {"name": "Bybit", "status": "error", "error": "接続エラー"}]}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        page.route("**/api/sources/auto-import**", exchange_job)
        page.goto(server_url)
        page.get_by_role("button", name="データ更新", exact=True).click()
        page.get_by_role("button", name="全取引所を更新", exact=True).click()
        page.wait_for_function("document.querySelector('#exchangeStatus')?.textContent.includes('5秒')")
        assert page.locator("#exchangeStatus .progress-status").count() == 0
        assert "成功 1件 / 失敗 1件" in page.locator("#exchangeStatus").inner_text()
        assert "5秒" in page.locator("#exchangeStatus").inner_text()
        browser.close()


def test_all_views_share_the_same_content_grid_and_location_detail_padding(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        grid_edges = []
        content_gaps = []
        for label in ["資産概要", "保管場所", "データ更新", "設定"]:
            page.get_by_role("button", name=label, exact=True).click()
            head_box = page.locator(".view.active > .page-head").bounding_box()
            content_box = page.locator(".view.active > .card").first.bounding_box()
            grid_edges.append((round(head_box["x"]), round(head_box["x"] + head_box["width"])))
            content_gaps.append(round(content_box["y"] - (head_box["y"] + head_box["height"])))
        assert len(set(grid_edges)) == 1
        assert len(set(content_gaps)) == 1
        page.get_by_role("button", name="保管場所", exact=True).click()
        page.locator(".location-open").first.click()
        detail_box = page.locator(".location-detail").bounding_box()
        table_box = page.locator(".location-detail table").bounding_box()
        assert table_box["x"] - detail_box["x"] >= 20
        assert detail_box["x"] + detail_box["width"] - (table_box["x"] + table_box["width"]) >= 20
        browser.close()


@pytest.mark.parametrize("width", [1440, 768, 375])
def test_no_body_horizontal_overflow_across_viewports(server_url, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        for label in ["資産概要", "保管場所", "データ更新", "設定"]:
            page.get_by_role("button", name=label, exact=True).click()
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"{label} overflowed by {overflow}px at {width}px"
        browser.close()
