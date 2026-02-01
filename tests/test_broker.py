import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import date

from src.broker.pdt_tracker import PDTTracker


class TestPDTTracker:
    """Tests for PDT rule tracking."""

    @pytest.fixture
    def mock_client(self):
        """Create mock Alpaca client."""
        return Mock()

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        db = Mock()
        db.get_day_trades_in_window.return_value = 0
        db.get_day_trade_dates.return_value = []
        db.get_position.return_value = None
        return db

    @pytest.fixture
    def tracker(self, mock_client, mock_db, monkeypatch):
        """Create PDTTracker with mocks."""
        monkeypatch.setattr("src.broker.pdt_tracker.get_database", lambda: mock_db)
        t = PDTTracker(client=mock_client)
        t.db = mock_db
        return t

    def test_get_day_trades_remaining_all_available(self, tracker, mock_db):
        """Test when all day trades are available."""
        mock_db.get_day_trades_in_window.return_value = 0

        remaining = tracker.get_day_trades_remaining()
        assert remaining == 3

    def test_get_day_trades_remaining_some_used(self, tracker, mock_db):
        """Test when some day trades are used."""
        mock_db.get_day_trades_in_window.return_value = 2

        remaining = tracker.get_day_trades_remaining()
        assert remaining == 1

    def test_get_day_trades_remaining_none_left(self, tracker, mock_db):
        """Test when no day trades are left."""
        mock_db.get_day_trades_in_window.return_value = 3

        remaining = tracker.get_day_trades_remaining()
        assert remaining == 0

    def test_can_day_trade_high_conviction(self, tracker, mock_db):
        """Test day trade allowed for high conviction signal."""
        mock_db.get_day_trades_in_window.return_value = 1

        can_trade = tracker.can_day_trade(confidence=0.9)
        assert can_trade is True

    def test_can_day_trade_low_conviction(self, tracker, mock_db):
        """Test day trade blocked for low conviction signal."""
        mock_db.get_day_trades_in_window.return_value = 1

        can_trade = tracker.can_day_trade(confidence=0.5)
        assert can_trade is False

    def test_can_day_trade_no_remaining(self, tracker, mock_db):
        """Test day trade blocked when none remaining."""
        mock_db.get_day_trades_in_window.return_value = 3

        can_trade = tracker.can_day_trade(confidence=0.95)
        assert can_trade is False

    def test_record_day_trade(self, tracker, mock_db):
        """Test recording a day trade."""
        tracker.record_day_trade("AAPL")

        mock_db.record_day_trade.assert_called_once()
        call_args = mock_db.record_day_trade.call_args
        assert call_args[0][0] == "AAPL"
        assert call_args[0][1] == date.today()

    def test_is_position_from_today_no_position(self, tracker, mock_db):
        """Test checking position opened today when no position exists."""
        mock_db.get_position.return_value = None

        is_from_today = tracker.is_position_from_today("AAPL")
        assert is_from_today is False

    def test_should_hold_overnight_no_day_trades(self, tracker, mock_db):
        """Test position held overnight when no day trades available."""
        from datetime import datetime

        mock_db.get_position.return_value = {
            "symbol": "AAPL",
            "entry_time": datetime.now().isoformat()
        }
        mock_db.get_day_trades_in_window.return_value = 3

        should_hold = tracker.should_hold_overnight("AAPL", confidence=0.9)
        assert should_hold is True

    def test_get_pdt_status(self, tracker, mock_db):
        """Test getting full PDT status."""
        mock_db.get_day_trades_in_window.return_value = 1
        mock_db.get_day_trade_dates.return_value = [date.today()]

        status = tracker.get_pdt_status()

        assert status["day_trades_used"] == 1
        assert status["day_trades_remaining"] == 2
        assert status["max_day_trades"] == 3
        assert status["rolling_window_days"] == 5
