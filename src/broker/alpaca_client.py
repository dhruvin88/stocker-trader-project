import time
from datetime import datetime, timedelta, date
from typing import Optional, TYPE_CHECKING
from dataclasses import dataclass

import alpaca_trade_api as tradeapi
from alpaca_trade_api.rest import APIError, TimeFrame, TimeFrameUnit

from config.settings import settings
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.broker.options_chain import OptionContract, OptionsChain

# Import at runtime to avoid circular imports
def _get_options_imports():
    from src.broker.options_chain import OptionContract, OptionsChain
    from src.risk.options_greeks import GreeksCalculator
    return OptionContract, OptionsChain, GreeksCalculator

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
    qty: float  # Changed to float for crypto fractional support
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
        self._options_chain_cache = {}  # Cache with (symbol, timestamp) key
        self._options_cache_ttl = 900  # 15 minutes in seconds
        self._greeks_calculator = None  # Lazy load to avoid circular import

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
                qty=float(p.qty),  # Use float for crypto fractional support
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
            # Alpaca uses ETHUSD format for crypto positions, not ETH/USD
            api_symbol = symbol.replace("/", "") if settings.is_crypto_symbol(symbol) else symbol
            # Don't use retry for position check - "not found" is expected
            self._rate_limit()
            p = self.api.get_position(api_symbol)
            return Position(
                symbol=symbol,  # Return original format
                qty=float(p.qty),  # Keep as float for crypto fractional support
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_plpc=float(p.unrealized_plpc),
                side=p.side
            )
        except APIError as e:
            if "position does not exist" in str(e).lower() or "404" in str(e):
                return None
            raise
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower() or "position does not exist" in str(e).lower():
                return None
            raise

    def get_quote(self, symbol: str) -> Quote:
        """Get real-time quote for a symbol."""
        if settings.is_crypto_symbol(symbol):
            # Crypto snapshot returns SnapshotsV2 dict keyed by symbol
            snapshots = self._retry_with_backoff(
                self.api.get_crypto_snapshot,
                symbol
            )
            # Access the snapshot for this symbol
            snapshot = snapshots[symbol] if symbol in snapshots else None

            if snapshot is None:
                return Quote(symbol=symbol, bid=0, ask=0, bid_size=0,
                           ask_size=0, last=0, timestamp=datetime.now())

            quote = snapshot.latest_quote
            trade = snapshot.latest_trade
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
                    snapshots = self._retry_with_backoff(
                        self.api.get_crypto_snapshot,
                        symbol
                    )
                    # Access the snapshot for this symbol
                    snapshot = snapshots[symbol] if symbol in snapshots else None

                    if snapshot is None:
                        quotes[symbol] = Quote(symbol=symbol, bid=0, ask=0, bid_size=0,
                                             ask_size=0, last=0, timestamp=datetime.now())
                        continue

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
        qty: float,  # Float for crypto fractional support
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
            # Alpaca uses ETHUSD format for crypto, not ETH/USD
            api_symbol = symbol.replace("/", "") if settings.is_crypto_symbol(symbol) else symbol
            self._retry_with_backoff(self.api.close_position, api_symbol)
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

    def get_options_chain(
        self,
        underlying: str,
        expiration_start: Optional[date] = None,
        expiration_end: Optional[date] = None,
        use_cache: bool = True
    ):  # Return type omitted to avoid circular import
        """
        Fetch options chain from Alpaca API.

        Args:
            underlying: Underlying symbol (e.g., "AAPL")
            expiration_start: Optional start date filter
            expiration_end: Optional end date filter
            use_cache: Use cached data if available (default True)

        Returns:
            OptionsChain with contracts and Greeks
        """
        # Lazy load options classes
        OptionContract, OptionsChain, GreeksCalculator = _get_options_imports()

        if self._greeks_calculator is None:
            self._greeks_calculator = GreeksCalculator()

        # Check cache first
        cache_key = (underlying, expiration_start, expiration_end)
        if use_cache and cache_key in self._options_chain_cache:
            cached_data, timestamp = self._options_chain_cache[cache_key]
            if time.time() - timestamp < self._options_cache_ttl:
                logger.debug(f"Using cached options chain for {underlying}")
                return cached_data

        # Get underlying price
        quote = self.get_quote(underlying)
        underlying_price = quote.last if quote.last > 0 else quote.bid

        # Fetch options snapshots from Alpaca
        # Note: Alpaca's options API endpoint is /v1beta1/options/snapshots/{underlying}
        try:
            # Build URL for options snapshots
            url = f"/v1beta1/options/snapshots/{underlying}"
            params = {}
            if expiration_start:
                params['expiration_date_gte'] = expiration_start.isoformat()
            if expiration_end:
                params['expiration_date_lte'] = expiration_end.isoformat()

            # Make API request using the underlying REST client
            response = self._retry_with_backoff(
                lambda: self.api._request('GET', url, params=params)
            )

            # Parse response
            contracts_dict = {}
            expirations_set = set()

            if 'snapshots' in response:
                for contract_symbol, snapshot_data in response['snapshots'].items():
                    contract = self._parse_option_contract(
                        contract_symbol,
                        underlying,
                        underlying_price,
                        snapshot_data
                    )
                    if contract:
                        contracts_dict[contract_symbol] = contract
                        expirations_set.add(contract.expiration)

            expirations = sorted(list(expirations_set))

            chain = OptionsChain(
                underlying=underlying,
                underlying_price=underlying_price,
                expirations=expirations,
                contracts=contracts_dict
            )

            # Update cache
            self._options_chain_cache[cache_key] = (chain, time.time())

            logger.info(
                f"Fetched options chain for {underlying}: "
                f"{len(contracts_dict)} contracts, {len(expirations)} expirations"
            )

            return chain

        except APIError as e:
            logger.error(f"Failed to fetch options chain for {underlying}: {e}")
            # Return empty chain
            return OptionsChain(
                underlying=underlying,
                underlying_price=underlying_price,
                expirations=[],
                contracts={}
            )

    def _parse_option_contract(
        self,
        contract_symbol: str,
        underlying: str,
        underlying_price: float,
        snapshot_data: dict
    ) -> Optional[OptionContract]:
        """
        Parse Alpaca option snapshot into OptionContract.

        Args:
            contract_symbol: Full OCC symbol
            underlying: Underlying symbol
            underlying_price: Current underlying price
            snapshot_data: Snapshot data from Alpaca API

        Returns:
            OptionContract or None if parsing fails
        """
        try:
            # Parse OCC symbol format: AAPL230120C00150000
            # Format: [Underlying][YYMMDD][C/P][Strike*1000]
            # Example: AAPL230120C00150000 = AAPL Jan 20 2023 $150 Call

            # Extract components
            symbol_without_underlying = contract_symbol[len(underlying):]

            # Date is next 6 characters (YYMMDD)
            date_str = symbol_without_underlying[:6]
            exp_year = 2000 + int(date_str[:2])
            exp_month = int(date_str[2:4])
            exp_day = int(date_str[4:6])
            expiration = date(exp_year, exp_month, exp_day)

            # Option type (C or P)
            option_type_char = symbol_without_underlying[6]
            contract_type = 'call' if option_type_char == 'C' else 'put'

            # Strike price (last 8 digits, divide by 1000)
            strike_str = symbol_without_underlying[7:]
            strike = int(strike_str) / 1000.0

            # Extract pricing data
            latest_quote = snapshot_data.get('latestQuote', {})
            latest_trade = snapshot_data.get('latestTrade', {})
            greeks_data = snapshot_data.get('greeks', {})
            implied_vol = snapshot_data.get('impliedVolatility', 0)

            bid = float(latest_quote.get('bp', 0)) if latest_quote else 0
            ask = float(latest_quote.get('ap', 0)) if latest_quote else 0
            last = float(latest_trade.get('p', 0)) if latest_trade else 0
            volume = int(latest_trade.get('s', 0)) if latest_trade else 0
            open_interest = int(snapshot_data.get('openInterest', 0))

            # Calculate Greeks if not provided by API
            if greeks_data:
                from src.risk.options_greeks import OptionGreeks
                greeks = OptionGreeks(
                    delta=float(greeks_data.get('delta', 0)),
                    gamma=float(greeks_data.get('gamma', 0)),
                    theta=float(greeks_data.get('theta', 0)),
                    vega=float(greeks_data.get('vega', 0)),
                    rho=float(greeks_data.get('rho', 0)),
                    iv=float(implied_vol)
                )
            else:
                # Calculate Greeks using Black-Scholes
                tte = self._greeks_calculator.time_to_expiry_years(expiration)
                if implied_vol > 0:
                    greeks = self._greeks_calculator.calculate_greeks(
                        contract_type,
                        underlying_price,
                        strike,
                        tte,
                        implied_vol
                    )
                else:
                    # Use default IV if not available
                    greeks = self._greeks_calculator.calculate_greeks(
                        contract_type,
                        underlying_price,
                        strike,
                        tte,
                        0.30  # Default 30% IV
                    )

            return OptionContract(
                symbol=contract_symbol,
                underlying=underlying,
                contract_type=contract_type,
                strike=strike,
                expiration=expiration,
                bid=bid,
                ask=ask,
                last=last,
                volume=volume,
                open_interest=open_interest,
                implied_volatility=float(implied_vol) if implied_vol else greeks.iv,
                greeks=greeks
            )

        except Exception as e:
            logger.warning(f"Failed to parse option contract {contract_symbol}: {e}")
            return None

    def get_option_quote(self, contract_symbol: str):
        """
        Get real-time quote for specific option contract.

        Args:
            contract_symbol: Full OCC option symbol

        Returns:
            OptionContract with current pricing, or None if not found
        """
        try:
            # Extract underlying from OCC symbol
            # Find where the date starts (after underlying ticker)
            underlying = None
            for i in range(1, len(contract_symbol)):
                if contract_symbol[i].isdigit():
                    underlying = contract_symbol[:i]
                    break

            if not underlying:
                logger.error(f"Could not parse underlying from {contract_symbol}")
                return None

            # Get full chain (will use cache if available)
            chain = self.get_options_chain(underlying)

            # Return specific contract
            return chain.contracts.get(contract_symbol)

        except Exception as e:
            logger.error(f"Failed to get option quote for {contract_symbol}: {e}")
            return None

    def get_options_contracts(
        self,
        underlying: str,
        strike: float,
        expiration: date,
        option_type: str
    ) -> list[OptionContract]:
        """
        Filter options by specific criteria.

        Args:
            underlying: Underlying symbol
            strike: Target strike price (will find closest)
            expiration: Expiration date
            option_type: 'call' or 'put'

        Returns:
            List of matching contracts (usually just one)
        """
        chain = self.get_options_chain(underlying)

        # Filter by expiration and type
        contracts = [
            c for c in chain.contracts.values()
            if c.expiration == expiration and c.contract_type == option_type
        ]

        if not contracts:
            return []

        # Find closest strike
        closest = min(contracts, key=lambda c: abs(c.strike - strike))
        return [closest]


_client_instance: Optional[AlpacaClient] = None


def get_alpaca_client() -> AlpacaClient:
    """Get the singleton Alpaca client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = AlpacaClient()
    return _client_instance
