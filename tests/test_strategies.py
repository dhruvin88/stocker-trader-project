import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.strategies.base import BaseStrategy, Signal, SignalDirection
from src.strategies.technical.rsi_strategy import RSIStrategy


class TestSignal:
    """Tests for the Signal dataclass."""

    def test_signal_creation(self):
        """Test basic signal creation."""
        signal = Signal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            confidence=0.75,
            strategy="test"
        )
        assert signal.symbol == "AAPL"
        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == 0.75
        assert signal.strategy == "test"

    def test_signal_confidence_validation(self):
        """Test that confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            Signal(
                symbol="AAPL",
                direction=SignalDirection.LONG,
                confidence=1.5,
                strategy="test"
            )

    def test_signal_is_actionable(self):
        """Test actionable signal detection."""
        high_conf_signal = Signal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            confidence=0.8,
            strategy="test"
        )
        assert high_conf_signal.is_actionable(threshold=0.6) is True

        low_conf_signal = Signal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            confidence=0.4,
            strategy="test"
        )
        assert low_conf_signal.is_actionable(threshold=0.6) is False

        neutral_signal = Signal(
            symbol="AAPL",
            direction=SignalDirection.NEUTRAL,
            confidence=0.9,
            strategy="test"
        )
        assert neutral_signal.is_actionable(threshold=0.6) is False

    def test_signal_to_dict(self):
        """Test signal serialization to dict."""
        signal = Signal(
            symbol="AAPL",
            direction=SignalDirection.LONG,
            confidence=0.75,
            strategy="test",
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0
        )
        d = signal.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["direction"] == "long"
        assert d["confidence"] == 0.75
        assert d["entry_price"] == 150.0


class TestRSIStrategy:
    """Tests for the RSI strategy."""

    @pytest.fixture
    def strategy(self):
        """Create RSI strategy instance."""
        return RSIStrategy(
            rsi_period=14,
            oversold_level=30,
            overbought_level=70
        )

    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data."""
        dates = pd.date_range(start="2024-01-01", periods=100, freq="1h")
        np.random.seed(42)

        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        high = close + np.random.rand(100) * 2
        low = close - np.random.rand(100) * 2
        open_ = close + np.random.randn(100) * 0.5
        volume = np.random.randint(1000000, 10000000, 100)

        return pd.DataFrame({
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume
        })

    def test_strategy_name(self, strategy):
        """Test strategy name property."""
        assert strategy.name == "rsi"

    def test_strategy_enabled(self, strategy):
        """Test strategy enable/disable."""
        assert strategy.enabled is True
        strategy.enabled = False
        assert strategy.enabled is False

    def test_strategy_weight(self, strategy):
        """Test strategy weight bounds."""
        strategy.weight = 0.5
        assert strategy.weight == 0.5

        strategy.weight = 1.5
        assert strategy.weight == 1.0

        strategy.weight = -0.5
        assert strategy.weight == 0.0

    def test_get_required_bars(self, strategy):
        """Test required bars calculation."""
        bars = strategy.get_required_bars()
        assert bars >= strategy.rsi_period

    def test_get_parameters(self, strategy):
        """Test getting strategy parameters."""
        params = strategy.get_parameters()
        assert params["name"] == "rsi"
        assert params["rsi_period"] == 14
        assert params["oversold_level"] == 30
        assert params["overbought_level"] == 70

    def test_set_parameters(self, strategy):
        """Test setting strategy parameters."""
        strategy.set_parameters({
            "rsi_period": 21,
            "oversold_level": 25,
            "weight": 0.3
        })
        assert strategy.rsi_period == 21
        assert strategy.oversold_level == 25
        assert strategy.weight == 0.3

    def test_get_signal_returns_signal(self, strategy, sample_data):
        """Test that get_signal returns a Signal object."""
        signal = strategy.get_signal("AAPL", {"1Hour": sample_data})
        assert isinstance(signal, Signal)
        assert signal.symbol == "AAPL"
        assert signal.strategy == "rsi"

    def test_signal_has_valid_direction(self, strategy, sample_data):
        """Test signal direction is valid."""
        signal = strategy.get_signal("AAPL", {"1Hour": sample_data})
        assert signal.direction in [
            SignalDirection.LONG,
            SignalDirection.SHORT,
            SignalDirection.NEUTRAL
        ]

    def test_signal_metadata_contains_rsi(self, strategy, sample_data):
        """Test that signal metadata contains RSI value."""
        signal = strategy.get_signal("AAPL", {"1Hour": sample_data})
        assert "rsi" in signal.metadata


class TestBaseStrategy:
    """Tests for the BaseStrategy abstract class."""

    def test_cannot_instantiate_directly(self):
        """Test that BaseStrategy cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_subclass_requires_name(self):
        """Test that subclasses must implement name property."""
        class IncompleteStrategy(BaseStrategy):
            def analyze(self, symbols):
                return []

            def get_signal(self, symbol, data):
                return Signal(
                    symbol=symbol,
                    direction=SignalDirection.NEUTRAL,
                    confidence=0.0,
                    strategy="incomplete"
                )

        with pytest.raises(TypeError):
            IncompleteStrategy()
