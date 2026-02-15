import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.storage.database import get_database, Trade
from src.utils.logger import get_logger, trade_logger
from src.utils.notifications import notifications
from config.settings import settings
from datetime import date

logger = get_logger(__name__)


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass
class OrderResult:
    """Result of an order submission."""
    success: bool
    order_id: Optional[str]
    status: OrderStatus
    filled_qty: int
    filled_price: Optional[float]
    message: str


class OrderManager:
    """Manages order execution with limit orders and fallback logic."""

    def __init__(self, client: Optional[AlpacaClient] = None, wash_sale_tracker=None):
        self.client = client or get_alpaca_client()
        self.db = get_database()
        self._wash_sale_tracker = wash_sale_tracker

    @property
    def wash_sale_tracker(self):
        """Lazy load wash sale tracker to avoid circular imports."""
        if self._wash_sale_tracker is None:
            from src.broker.wash_sale_tracker import WashSaleTracker
            self._wash_sale_tracker = WashSaleTracker()
        return self._wash_sale_tracker

    def execute_entry(
        self,
        symbol: str,
        quantity: int,
        direction: str,
        strategy: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> OrderResult:
        """
        Execute an entry order using limit orders.

        Args:
            symbol: Stock symbol
            quantity: Number of shares
            direction: 'long' or 'short'
            strategy: Name of the strategy generating the signal
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        side = "buy" if direction == "long" else "sell"

        try:
            quote = self.client.get_quote(symbol)
            limit_price = self._calculate_limit_price(quote, side)

            # Recalculate stop loss and take profit based on actual execution price
            # This handles cases where signal prices are stale
            if stop_loss and take_profit:
                if direction == "long":
                    # For long positions: stop below entry, take profit above
                    adj_stop_loss = round(limit_price * (1 - settings.DEFAULT_STOP_LOSS), 2)
                    adj_take_profit = round(limit_price * (1 + settings.DEFAULT_TAKE_PROFIT), 2)
                else:
                    # For short positions: stop above entry, take profit below
                    adj_stop_loss = round(limit_price * (1 + settings.DEFAULT_STOP_LOSS), 2)
                    adj_take_profit = round(limit_price * (1 - settings.DEFAULT_TAKE_PROFIT), 2)
                stop_loss = adj_stop_loss
                take_profit = adj_take_profit

            logger.info(
                f"Executing {direction} entry: {quantity} {symbol} @ ${limit_price:.2f} "
                f"(SL: ${stop_loss:.2f}, TP: ${take_profit:.2f})"
            )

            # Crypto doesn't support bracket orders, use simple limit orders
            is_crypto = settings.is_crypto_symbol(symbol)

            if stop_loss and take_profit and not is_crypto:
                order = self.client.submit_bracket_order(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    limit_price=limit_price,
                    take_profit_price=take_profit,
                    stop_loss_price=stop_loss
                )
            else:
                # Simple limit order (crypto or no stops)
                # For crypto, time_in_force must be 'gtc' (good til cancelled)
                order = self.client.submit_order(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    order_type="limit",
                    limit_price=limit_price,
                    time_in_force="gtc" if is_crypto else "day"
                )

            result = self._wait_for_fill(order.id, settings.ORDER_TIMEOUT_SECONDS)

            if result.success:
                trade = Trade(
                    id=None,
                    symbol=symbol,
                    direction=direction,
                    entry_time=datetime.now(),
                    entry_price=result.filled_price,
                    quantity=result.filled_qty,
                    exit_time=None,
                    exit_price=None,
                    pnl=None,
                    pnl_percent=None,
                    strategy=strategy,
                    is_day_trade=False,
                    notes=None
                )
                trade_id = self.db.insert_trade(trade)

                self.db.save_position(
                    symbol=symbol,
                    quantity=result.filled_qty,
                    entry_price=result.filled_price,
                    entry_time=datetime.now(),
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    strategy=strategy
                )

                trade_logger.info(
                    f"ENTRY: {direction.upper()} {result.filled_qty} {symbol} "
                    f"@ ${result.filled_price:.2f} (Strategy: {strategy})"
                )

                notifications.notify_trade_entry(
                    symbol=symbol,
                    direction=direction,
                    quantity=result.filled_qty,
                    price=result.filled_price,
                    strategy=strategy
                )

            return result

        except Exception as e:
            logger.error(f"Failed to execute entry for {symbol}: {e}")
            return OrderResult(
                success=False,
                order_id=None,
                status=OrderStatus.FAILED,
                filled_qty=0,
                filled_price=None,
                message=str(e)
            )

    def execute_exit(
        self,
        symbol: str,
        quantity: Optional[int] = None,
        reason: str = "manual"
    ) -> OrderResult:
        """
        Execute an exit order.

        Args:
            symbol: Stock symbol
            quantity: Number of shares (None = close entire position)
            reason: Reason for exit (stop_loss, take_profit, trailing_stop, signal, manual)
        """
        try:
            position = self.client.get_position(symbol)
            if position is None:
                # Position doesn't exist at broker - clean up local DB if present
                # This can happen when bracket orders execute stop/take-profit
                db_position = self.db.get_position(symbol)
                if db_position:
                    logger.warning(
                        f"Position {symbol} not found at broker but exists in local DB. "
                        f"Cleaning up stale position (likely closed by bracket order)."
                    )
                    self.db.remove_position(symbol)
                return OrderResult(
                    success=False,
                    order_id=None,
                    status=OrderStatus.FAILED,
                    filled_qty=0,
                    filled_price=None,
                    message=f"No position found for {symbol}"
                )

            exit_qty = quantity or abs(position.qty)
            side = "sell" if position.qty > 0 else "buy"

            quote = self.client.get_quote(symbol)
            limit_price = self._calculate_limit_price(quote, side)

            logger.info(
                f"Executing exit: {exit_qty} {symbol} @ ${limit_price:.2f} (Reason: {reason})"
            )

            # Crypto requires 'gtc' time_in_force, stocks use 'day'
            is_crypto = settings.is_crypto_symbol(symbol)
            order = self.client.submit_order(
                symbol=symbol,
                qty=exit_qty,
                side=side,
                order_type="limit",
                limit_price=limit_price,
                time_in_force="gtc" if is_crypto else "day"
            )

            result = self._wait_for_fill(order.id, settings.ORDER_TIMEOUT_SECONDS)

            if result.success:
                entry_price = position.avg_entry_price
                pnl = (result.filled_price - entry_price) * exit_qty
                if position.qty < 0:  # Short position
                    pnl = -pnl
                pnl_percent = (pnl / (entry_price * exit_qty)) * 100

                db_position = self.db.get_position(symbol)
                if db_position:
                    trades = self.db.get_trades_by_date_range(
                        datetime.now().date(),
                        datetime.now().date()
                    )
                    for trade in trades:
                        if trade.symbol == symbol and trade.exit_time is None:
                            self.db.update_trade_exit(
                                trade_id=trade.id,
                                exit_time=datetime.now(),
                                exit_price=result.filled_price,
                                pnl=pnl,
                                pnl_percent=pnl_percent
                            )
                            break

                if exit_qty >= abs(position.qty):
                    self.db.remove_position(symbol)

                # Record wash sale if sold at a loss
                if pnl < 0 and settings.WASH_SALE_ENABLED:
                    self.wash_sale_tracker.record_loss_sale(
                        symbol=symbol,
                        exit_date=date.today(),
                        loss_amount=abs(pnl),
                        exit_price=result.filled_price
                    )

                trade_logger.info(
                    f"EXIT: {exit_qty} {symbol} @ ${result.filled_price:.2f} | "
                    f"P&L: ${pnl:.2f} ({pnl_percent:+.2f}%) | Reason: {reason}"
                )

                notifications.notify_trade_exit(
                    symbol=symbol,
                    quantity=exit_qty,
                    entry_price=entry_price,
                    exit_price=result.filled_price,
                    pnl=pnl,
                    pnl_percent=pnl_percent
                )

            return result

        except Exception as e:
            logger.error(f"Failed to execute exit for {symbol}: {e}")
            return OrderResult(
                success=False,
                order_id=None,
                status=OrderStatus.FAILED,
                filled_qty=0,
                filled_price=None,
                message=str(e)
            )

    def _calculate_limit_price(self, quote, side: str) -> float:
        """
        Calculate limit price with offset from current quote.

        For buys, use ask + small offset to improve fill probability.
        For sells, use bid - small offset.
        """
        offset_pct = settings.LIMIT_ORDER_OFFSET

        if side == "buy":
            base_price = quote.ask if quote.ask > 0 else quote.last
            limit_price = base_price * (1 + offset_pct)
        else:
            base_price = quote.bid if quote.bid > 0 else quote.last
            limit_price = base_price * (1 - offset_pct)

        return round(limit_price, 2)

    def _wait_for_fill(
        self,
        order_id: str,
        timeout_seconds: int
    ) -> OrderResult:
        """Wait for an order to fill with timeout."""
        start_time = time.time()
        poll_interval = 0.5  # Check every 500ms

        while time.time() - start_time < timeout_seconds:
            try:
                order = self.client.get_order(order_id)

                if order.status == "filled":
                    return OrderResult(
                        success=True,
                        order_id=order_id,
                        status=OrderStatus.FILLED,
                        filled_qty=float(order.filled_qty),  # Use float for crypto support
                        filled_price=float(order.filled_avg_price),
                        message="Order filled"
                    )

                if order.status == "partially_filled":
                    logger.debug(
                        f"Order {order_id} partially filled: "
                        f"{order.filled_qty}/{order.qty}"
                    )

                if order.status in ["cancelled", "expired", "rejected"]:
                    return OrderResult(
                        success=False,
                        order_id=order_id,
                        status=OrderStatus(order.status),
                        filled_qty=float(order.filled_qty) if order.filled_qty else 0,
                        filled_price=float(order.filled_avg_price) if order.filled_avg_price else None,
                        message=f"Order {order.status}"
                    )

                time.sleep(poll_interval)

            except Exception as e:
                logger.warning(f"Error checking order status: {e}")
                time.sleep(poll_interval)

        logger.warning(f"Order {order_id} timed out, attempting to cancel")
        self.client.cancel_order(order_id)

        try:
            order = self.client.get_order(order_id)
            if float(order.filled_qty) > 0:
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    status=OrderStatus.PARTIALLY_FILLED,
                    filled_qty=float(order.filled_qty),
                    filled_price=float(order.filled_avg_price),
                    message="Order partially filled before timeout"
                )
        except Exception:
            pass

        return OrderResult(
            success=False,
            order_id=order_id,
            status=OrderStatus.EXPIRED,
            filled_qty=0,
            filled_price=None,
            message="Order timed out"
        )

    def cancel_open_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel open orders, optionally for a specific symbol."""
        orders = self.client.get_open_orders(symbol)
        cancelled = 0
        for order in orders:
            if self.client.cancel_order(order.id):
                cancelled += 1
        logger.info(f"Cancelled {cancelled} orders")
        return cancelled

    def get_order_status(self, order_id: str) -> OrderStatus:
        """Get the current status of an order."""
        try:
            order = self.client.get_order(order_id)
            return OrderStatus(order.status)
        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return OrderStatus.FAILED
