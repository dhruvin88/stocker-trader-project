import time
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import APIError, TimeFrame, TimeFrameUnit

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AccountInfo:
    """Account information from Alpaca."""
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    day_trade_count: int
    pattern_day_trader: bool
    trading_blocked: bool
    account_blocked: bool


@dataclass
class Position:
    """Position information from Alpaca."""
    symbol: str
    qty: int
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float
    side: str


@dataclass
class Quote:
    """Real-time quote data."""
    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    last: float
    timestamp: datetime


def _parse_timeframe(timeframe_str: str) -> TimeFrame:
    """Convert timeframe string to TimeFrame object.

    Supported formats: '1Min', '5Min', '15Min', '1Hour', '1Day', etc.
    """
    timeframe_str = timeframe_str.strip()

    # Handle common formats
    if timeframe_str == "1Min" or timeframe_str == "Minute":
        return TimeFrame.Minute
    elif timeframe_str == "1Hour" or timeframe_str == "Hour":
        return TimeFrame.Hour
    elif timeframe_str == "1Day" or timeframe_str == "Day":
        return TimeFrame.Day

    # Parse numeric prefix (e.g., "15Min", "5Min")
    import re
    match = re.match(r'^(\d+)(Min|Hour|Day|Week|Month)$', timeframe_str)
    if match:
        amount = int(match.group(1))
        unit_str = match.group(2)
        unit_map = {
            'Min': TimeFrameUnit.Minute,
            'Hour': TimeFrameUnit.Hour,
            'Day': TimeFrameUnit.Day,
            'Week': TimeFrameUnit.Week,
            'Month': TimeFrameUnit.Month
        }
        return TimeFrame(amount, unit_map[unit_str])

    # Default to daily
    logger.warning(f"Unknown timeframe format '{timeframe_str}', defaulting to Day")
    return TimeFrame.Day


class AlpacaClient:
    """Wrapper for the Alpaca Trading API."""

    def __init__(self):
        self.api = tradeapi.REST(
            key_id=settings.ALPACA_API_KEY,
            secret_key=settings.ALPACA_SECRET_KEY,
            base_url=settings.ALPACA_BASE_URL,
            api_version="v2"
        )
        self._last_request_time = 0
        self._min_request_interval = 0.2  # 200ms between requests

    def _rate_limit(self):
        """Simple rate limiting."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _retry_with_backoff(self, func, *args, max_retries: int = 3, **kwargs):
        """Execute a function with exponential backoff on failure."""
        last_exception = None
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except APIError as e:
                last_exception = e
                if attempt == max_retries - 1:
                    raise
                wait_time = (2 ** attempt) * settings.RETRY_DELAY_SECONDS
                logger.warning(f"API error (attempt {attempt + 1}): {e}. Retrying in {wait_time}s")
                time.sleep(wait_time)
            except (ConnectionError, ConnectionResetError, OSError) as e:
                last_exception = e
                if attempt == max_retries - 1:
                    raise
                wait_time = (2 ** attempt) * settings.RETRY_DELAY_SECONDS
                logger.warning(f"Connection error (attempt {attempt + 1}): {e}. Retrying in {wait_time}s")
                time.sleep(wait_time)
            except Exception as e:
                # Catch requests/urllib3 connection errors
                if "Connection" in str(type(e).__name__) or "connection" in str(e).lower():
                    last_exception = e
                    if attempt == max_retries - 1:
                        raise
                    wait_time = (2 ** attempt) * settings.RETRY_DELAY_SECONDS
                    logger.warning(f"Connection error (attempt {attempt + 1}): {e}. Retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    raise

    def get_account(self) -> AccountInfo:
        """Get account information."""
        account = self._retry_with_backoff(self.api.get_account)
        return AccountInfo(
            equity=float(account.equity),
            cash=float(account.cash),
            buying_power=float(account.buying_power),
            portfolio_value=float(account.portfolio_value),
            day_trade_count=int(account.daytrade_count),
            pattern_day_trader=account.pattern_day_trader,
            trading_blocked=account.trading_blocked,
            account_blocked=account.account_blocked
        )

    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        positions = self._retry_with_backoff(self.api.list_positions)
        return [
            Position(
                symbol=p.symbol,
                qty=int(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_plpc=float(p.unrealized_plpc),
                side=p.side
            )
            for p in positions
        ]

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a specific symbol."""
        try:
            p = self._retry_with_backoff(self.api.get_position, symbol)
            return Position(
                symbol=p.symbol,
                qty=int(p.qty),
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_plpc=float(p.unrealized_plpc),
                side=p.side
            )
        except APIError as e:
            if "position does not exist" in str(e).lower():
                return None
            raise

    def get_quote(self, symbol: str) -> Quote:
        """Get real-time quote for a symbol."""
        if settings.is_crypto_symbol(symbol):
            snapshot = self._retry_with_backoff(
                self.api.get_crypto_snapshot,
                symbol
            )
        else:
            snapshot = self._retry_with_backoff(
                self.api.get_snapshot,
                symbol,
                feed='iex'
            )
        quote = snapshot.latest_quote
        trade = snapshot.latest_trade

        return Quote(
            symbol=symbol,
            bid=float(quote.bp) if quote else 0,
            ask=float(quote.ap) if quote else 0,
            bid_size=int(quote.bs) if quote and hasattr(quote, 'bs') else 0,
            ask_size=int(quote.as_) if quote and hasattr(quote, 'as_') else 0,
            last=float(trade.p) if trade else 0,
            timestamp=datetime.now()
        )

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Get quotes for multiple symbols."""
        # Separate crypto and stock symbols
        crypto_symbols = [s for s in symbols if settings.is_crypto_symbol(s)]
        stock_symbols = [s for s in symbols if not settings.is_crypto_symbol(s)]

        quotes = {}

        # Get stock quotes
        if stock_symbols:
            snapshots = self._retry_with_backoff(
                self.api.get_snapshots,
                stock_symbols,
                feed='iex'
            )
            for symbol, snapshot in snapshots.items():
                quote = snapshot.latest_quote
                trade = snapshot.latest_trade
                quotes[symbol] = Quote(
                    symbol=symbol,
                    bid=float(quote.bp) if quote else 0,
                    ask=float(quote.ap) if quote else 0,
                    bid_size=int(quote.bs) if quote and hasattr(quote, 'bs') else 0,
                    ask_size=int(quote.as_) if quote and hasattr(quote, 'as_') else 0,
                    last=float(trade.p) if trade else 0,
                    timestamp=datetime.now()
                )

        # Get crypto quotes
        if crypto_symbols:
            for symbol in crypto_symbols:
                try:
                    snapshot = self._retry_with_backoff(
                        self.api.get_crypto_snapshot,
                        symbol
                    )
                    quote = snapshot.latest_quote
                    trade = snapshot.latest_trade
                    quotes[symbol] = Quote(
                        symbol=symbol,
                        bid=float(quote.bp) if quote else 0,
                        ask=float(quote.ap) if quote else 0,
                        bid_size=int(quote.bs) if quote and hasattr(quote, 'bs') else 0,
                        ask_size=int(quote.as_) if quote and hasattr(quote, 'as_') else 0,
                        last=float(trade.p) if trade else 0,
                        timestamp=datetime.now()
                    )
                except Exception as e:
                    logger.warning(f"Failed to get crypto quote for {symbol}: {e}")

        return quotes

    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "limit",
        time_in_force: str = "day",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None
    ):
        """Submit an order to Alpaca."""
        kwargs = {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
        }

        if limit_price is not None:
            kwargs["limit_price"] = round(limit_price, 2)
        if stop_price is not None:
            kwargs["stop_price"] = round(stop_price, 2)
        if client_order_id is not None:
            kwargs["client_order_id"] = client_order_id

        logger.info(f"Submitting order: {kwargs}")
        order = self._retry_with_backoff(self.api.submit_order, **kwargs)
        return order

    def submit_bracket_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        limit_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        time_in_force: str = "day"
    ):
        """Submit a bracket order (entry + take profit + stop loss)."""
        order = self._retry_with_backoff(
            self.api.submit_order,
            symbol=symbol,
            qty=qty,
            side=side,
            type="limit",
            time_in_force=time_in_force,
            limit_price=round(limit_price, 2),
            order_class="bracket",
            take_profit={"limit_price": round(take_profit_price, 2)},
            stop_loss={"stop_price": round(stop_loss_price, 2)}
        )
        return order

    def get_order(self, order_id: str):
        """Get order by ID."""
        return self._retry_with_backoff(self.api.get_order, order_id)

    def cancel_order(self, order_id: str):
        """Cancel an order."""
        try:
            self._retry_with_backoff(self.api.cancel_order, order_id)
            logger.info(f"Cancelled order {order_id}")
            return True
        except APIError as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_all_orders(self):
        """Cancel all open orders."""
        try:
            self._retry_with_backoff(self.api.cancel_all_orders)
            logger.info("Cancelled all open orders")
            return True
        except APIError as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False

    def get_open_orders(self, symbol: Optional[str] = None):
        """Get all open orders, optionally filtered by symbol."""
        orders = self._retry_with_backoff(
            self.api.list_orders,
            status="open",
            symbols=[symbol] if symbol else None
        )
        return orders

    def close_position(self, symbol: str):
        """Close a position completely."""
        try:
            self._retry_with_backoff(self.api.close_position, symbol)
            logger.info(f"Closed position for {symbol}")
            return True
        except APIError as e:
            logger.error(f"Failed to close position {symbol}: {e}")
            return False

    def close_all_positions(self):
        """Close all positions."""
        try:
            self._retry_with_backoff(self.api.close_all_positions)
            logger.info("Closed all positions")
            return True
        except APIError as e:
            logger.error(f"Failed to close all positions: {e}")
            return False

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ):
        """Get historical bars for a symbol."""
        if start is None:
            start = datetime.now() - timedelta(days=limit)
        if end is None:
            end = datetime.now()

        tf = _parse_timeframe(timeframe)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        # Use crypto endpoint for crypto symbols
        if settings.is_crypto_symbol(symbol):
            bars = self._retry_with_backoff(
                lambda: self.api.get_crypto_bars(
                    symbol,
                    tf,
                    start=start_str,
                    end=end_str,
                    limit=limit
                )
            )
        else:
            bars = self._retry_with_backoff(
                lambda: self.api.get_bars(
                    symbol,
                    tf,
                    start=start_str,
                    end=end_str,
                    limit=limit,
                    feed='iex'
                )
            )
        return bars

    def get_bars_multi(
        self,
        symbols: list[str],
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ):
        """Get historical bars for multiple symbols."""
        if start is None:
            start = datetime.now() - timedelta(days=limit)
        if end is None:
            end = datetime.now()

        tf = _parse_timeframe(timeframe)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        bars = self._retry_with_backoff(
            lambda: self.api.get_bars(
                symbols,
                tf,
                start=start_str,
                end=end_str,
                limit=limit,
                feed='iex'
            )
        )
        return bars

    def is_market_open(self) -> bool:
        """Check if the market is currently open."""
        clock = self._retry_with_backoff(self.api.get_clock)
        return clock.is_open

    def get_market_hours(self) -> dict:
        """Get today's market hours."""
        clock = self._retry_with_backoff(self.api.get_clock)
        return {
            "is_open": clock.is_open,
            "next_open": clock.next_open,
            "next_close": clock.next_close
        }

    def get_calendar(self, start_date: str, end_date: str):
        """Get market calendar."""
        return self._retry_with_backoff(
            self.api.get_calendar,
            start=start_date,
            end=end_date
        )


_client_instance: Optional[AlpacaClient] = None


def get_alpaca_client() -> AlpacaClient:
    """Get the singleton Alpaca client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = AlpacaClient()
    return _client_instance
