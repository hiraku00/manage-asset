#!/usr/bin/env python3
"""Run the configured wallet and exchange updates once.

This command is intended to be invoked by macOS launchd.  It does not start
the web server and therefore can run independently of the dashboard UI.
"""

from __future__ import annotations

import fcntl
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
from debank_auto import fetch_wallets_html  # noqa: E402


LOCK_FILE = app.DATA / "daily-update.lock"
LOG = logging.getLogger("manage_asset.daily_update")


def acquire_lock():
    LOCK_FILE.parent.mkdir(exist_ok=True)
    lock = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def update_wallets(run_id: str, as_of_date: str) -> tuple[int, int]:
    wallets = [wallet for wallet in app.load_wallets() if wallet.get("enabled", True)]
    if not wallets:
        LOG.info("No enabled wallets configured")
        return 0, 0

    success = 0
    failed = 0
    fx_rate = app.usd_jpy_rate()

    def handle(fetched) -> None:
        nonlocal success, failed
        if fetched.html is None:
            failed += 1
            app.append_jsonl(app.RUNS_FILE, {
                "schema_version": 1,
                "record_type": "import_event",
                "run_id": run_id,
                "wallet_id": fetched.wallet_id,
                "wallet_name": fetched.name,
                "as_of_date": as_of_date,
                "captured_at": app.now_iso(),
                "status": "error",
                "error": fetched.error,
                "trigger": "launchd",
            })
            LOG.error("Wallet %s failed: %s", fetched.name, fetched.error)
            return

        wallet = next(wallet for wallet in wallets if wallet["wallet_id"] == fetched.wallet_id)
        try:
            record = app.build_snapshot_record(
                wallet,
                fetched.html,
                as_of_date,
                run_id=run_id,
                source="debank_auto_browser",
                fx_usdjpy=fx_rate,
            )
            app.append_jsonl(app.SNAPSHOTS_FILE, record)
            app.append_jsonl(app.RUNS_FILE, {
                "schema_version": 1,
                "record_type": "import_event",
                "run_id": run_id,
                "wallet_id": fetched.wallet_id,
                "wallet_name": fetched.name,
                "as_of_date": as_of_date,
                "captured_at": record["captured_at"],
                "status": "success",
                "trigger": "launchd",
            })
            success += 1
            LOG.info("Wallet %s updated", fetched.name)
        except Exception as exc:  # noqa: BLE001 - continue with other wallets
            failed += 1
            LOG.exception("Wallet %s could not be saved: %s", fetched.name, exc)

    fetch_wallets_html(wallets, on_result=handle)
    return success, failed


def update_exchanges(run_id: str) -> tuple[int, int]:
    sources = [
        source for source in app.load_sources()
        if source.get("enabled", True) and source.get("credential_ref")
    ]
    success = 0
    failed = 0
    for source in sources:
        try:
            snapshot = app.build_exchange_snapshot(source)
            snapshot["run_id"] = run_id
            app.append_jsonl(app.PORTFOLIO_SNAPSHOTS_FILE, snapshot)
            app.append_jsonl(app.RUNS_FILE, {
                "schema_version": 2,
                "record_type": "exchange_import_event",
                "run_id": run_id,
                "source_id": source["source_id"],
                "provider": source["provider"],
                "captured_at": snapshot["captured_at"],
                "status": "success",
                "trigger": "launchd",
            })
            success += 1
            LOG.info("Exchange %s updated", source.get("display_name"))
        except Exception as exc:  # noqa: BLE001 - continue with other sources
            failed += 1
            LOG.exception("Exchange %s failed: %s", source.get("display_name"), exc)
    return success, failed


def main() -> int:
    # launchd may start a calendar job after a sleeping Mac wakes up.  The
    # requested policy is to skip that missed 07:00 run rather than catch up.
    if datetime.now().hour != 7:
        LOG.info("Outside the 07:00 run window; skipping")
        return 0

    lock = acquire_lock()
    if lock is None:
        LOG.warning("Daily update is already running; skipping this run")
        return 0
    try:
        run_id = "run_" + uuid.uuid4().hex[:12]
        as_of_date = date.today().isoformat()
        wallet_success, wallet_failed = update_wallets(run_id, as_of_date)
        exchange_success, exchange_failed = update_exchanges(run_id)
        total_failed = wallet_failed + exchange_failed
        LOG.info(
            "Daily update finished: wallets=%d/%d, exchanges=%d/%d",
            wallet_success, wallet_success + wallet_failed,
            exchange_success, exchange_success + exchange_failed,
        )
        return 1 if total_failed else 0
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
