#!/usr/bin/env python3
"""
Clean up stale trade records.

Identifies trades marked as "open" (exit_time IS NULL) where the position
no longer exists at the broker, and marks them as closed with exit reason
"stale_cleanup".

This can happen when bracket orders close positions but the database isn't
updated (the bug we just fixed).
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.broker.alpaca_client import AlpacaClient
from src.storage.database import get_database
from config.settings import settings


def cleanup_stale_trades(auto_confirm=False):
    """Find and clean up stale trade records."""

    print("=" * 60)
    print("STALE TRADE CLEANUP")
    print("=" * 60)

    # Initialize
    client = AlpacaClient()
    db = get_database()

    # Get all open trades from database
    open_trades = db.get_open_trades()
    print(f"\nFound {len(open_trades)} open trades in database")

    if not open_trades:
        print("No open trades to clean up!")
        return

    # Get actual positions from broker
    broker_positions = {pos.symbol: pos for pos in client.get_positions()}
    print(f"Found {len(broker_positions)} actual positions at broker")
    print(f"Broker positions: {list(broker_positions.keys())}")

    # Normalize symbols for comparison (handle BTC/USD vs BTCUSD)
    def normalize_symbol(symbol):
        """Normalize symbol format for comparison."""
        return symbol.replace("/", "")

    # Normalize broker position symbols for comparison
    normalized_broker_symbols = {normalize_symbol(sym) for sym in broker_positions.keys()}

    # Find stale trades
    stale_trades = []
    valid_trades = []

    for trade in open_trades:
        if normalize_symbol(trade.symbol) not in normalized_broker_symbols:
            stale_trades.append(trade)
        else:
            valid_trades.append(trade)

    print(f"\n{len(stale_trades)} stale trades found (position doesn't exist at broker)")
    print(f"{len(valid_trades)} valid trades found (position exists at broker)")

    if not stale_trades:
        print("\nNo stale trades to clean up!")
        return

    # Show stale trades
    print("\nStale trades to clean up:")
    print("-" * 60)
    for trade in stale_trades:
        print(f"ID: {trade.id} | {trade.symbol} | {trade.direction} | "
              f"{trade.quantity} @ ${trade.entry_price:.2f} | "
              f"Entry: {trade.entry_time}")
    print("-" * 60)

    # Confirm cleanup
    if not auto_confirm:
        try:
            response = input(f"\nMark these {len(stale_trades)} trades as closed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("Cleanup cancelled.")
                return
        except EOFError:
            print("\nRunning in non-interactive mode. Use --yes flag to auto-confirm.")
            return
    else:
        print(f"\nAuto-confirming cleanup of {len(stale_trades)} trades...")

    # Clean up stale trades
    # We don't know the exact exit price, so use entry price (breakeven)
    cleaned = 0
    for trade in stale_trades:
        try:
            db.update_trade_exit(
                trade_id=trade.id,
                exit_time=datetime.now(),
                exit_price=trade.entry_price,  # Assume breakeven since we don't know
                pnl=0.0,  # Unknown P&L
                pnl_percent=0.0
            )
            cleaned += 1
            print(f"✓ Cleaned up trade {trade.id} ({trade.symbol})")
        except Exception as e:
            print(f"✗ Failed to clean up trade {trade.id}: {e}")

    print(f"\n{cleaned}/{len(stale_trades)} stale trades cleaned up")

    # Also clean up stale positions table
    positions = db.get_positions()
    stale_positions = [pos for pos in positions if normalize_symbol(pos['symbol']) not in normalized_broker_symbols]

    if stale_positions:
        print(f"\n{len(stale_positions)} stale positions in positions table")
        for pos in stale_positions:
            db.remove_position(pos['symbol'])
            print(f"✓ Removed stale position: {pos['symbol']}")

    print("\n" + "=" * 60)
    print("CLEANUP COMPLETE")
    print("=" * 60)

    # Show remaining valid trades
    remaining_open = db.get_open_trades()
    print(f"\nRemaining open trades: {len(remaining_open)}")
    for trade in remaining_open:
        print(f"  - {trade.symbol}: {trade.quantity} @ ${trade.entry_price:.2f}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up stale trade records")
    parser.add_argument("--yes", "-y", action="store_true",
                       help="Auto-confirm cleanup without prompting")
    args = parser.parse_args()

    cleanup_stale_trades(auto_confirm=args.yes)
