import pytest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass

from src.risk.position_sizer import PositionSizer, PositionSize
from src.risk.stop_manager import StopManager, StopCheck, ExitReason


@dataclass
class MockAccount:
    portfolio_value: float = 10000.0
    cash: float = 10000.0
    buying_power: float = 10000.0


@dataclass
class MockPosition:
    symbol: str
    qty: int
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float
    side: str


class TestPositionSizer:
    """Tests for position sizing logic."""

    @pytest.fixture
    def mock_client(self):
        """Create mock Alpaca client."""
        client = Mock()
        client.get_account.return_value = MockAccount()
        client.get_positions.return_value = []
        return client

    @pytest.fixture
    def sizer(self, mock_client):
        """Create PositionSizer with mock client."""
        return PositionSizer(client=mock_client)

    def test_calculate_position_size_basic(self, sizer):
        """Test basic position size calculation."""
        result = sizer.calculate_position_size(
            symbol="AAPL",
            entry_price=100.0,
            stop_loss_price=98.0,
            direction="long"
        )

        assert isinstance(result, PositionSize)
        assert result.valid is True
        assert result.shares > 0
        assert result.risk_percent <= 0.02

    def test_position_size_respects_max_risk(self, sizer):
        """Test that position size respects max risk per trade."""
        result = sizer.calculate_position_size(
            symbol="AAPL",
            entry_price=100.0,
            stop_loss_price=95.0,
            direction="long",
            risk_percent=0.02
        )

        assert result.risk_percent <= 0.02

    def test_position_size_max_positions_reached(self, sizer, mock_client):
        """Test that position is invalid when max positions reached."""
        mock_client.get_positions.return_value = [
            MockPosition(f"SYM{i}", 10, 100, 100, 1000, 0, 0, "long")
            for i in range(10)
        ]

        result = sizer.calculate_position_size(
            symbol="AAPL",
            entry_price=100.0,
            stop_loss_price=98.0,
            direction="long"
        )

        assert result.valid is False
        assert "max positions" in result.reason.lower()

    def test_calculate_stop_loss_long(self, sizer):
        """Test stop loss calculation for long position."""
        stop = sizer.calculate_stop_loss(
            entry_price=100.0,
            direction="long"
        )

        assert stop < 100.0

    def test_calculate_stop_loss_short(self, sizer):
        """Test stop loss calculation for short position."""
        stop = sizer.calculate_stop_loss(
            entry_price=100.0,
            direction="short"
        )

        assert stop > 100.0

    def test_calculate_take_profit(self, sizer):
        """Test take profit calculation."""
        take_profit = sizer.calculate_take_profit(
            entry_price=100.0,
            stop_loss_price=98.0,
            direction="long",
            risk_reward_ratio=2.0
        )

        risk = 100.0 - 98.0
        expected = 100.0 + (risk * 2.0)
        assert take_profit == expected

    def test_validate_trade_insufficient_buying_power(self, sizer, mock_client):
        """Test trade validation with insufficient buying power."""
        mock_client.get_account.return_value = MockAccount(buying_power=100.0)

        is_valid, reason = sizer.validate_trade(
            symbol="AAPL",
            shares=100,
            entry_price=100.0,
            stop_loss_price=98.0
        )

        assert is_valid is False
        assert "buying power" in reason.lower()


class TestStopManager:
    """Tests for stop management logic."""

    @pytest.fixture
    def mock_client(self):
        """Create mock Alpaca client."""
        return Mock()

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = Mock()
        db.get_position.return_value = {
            "symbol": "AAPL",
            "quantity": 10,
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "trailing_stop": None
        }
        return db

    @pytest.fixture
    def stop_manager(self, mock_client, mock_db, monkeypatch):
        """Create StopManager with mocks."""
        monkeypatch.setattr("src.risk.stop_manager.get_database", lambda: mock_db)
        manager = StopManager(client=mock_client)
        manager.db = mock_db
        return manager

    def test_check_stops_stop_loss_triggered(self, stop_manager):
        """Test stop loss detection."""
        result = stop_manager.check_stops("AAPL", current_price=94.0)

        assert isinstance(result, StopCheck)
        assert result.should_exit is True
        assert result.reason == ExitReason.STOP_LOSS

    def test_check_stops_no_trigger(self, stop_manager):
        """Test no stop triggered when price is normal."""
        result = stop_manager.check_stops("AAPL", current_price=102.0)

        assert result.should_exit is False
        assert result.reason is None

    def test_check_stops_take_profit_triggered(self, stop_manager):
        """Test take profit detection."""
        result = stop_manager.check_stops("AAPL", current_price=112.0)

        assert result.should_exit is True
        assert result.reason == ExitReason.TAKE_PROFIT
        assert result.partial_exit is True

    def test_check_stops_no_position(self, stop_manager, mock_db):
        """Test handling of non-existent position."""
        mock_db.get_position.return_value = None

        result = stop_manager.check_stops("AAPL", current_price=100.0)

        assert result.should_exit is False

    def test_trailing_stop_activation(self, stop_manager):
        """Test trailing stop is activated at profit threshold."""
        stop_manager.check_stops("AAPL", current_price=103.0)

        assert "AAPL" in stop_manager._high_water_marks

    def test_trailing_stop_updates_on_new_high(self, stop_manager):
        """Test trailing stop updates with new highs."""
        stop_manager.check_stops("AAPL", current_price=103.0)
        initial_hwm = stop_manager._high_water_marks["AAPL"]

        stop_manager.check_stops("AAPL", current_price=105.0)
        new_hwm = stop_manager._high_water_marks["AAPL"]

        assert new_hwm > initial_hwm

    def test_reset_tracking(self, stop_manager):
        """Test resetting tracking data."""
        stop_manager._high_water_marks["AAPL"] = 105.0
        stop_manager._high_water_marks["GOOGL"] = 150.0

        stop_manager.reset_tracking("AAPL")
        assert "AAPL" not in stop_manager._high_water_marks
        assert "GOOGL" in stop_manager._high_water_marks

        stop_manager.reset_tracking()
        assert len(stop_manager._high_water_marks) == 0
