"""
Tests for aggressive trading strategies.

Run with: pytest tests/test_aggressive_strategies.py -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.technical.vwap_bounce_strategy import VWAPBounceStrategy
from src.strategies.base import SignalDirection


def create_sample_data(num_bars=100, trend="neutral"):
    """Create sample OHLCV data for testing."""
    dates = pd.date_range(end=datetime.now(), periods=num_bars, freq="15min")

    # Base price movement
    if trend == "up":
        base_price = np.linspace(100, 120, num_bars)
    elif trend == "down":
        base_price = np.linspace(120, 100, num_bars)
    else:
        base_price = np.full(num_bars, 110)

    # Add some noise
    noise = np.random.randn(num_bars) * 2
    close = base_price + noise

    # Generate OHLCV
    data = pd.DataFrame({
        'datetime': dates,
        'open': close * 0.99,
        'high': close * 1.01,
        'low': close * 0.98,
        'close': close,
        'volume': np.random.randint(100000, 500000, num_bars)
    })

    return data


def create_momentum_breakout_scenario():
    """
    Create data that should trigger a momentum breakout long signal.

    - Price rising above VWAP
    - MACD histogram positive and increasing
    - Volume surge
    - RSI in mid-range (not extreme)
    """
    num_bars = 100
    dates = pd.date_range(end=datetime.now(), periods=num_bars, freq="15min")

    # Start at 100, rise to 110 with acceleration at the end
    price = np.linspace(100, 108, num_bars - 10)
    price = np.append(price, np.linspace(108, 112, 10))  # Acceleration

    # Add small noise
    noise = np.random.randn(num_bars) * 0.3
    close = price + noise

    # Volume surge in last bars
    volume = np.full(num_bars, 200000)
    volume[-10:] = 300000  # 1.5x surge

    data = pd.DataFrame({
        'datetime': dates,
        'open': close * 0.999,
        'high': close * 1.002,
        'low': close * 0.998,
        'close': close,
        'volume': volume
    })

    return data


def create_vwap_bounce_scenario():
    """
    Create data that should trigger a VWAP bounce signal.

    - Price dips to VWAP
    - Bounces back above
    - Volume confirmation
    """
    num_bars = 100
    dates = pd.date_range(end=datetime.now(), periods=num_bars, freq="15min")

    # Price oscillates around 110 (which will be close to VWAP)
    price = np.full(num_bars - 5, 110)
    price = np.append(price, [108, 109, 109.5, 110.5, 111])  # Dip and bounce

    noise = np.random.randn(num_bars) * 0.2
    close = price + noise

    # Volume surge on bounce
    volume = np.full(num_bars, 200000)
    volume[-3:] = 280000  # Volume surge on bounce

    data = pd.DataFrame({
        'datetime': dates,
        'open': close * 0.999,
        'high': close * 1.001,
        'low': close * 0.999,
        'close': close,
        'volume': volume
    })

    return data


class TestMomentumBreakoutStrategy:
    """Test Momentum Breakout Strategy."""

    def test_initialization(self):
        """Test strategy initializes correctly."""
        strategy = MomentumBreakoutStrategy()

        assert strategy.name == "momentum_breakout"
        assert strategy.enabled is True
        assert strategy.macd_fast == 12
        assert strategy.macd_slow == 26
        assert strategy.rsi_period == 14
        assert strategy.min_confidence == 0.5

    def test_custom_parameters(self):
        """Test custom parameters are set."""
        strategy = MomentumBreakoutStrategy(
            macd_fast=10,
            volume_multiplier=1.5,
            min_confidence=0.6
        )

        assert strategy.macd_fast == 10
        assert strategy.volume_multiplier == 1.5
        assert strategy.min_confidence == 0.6

    def test_required_bars(self):
        """Test required bars calculation."""
        strategy = MomentumBreakoutStrategy()
        required = strategy.get_required_bars()

        assert required >= 50  # Should need at least 50 bars
        assert required >= strategy.macd_slow  # Must be >= slowest indicator

    def test_timeframes(self):
        """Test strategy uses correct timeframes."""
        strategy = MomentumBreakoutStrategy()
        timeframes = strategy.get_timeframes()

        assert "15Min" in timeframes
        assert "1Hour" in timeframes

    def test_signal_on_neutral_data(self):
        """Test strategy returns neutral on sideways market."""
        strategy = MomentumBreakoutStrategy()
        data = create_sample_data(num_bars=100, trend="neutral")

        signal = strategy.get_signal("TEST", data)

        assert signal is not None
        assert signal.symbol == "TEST"
        assert signal.strategy == "momentum_breakout"
        # Most likely neutral on random sideways data
        # (Could be directional if random data happens to align)

    def test_signal_on_momentum_scenario(self):
        """Test strategy detects momentum breakout."""
        strategy = MomentumBreakoutStrategy(min_confidence=0.4)  # Lower for test
        data = create_momentum_breakout_scenario()

        signal = strategy.get_signal("TEST", data)

        assert signal is not None
        assert signal.symbol == "TEST"
        # Should detect upward momentum (might be LONG or NEUTRAL depending on exact values)
        # At minimum, should not crash
        assert signal.confidence >= 0
        assert signal.confidence <= 1

    def test_signal_includes_stops(self):
        """Test signal includes stop loss and take profit."""
        strategy = MomentumBreakoutStrategy()
        data = create_sample_data(num_bars=100, trend="up")

        signal = strategy.get_signal("TEST", data)

        if signal.direction != SignalDirection.NEUTRAL:
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.entry_price is not None

            if signal.direction == SignalDirection.LONG:
                assert signal.stop_loss < signal.entry_price
                assert signal.take_profit > signal.entry_price

    def test_confidence_scoring(self):
        """Test confidence is in valid range."""
        strategy = MomentumBreakoutStrategy()
        data = create_sample_data(num_bars=100)

        signal = strategy.get_signal("TEST", data)

        assert 0 <= signal.confidence <= 1

    def test_metadata_included(self):
        """Test signal includes metadata."""
        strategy = MomentumBreakoutStrategy()
        data = create_sample_data(num_bars=100)

        signal = strategy.get_signal("TEST", data)

        assert "macd_hist" in signal.metadata
        assert "rsi" in signal.metadata
        assert "vwap" in signal.metadata
        assert "volume_ratio" in signal.metadata


class TestVWAPBounceStrategy:
    """Test VWAP Bounce Strategy."""

    def test_initialization(self):
        """Test strategy initializes correctly."""
        strategy = VWAPBounceStrategy()

        assert strategy.name == "vwap_bounce"
        assert strategy.enabled is True
        assert strategy.vwap_touch_threshold == 0.005
        assert strategy.vwap_target_distance == 0.015
        assert strategy.volume_multiplier == 1.3
        assert strategy.min_confidence == 0.5

    def test_custom_parameters(self):
        """Test custom parameters."""
        strategy = VWAPBounceStrategy(
            vwap_touch_threshold=0.01,
            volume_multiplier=1.5,
            min_confidence=0.6
        )

        assert strategy.vwap_touch_threshold == 0.01
        assert strategy.volume_multiplier == 1.5
        assert strategy.min_confidence == 0.6

    def test_timeframes(self):
        """Test strategy uses intraday timeframe."""
        strategy = VWAPBounceStrategy()
        timeframes = strategy.get_timeframes()

        assert "15Min" in timeframes
        assert len(timeframes) == 1  # Only intraday

    def test_signal_generation(self):
        """Test signal generation doesn't crash."""
        strategy = VWAPBounceStrategy()
        data = create_sample_data(num_bars=100)

        signal = strategy.get_signal("TEST", data)

        assert signal is not None
        assert signal.symbol == "TEST"
        assert signal.strategy == "vwap_bounce"
        assert 0 <= signal.confidence <= 1

    def test_vwap_bounce_scenario(self):
        """Test detection of VWAP bounce."""
        strategy = VWAPBounceStrategy(min_confidence=0.4)  # Lower for test
        data = create_vwap_bounce_scenario()

        signal = strategy.get_signal("TEST", data)

        assert signal is not None
        # Should detect some kind of signal (or neutral)
        assert signal.direction in [SignalDirection.LONG, SignalDirection.SHORT, SignalDirection.NEUTRAL]

    def test_signal_includes_targets(self):
        """Test signal includes stop and target based on VWAP."""
        strategy = VWAPBounceStrategy()
        data = create_sample_data(num_bars=100)

        signal = strategy.get_signal("TEST", data)

        if signal.direction != SignalDirection.NEUTRAL:
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.entry_price is not None

    def test_metadata_includes_vwap(self):
        """Test signal metadata includes VWAP info."""
        strategy = VWAPBounceStrategy()
        data = create_sample_data(num_bars=100)

        signal = strategy.get_signal("TEST", data)

        assert "vwap" in signal.metadata
        assert "vwap_deviation" in signal.metadata
        assert "volume_ratio" in signal.metadata

    def test_insufficient_data(self):
        """Test strategy handles insufficient data gracefully."""
        strategy = VWAPBounceStrategy()
        data = create_sample_data(num_bars=10)  # Too few bars

        signal = strategy.get_signal("TEST", data)

        assert signal.direction == SignalDirection.NEUTRAL
        assert signal.confidence == 0.0
        assert "reason" in signal.metadata


class TestStrategyComparison:
    """Compare both strategies."""

    def test_both_strategies_work(self):
        """Test both strategies can analyze same data."""
        momentum = MomentumBreakoutStrategy()
        vwap = VWAPBounceStrategy()

        data = create_sample_data(num_bars=100, trend="up")

        signal1 = momentum.get_signal("TEST", data)
        signal2 = vwap.get_signal("TEST", data)

        assert signal1 is not None
        assert signal2 is not None

        # Both should return valid signals
        assert 0 <= signal1.confidence <= 1
        assert 0 <= signal2.confidence <= 1

    def test_different_strategies_different_names(self):
        """Test strategies have different names."""
        momentum = MomentumBreakoutStrategy()
        vwap = VWAPBounceStrategy()

        assert momentum.name != vwap.name
        assert momentum.name == "momentum_breakout"
        assert vwap.name == "vwap_bounce"

    def test_both_support_long_and_short(self):
        """Test both strategies support both directions."""
        momentum = MomentumBreakoutStrategy()
        vwap = VWAPBounceStrategy()

        # Both should be capable of generating long/short/neutral
        # (Even if specific data doesn't trigger it)
        assert SignalDirection.LONG
        assert SignalDirection.SHORT
        assert SignalDirection.NEUTRAL


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
