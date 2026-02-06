from datetime import date, timedelta
from typing import Optional

from src.storage.database import get_database
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class WashSaleTracker:
    """
    Tracks wash sale rule compliance.

    Wash Sale Rule: When you sell a security at a loss and buy a substantially
    identical security within 30 days before or after the sale, the loss is
    disallowed for tax purposes.

    This tracker prevents re-entering positions within 30 days of selling at a loss.
    """

    def __init__(self):
        self.db = get_database()
        self.window_days = settings.WASH_SALE_WINDOW_DAYS

    def record_loss_sale(
        self,
        symbol: str,
        exit_date: date,
        loss_amount: float,
        exit_price: float
    ) -> None:
        """
        Record a symbol sold at a loss.

        Args:
            symbol: Stock symbol that was sold.
            exit_date: Date of the sale.
            loss_amount: Absolute value of the loss (positive number).
            exit_price: Price at which the position was exited.
        """
        self.db.record_wash_sale(
            symbol=symbol,
            exit_date=exit_date,
            exit_price=exit_price,
            loss_amount=loss_amount
        )
        logger.info(
            f"Recorded wash sale for {symbol}: "
            f"loss=${loss_amount:.2f}, exit_price=${exit_price:.2f}. "
            f"Blocked until {exit_date + timedelta(days=self.window_days)}"
        )

    def is_in_wash_sale_window(self, symbol: str) -> bool:
        """
        Check if a symbol was sold at a loss within the wash sale window.

        Args:
            symbol: Stock symbol to check.

        Returns:
            True if the symbol is in the wash sale window, False otherwise.
        """
        return self.db.is_symbol_in_wash_window(symbol, self.window_days)

    def can_enter(self, symbol: str) -> tuple[bool, str]:
        """
        Check if entry is allowed for a symbol.

        Args:
            symbol: Stock symbol to check.

        Returns:
            Tuple of (allowed, reason). If allowed is False, reason explains why.
        """
        if self.is_in_wash_sale_window(symbol):
            wash_sales = self.db.get_wash_sales_in_window(self.window_days)
            for sale in wash_sales:
                if sale["symbol"] == symbol:
                    exit_date = date.fromisoformat(sale["exit_date"])
                    days_remaining = self.window_days - (date.today() - exit_date).days
                    return (
                        False,
                        f"Wash sale rule: {symbol} sold at loss on {exit_date}. "
                        f"{days_remaining} days until entry allowed."
                    )
            return False, f"Wash sale rule: {symbol} in restricted window"

        return True, ""

    def get_wash_sale_status(self) -> dict:
        """
        Get a summary of all symbols in the wash sale window.

        Returns:
            Dictionary with wash sale status information.
        """
        wash_sales = self.db.get_wash_sales_in_window(self.window_days)
        restricted_symbols = self.get_restricted_symbols()

        status = {
            "enabled": settings.WASH_SALE_ENABLED,
            "window_days": self.window_days,
            "restricted_count": len(restricted_symbols),
            "restricted_symbols": restricted_symbols,
            "recent_loss_sales": []
        }

        for sale in wash_sales:
            exit_date = date.fromisoformat(sale["exit_date"])
            days_remaining = self.window_days - (date.today() - exit_date).days
            status["recent_loss_sales"].append({
                "symbol": sale["symbol"],
                "exit_date": sale["exit_date"],
                "loss_amount": sale["loss_amount"],
                "exit_price": sale["exit_price"],
                "days_remaining": days_remaining
            })

        return status

    def get_restricted_symbols(self) -> list[str]:
        """
        Get list of symbols currently restricted by wash sale rule.

        Returns:
            List of symbol strings that cannot be entered.
        """
        wash_sales = self.db.get_wash_sales_in_window(self.window_days)
        # Use a set to avoid duplicates if same symbol sold multiple times
        return list(set(sale["symbol"] for sale in wash_sales))

    def cleanup_expired(self) -> int:
        """
        Remove records older than the wash sale window.

        Returns:
            Number of records removed.
        """
        removed = self.db.cleanup_old_wash_sales(self.window_days)
        if removed > 0:
            logger.info(f"Cleaned up {removed} expired wash sale records")
        return removed
