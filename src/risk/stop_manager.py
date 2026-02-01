from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.broker.order_manager import OrderManager
from src.storage.database import get_database
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    INDICATOR_REVERSAL = "indicator_reversal"
    TIME_BASED = "time_based"
    MANUAL = "manual"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"


@dataclass
class StopCheck:
    """Result of checking stop conditions."""
    should_exit: bool
    reason: Optional[ExitReason]
    exit_price: Optional[float]
    partial_exit: bool
    exit_quantity: Optional[int]


class StopManager:
    """
    Manages hybrid exit rules for positions.

    Exit priority:
    1. Hard stop-loss hit → exit immediately
    2. Trailing stop triggered → exit
    3. Take-profit target reached → scale out 50%
    4. Indicator reversal → exit remaining
    """

    def __init__(
        self,
        client: Optional[AlpacaClient] = None,
        order_manager: Optional[OrderManager] = None
    ):
        self.client = client or get_alpaca_client()
        self.order_manager = order_manager or OrderManager(self.client)
        self.db = get_database()
        self.trailing_stop_activation = settings.TRAILING_STOP_ACTIVATION
        self.trailing_stop_distance = settings.TRAILING_STOP_DISTANCE

        self._high_water_marks: dict[str, float] = {}

    def check_stops(self, symbol: str, current_price: float) -> StopCheck:
        """
        Check all stop conditions for a position.

        Args:
            symbol: Stock symbol
            current_price: Current market price

        Returns:
            StopCheck with exit decision and details
        """
        position_data = self.db.get_position(symbol)
        if position_data is None:
            return StopCheck(
                should_exit=False,
                reason=None,
                exit_price=None,
                partial_exit=False,
                exit_quantity=None
            )

        entry_price = position_data["entry_price"]
        quantity = position_data["quantity"]
        stop_loss = position_data.get("stop_loss")
        take_profit = position_data.get("take_profit")
        trailing_stop = position_data.get("trailing_stop")

        is_long = quantity > 0
        pnl_pct = (current_price - entry_price) / entry_price
        if not is_long:
            pnl_pct = -pnl_pct

        if stop_loss:
            if is_long and current_price <= stop_loss:
                logger.warning(f"{symbol}: Stop loss triggered at ${current_price:.2f}")
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.STOP_LOSS,
                    exit_price=current_price,
                    partial_exit=False,
                    exit_quantity=abs(quantity)
                )
            elif not is_long and current_price >= stop_loss:
                logger.warning(f"{symbol}: Stop loss triggered at ${current_price:.2f}")
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.STOP_LOSS,
                    exit_price=current_price,
                    partial_exit=False,
                    exit_quantity=abs(quantity)
                )

        trailing_check = self._check_trailing_stop(
            symbol, current_price, entry_price, is_long
        )
        if trailing_check.should_exit:
            return trailing_check

        if take_profit:
            if is_long and current_price >= take_profit:
                logger.info(f"{symbol}: Take profit triggered at ${current_price:.2f}")
                exit_qty = max(1, abs(quantity) // 2)
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.TAKE_PROFIT,
                    exit_price=current_price,
                    partial_exit=True,
                    exit_quantity=exit_qty
                )
            elif not is_long and current_price <= take_profit:
                logger.info(f"{symbol}: Take profit triggered at ${current_price:.2f}")
                exit_qty = max(1, abs(quantity) // 2)
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.TAKE_PROFIT,
                    exit_price=current_price,
                    partial_exit=True,
                    exit_quantity=exit_qty
                )

        return StopCheck(
            should_exit=False,
            reason=None,
            exit_price=None,
            partial_exit=False,
            exit_quantity=None
        )

    def _check_trailing_stop(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        is_long: bool
    ) -> StopCheck:
        """Check and update trailing stop."""
        pnl_pct = (current_price - entry_price) / entry_price
        if not is_long:
            pnl_pct = -pnl_pct

        if pnl_pct < self.trailing_stop_activation:
            return StopCheck(
                should_exit=False,
                reason=None,
                exit_price=None,
                partial_exit=False,
                exit_quantity=None
            )

        if symbol not in self._high_water_marks:
            self._high_water_marks[symbol] = current_price
            logger.info(
                f"{symbol}: Trailing stop activated at {pnl_pct:.1%} profit. "
                f"High: ${current_price:.2f}"
            )

        if is_long:
            if current_price > self._high_water_marks[symbol]:
                self._high_water_marks[symbol] = current_price
                new_trailing = current_price * (1 - self.trailing_stop_distance)
                self.db.update_position_stops(symbol, trailing_stop=new_trailing)
                logger.debug(
                    f"{symbol}: New high ${current_price:.2f}, "
                    f"trailing stop ${new_trailing:.2f}"
                )

            trailing_stop = self._high_water_marks[symbol] * (1 - self.trailing_stop_distance)
            if current_price <= trailing_stop:
                logger.info(f"{symbol}: Trailing stop triggered at ${current_price:.2f}")
                del self._high_water_marks[symbol]
                position_data = self.db.get_position(symbol)
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.TRAILING_STOP,
                    exit_price=current_price,
                    partial_exit=False,
                    exit_quantity=abs(position_data["quantity"]) if position_data else None
                )
        else:
            if current_price < self._high_water_marks[symbol]:
                self._high_water_marks[symbol] = current_price
                new_trailing = current_price * (1 + self.trailing_stop_distance)
                self.db.update_position_stops(symbol, trailing_stop=new_trailing)

            trailing_stop = self._high_water_marks[symbol] * (1 + self.trailing_stop_distance)
            if current_price >= trailing_stop:
                logger.info(f"{symbol}: Trailing stop triggered at ${current_price:.2f}")
                del self._high_water_marks[symbol]
                position_data = self.db.get_position(symbol)
                return StopCheck(
                    should_exit=True,
                    reason=ExitReason.TRAILING_STOP,
                    exit_price=current_price,
                    partial_exit=False,
                    exit_quantity=abs(position_data["quantity"]) if position_data else None
                )

        return StopCheck(
            should_exit=False,
            reason=None,
            exit_price=None,
            partial_exit=False,
            exit_quantity=None
        )

    def update_stop_loss(self, symbol: str, new_stop: float) -> None:
        """Update stop loss for a position."""
        self.db.update_position_stops(symbol, stop_loss=new_stop)
        logger.info(f"{symbol}: Stop loss updated to ${new_stop:.2f}")

    def update_take_profit(self, symbol: str, new_target: float) -> None:
        """Update take profit for a position."""
        self.db.update_position_stops(symbol, take_profit=new_target)
        logger.info(f"{symbol}: Take profit updated to ${new_target:.2f}")

    def move_stop_to_breakeven(self, symbol: str) -> bool:
        """
        Move stop loss to breakeven (entry price).

        Returns:
            True if stop was moved, False otherwise.
        """
        position_data = self.db.get_position(symbol)
        if position_data is None:
            return False

        entry_price = position_data["entry_price"]
        self.update_stop_loss(symbol, entry_price)
        logger.info(f"{symbol}: Stop moved to breakeven at ${entry_price:.2f}")
        return True

    def check_all_positions(self) -> list[StopCheck]:
        """Check stops for all open positions."""
        results = []
        positions = self.db.get_positions()

        symbols = [p["symbol"] for p in positions]
        if not symbols:
            return results

        try:
            quotes = self.client.get_quotes(symbols)

            for position in positions:
                symbol = position["symbol"]
                if symbol in quotes:
                    current_price = quotes[symbol].last
                    check = self.check_stops(symbol, current_price)
                    if check.should_exit:
                        results.append(check)
                        logger.info(
                            f"{symbol}: Exit signal - {check.reason.value} "
                            f"@ ${check.exit_price:.2f}"
                        )

        except Exception as e:
            logger.error(f"Error checking positions: {e}")

        return results

    def execute_stop_exits(self) -> int:
        """
        Check all positions and execute any triggered stops.

        Returns:
            Number of exits executed.
        """
        exits_executed = 0
        checks = self.check_all_positions()

        for check in checks:
            if check.should_exit:
                positions = self.db.get_positions()
                for pos in positions:
                    pos_data = self.db.get_position(pos["symbol"])
                    if pos_data:
                        result = self.order_manager.execute_exit(
                            symbol=pos["symbol"],
                            quantity=check.exit_quantity if check.partial_exit else None,
                            reason=check.reason.value
                        )
                        if result.success:
                            exits_executed += 1
                        break

        return exits_executed

    def reset_tracking(self, symbol: Optional[str] = None) -> None:
        """Reset trailing stop tracking for a symbol or all symbols."""
        if symbol:
            self._high_water_marks.pop(symbol, None)
        else:
            self._high_water_marks.clear()
