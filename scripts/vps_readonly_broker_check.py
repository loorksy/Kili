"""Read-only MetaApi check. Prints status lines only, never credentials or balances."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from nanobot.config.loader import load_config, set_config_path
from nanobot.market.broker import BrokerMarket
from nanobot.trading.accounts import TradingAccounts


def _pick(symbols: list[str], needle: str) -> str | None:
    upper = needle.upper()
    return next((symbol for symbol in symbols if upper in symbol.upper()), None)


async def _run(config_path: Path) -> None:
    set_config_path(config_path.resolve())
    config = load_config(config_path)
    accounts = TradingAccounts(config.tools.integrations)
    connection = accounts.connection()
    client = accounts.client(connection.account_id)
    state = await client.connection_state()
    account = await client.account()
    market = BrokerMarket(client)
    instruments = await market.instruments()
    names = [item.name for item in instruments]
    print(f"connection_status: {state.connection_status}")
    print(f"region: {state.region}")
    print(f"currency: {account.currency}")
    print(f"trade_allowed: {str(account.trade_allowed).lower()}")
    print(f"symbol_count: {len(names)}")
    for label, needle in (("btc", "BTC"), ("xau", "XAU"), ("eur", "EUR")):
        print(f"symbol_{label}: {_pick(names, needle) or 'absent'}")
    sample = _pick(names, "XAU") or _pick(names, "EUR") or _pick(names, "BTC") or (names[0] if names else None)
    if sample is None:
        raise SystemExit("No broker symbols")
    quote = await market.quote(sample, sample)
    candles = await market.candles(sample, sample, "H1", count=5)
    print(f"quote_symbol: {sample}")
    print(f"quote_ok: {quote.bid > 0 and quote.ask > 0}")
    print(f"candle_count: {len(candles)}")
    print("broker_order_sent: no")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/opt/kili/data/config.json"))
    args = parser.parse_args()
    asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
