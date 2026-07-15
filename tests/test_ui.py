import json
import os
import socket
import subprocess
import time
from datetime import date, timedelta
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


def install_routes(page, history=None):
    history = history or {"snapshots": SAMPLE_STATE["snapshots"], "exchange_snapshots": SAMPLE_STATE["exchange_snapshots"], "runs": []}
    providers = {"providers": [{"provider": "binance", "label": "Binance"}]}
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
        expected = {"資産概要": "#overview", "保管場所": "#locations", "通貨推移": "#currency", "データ更新": "#update", "設定": "#settings"}
        for label, selector in expected.items():
            page.get_by_role("button", name=label, exact=True).click()
            assert page.locator(f"{selector}.active").is_visible()
            assert page.locator(".view.active").count() == 1
        browser.close()


def test_top_navigation_uses_distinct_box_tabs(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        tab = page.get_by_role("button", name="資産概要", exact=True)
        assert tab.evaluate("el => getComputedStyle(el).borderStyle") == "solid"
        assert tab.evaluate("el => getComputedStyle(el).backgroundColor") != "rgba(0, 0, 0, 0)"
        assert page.locator(".brand").evaluate("el => getComputedStyle(el).fontSize") != tab.evaluate("el => getComputedStyle(el).fontSize")
        browser.close()


def test_asset_history_period_only_filters_the_chart(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        snapshots = [{"wallet_id": "w1", "as_of_date": f"2026-07-{day:02d}", "captured_at": f"2026-07-{day:02d}T01:00:00Z", "total_usd": 100 + day} for day in range(1, 11)]
        install_routes(page, history={"snapshots": snapshots, "exchange_snapshots": [], "runs": []})
        page.goto(server_url)
        page.wait_for_selector("#trend .dot")
        assert page.locator("#assetPeriod").input_value() == "7"
        assert page.locator("#trend .dot").count() == 7
        page.locator("#assetPeriod").select_option("all")
        assert page.locator("#trend .dot").count() == 10
        chart_box = page.locator("#trend").locator("xpath=..").bounding_box()
        svg_box = page.locator("#trend .linechart").bounding_box()
        assert chart_box["y"] + chart_box["height"] - (svg_box["y"] + svg_box["height"]) <= 32
        allocation_box = page.locator("#allocation").locator("xpath=..").bounding_box()
        assert round(chart_box["height"]) == round(allocation_box["height"]) == 410
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


def test_currency_display_formats_usd_with_cents_and_jpy_without_decimals(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        assert page.locator("#total").inner_text() == "$229,203.59"
        assert page.locator("#total").evaluate("el => getComputedStyle(el).fontSize") == "33.6px"
        assert page.locator("#totalJpy").inner_text() == "円換算 ¥37,101,185"
        assert page.locator("#fxAt").count() == 0
        assert "取得日時：" not in page.locator(".hero").inner_text()
        assert "¥37,101,185." not in page.locator("body").inner_text()
        browser.close()


def test_steth_csv_to_snapshot_transition_renders_correct_daily_changes(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        def snapshot(date, amount, usd):
            return {
                "wallet_id": "wallet_lido", "wallet_name": "Lido2", "as_of_date": date,
                "captured_at": f"{date}T23:00:00Z", "fx_usdjpy": "162.22", "total_usd": str(usd),
                "tokens": [], "protocols": [{"panels": [{"assets": [{
                    "asset_symbol": "stETH", "amount_value": str(amount), "usd_value": str(usd)
                }]}]}]
            }
        history = {"snapshots": [
            snapshot("2026-07-12", 119.7089, 215879.37),
            snapshot("2026-07-13", 119.7160, 216857.19),
            snapshot("2026-07-14", 119.7232, 213565.91),
            snapshot("2026-07-15", 119.7305, 225053.90),
        ], "exchange_snapshots": [], "runs": []}
        install_routes(page, history=history)
        rewards = {"rows": [{
            "date": "2026-07-11T12:00:00Z", "type": "reward", "change": "0.00721365",
            "change_USD": "12.94", "apr": "2.20", "balance": "119.70885379510868"
        }]}
        rates = {"rows": [{"date": "2026-07-11", "rate": 162.04}, {"date": "2026-07-15", "rate": 162.22}]}
        page.route("**/api/lido-rewards", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(rewards)))
        page.route("**/api/usd-jpy-rates", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(rates)))
        page.goto(server_url)
        page.get_by_role("button", name="通貨推移", exact=True).click()
        page.wait_for_selector("#currencyTable tbody tr")
        assert page.locator("#currencyTotal").inner_text() == "119.7305 stETH"
        assert page.locator("#currencyDelta").inner_text() == "+0.00730 stETH"
        assert page.locator("#currencyTotalValue").bounding_box()["x"] > page.locator("#currencyTotal").bounding_box()["x"]
        assert page.locator("#currencyTable thead th").all_inner_texts() == ["Date", "Rate\n(stETH)", "Rate\n(USD/JPY)", "APR", "Reward\n(stETH)", "Reward\n(USD/JPY)", "Balance\n(stETH)", "Balance\n(USD/JPY)"]
        rows = page.locator("#currencyTable tbody tr")
        assert rows.count() == 5
        assert rows.nth(0).locator("td").nth(0).inner_text() == "2026-07-15"
        assert rows.nth(0).locator("td").nth(4).inner_text() == "0.00730"
        assert rows.nth(0).locator("td").nth(3).inner_text() == "2.23%"
        assert rows.nth(3).locator("td").nth(0).inner_text() == "2026-07-12"
        assert rows.nth(3).locator("td").nth(4).inner_text() == "0.00005"
        assert rows.nth(0).locator("td").nth(6).inner_text() == "119.7305"
        assert page.locator("#currencyChart .bar-axis-label").count() == 5
        axis_text = page.locator("#currencyChart .bar-axis-label").first.text_content()
        assert axis_text.startswith("$")
        assert "¥" in axis_text
        assert page.locator("#currencyChart .reward-line").count() == 1
        assert page.locator("#currencyChart .reward-line").evaluate("el => getComputedStyle(el).stroke") == page.locator("#trend .line").evaluate("el => getComputedStyle(el).stroke")
        assert "0.14" in page.locator("#currencyChart .reward-area").evaluate("el => getComputedStyle(el).fill")
        assert page.locator("#currencyTable .currency-page.active").inner_text() == "1"
        before = rows.all_inner_texts()
        page.locator("#currencyPeriod").select_option("30")
        assert page.locator("#currencyTable tbody tr").all_inner_texts() == before
        browser.close()


def test_currency_pagination_uses_numbered_pages_and_ellipses(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        last_date = date(2026, 7, 11)
        rewards = []
        for index in range(825):
            reward_date = last_date - timedelta(days=824 - index)
            rewards.append({"date": reward_date.isoformat(), "type": "reward", "change": "0.01", "change_USD": "10", "apr": "2.0", "balance": str(100 + index * .01)})
        page.route("**/api/lido-rewards", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"rows": rewards})))
        page.route("**/api/usd-jpy-rates", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"rows": [{"date": "2026-07-12", "rate": 160}]})))
        page.goto(server_url)
        page.get_by_role("button", name="通貨推移", exact=True).click()
        page.wait_for_selector("#currencyTable .pagination")
        assert page.locator("#currencyTable tbody tr").count() == 10
        labels = page.locator("#currencyTable .pagination > *").all_inner_texts()
        assert labels[0] == "‹"
        assert labels[1:4] == ["1", "2", "…"]
        assert labels[-1] == "›"
        page.get_by_role("button", name="2", exact=True).click()
        page.locator("#currencyTable .currency-next").click()
        assert page.locator("#currencyTable .pagination > *").all_inner_texts() == ["‹", "1", "2", "3", "…", "83", "›"]
        assert page.locator("#currencyTable .currency-page.active").inner_text() == "3"
        page.locator("#currencyTable .currency-next").click()
        assert page.locator("#currencyTable .currency-page.active").inner_text() == "4"
        assert page.locator("#currencyTable .pagination-ellipsis").count() == 2
        page.locator("#currencyPeriod").select_option("all")
        assert page.locator("#currencyChart .reward-dot").count() <= 24
        browser.close()


def test_change_display_includes_usd_and_jpy(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        history = {
            "snapshots": [
                {"wallet_id": "wallet_lido", "captured_at": "2026-07-11T10:00:00Z", "as_of_date": "2026-07-11", "total_usd": "200000.00"},
                *SAMPLE_STATE["snapshots"],
            ],
            "exchange_snapshots": [
                {"source_id": "src_binance", "captured_at": "2026-07-11T11:00:00Z", "as_of_date": "2026-07-11", "totals": {"net_asset_usd": "10000.00"}},
                *SAMPLE_STATE["exchange_snapshots"],
            ],
            "runs": [],
        }
        install_routes(page, history=history)
        page.goto(server_url)
        page.wait_for_selector("#assets tbody tr")
        assert page.locator("#change .comparison-amount").all_inner_texts() == ["+$19,203.59", "+¥3,108,485"]
        assert page.locator("#change .comparison-percent").inner_text() == "（9.14%）"
        amount_edges = page.locator("#change .comparison-amount").evaluate_all("els => els.map(el => Math.round(el.getBoundingClientRect().left))")
        assert len(set(amount_edges)) == 1
        metric_tops = page.locator("#change, #fxNote, #freshness").evaluate_all("els => els.map(el => Math.round(el.closest('.metric').getBoundingClientRect().top))")
        assert len(set(metric_tops)) == 1
        metric_heights = page.locator("#change, #fxNote, #freshness").evaluate_all("els => els.map(el => Math.round(el.closest('.metric').getBoundingClientRect().height))")
        assert len(set(metric_heights)) == 1
        label_box = page.locator(".comparison-metric > .label").bounding_box()
        value_box = page.locator("#change").bounding_box()
        assert value_box["y"] - (label_box["y"] + label_box["height"]) <= 2
        assert page.locator("#trend .chartlabel-sub").first.text_content().startswith("(¥")
        assert page.locator("#trend .axis").first.get_attribute("x1") == "76"
        assert page.locator("#trend .axis").first.get_attribute("x2") == "714"
        assert page.locator("#trend .axis").count() == 5
        assert page.locator("#trend .chartlabel").last.text_content() == "7/12"
        assert page.locator("#trend .chartlabel").last.get_attribute("text-anchor") == "end"
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


def test_exchange_provider_labels_are_user_facing_names(server_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        install_routes(page)
        page.goto(server_url)
        page.get_by_role("button", name="設定", exact=True).click()
        page.wait_for_selector("#sourceList tbody tr")
        assert page.locator("#provider option").first.inner_text() == "Binance"
        assert page.locator("#sourceList tbody tr").first.locator("td").nth(1).inner_text() == "Binance"
        page.get_by_role("button", name="データ更新", exact=True).click()
        assert page.locator("#updateSource option").first.inner_text() == "Binance (Binance)"
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
        for label in ["保管場所", "データ更新", "設定"]:
            page.get_by_role("button", name=label, exact=True).click()
            head_box = page.locator(".view.active > .page-head").bounding_box()
            content_box = page.locator(".view.active > .card").first.bounding_box()
            grid_edges.append((round(head_box["x"]), round(head_box["x"] + head_box["width"])))
            content_gaps.append(round(content_box["y"] - (head_box["y"] + head_box["height"])))
        assert len(set(grid_edges)) == 1
        assert len(set(content_gaps)) == 1
        page.get_by_role("button", name="資産概要", exact=True).click()
        assert page.locator("#overview > .page-head").count() == 0
        assert page.locator("#overview > .hero").bounding_box()["y"] > page.locator(".topbar").bounding_box()["height"]
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
