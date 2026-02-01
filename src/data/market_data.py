from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketDataProvider:
    """Provides market data from Alpaca."""

    def __init__(self, client: Optional[AlpacaClient] = None):
        self.client = client or get_alpaca_client()
        self._cache: dict[str, dict] = {}
        self._cache_duration = timedelta(minutes=1)

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Get historical bars for a symbol.

        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe (1Min, 5Min, 15Min, 1Hour, 1Day)
            start: Start datetime
            end: End datetime
            limit: Maximum number of bars

        Returns:
            DataFrame with OHLCV data
        """
        try:
            if start is None:
                if timeframe == "1Day":
                    start = datetime.now() - timedelta(days=limit * 2)
                elif timeframe in ["1Hour", "1H"]:
                    start = datetime.now() - timedelta(hours=limit * 2)
                else:
                    start = datetime.now() - timedelta(days=10)

            if end is None:
                end = datetime.now()

            bars = self.client.get_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                limit=limit
            )

            if bars is None or len(bars) == 0:
                return pd.DataFrame()

            if hasattr(bars, 'df'):
                df = bars.df
            else:
                df = pd.DataFrame([{
                    'timestamp': b.t,
                    'open': b.o,
                    'high': b.h,
                    'low': b.l,
                    'close': b.c,
                    'volume': b.v
                } for b in bars])

            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]

            if 'timestamp' in df.columns:
                df = df.rename(columns={'timestamp': 'datetime'})

            return df

        except Exception as e:
            logger.error(f"Error getting bars for {symbol}: {e}")
            return pd.DataFrame()

    def get_bars_multi(
        self,
        symbols: list[str],
        timeframe: str = "1Day",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100
    ) -> dict[str, pd.DataFrame]:
        """
        Get historical bars for multiple symbols.

        Returns:
            Dict mapping symbol to DataFrame
        """
        result = {}

        for symbol in symbols:
            df = self.get_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                limit=limit
            )
            if not df.empty:
                result[symbol] = df

        return result

    def get_quote(self, symbol: str) -> dict:
        """Get real-time quote for a symbol."""
        try:
            quote = self.client.get_quote(symbol)
            return {
                "symbol": quote.symbol,
                "bid": quote.bid,
                "ask": quote.ask,
                "bid_size": quote.bid_size,
                "ask_size": quote.ask_size,
                "last": quote.last,
                "timestamp": quote.timestamp
            }
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            return {}

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Get real-time quotes for multiple symbols."""
        try:
            quotes = self.client.get_quotes(symbols)
            return {
                symbol: {
                    "symbol": q.symbol,
                    "bid": q.bid,
                    "ask": q.ask,
                    "bid_size": q.bid_size,
                    "ask_size": q.ask_size,
                    "last": q.last,
                    "timestamp": q.timestamp
                }
                for symbol, q in quotes.items()
            }
        except Exception as e:
            logger.error(f"Error getting quotes: {e}")
            return {}

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get the latest price for a symbol."""
        quote = self.get_quote(symbol)
        return quote.get("last")

    def get_latest_prices(self, symbols: list[str]) -> dict[str, float]:
        """Get latest prices for multiple symbols."""
        quotes = self.get_quotes(symbols)
        return {symbol: q["last"] for symbol, q in quotes.items() if q.get("last")}

    def is_market_open(self) -> bool:
        """Check if market is currently open."""
        return self.client.is_market_open()

    def get_market_hours(self) -> dict:
        """Get today's market hours."""
        return self.client.get_market_hours()


market_data = MarketDataProvider()
