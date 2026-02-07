"""
Momentum Breakout Strategy

An aggressive multi-factor strategy designed to generate frequent trading signals
by combining momentum indicators, volume analysis, and VWAP positioning.

Entry Conditions (LONG):
1. MACD histogram positive and increasing (momentum building)
2. Price above VWAP (institutional support)
3. Volume > 1.2x average (participation confirmation)
4. Price above EMA9 (short-term trend)
5. RSI between 40-70 (not extreme, but has room to run)

Entry Conditions (SHORT):
1. MACD histogram negative and decreasing
2. Price below VWAP
3. Volume > 1.2x average
4. Price below EMA9
5. RSI between 30-60

Exit Conditions:
- MACD crossover reversal
- Price crosses VWAP in opposite direction
- RSI extreme (>75 for long, <25 for short)
- ATR-based stops

This strategy is more aggressive than RSI mean reversion:
- Does NOT require oversold/overbought extremes
- Does NOT require daily timeframe confirmation
- Trades WITH momentum rather than against it
- Enables both long and short signals
- Lower confidence threshold for execution
"""

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volume import VolumeWeightedAveragePrice

from src.strategies.base import BaseStrategy, Signal, SignalDirection
from src.broker.alpaca_client import get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class MomentumBreakoutStrategy(BaseStrategy):
    """
    Aggressive momentum breakout strategy with multi-factor confirmation.

    Designed to generate 2-3x more signals than RSI mean reversion by:
    - Trading with momentum instead of against it
    - Using multiple confirming factors instead of single indicator
    - Relaxed entry thresholds
    - Shorter timeframes for faster signals
    """

    def __init__(
        self,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        ema_period: int = 9,
        rsi_period: int = 14,
        volume_multiplier: float = 1.2,
        min_confidence: float = 0.5
    ):
        super().__init__()
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.volume_multiplier = volume_multiplier
        self.min_confidence = min_confidence
        self.client = get_alpaca_client()

    @property
    def name(self) -> str:
        return "momentum_breakout"

    def get_required_bars(self) -> int:
        return max(self.macd_slow, self.rsi_period) + 50

    def get_timeframes(self) -> list[str]:
        # Focus on intraday timeframes for faster signals
        return ["15Min", "1Hour"]

    def analyze(self, symbols: list[str]) -> list[Signal]:
        """Analyze symbols and generate momentum breakout signals."""
        if not self.enabled:
            return []

        signals = []
        start_date = datetime.now() - timedelta(days=30)

        for symbol in symbols:
            try:
                data = self._get_multi_timeframe_data(symbol, start_date)
                if data is None:
                    continue

                signal = self.get_signal(symbol, data)

                # More lenient threshold - we want more signals
                if signal.is_actionable(threshold=self.min_confidence):
                    signals.append(signal)
                    self._cache_signal(signal)
                    logger.info(
                        f"[{self.name}] Signal generated: {signal.direction.value.upper()} "
                        f"{symbol} @ {signal.confidence:.2f} confidence"
                    )

            except Exception as e:
                logger.error(f"Error analyzing {symbol} with {self.name}: {e}")

        return signals

    def get_signal(self, symbol: str, data: dict[str, pd.DataFrame]) -> Signal:
        """
        Generate momentum breakout signal for a symbol.

        Args:
            symbol: Stock symbol
            data: Dict of DataFrames keyed by timeframe
        """
        if isinstance(data, pd.DataFrame):
            data = {"1Hour": data}

        # Primary analysis on 1Hour, confirmation on 15Min
        primary_tf = "1Hour" if "1Hour" in data else list(data.keys())[0]
        entry_tf = "15Min" if "15Min" in data else primary_tf

        primary_data = data[primary_tf]
        entry_data = data.get(entry_tf, primary_data)

        if len(primary_data) < self.macd_slow + 10:
            return Signal(
                symbol=symbol,
                direction=SignalDirection.NEUTRAL,
                confidence=0.0,
                strategy=self.name,
                metadata={"reason": "Insufficient data"}
            )

        # Calculate indicators on primary timeframe
        indicators = self._calculate_indicators(primary_data)

        # Get entry timeframe price for precise entry
        current_price = float(entry_data["close"].iloc[-1])

        # Analyze signal
        direction, confidence, metadata = self._analyze_signals(
            indicators,
            symbol,
            current_price
        )

        # Calculate stops and targets
        stop_loss = None
        take_profit = None

        if direction != SignalDirection.NEUTRAL:
            atr = indicators["atr"]

            if direction == SignalDirection.LONG:
                # Tighter stops for aggressive strategy
                stop_loss = current_price - (atr * 1.5)
                # Multiple targets: 2R, 3R
                take_profit = current_price + (atr * 3)
            elif direction == SignalDirection.SHORT:
                stop_loss = current_price + (atr * 1.5)
                take_profit = current_price - (atr * 3)

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

    def _calculate_indicators(self, data: pd.DataFrame) -> dict:
        """Calculate all required indicators."""
        indicators = {}

        # MACD
        macd = MACD(
            close=data["close"],
            window_slow=self.macd_slow,
            window_fast=self.macd_fast,
            window_sign=self.macd_signal
        )
        indicators["macd"] = macd.macd().iloc[-1]
        indicators["macd_signal"] = macd.macd_signal().iloc[-1]
        indicators["macd_hist"] = macd.macd_diff().iloc[-1]
        indicators["macd_hist_prev"] = macd.macd_diff().iloc[-2]

        # RSI
        rsi = RSIIndicator(close=data["close"], window=self.rsi_period)
        indicators["rsi"] = rsi.rsi().iloc[-1]

        # EMA
        ema = EMAIndicator(close=data["close"], window=self.ema_period)
        indicators["ema"] = ema.ema_indicator().iloc[-1]

        # VWAP
        vwap = VolumeWeightedAveragePrice(
            high=data["high"],
            low=data["low"],
            close=data["close"],
            volume=data["volume"]
        )
        indicators["vwap"] = vwap.volume_weighted_average_price().iloc[-1]

        # Volume analysis
        avg_volume = data["volume"].rolling(window=20).mean().iloc[-1]
        current_volume = data["volume"].iloc[-1]
        indicators["volume_ratio"] = current_volume / avg_volume if avg_volume > 0 else 0

        # ATR for stops
        indicators["atr"] = self._calculate_atr(data)

        # Price
        indicators["price"] = data["close"].iloc[-1]

        return indicators

    def _analyze_signals(
        self,
        indicators: dict,
        symbol: str,
        current_price: float
    ) -> tuple[SignalDirection, float, dict]:
        """
        Analyze indicators and generate signal with confidence.

        Returns:
            (direction, confidence, metadata)
        """
        metadata = {
            "macd_hist": round(indicators["macd_hist"], 4),
            "rsi": round(indicators["rsi"], 2),
            "vwap": round(indicators["vwap"], 2),
            "volume_ratio": round(indicators["volume_ratio"], 2),
            "factors_aligned": []
        }

        # Check LONG conditions
        long_factors = []

        # Factor 1: MACD momentum building
        if indicators["macd_hist"] > 0 and indicators["macd_hist"] > indicators["macd_hist_prev"]:
            long_factors.append("macd_positive_increasing")

        # Factor 2: Price above VWAP
        if current_price > indicators["vwap"]:
            long_factors.append("above_vwap")

        # Factor 3: Volume confirmation
        if indicators["volume_ratio"] >= self.volume_multiplier:
            long_factors.append("volume_surge")

        # Factor 4: Short-term trend
        if current_price > indicators["ema"]:
            long_factors.append("above_ema9")

        # Factor 5: RSI not extreme (has room to run)
        if 40 <= indicators["rsi"] <= 70:
            long_factors.append("rsi_mid_range")

        # Check SHORT conditions
        short_factors = []

        # Factor 1: MACD momentum declining
        if indicators["macd_hist"] < 0 and indicators["macd_hist"] < indicators["macd_hist_prev"]:
            short_factors.append("macd_negative_decreasing")

        # Factor 2: Price below VWAP
        if current_price < indicators["vwap"]:
            short_factors.append("below_vwap")

        # Factor 3: Volume confirmation
        if indicators["volume_ratio"] >= self.volume_multiplier:
            short_factors.append("volume_surge")

        # Factor 4: Short-term trend
        if current_price < indicators["ema"]:
            short_factors.append("below_ema9")

        # Factor 5: RSI not extreme
        if 30 <= indicators["rsi"] <= 60:
            short_factors.append("rsi_mid_range")

        # Determine direction and confidence
        # Require at least 3 of 5 factors aligned
        if len(long_factors) >= 3:
            direction = SignalDirection.LONG
            # Confidence scales with number of aligned factors
            base_confidence = 0.5
            factor_bonus = len(long_factors) * 0.1  # +0.1 per factor

            # Bonus for strong volume
            volume_bonus = 0.05 if indicators["volume_ratio"] >= 1.5 else 0

            # Bonus for strong MACD
            macd_bonus = 0.05 if abs(indicators["macd_hist"]) > abs(indicators["macd_hist_prev"]) * 1.2 else 0

            confidence = min(base_confidence + factor_bonus + volume_bonus + macd_bonus, 0.95)
            metadata["factors_aligned"] = long_factors
            metadata["signal_type"] = "momentum_long"

        elif len(short_factors) >= 3:
            direction = SignalDirection.SHORT
            base_confidence = 0.5
            factor_bonus = len(short_factors) * 0.1
            volume_bonus = 0.05 if indicators["volume_ratio"] >= 1.5 else 0
            macd_bonus = 0.05 if abs(indicators["macd_hist"]) > abs(indicators["macd_hist_prev"]) * 1.2 else 0

            confidence = min(base_confidence + factor_bonus + volume_bonus + macd_bonus, 0.95)
            metadata["factors_aligned"] = short_factors
            metadata["signal_type"] = "momentum_short"

        else:
            direction = SignalDirection.NEUTRAL
            confidence = 0.0
            metadata["reason"] = f"Insufficient factors (long: {len(long_factors)}, short: {len(short_factors)})"

        return direction, confidence, metadata

    def should_exit(self, symbol: str, data: pd.DataFrame) -> tuple[bool, str]:
        """Check if momentum suggests exiting a position."""
        if len(data) < self.macd_slow + 10:
            return False, ""

        last_signal = self.get_last_signal(symbol)
        if last_signal is None:
            return False, ""

        indicators = self._calculate_indicators(data)

        # Exit LONG if:
        # 1. MACD crosses below signal
        # 2. Price crosses below VWAP
        # 3. RSI extreme overbought
        if last_signal.direction == SignalDirection.LONG:
            if indicators["macd"] < indicators["macd_signal"]:
                return True, "MACD bearish crossover"

            if indicators["price"] < indicators["vwap"]:
                return True, "Price below VWAP"

            if indicators["rsi"] > 75:
                return True, f"RSI overbought ({indicators['rsi']:.1f})"

        # Exit SHORT if:
        # 1. MACD crosses above signal
        # 2. Price crosses above VWAP
        # 3. RSI extreme oversold
        elif last_signal.direction == SignalDirection.SHORT:
            if indicators["macd"] > indicators["macd_signal"]:
                return True, "MACD bullish crossover"

            if indicators["price"] > indicators["vwap"]:
                return True, "Price above VWAP"

            if indicators["rsi"] < 25:
                return True, f"RSI oversold ({indicators['rsi']:.1f})"

        return False, ""

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
            "1Hour": "1Hour"
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
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "ema_period": self.ema_period,
            "rsi_period": self.rsi_period,
            "volume_multiplier": self.volume_multiplier,
            "min_confidence": self.min_confidence
        })
        return params

    def set_parameters(self, params: dict) -> None:
        """Set strategy parameters."""
        super().set_parameters(params)
        if "macd_fast" in params:
            self.macd_fast = params["macd_fast"]
        if "macd_slow" in params:
            self.macd_slow = params["macd_slow"]
        if "macd_signal" in params:
            self.macd_signal = params["macd_signal"]
        if "ema_period" in params:
            self.ema_period = params["ema_period"]
        if "rsi_period" in params:
            self.rsi_period = params["rsi_period"]
        if "volume_multiplier" in params:
            self.volume_multiplier = params["volume_multiplier"]
        if "min_confidence" in params:
            self.min_confidence = params["min_confidence"]
