#!/usr/bin/env python3
"""Run the configured wallet and exchange updates once.

This command is intended to be invoked by macOS launchd.  It does not start
the web server and therefore can run independently of the dashboard UI.
"""

from __future__ import annotations

import fcntl
import json
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
STATE_FILE = app.DATA / "daily-update-state.json"
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


def update_wallets(run_id: str, as_of_date: str, wallet_ids: set[str] | None = None) -> tuple[int, int, list[str]]:
    wallets = [wallet for wallet in app.load_wallets() if wallet.get("enabled", True)]
    if wallet_ids is not None:
        wallets = [wallet for wallet in wallets if wallet.get("wallet_id") in wallet_ids]
    if not wallets:
        LOG.info("No enabled wallets configured")
        return 0, 0, []

    success = 0
    failed = 0
    failed_ids: list[str] = []
    fx_rate = app.usd_jpy_rate()

    def handle(fetched) -> None:
        nonlocal success, failed
        if fetched.html is None:
            failed += 1
            failed_ids.append(fetched.wallet_id)
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
            failed_ids.append(fetched.wallet_id)
            LOG.exception("Wallet %s could not be saved: %s", fetched.name, exc)

    fetch_wallets_html(wallets, on_result=handle)
    return success, failed, failed_ids


def update_exchanges(run_id: str, source_ids: set[str] | None = None) -> tuple[int, int, list[str]]:
    sources = [
        source for source in app.load_sources()
        if source.get("enabled", True) and source.get("credential_ref")
    ]
    if source_ids is not None:
        sources = [source for source in sources if source.get("source_id") in source_ids]
    success = 0
    failed = 0
    failed_ids: list[str] = []
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
            failed_ids.append(source["source_id"])
            LOG.exception("Exchange %s failed: %s", source.get("display_name"), exc)
    return success, failed, failed_ids


def load_retry_state(as_of_date: str) -> tuple[set[str] | None, set[str] | None]:
    """Return failed targets from today's earlier attempt, if any.

    A missing or stale state means this is the first attempt of the day and
    all enabled targets should be fetched.
    """
    if not STATE_FILE.exists():
        return None, None
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LOG.warning("Could not read retry state; starting a full update")
        return None, None
    if state.get("as_of_date") != as_of_date:
        return None, None
    return set(state.get("failed_wallet_ids", [])), set(state.get("failed_source_ids", []))


def save_retry_state(as_of_date: str, failed_wallet_ids: list[str], failed_source_ids: list[str]) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "as_of_date": as_of_date,
                "failed_wallet_ids": failed_wallet_ids,
                "failed_source_ids": failed_source_ids,
                "updated_at": app.now_iso(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


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
        retry_wallet_ids, retry_source_ids = load_retry_state(as_of_date)
        attempt_label = "initial" if retry_wallet_ids is None else "retry"
        wallet_success, wallet_failed, failed_wallet_ids = update_wallets(
            run_id, as_of_date, retry_wallet_ids
        )
        exchange_success, exchange_failed, failed_source_ids = update_exchanges(
            run_id, retry_source_ids
        )
        save_retry_state(as_of_date, failed_wallet_ids, failed_source_ids)
        total_failed = wallet_failed + exchange_failed
        LOG.info(
            "Daily update finished (%s): wallets=%d/%d, exchanges=%d/%d, retry_targets=%d",
            attempt_label,
            wallet_success, wallet_success + wallet_failed,
            exchange_success, exchange_success + exchange_failed,
            total_failed,
        )
        return 1 if total_failed else 0
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
