import time
from datetime import datetime, date as date_type
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.storage.database import get_database, Trade
from src.utils.logger import get_logger, trade_logger
from src.utils.notifications import notifications
from config.settings import settings

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


@dataclass
class OptionLeg:
    """Single leg of an options order."""
    contract_symbol: str
    side: str          # "buy" or "sell"
    quantity: int      # Number of contracts
    limit_price: float


@dataclass
class OptionsOrderResult:
    """Result of options order execution."""
    success: bool
    order_ids: list[str]      # Can be multiple for spreads
    status: OrderStatus
    filled_legs: list[dict]
    net_premium: float
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
            if position is None or abs(position.qty) == 0:
                # Position doesn't exist at broker or has zero quantity - clean up local DB if present
                # This can happen when bracket orders execute stop/take-profit
                db_position = self.db.get_position(symbol)
                if db_position:
                    logger.warning(
                        f"Position {symbol} not found at broker (qty={position.qty if position else 'None'}) "
                        f"but exists in local DB. Cleaning up stale position (likely closed by bracket order)."
                    )
                    self.db.remove_position(symbol)
                return OrderResult(
                    success=False,
                    order_id=None,
                    status=OrderStatus.FAILED,
                    filled_qty=0,
                    filled_price=None,
                    message=f"No position found for {symbol} or quantity is zero"
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

                # Update trade record in database - search ALL open trades, not just today
                # This fixes the issue where bracket orders close positions days after entry
                open_trades = self.db.get_open_trades()
                for trade in open_trades:
                    if trade.symbol == symbol:
                        self.db.update_trade_exit(
                            trade_id=trade.id,
                            exit_time=datetime.now(),
                            exit_price=result.filled_price,
                            pnl=pnl,
                            pnl_percent=pnl_percent
                        )
                        logger.info(f"Updated trade record {trade.id} for {symbol} exit")
                        break
                else:
                    # No open trade found - log warning but continue
                    logger.warning(
                        f"No open trade found in database for {symbol} exit. "
                        f"P&L: ${pnl:.2f} ({pnl_percent:+.2f}%) will not be tracked."
                    )

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

    # Options Trading Methods

    def execute_option_entry(
        self,
        contract: 'OptionContract',  # Forward reference
        quantity: int,
        strategy: str,
        limit_price: Optional[float] = None
    ) -> OptionsOrderResult:
        """
        Execute single-leg option entry.

        Args:
            contract: OptionContract object
            quantity: Number of contracts
            strategy: Name of strategy
            limit_price: Optional limit price (defaults to mid-point)

        Returns:
            OptionsOrderResult
        """
        try:
            # Validate options enabled
            if not settings.OPTIONS_ENABLED:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message="Options trading not enabled"
                )

            # Validate liquidity
            if not contract.is_liquid(
                settings.MAX_BID_ASK_SPREAD_PCT,
                settings.MIN_OPTION_OPEN_INTEREST
            ):
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message=f"Contract not liquid: spread {contract.spread_percentage:.1f}%, OI {contract.open_interest}"
                )

            # Calculate limit price
            if limit_price is None:
                limit_price = contract.mid_price

            # Validate days to expiration
            from src.risk.options_greeks import GreeksCalculator
            tte_days = (contract.expiration - date_type.today()).days
            if tte_days < settings.MIN_DAYS_TO_EXPIRATION:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message=f"Too close to expiration: {tte_days} days"
                )

            logger.info(
                f"Executing option entry: {quantity} {contract.symbol} "
                f"@ ${limit_price:.2f} ({strategy})"
            )

            # Submit order
            order = self.client.submit_order(
                symbol=contract.symbol,
                qty=quantity,
                side="buy",
                order_type="limit",
                time_in_force="day",
                limit_price=limit_price
            )

            # Wait for fill
            result = self._wait_for_fill(order.id, settings.ORDER_TIMEOUT_SECONDS)

            if result.success:
                # Record position in database
                self.db.save_option_position(
                    contract_symbol=contract.symbol,
                    underlying=contract.underlying,
                    contract_type=contract.contract_type,
                    strike=contract.strike,
                    expiration=contract.expiration,
                    quantity=quantity,
                    entry_price=result.filled_price,
                    entry_time=datetime.now(),
                    strategy=strategy,
                    current_delta=contract.greeks.delta if contract.greeks else None,
                    current_theta=contract.greeks.theta if contract.greeks else None
                )

                net_premium = result.filled_price * quantity * 100  # Premium x contracts x shares

                trade_logger.info(
                    f"OPTION_ENTRY: {contract.contract_type.upper()} {quantity} {contract.underlying} "
                    f"${contract.strike} exp {contract.expiration} @ ${result.filled_price:.2f} "
                    f"premium ${net_premium:.2f} ({strategy})"
                )

                notifications.send_trade_notification(
                    f"Option Entry: {quantity} {contract.symbol} @ ${result.filled_price:.2f}",
                    f"Strategy: {strategy}\nPremium: ${net_premium:.2f}"
                )

                return OptionsOrderResult(
                    success=True,
                    order_ids=[order.id],
                    status=OrderStatus.FILLED,
                    filled_legs=[{
                        "contract": contract.symbol,
                        "quantity": quantity,
                        "price": result.filled_price
                    }],
                    net_premium=net_premium,
                    message="Option entry filled"
                )
            else:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[order.id],
                    status=result.status,
                    filled_legs=[],
                    net_premium=0,
                    message=result.message
                )

        except Exception as e:
            logger.error(f"Failed to execute option entry: {e}")
            return OptionsOrderResult(
                success=False,
                order_ids=[],
                status=OrderStatus.FAILED,
                filled_legs=[],
                net_premium=0,
                message=str(e)
            )

    def execute_spread_entry(
        self,
        legs: list[OptionLeg],
        spread_type: str,
        strategy: str
    ) -> OptionsOrderResult:
        """
        Execute multi-leg spread order.

        Args:
            legs: List of OptionLeg objects
            spread_type: Type of spread (e.g., "bull_call_spread")
            strategy: Name of strategy

        Returns:
            OptionsOrderResult
        """
        try:
            if not settings.OPTIONS_ENABLED:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message="Options trading not enabled"
                )

            logger.info(f"Executing {spread_type}: {len(legs)} legs ({strategy})")

            # Execute each leg individually
            # Note: Alpaca may support multi-leg orders, but sequential is safer
            order_ids = []
            filled_legs = []
            net_premium = 0.0

            for leg in legs:
                # Get contract details
                contract = self.client.get_option_quote(leg.contract_symbol)
                if not contract:
                    logger.error(f"Could not get quote for {leg.contract_symbol}")
                    # Cancel previous legs
                    for oid in order_ids:
                        self.client.cancel_order(oid)
                    return OptionsOrderResult(
                        success=False,
                        order_ids=order_ids,
                        status=OrderStatus.FAILED,
                        filled_legs=filled_legs,
                        net_premium=0,
                        message=f"Failed to get quote for {leg.contract_symbol}"
                    )

                # Submit leg order
                order = self.client.submit_order(
                    symbol=leg.contract_symbol,
                    qty=leg.quantity,
                    side=leg.side,
                    order_type="limit",
                    time_in_force="day",
                    limit_price=leg.limit_price
                )

                order_ids.append(order.id)

                # Wait for fill
                result = self._wait_for_fill(order.id, settings.ORDER_TIMEOUT_SECONDS)

                if not result.success:
                    # Cancel all previous legs
                    for oid in order_ids:
                        self.client.cancel_order(oid)
                    return OptionsOrderResult(
                        success=False,
                        order_ids=order_ids,
                        status=result.status,
                        filled_legs=filled_legs,
                        net_premium=0,
                        message=f"Leg failed: {result.message}"
                    )

                # Track filled leg
                filled_legs.append({
                    "contract": leg.contract_symbol,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "price": result.filled_price
                })

                # Calculate net premium (debit or credit)
                leg_premium = result.filled_price * leg.quantity * 100
                if leg.side == "buy":
                    net_premium -= leg_premium  # Debit
                else:
                    net_premium += leg_premium  # Credit

            # Calculate max risk and profit
            # For vertical spreads: max_risk = spread_width - net_credit (or net_debit)
            # Simplified calculation - should be enhanced per spread type
            max_risk = abs(net_premium)  # Simplified
            max_profit = abs(net_premium)  # Simplified

            # Create spread record
            spread_id = self.db.create_spread(
                underlying=contract.underlying,
                spread_type=spread_type,
                entry_time=datetime.now(),
                net_premium=net_premium,
                max_risk=max_risk,
                max_profit=max_profit,
                strategy=strategy
            )

            # Link all legs to spread
            for leg in filled_legs:
                self.db.save_option_position(
                    contract_symbol=leg["contract"],
                    underlying=contract.underlying,
                    contract_type="call",  # Should parse from symbol
                    strike=0.0,  # Should parse from symbol
                    expiration=contract.expiration,
                    quantity=leg["quantity"],
                    entry_price=leg["price"],
                    entry_time=datetime.now(),
                    strategy=strategy,
                    spread_id=spread_id
                )

            trade_logger.info(
                f"SPREAD_ENTRY: {spread_type} {contract.underlying} "
                f"net_premium ${net_premium:.2f} ({strategy})"
            )

            notifications.send_trade_notification(
                f"Spread Entry: {spread_type}",
                f"Legs: {len(filled_legs)}\nNet Premium: ${net_premium:.2f}"
            )

            return OptionsOrderResult(
                success=True,
                order_ids=order_ids,
                status=OrderStatus.FILLED,
                filled_legs=filled_legs,
                net_premium=net_premium,
                message="Spread filled successfully"
            )

        except Exception as e:
            logger.error(f"Failed to execute spread: {e}")
            return OptionsOrderResult(
                success=False,
                order_ids=[],
                status=OrderStatus.FAILED,
                filled_legs=[],
                net_premium=0,
                message=str(e)
            )

    def execute_option_exit(
        self,
        contract_symbol: str,
        quantity: Optional[int] = None,
        reason: str = "manual"
    ) -> OptionsOrderResult:
        """
        Close option position.

        Args:
            contract_symbol: OCC symbol
            quantity: Number of contracts (None = close all)
            reason: Exit reason

        Returns:
            OptionsOrderResult
        """
        try:
            # Get position from database
            position = self.db.get_option_position(contract_symbol)
            if not position:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message="Position not found"
                )

            # Default to closing entire position
            if quantity is None:
                quantity = position["quantity"]

            # Get current quote
            contract = self.client.get_option_quote(contract_symbol)
            if not contract:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.FAILED,
                    filled_legs=[],
                    net_premium=0,
                    message="Could not get quote"
                )

            limit_price = contract.mid_price

            logger.info(f"Closing option position: {quantity} {contract_symbol} @ ${limit_price:.2f}")

            # Submit sell order
            order = self.client.submit_order(
                symbol=contract_symbol,
                qty=quantity,
                side="sell",
                order_type="limit",
                time_in_force="day",
                limit_price=limit_price
            )

            result = self._wait_for_fill(order.id, settings.ORDER_TIMEOUT_SECONDS)

            if result.success:
                # Calculate P&L
                entry_price = position["entry_price"]
                exit_price = result.filled_price
                pnl = (exit_price - entry_price) * quantity * 100
                pnl_percent = ((exit_price - entry_price) / entry_price) * 100

                # Record trade
                self.db.insert_option_trade(
                    contract_symbol=contract_symbol,
                    underlying=position["underlying"],
                    contract_type=position["contract_type"],
                    strike=position["strike"],
                    expiration=position["expiration"],
                    quantity=quantity,
                    entry_time=datetime.fromisoformat(position["entry_time"]),
                    entry_price=entry_price,
                    exit_time=datetime.now(),
                    exit_price=exit_price,
                    pnl=pnl,
                    pnl_percent=pnl_percent,
                    exit_reason=reason,
                    strategy=position["strategy"],
                    spread_id=position.get("spread_id")
                )

                # Remove from positions
                self.db.remove_option_position(contract_symbol)

                trade_logger.info(
                    f"OPTION_EXIT: {contract_symbol} @ ${exit_price:.2f} "
                    f"PNL ${pnl:.2f} ({pnl_percent:+.1f}%) - {reason}"
                )

                notifications.send_trade_notification(
                    f"Option Exit: {contract_symbol}",
                    f"Exit: ${exit_price:.2f}\nP&L: ${pnl:.2f} ({pnl_percent:+.1f}%)\nReason: {reason}"
                )

                return OptionsOrderResult(
                    success=True,
                    order_ids=[order.id],
                    status=OrderStatus.FILLED,
                    filled_legs=[{
                        "contract": contract_symbol,
                        "quantity": quantity,
                        "price": exit_price
                    }],
                    net_premium=pnl,
                    message=f"Position closed: P&L ${pnl:.2f}"
                )
            else:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[order.id],
                    status=result.status,
                    filled_legs=[],
                    net_premium=0,
                    message=result.message
                )

        except Exception as e:
            logger.error(f"Failed to execute option exit: {e}")
            return OptionsOrderResult(
                success=False,
                order_ids=[],
                status=OrderStatus.FAILED,
                filled_legs=[],
                net_premium=0,
                message=str(e)
            )

    def execute_spread_exit(
        self,
        spread_id: int,
        reason: str = "manual"
    ) -> OptionsOrderResult:
        """
        Close entire spread position.

        Args:
            spread_id: Spread ID from database
            reason: Exit reason

        Returns:
            OptionsOrderResult
        """
        try:
            # Get all legs
            legs = self.db.get_spread_legs(spread_id)
            if not legs:
                return OptionsOrderResult(
                    success=False,
                    order_ids=[],
                    status=OrderStatus.REJECTED,
                    filled_legs=[],
                    net_premium=0,
                    message="Spread not found"
                )

            logger.info(f"Closing spread {spread_id}: {len(legs)} legs")

            # Close each leg
            order_ids = []
            filled_legs = []
            total_pnl = 0.0

            for leg in legs:
                result = self.execute_option_exit(
                    leg["contract_symbol"],
                    leg["quantity"],
                    reason=f"spread_exit_{reason}"
                )

                if result.success:
                    order_ids.extend(result.order_ids)
                    filled_legs.extend(result.filled_legs)
                    total_pnl += result.net_premium
                else:
                    logger.warning(f"Failed to close leg {leg['contract_symbol']}: {result.message}")

            # Update spread status
            self.db.update_spread_status(spread_id, "closed")

            trade_logger.info(f"SPREAD_EXIT: spread_id={spread_id} total_pnl ${total_pnl:.2f}")

            return OptionsOrderResult(
                success=True,
                order_ids=order_ids,
                status=OrderStatus.FILLED,
                filled_legs=filled_legs,
                net_premium=total_pnl,
                message=f"Spread closed: P&L ${total_pnl:.2f}"
            )

        except Exception as e:
            logger.error(f"Failed to close spread: {e}")
            return OptionsOrderResult(
                success=False,
                order_ids=[],
                status=OrderStatus.FAILED,
                filled_legs=[],
                net_premium=0,
                message=str(e)
            )
