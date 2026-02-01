from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator

from src.strategies.base import BaseStrategy, Signal, SignalDirection
from src.broker.alpaca_client import get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class RSIStrategy(BaseStrategy):
    """
    RSI-based mean reversion strategy with multi-timeframe confirmation.

    Entry Conditions:
    - RSI < oversold_level (30) on entry timeframe
    - Higher timeframe shows uptrend (price above EMA)

    Exit Conditions:
    - RSI > overbought_level (70)
    - Or trailing stop triggered

    Timeframes:
    - Entry: 15m, 1h
    - Confirmation: Daily
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold_level: int = 30,
        overbought_level: int = 70,
        ema_period: int = 21
    ):
        super().__init__()
        self.rsi_period = rsi_period
        self.oversold_level = oversold_level
        self.overbought_level = overbought_level
        self.ema_period = ema_period
        self.client = get_alpaca_client()

    @property
    def name(self) -> str:
        return "rsi"

    def get_required_bars(self) -> int:
        return max(self.rsi_period, self.ema_period) + 50

    def get_timeframes(self) -> list[str]:
        return ["15Min", "1Hour", "1Day"]

    def analyze(self, symbols: list[str]) -> list[Signal]:
        """Analyze symbols and generate RSI-based signals."""
        if not self.enabled:
            return []

        signals = []
        start_date = datetime.now() - timedelta(days=60)

        for symbol in symbols:
            try:
                data = self._get_multi_timeframe_data(symbol, start_date)
                if data is None:
                    continue

                signal = self.get_signal(symbol, data)
                if signal.is_actionable(settings.SIGNAL_THRESHOLD):
                    signals.append(signal)
                    self._cache_signal(signal)

            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")

        return signals

    def get_signal(self, symbol: str, data: dict[str, pd.DataFrame]) -> Signal:
        """
        Generate RSI signal for a symbol.

        Args:
            symbol: Stock symbol
            data: Dict of DataFrames keyed by timeframe
        """
        if isinstance(data, pd.DataFrame):
            data = {"1Hour": data}

        entry_tf = "1Hour" if "1Hour" in data else list(data.keys())[0]
        confirm_tf = "1Day" if "1Day" in data else entry_tf

        entry_data = data[entry_tf]
        confirm_data = data.get(confirm_tf, entry_data)

        if len(entry_data) < self.rsi_period + 5:
            return Signal(
                symbol=symbol,
                direction=SignalDirection.NEUTRAL,
                confidence=0.0,
                strategy=self.name,
                metadata={"reason": "Insufficient data"}
            )

        entry_rsi = self._calculate_rsi(entry_data)
        confirm_trend = self._check_trend(confirm_data)

        current_rsi = entry_rsi.iloc[-1]
        current_price = float(entry_data["close"].iloc[-1])

        direction = SignalDirection.NEUTRAL
        confidence = 0.0
        metadata = {
            "rsi": round(current_rsi, 2),
            "trend": confirm_trend,
            "rsi_period": self.rsi_period
        }

        if current_rsi < self.oversold_level and confirm_trend == "up":
            direction = SignalDirection.LONG
            oversold_depth = (self.oversold_level - current_rsi) / self.oversold_level
            trend_bonus = 0.2 if confirm_trend == "up" else 0
            confidence = min(0.5 + oversold_depth + trend_bonus, 0.95)
            metadata["signal_type"] = "oversold_bounce"

        elif current_rsi < self.oversold_level and confirm_trend == "neutral":
            direction = SignalDirection.LONG
            oversold_depth = (self.oversold_level - current_rsi) / self.oversold_level
            confidence = min(0.4 + oversold_depth * 0.5, 0.7)
            metadata["signal_type"] = "oversold_neutral_trend"

        elif current_rsi > self.overbought_level:
            direction = SignalDirection.SHORT
            overbought_depth = (current_rsi - self.overbought_level) / (100 - self.overbought_level)
            trend_bonus = 0.2 if confirm_trend == "down" else 0
            confidence = min(0.5 + overbought_depth + trend_bonus, 0.95)
            metadata["signal_type"] = "overbought_reversal"

        stop_loss = None
        take_profit = None
        if direction == SignalDirection.LONG:
            atr = self._calculate_atr(entry_data)
            stop_loss = current_price - (atr * 2)
            take_profit = current_price + (atr * 4)
        elif direction == SignalDirection.SHORT:
            atr = self._calculate_atr(entry_data)
            stop_loss = current_price + (atr * 2)
            take_profit = current_price - (atr * 4)

        return Signal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            strategy=self.name,
            entry_price=current_price,
            stop_loss=round(stop_loss, 2) if stop_loss else None,
            take_profit=round(take_profit, 2) if take_profit else None,
            timeframe=entry_tf,
            metadata=metadata
        )

    def should_exit(self, symbol: str, data: pd.DataFrame) -> tuple[bool, str]:
        """Check if RSI suggests exiting a position."""
        if len(data) < self.rsi_period + 5:
            return False, ""

        rsi = self._calculate_rsi(data)
        current_rsi = rsi.iloc[-1]

        last_signal = self.get_last_signal(symbol)
        if last_signal is None:
            return False, ""

        if last_signal.direction == SignalDirection.LONG and current_rsi > self.overbought_level:
            return True, f"RSI overbought ({current_rsi:.1f})"

        if last_signal.direction == SignalDirection.SHORT and current_rsi < self.oversold_level:
            return True, f"RSI oversold ({current_rsi:.1f})"

        return False, ""

    def _calculate_rsi(self, data: pd.DataFrame) -> pd.Series:
        """Calculate RSI indicator."""
        rsi = RSIIndicator(close=data["close"], window=self.rsi_period)
        return rsi.rsi()

    def _check_trend(self, data: pd.DataFrame) -> str:
        """
        Check trend direction using EMA.

        Returns:
            'up', 'down', or 'neutral'
        """
        if len(data) < self.ema_period + 5:
            return "neutral"

        ema = EMAIndicator(close=data["close"], window=self.ema_period)
        ema_values = ema.ema_indicator()

        current_price = data["close"].iloc[-1]
        current_ema = ema_values.iloc[-1]
        prev_ema = ema_values.iloc[-5]

        if current_price > current_ema and current_ema > prev_ema:
            return "up"
        elif current_price < current_ema and current_ema < prev_ema:
            return "down"
        return "neutral"

    def _calculate_atr(self, data: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return float(atr.iloc[-1])

    def _get_multi_timeframe_data(
        self,
        symbol: str,
        start_date: datetime
    ) -> Optional[dict[str, pd.DataFrame]]:
        """Fetch data for multiple timeframes."""
        timeframes = {
            "15Min": "15Min",
            "1Hour": "1Hour",
            "1Day": "1Day"
        }

        data = {}
        for tf_name, tf_api in timeframes.items():
            try:
                bars = self.client.get_bars(
                    symbol=symbol,
                    timeframe=tf_api,
                    start=start_date,
                    limit=self.get_required_bars()
                )

                if bars:
                    df = bars.df if hasattr(bars, 'df') else pd.DataFrame(bars)
                    if len(df) > 0:
                        df = df.reset_index()
                        df.columns = [c.lower() for c in df.columns]
                        if 'timestamp' in df.columns:
                            df = df.rename(columns={'timestamp': 'datetime'})
                        data[tf_name] = df

            except Exception as e:
                logger.warning(f"Failed to get {tf_name} data for {symbol}: {e}")

        return data if data else None

    def get_parameters(self) -> dict:
        """Get strategy parameters."""
        params = super().get_parameters()
        params.update({
            "rsi_period": self.rsi_period,
            "oversold_level": self.oversold_level,
            "overbought_level": self.overbought_level,
            "ema_period": self.ema_period
        })
        return params

    def set_parameters(self, params: dict) -> None:
        """Set strategy parameters."""
        super().set_parameters(params)
        if "rsi_period" in params:
            self.rsi_period = params["rsi_period"]
        if "oversold_level" in params:
            self.oversold_level = params["oversold_level"]
        if "overbought_level" in params:
            self.overbought_level = params["overbought_level"]
        if "ema_period" in params:
            self.ema_period = params["ema_period"]
