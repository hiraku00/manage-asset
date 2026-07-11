#!/usr/bin/env python3
"""Local DeBank HTML snapshot importer."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
WALLETS_FILE = DATA / "wallets.json"
SNAPSHOTS_FILE = DATA / "snapshots.jsonl"
RUNS_FILE = DATA / "runs.jsonl"
STATIC = ROOT / "static"
LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def append_jsonl(path: Path, record: dict) -> None:
    with LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def load_wallets() -> list[dict]:
    if not WALLETS_FILE.exists():
        return []
    return json.loads(WALLETS_FILE.read_text(encoding="utf-8")).get("wallets", [])


def save_wallets(wallets: list[dict]) -> None:
    WALLETS_FILE.write_text(
        json.dumps({"schema_version": 1, "wallets": wallets}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_address(value: str) -> str:
    value = (value or "").strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", value):
        raise ValueError("EVMアドレス形式ではありません")
    return value


def parse_money(text: str) -> str | None:
    """Return a display-safe numeric string, preserving small-value markers."""
    text = " ".join((text or "").split())
    match = re.search(r"(?:\$|USD\s*)([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not match:
        return None
    return match.group(1).replace(",", "")


def parse_quantity(text: str) -> str | None:
    """Parse plain decimal quantities; return None for compact subscript notation."""
    text = " ".join((text or "").split()).replace(",", "")
    if not text or any(ch in text for ch in "₀₁₂₃₄₅₆₇₈₉"):
        return None
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*[A-Za-z0-9]*", text)
    if not match:
        return None
    return match.group(1)


def parse_protocol_assets(panel) -> list[dict]:
    assets = []
    for row in panel.select('[class*="table_contentRow__"]'):
        cells = row.find_all("div", recursive=False)
        if len(cells) < 4:
            continue
        asset_symbol = " ".join(cells[0].get_text(" ", strip=True).split())
        balance_token = " ".join(cells[1].get_text(" ", strip=True).split())
        amount_text = " ".join(cells[2].get_text(" ", strip=True).split())
        usd_text = " ".join(cells[3].get_text(" ", strip=True).split())
        amount_match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Za-z0-9]+)?", amount_text.replace(",", ""))
        assets.append({
            "asset_symbol": asset_symbol or None,
            "balance_token_symbol": balance_token or None,
            "amount_display": amount_text or None,
            "amount_value": amount_match.group(1).replace(",", "") if amount_match else parse_quantity(amount_text),
            "amount_unit_symbol": amount_match.group(2) if amount_match and amount_match.group(2) else (balance_token or None),
            "usd_value_display": usd_text or None,
            "usd_value": parse_money(usd_text),
        })
    return assets


def parse_html(html: str) -> dict:
    if not html or len(html) > 5_000_000:
        raise ValueError("HTMLが空、またはサイズ上限を超えています")
    soup = BeautifulSoup(html, "html.parser")

    address_node = soup.select_one('[class*="HeaderInfo_address__"]')
    address_match = re.search(r"0x[0-9a-fA-F]{40}", address_node.get_text() if address_node else "")
    if not address_match:
        address_match = re.search(r"0x[0-9a-fA-F]{40}", html)
    if not address_match:
        raise ValueError("HTMLからウォレットアドレスを検出できません")
    address = normalize_address(address_match.group(0))

    total_node = soup.select_one('[class*="HeaderInfo_totalAssetInner__"]')
    total_text = ""
    if total_node:
        # change percent is nested in this element; use the first dollar value.
        total_text = total_node.get_text(" ", strip=True)
    total_usd = parse_money(total_text)
    if total_usd is None:
        raise ValueError("HTMLから総資産額を検出できません")

    change_node = soup.select_one('[class*="HeaderInfo_changePercent__"]')
    change = change_node.get_text(" ", strip=True) if change_node else None

    chains = []
    for node in soup.select('[class*="AssetsOnChain_item__"][data-chain]'):
        name_node = node.select_one('[class*="AssetsOnChain_chainName__"]')
        value_node = node.select_one('[class*="AssetsOnChain_usdValue__"]')
        if name_node and value_node:
            chains.append({
                "chain_id": node.get("data-chain"),
                "name": name_node.get_text(" ", strip=True),
                "usd_value": parse_money(value_node.get_text(" ", strip=True)),
            })

    headers = [x.get_text(" ", strip=True) for x in soup.select(".db-table-headerItem")]
    header_index = {name.lower(): i for i, name in enumerate(headers)}
    tokens = []
    for row in soup.select(".db-table-row"):
        cells = [c.get_text(" ", strip=True) for c in row.select(":scope > .db-table-cell")]
        if not cells or len(cells) < len(headers):
            continue
        link = row.select_one('a[href*="/token/"]')
        token_id = link.get("href") if link else None
        tokens.append({
            "symbol": cells[header_index.get("token", 0)],
            "price_display": cells[header_index.get("price", 1)] if len(cells) > 1 else None,
            "amount_display": cells[header_index.get("amount", 2)] if len(cells) > 2 else None,
            "usd_value_display": cells[header_index.get("usd value", 3)] if len(cells) > 3 else None,
            "asset_ref": token_id,
        })

    protocols = []
    for project in soup.select('div[class*="Project_project__"]'):
        name_node = project.select_one('[class*="ProjectTitle_name__"]')
        value_node = project.select_one(".projectTitle-number")
        if not name_node:
            continue
        panels = []
        for panel in project.select('[class*="Panel_container__"]'):
            panels.append({
                "display_text": " ".join(panel.get_text(" ", strip=True).split()),
                "assets": parse_protocol_assets(panel),
            })
        protocols.append({
            "name": name_node.get_text(" ", strip=True),
            "usd_value": parse_money(value_node.get_text(" ", strip=True)) if value_node else None,
            "panels": panels,
        })

    return {
        "address": address,
        "total_usd": total_usd,
        "change_display": change,
        "chains": chains,
        "tokens": tokens,
        "protocols": protocols,
        "parser_version": "1.0.0",
    }


def latest_snapshots() -> list[dict]:
    records = read_jsonl(SNAPSHOTS_FILE)
    latest = {}
    for record in records:
        latest[record["wallet_id"]] = record
    return list(latest.values())


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            wallets = load_wallets()
            snapshots = latest_snapshots()
            return json_response(self, {"wallets": wallets, "snapshots": snapshots})
        if path == "/api/history":
            return json_response(self, {"runs": read_jsonl(RUNS_FILE), "snapshots": read_jsonl(SNAPSHOTS_FILE)})
        if path == "/":
            target = STATIC / "index.html"
        else:
            target = STATIC / path.lstrip("/")
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        if length > 6_000_000:
            return json_response(self, {"error": "リクエストサイズが大きすぎます"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/wallets":
                wallets = body.get("wallets", [])
                for wallet in wallets:
                    wallet["address"] = normalize_address(wallet.get("address", ""))
                    wallet.setdefault("wallet_id", "wallet_" + uuid.uuid4().hex[:12])
                    wallet.setdefault("name", wallet["address"][:10])
                    wallet.setdefault("enabled", True)
                save_wallets(wallets)
                return json_response(self, {"wallets": wallets})
            if path == "/api/import":
                parsed = parse_html(body.get("html", ""))
                wallet_id = body.get("wallet_id")
                as_of_date = body.get("as_of_date") or date.today().isoformat()
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of_date):
                    raise ValueError("基準日はYYYY-MM-DDで指定してください")
                date.fromisoformat(as_of_date)
                wallet = next((x for x in load_wallets() if x.get("wallet_id") == wallet_id), None)
                if not wallet:
                    raise ValueError("対象ウォレットが登録されていません")
                if normalize_address(wallet["address"]) != parsed["address"]:
                    raise ValueError("HTMLのアドレスと選択したウォレットが一致しません")
                run_id = body.get("run_id") or "run_" + uuid.uuid4().hex[:12]
                captured_at = now_iso()
                record = {
                    "schema_version": 1,
                    "record_type": "wallet_snapshot",
                    "run_id": run_id,
                    "wallet_id": wallet_id,
                    "wallet_name": wallet.get("name"),
                    "address": parsed["address"],
                    "as_of_date": as_of_date,
                    "captured_at": captured_at,
                    "source": "debank_html_clipboard",
                    "input_sha256": hashlib.sha256(body.get("html", "").encode()).hexdigest(),
                    **parsed,
                }
                # The UI first asks for a parse preview.  Never persist data
                # until the user explicitly confirms the snapshot.
                if body.get("preview"):
                    return json_response(self, {"record": record, "run_id": run_id, "preview": True})
                append_jsonl(SNAPSHOTS_FILE, record)
                append_jsonl(RUNS_FILE, {
                    "schema_version": 1,
                    "record_type": "import_event",
                    "run_id": run_id,
                    "wallet_id": wallet_id,
                    "wallet_name": wallet.get("name"),
                    "as_of_date": as_of_date,
                    "captured_at": captured_at,
                    "status": "success",
                })
                return json_response(self, {"record": record, "run_id": run_id})
            raise ValueError("未対応のAPIです")
        except Exception as exc:
            return json_response(self, {"error": str(exc)}, 400)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8877), Handler)
    print("Asset tracker: http://127.0.0.1:8877")
    server.serve_forever()


if __name__ == "__main__":
    main()
