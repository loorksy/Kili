"""Exercise watcher pause, resume, and owner cancel against the running gateway.

This does not place a broker order. It writes one test responsibility and one
watcher, then lets the gateway scheduler observe it.
"""
from __future__ import annotations

import argparse
import subprocess
import time
from decimal import Decimal
from pathlib import Path

from nanobot.config.loader import load_config, set_config_path
from nanobot.market.watch_control import cancel_owned_watcher
from nanobot.market.watchers import MarketWatcher, open_watcher_records
from nanobot.session.responsibilities import ResponsibilityStore


def _journal_count(unit: str, since: str) -> int:
    completed = subprocess.run(
        ["journalctl", "-u", unit, "--since", since, "--no-pager", "-o", "cat"],
        check=False, capture_output=True, text=True,
    )
    return completed.stdout.count("StaleExecutionError")


def _pause(store: ResponsibilityStore, responsibility_id: str):
    record = store.get(responsibility_id)
    record.state = "PAUSED"
    record.next_wake_ms = None
    return store.control_update(record)


def _resume(store: ResponsibilityStore, responsibility_id: str):
    record = store.get(responsibility_id)
    record.state = "SCHEDULED"
    record.recovery_required = False
    record.waiting_for = None
    record.next_wake_ms = int(time.time() * 1000)
    return store.control_update(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/opt/kili/data/config.json"))
    parser.add_argument("--unit", default="kili.service")
    parser.add_argument("--wait-seconds", type=int, default=30)
    args = parser.parse_args()
    set_config_path(args.config.resolve())
    config = load_config(args.config)
    workspace = Path(config.agents.defaults.workspace).expanduser().resolve()
    account_id = next(iter(config.tools.integrations.broker_accounts()))
    store = ResponsibilityStore(workspace)
    parent = store.create(
        objective="Watcher lifecycle acceptance", session_key="websocket:vps-accept",
        channel="websocket", chat_id="vps-accept",
    )
    records = open_watcher_records(workspace)
    watcher = MarketWatcher(
        provider="metaapi", account_id=account_id, id="watch_vps_accept",
        responsibility_id=parent.id, provider_instrument="EURUSD", canonical_instrument="EURUSD",
        condition="above", threshold=Decimal("1"), interval_ms=5000, next_check_ms=int(time.time() * 1000),
    )
    records.create(watcher)
    since = time.strftime("%Y-%m-%d %H:%M:%S")
    deadline = time.time() + args.wait_seconds
    observed = False
    while time.time() < deadline:
        current = records.get(watcher.id)
        if current.last_price is not None or current.failures or current.lifecycle != "ACTIVE":
            observed = True
            break
        time.sleep(2)
    print(f"scheduler_observed: {str(observed).lower()}")
    _pause(store, parent.id)
    time.sleep(16)
    paused = records.get(watcher.id)
    print(f"paused_lifecycle: {paused.lifecycle}")
    _resume(store, parent.id)
    time.sleep(8)
    resumed = records.get(watcher.id)
    print(f"resumed_lifecycle: {resumed.lifecycle}")
    _pause(store, parent.id)
    cancelled = cancel_owned_watcher(workspace, "websocket:vps-accept", watcher.id, records=records, responsibilities=store)
    print(f"owner_cancel: {cancelled['lifecycle']}")
    print(f"stale_execution_error_count: {_journal_count(args.unit, since)}")
    print("broker_order_sent: no")


if __name__ == "__main__":
    main()
