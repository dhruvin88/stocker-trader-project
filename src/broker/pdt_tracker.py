from datetime import datetime, date, timedelta
from typing import Optional

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.storage.database import get_database
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class PDTTracker:
    """
    Tracks Pattern Day Trader (PDT) rule compliance.

    PDT Rule: Accounts under $25k are limited to 3 day trades per 5 rolling business days.
    A day trade is when you buy and sell (or sell and buy) the same security on the same day.

    Strategy: Reserve day trades for high-conviction signals above a threshold.
    """

    def __init__(self, client: Optional[AlpacaClient] = None):
        self.client = client or get_alpaca_client()
        self.db = get_database()
        self.max_day_trades = settings.MAX_DAY_TRADES
        self.rolling_days = settings.PDT_ROLLING_DAYS
        self.high_conviction_threshold = settings.HIGH_CONVICTION_THRESHOLD

    def get_day_trades_used(self) -> int:
        """Get the number of day trades used in the rolling window."""
        return self.db.get_day_trades_in_window(self.rolling_days)

    def get_day_trades_remaining(self) -> int:
        """Get the number of day trades remaining."""
        used = self.get_day_trades_used()
        return max(0, self.max_day_trades - used)

    def can_day_trade(self, confidence: float = 0.0) -> bool:
        """
        Check if a day trade is allowed.

        Args:
            confidence: Signal confidence score (0-1). Day trades are reserved
                       for signals above the high_conviction_threshold.

        Returns:
            True if day trade is allowed, False otherwise.
        """
        remaining = self.get_day_trades_remaining()

        if remaining <= 0:
            logger.warning("No day trades remaining in rolling window")
            return False

        if confidence < self.high_conviction_threshold:
            logger.info(
                f"Confidence {confidence:.2f} below threshold {self.high_conviction_threshold}. "
                f"Reserving day trades for high-conviction signals. "
                f"({remaining} day trades remaining)"
            )
            return False

        logger.info(
            f"Day trade allowed. Confidence: {confidence:.2f}, "
            f"Remaining after this trade: {remaining - 1}"
        )
        return True

    def record_day_trade(self, symbol: str) -> None:
        """
        Record a day trade.

        Args:
            symbol: The symbol that was day traded.
        """
        self.db.record_day_trade(symbol, date.today())
        logger.info(
            f"Recorded day trade for {symbol}. "
            f"Remaining: {self.get_day_trades_remaining()}"
        )

    def is_position_from_today(self, symbol: str) -> bool:
        """
        Check if a position was opened today (would be a day trade if closed).

        Args:
            symbol: Stock symbol to check.

        Returns:
            True if selling this position today would count as a day trade.
        """
        position = self.db.get_position(symbol)
        if position is None:
            return False

        entry_time = datetime.fromisoformat(position["entry_time"])
        return entry_time.date() == date.today()

    def should_hold_overnight(self, symbol: str, confidence: float = 0.0) -> bool:
        """
        Determine if a position should be held overnight due to PDT rules.

        Args:
            symbol: Stock symbol.
            confidence: Exit signal confidence.

        Returns:
            True if position should be held overnight, False if can close.
        """
        if not self.is_position_from_today(symbol):
            return False

        if not self.can_day_trade(confidence):
            logger.info(
                f"Holding {symbol} overnight due to PDT rules. "
                f"Would be day trade #{self.get_day_trades_used() + 1}"
            )
            return True

        return False

    def get_next_day_trade_available(self) -> Optional[date]:
        """
        Get the date when the next day trade will become available.

        Returns:
            Date when a day trade will free up, or None if trades available now.
        """
        if self.get_day_trades_remaining() > 0:
            return None

        trade_dates = self.db.get_day_trade_dates(self.rolling_days)
        if not trade_dates:
            return None

        oldest_trade = min(trade_dates)
        return oldest_trade + timedelta(days=self.rolling_days + 1)

    def get_pdt_status(self) -> dict:
        """Get a summary of PDT status."""
        used = self.get_day_trades_used()
        remaining = self.get_day_trades_remaining()
        next_available = self.get_next_day_trade_available()

        return {
            "day_trades_used": used,
            "day_trades_remaining": remaining,
            "max_day_trades": self.max_day_trades,
            "rolling_window_days": self.rolling_days,
            "high_conviction_threshold": self.high_conviction_threshold,
            "next_day_trade_available": next_available.isoformat() if next_available else None,
            "trade_dates": [d.isoformat() for d in self.db.get_day_trade_dates()]
        }

    def check_account_pdt_status(self) -> dict:
        """Check PDT status from the broker account."""
        account = self.client.get_account()
        return {
            "is_pattern_day_trader": account.pattern_day_trader,
            "broker_day_trade_count": account.day_trade_count,
            "equity": account.equity,
            "above_pdt_threshold": account.equity >= 25000
        }
