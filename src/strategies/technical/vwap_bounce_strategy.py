"""
VWAP Bounce Strategy

An aggressive intraday strategy that trades bounces and rejections from VWAP.
VWAP acts as a dynamic support/resistance level where institutions often execute orders.

Entry Conditions (LONG - VWAP Bounce):
1. Price touches or dips below VWAP (within 0.5% deviation)
2. Price starts bouncing back above VWAP
3. Volume surge on the bounce (1.3x average)
4. Short-term momentum turning positive (MACD histogram)
5. Not in a strong downtrend (price above EMA21)

Entry Conditions (SHORT - VWAP Rejection):
1. Price touches or spikes above VWAP (within 0.5% deviation)
2. Price gets rejected and falls below VWAP
3. Volume surge on the rejection
4. Short-term momentum turning negative
5. Not in a strong uptrend (price below EMA21)

Exit Conditions:
- Price reaches opposite VWAP deviation band (±1.5%)
- Momentum reversal
- Time-based exit (if no movement after 20 bars)

This strategy is highly active:
- Intraday only (15-min bars)
- Multiple signals per day per symbol
- Quick entries and exits
- Lower confidence threshold (0.5+)
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


class VWAPBounceStrategy(BaseStrategy):
    """
    Aggressive VWAP bounce/rejection strategy for intraday trading.

    Trades price action around VWAP as a dynamic support/resistance level.
    Generates frequent signals by capturing institutional order flow areas.
    """

    def __init__(
        self,
        vwap_touch_threshold: float = 0.005,  # 0.5% from VWAP
        vwap_target_distance: float = 0.015,  # 1.5% target
        volume_multiplier: float = 1.3,
        ema_period: int = 21,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        min_confidence: float = 0.5
    ):
        super().__init__()
        self.vwap_touch_threshold = vwap_touch_threshold
        self.vwap_target_distance = vwap_target_distance
        self.volume_multiplier = volume_multiplier
        self.ema_period = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.min_confidence = min_confidence
        self.client = get_alpaca_client()

    @property
    def name(self) -> str:
        return "vwap_bounce"

    def get_required_bars(self) -> int:
        return max(self.ema_period, self.macd_slow) + 50

    def get_timeframes(self) -> list[str]:
        # Intraday focus - 15min is sweet spot for VWAP bounces
        return ["15Min"]

    def analyze(self, symbols: list[str]) -> list[Signal]:
        """Analyze symbols for VWAP bounce/rejection signals."""
        if not self.enabled:
            return []

        signals = []
        start_date = datetime.now() - timedelta(days=10)

        for symbol in symbols:
            try:
                data = self._get_data(symbol, start_date)
                if data is None or len(data) < self.get_required_bars():
                    continue

                signal = self.get_signal(symbol, data)

                if signal.is_actionable(threshold=self.min_confidence):
                    signals.append(signal)
                    self._cache_signal(signal)
                    logger.info(
                        f"[{self.name}] Signal: {signal.direction.value.upper()} "
                        f"{symbol} @ {signal.confidence:.2f} - {signal.metadata.get('signal_type')}"
                    )

            except Exception as e:
                logger.error(f"Error analyzing {symbol} with {self.name}: {e}")

        return signals

    def get_signal(self, symbol: str, data: pd.DataFrame) -> Signal:
        """
        Generate VWAP bounce/rejection signal.

        Args:
            symbol: Stock symbol
            data: DataFrame with OHLCV data
        """
        if len(data) < self.get_required_bars():
            return Signal(
                symbol=symbol,
                direction=SignalDirection.NEUTRAL,
                confidence=0.0,
                strategy=self.name,
                metadata={"reason": "Insufficient data"}
            )

        # Calculate indicators
        indicators = self._calculate_indicators(data)

        current_price = float(data["close"].iloc[-1])
        prev_price = float(data["close"].iloc[-2])

        # Analyze for bounce/rejection signals
        direction, confidence, metadata = self._analyze_vwap_action(
            indicators,
            current_price,
            prev_price,
            symbol
        )

        # Calculate stops and targets
        stop_loss = None
        take_profit = None

        if direction != SignalDirection.NEUTRAL:
            vwap = indicators["vwap"]

            if direction == SignalDirection.LONG:
                # Stop below recent low or VWAP - whichever is lower
                recent_low = float(data["low"].iloc[-5:].min())
                stop_loss = min(recent_low, vwap * (1 - self.vwap_touch_threshold * 2))

                # Target is VWAP + target distance
                take_profit = vwap * (1 + self.vwap_target_distance)

            elif direction == SignalDirection.SHORT:
                # Stop above recent high or VWAP + threshold
                recent_high = float(data["high"].iloc[-5:].max())
                stop_loss = max(recent_high, vwap * (1 + self.vwap_touch_threshold * 2))

                # Target is VWAP - target distance
                take_profit = vwap * (1 - self.vwap_target_distance)

        return Signal(
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            strategy=self.name,
            entry_price=current_price,
            stop_loss=round(stop_loss, 2) if stop_loss else None,
            take_profit=round(take_profit, 2) if take_profit else None,
            timeframe="15Min",
            metadata=metadata
        )

    def _calculate_indicators(self, data: pd.DataFrame) -> dict:
        """Calculate all required indicators."""
        indicators = {}

        # VWAP
        vwap = VolumeWeightedAveragePrice(
            high=data["high"],
            low=data["low"],
            close=data["close"],
            volume=data["volume"]
        )
        indicators["vwap"] = vwap.volume_weighted_average_price().iloc[-1]
        indicators["vwap_prev"] = vwap.volume_weighted_average_price().iloc[-2]

        # EMA for trend filter
        ema = EMAIndicator(close=data["close"], window=self.ema_period)
        indicators["ema"] = ema.ema_indicator().iloc[-1]

        # MACD for momentum
        macd = MACD(
            close=data["close"],
            window_slow=self.macd_slow,
            window_fast=self.macd_fast,
            window_sign=self.macd_signal
        )
        indicators["macd_hist"] = macd.macd_diff().iloc[-1]
        indicators["macd_hist_prev"] = macd.macd_diff().iloc[-2]

        # Volume
        avg_volume = data["volume"].rolling(window=20).mean().iloc[-1]
        current_volume = data["volume"].iloc[-1]
        indicators["volume_ratio"] = current_volume / avg_volume if avg_volume > 0 else 0

        # Price data
        indicators["price"] = data["close"].iloc[-1]
        indicators["price_prev"] = data["close"].iloc[-2]
        indicators["high"] = data["high"].iloc[-1]
        indicators["low"] = data["low"].iloc[-1]

        return indicators

    def _analyze_vwap_action(
        self,
        indicators: dict,
        current_price: float,
        prev_price: float,
        symbol: str
    ) -> tuple[SignalDirection, float, dict]:
        """
        Analyze price action around VWAP for bounce/rejection signals.

        Returns:
            (direction, confidence, metadata)
        """
        vwap = indicators["vwap"]
        vwap_deviation = abs(current_price - vwap) / vwap

        metadata = {
            "vwap": round(vwap, 2),
            "vwap_deviation": round(vwap_deviation * 100, 2),  # as percentage
            "volume_ratio": round(indicators["volume_ratio"], 2),
            "macd_hist": round(indicators["macd_hist"], 4),
            "conditions": []
        }

        # LONG: VWAP Bounce
        # Price was below/at VWAP and is bouncing back above
        if self._is_vwap_bounce(indicators, current_price, prev_price, vwap):
            conditions = []

            # Condition 1: Near VWAP (within threshold)
            if vwap_deviation <= self.vwap_touch_threshold * 1.5:
                conditions.append("near_vwap")

            # Condition 2: Bouncing (price crossed above VWAP)
            if current_price > vwap and prev_price <= vwap:
                conditions.append("crossed_above_vwap")

            # Condition 3: Volume confirmation
            if indicators["volume_ratio"] >= self.volume_multiplier:
                conditions.append("volume_surge")

            # Condition 4: Momentum turning positive
            if indicators["macd_hist"] > indicators["macd_hist_prev"]:
                conditions.append("momentum_improving")

            # Condition 5: Not in strong downtrend
            if indicators["price"] > indicators["ema"]:
                conditions.append("above_ema21")

            # Need at least 3 conditions for entry
            if len(conditions) >= 3:
                # Confidence based on conditions and proximity to VWAP
                base_confidence = 0.5
                condition_bonus = len(conditions) * 0.08
                proximity_bonus = (1 - vwap_deviation / self.vwap_touch_threshold) * 0.1
                volume_bonus = 0.05 if indicators["volume_ratio"] >= 1.5 else 0

                confidence = min(base_confidence + condition_bonus + proximity_bonus + volume_bonus, 0.9)

                metadata["conditions"] = conditions
                metadata["signal_type"] = "vwap_bounce_long"

                return SignalDirection.LONG, confidence, metadata

        # SHORT: VWAP Rejection
        # Price was above VWAP and is getting rejected back below
        if self._is_vwap_rejection(indicators, current_price, prev_price, vwap):
            conditions = []

            # Condition 1: Near VWAP
            if vwap_deviation <= self.vwap_touch_threshold * 1.5:
                conditions.append("near_vwap")

            # Condition 2: Rejecting (price crossed below VWAP)
            if current_price < vwap and prev_price >= vwap:
                conditions.append("crossed_below_vwap")

            # Condition 3: Volume confirmation
            if indicators["volume_ratio"] >= self.volume_multiplier:
                conditions.append("volume_surge")

            # Condition 4: Momentum turning negative
            if indicators["macd_hist"] < indicators["macd_hist_prev"]:
                conditions.append("momentum_deteriorating")

            # Condition 5: Not in strong uptrend
            if indicators["price"] < indicators["ema"]:
                conditions.append("below_ema21")

            if len(conditions) >= 3:
                base_confidence = 0.5
                condition_bonus = len(conditions) * 0.08
                proximity_bonus = (1 - vwap_deviation / self.vwap_touch_threshold) * 0.1
                volume_bonus = 0.05 if indicators["volume_ratio"] >= 1.5 else 0

                confidence = min(base_confidence + condition_bonus + proximity_bonus + volume_bonus, 0.9)

                metadata["conditions"] = conditions
                metadata["signal_type"] = "vwap_rejection_short"

                return SignalDirection.SHORT, confidence, metadata

        # No signal
        metadata["reason"] = "No clear VWAP bounce or rejection pattern"
        return SignalDirection.NEUTRAL, 0.0, metadata

    def _is_vwap_bounce(
        self,
        indicators: dict,
        current_price: float,
        prev_price: float,
        vwap: float
    ) -> bool:
        """Check if price is bouncing off VWAP from below."""
        # Price crossed from below VWAP to above OR
        # Price is very close to VWAP and momentum is turning up
        crossed_above = current_price > vwap and prev_price <= vwap
        near_and_turning = (
            abs(current_price - vwap) / vwap <= self.vwap_touch_threshold and
            indicators["macd_hist"] > indicators["macd_hist_prev"] and
            indicators["low"] <= vwap  # Low touched VWAP
        )

        return crossed_above or near_and_turning

    def _is_vwap_rejection(
        self,
        indicators: dict,
        current_price: float,
        prev_price: float,
        vwap: float
    ) -> bool:
        """Check if price is getting rejected at VWAP from above."""
        # Price crossed from above VWAP to below OR
        # Price is very close to VWAP and momentum is turning down
        crossed_below = current_price < vwap and prev_price >= vwap
        near_and_turning = (
            abs(current_price - vwap) / vwap <= self.vwap_touch_threshold and
            indicators["macd_hist"] < indicators["macd_hist_prev"] and
            indicators["high"] >= vwap  # High touched VWAP
        )

        return crossed_below or near_and_turning

    def should_exit(self, symbol: str, data: pd.DataFrame) -> tuple[bool, str]:
        """Check if VWAP action suggests exiting."""
        if len(data) < self.ema_period + 10:
            return False, ""

        last_signal = self.get_last_signal(symbol)
        if last_signal is None:
            return False, ""

        indicators = self._calculate_indicators(data)
        vwap = indicators["vwap"]
        current_price = indicators["price"]

        # Exit LONG if:
        # 1. Price reaches target distance above VWAP
        # 2. Price crosses back below VWAP with momentum
        # 3. Momentum turns sharply negative
        if last_signal.direction == SignalDirection.LONG:
            if current_price >= vwap * (1 + self.vwap_target_distance):
                return True, "Target reached (VWAP + 1.5%)"

            if current_price < vwap and indicators["macd_hist"] < 0:
                return True, "Crossed below VWAP with negative momentum"

            if indicators["macd_hist"] < indicators["macd_hist_prev"] * 2:
                return True, "Sharp momentum deterioration"

        # Exit SHORT if:
        # 1. Price reaches target distance below VWAP
        # 2. Price crosses back above VWAP with momentum
        # 3. Momentum turns sharply positive
        elif last_signal.direction == SignalDirection.SHORT:
            if current_price <= vwap * (1 - self.vwap_target_distance):
                return True, "Target reached (VWAP - 1.5%)"

            if current_price > vwap and indicators["macd_hist"] > 0:
                return True, "Crossed above VWAP with positive momentum"

            if indicators["macd_hist"] > indicators["macd_hist_prev"] * 2:
                return True, "Sharp momentum improvement"

        return False, ""

    def _get_data(
        self,
        symbol: str,
        start_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch intraday data."""
        try:
            bars = self.client.get_bars(
                symbol=symbol,
                timeframe="15Min",
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
                    return df

        except Exception as e:
            logger.warning(f"Failed to get data for {symbol}: {e}")

        return None

    def get_parameters(self) -> dict:
        """Get strategy parameters."""
        params = super().get_parameters()
        params.update({
            "vwap_touch_threshold": self.vwap_touch_threshold,
            "vwap_target_distance": self.vwap_target_distance,
            "volume_multiplier": self.volume_multiplier,
            "ema_period": self.ema_period,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "min_confidence": self.min_confidence
        })
        return params

    def set_parameters(self, params: dict) -> None:
        """Set strategy parameters."""
        super().set_parameters(params)
        if "vwap_touch_threshold" in params:
            self.vwap_touch_threshold = params["vwap_touch_threshold"]
        if "vwap_target_distance" in params:
            self.vwap_target_distance = params["vwap_target_distance"]
        if "volume_multiplier" in params:
            self.volume_multiplier = params["volume_multiplier"]
        if "ema_period" in params:
            self.ema_period = params["ema_period"]
        if "macd_fast" in params:
            self.macd_fast = params["macd_fast"]
        if "macd_slow" in params:
            self.macd_slow = params["macd_slow"]
        if "macd_signal" in params:
            self.macd_signal = params["macd_signal"]
        if "min_confidence" in params:
            self.min_confidence = params["min_confidence"]
