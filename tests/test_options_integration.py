"""
Integration tests for options trading functionality.

Tests the complete options trading stack without requiring live market data.
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

# Test imports to verify all modules load correctly
def test_imports():
    """Test that all options modules can be imported."""
    from src.risk.options_greeks import GreeksCalculator, OptionGreeks
    from src.broker.options_chain import OptionContract, OptionsChain
    from src.strategies.options import (
        CoveredCallStrategy,
        ProtectivePutStrategy,
        VerticalSpreadStrategy,
        UnusualOptionsActivity
    )
    from src.strategies.base import OptionsSignal

    assert GreeksCalculator is not None
    assert OptionGreeks is not None
    assert OptionContract is not None
    assert OptionsChain is not None
    assert CoveredCallStrategy is not None
    assert ProtectivePutStrategy is not None
    assert VerticalSpreadStrategy is not None
    assert UnusualOptionsActivity is not None
    assert OptionsSignal is not None

    print("✅ All imports successful")


def test_greeks_calculator():
    """Test Greeks calculation."""
    from src.risk.options_greeks import GreeksCalculator

    calc = GreeksCalculator(risk_free_rate=0.05)

    # Calculate Greeks for an ATM call
    greeks = calc.calculate_greeks(
        option_type='call',
        spot_price=100.0,
        strike=100.0,
        time_to_expiry=0.25,  # 3 months
        volatility=0.30  # 30% IV
    )

    # Validate Greeks are reasonable
    assert 0.4 < greeks.delta < 0.6, f"ATM call delta should be ~0.5, got {greeks.delta}"
    assert greeks.gamma > 0, "Gamma should be positive"
    assert greeks.theta < 0, "Theta should be negative (time decay)"
    assert greeks.vega > 0, "Vega should be positive"
    assert greeks.iv == 0.30, "IV should match input"

    print(f"✅ Greeks calculation working: Delta={greeks.delta:.3f}, "
          f"Gamma={greeks.gamma:.4f}, Theta={greeks.theta:.4f}")


def test_option_contract():
    """Test OptionContract dataclass."""
    from src.broker.options_chain import OptionContract
    from src.risk.options_greeks import OptionGreeks

    greeks = OptionGreeks(
        delta=0.5,
        gamma=0.02,
        theta=-0.05,
        vega=0.15,
        rho=0.03,
        iv=0.30
    )

    contract = OptionContract(
        symbol="AAPL240315C00180000",
        underlying="AAPL",
        contract_type="call",
        strike=180.0,
        expiration=date(2024, 3, 15),
        bid=3.40,
        ask=3.60,
        last=3.50,
        volume=1500,
        open_interest=2500,
        implied_volatility=0.30,
        greeks=greeks
    )

    assert contract.mid_price == 3.50
    assert contract.bid_ask_spread == 0.20
    assert abs(contract.spread_percentage - 5.71) < 0.1  # ~5.71%
    assert contract.is_liquid(max_spread_pct=10.0, min_oi=100)

    print(f"✅ OptionContract working: mid={contract.mid_price}, "
          f"spread={contract.spread_percentage:.2f}%")


def test_options_chain():
    """Test OptionsChain filtering."""
    from src.broker.options_chain import OptionContract, OptionsChain
    from src.risk.options_greeks import OptionGreeks

    # Create sample contracts
    greeks_call = OptionGreeks(0.3, 0.02, -0.05, 0.15, 0.03, 0.30)
    greeks_put = OptionGreeks(-0.3, 0.02, -0.05, 0.15, 0.03, 0.30)

    exp_date = date.today() + timedelta(days=30)

    call_180 = OptionContract(
        "AAPL240315C00180000", "AAPL", "call", 180.0, exp_date,
        3.40, 3.60, 3.50, 1500, 2500, 0.30, greeks_call
    )

    put_170 = OptionContract(
        "AAPL240315P00170000", "AAPL", "put", 170.0, exp_date,
        2.80, 3.00, 2.90, 1200, 2000, 0.30, greeks_put
    )

    chain = OptionsChain(
        underlying="AAPL",
        underlying_price=175.0,
        expirations=[exp_date],
        contracts={
            call_180.symbol: call_180,
            put_170.symbol: put_170
        }
    )

    # Test filtering
    calls = chain.get_contracts_by_expiration(exp_date, "call")
    assert len(calls) == 1
    assert calls[0].strike == 180.0

    closest = chain.get_closest_strike(179.0, "call", exp_date)
    assert closest.strike == 180.0

    atm = chain.get_atm_contract("call", exp_date)
    assert atm.strike == 180.0

    print(f"✅ OptionsChain filtering working: {len(chain.contracts)} contracts")


def test_database_schema():
    """Test options database tables exist."""
    from src.storage.database import Database
    import tempfile
    import os

    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    try:
        db = Database(db_path)

        # Test option_positions table
        db.save_option_position(
            contract_symbol="TEST240315C00100000",
            underlying="TEST",
            contract_type="call",
            strike=100.0,
            expiration=date(2024, 3, 15),
            quantity=1,
            entry_price=5.0,
            entry_time=datetime.now(),
            strategy="test_strategy"
        )

        positions = db.get_option_positions()
        assert len(positions) == 1
        assert positions[0]['contract_symbol'] == "TEST240315C00100000"

        # Test spread table
        spread_id = db.create_spread(
            underlying="TEST",
            spread_type="bull_call_spread",
            entry_time=datetime.now(),
            net_premium=500.0,
            max_risk=500.0,
            max_profit=500.0,
            strategy="vertical_spread"
        )

        spreads = db.get_active_spreads()
        assert len(spreads) == 1
        assert spread_id > 0

        print("✅ Database schema working: tables created and accessible")

    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)


def test_position_sizer():
    """Test options position sizing."""
    from src.risk.position_sizer import PositionSizer
    from src.broker.alpaca_client import AlpacaClient
    from src.broker.options_chain import OptionContract
    from src.risk.options_greeks import OptionGreeks

    # Mock the client
    mock_client = Mock(spec=AlpacaClient)
    mock_account = Mock()
    mock_account.portfolio_value = 10000.0
    mock_account.buying_power = 5000.0
    mock_client.get_account.return_value = mock_account

    sizer = PositionSizer(client=mock_client)

    # Create test contract
    greeks = OptionGreeks(0.5, 0.02, -0.05, 0.15, 0.03, 0.30)
    contract = OptionContract(
        "TEST240315C00100000", "TEST", "call", 100.0,
        date.today() + timedelta(days=30),
        5.0, 5.20, 5.10, 1000, 2000, 0.30, greeks
    )

    # Mock database
    with patch('src.risk.position_sizer.get_database') as mock_db:
        mock_db.return_value.get_option_positions.return_value = []

        # Calculate position size
        position_size = sizer.calculate_option_position_size(
            contract=contract,
            is_debit=True
        )

        assert position_size.valid
        assert position_size.contracts > 0
        assert position_size.total_premium > 0
        assert position_size.delta_exposure > 0

        print(f"✅ Position sizing working: {position_size.contracts} contracts, "
              f"${position_size.total_premium:.2f} premium")


def test_covered_call_strategy():
    """Test covered call strategy signal generation."""
    from src.strategies.options import CoveredCallStrategy

    strategy = CoveredCallStrategy()

    assert strategy.name == "covered_call"
    assert strategy.enabled

    # Test with mock - would need position and options chain
    # This validates the strategy object is created correctly

    print("✅ CoveredCallStrategy initialized successfully")


def test_all_strategies_load():
    """Test all strategies can be instantiated."""
    from src.strategies.options import (
        CoveredCallStrategy,
        ProtectivePutStrategy,
        VerticalSpreadStrategy,
        UnusualOptionsActivity
    )

    strategies = [
        CoveredCallStrategy(),
        ProtectivePutStrategy(),
        VerticalSpreadStrategy(),
        UnusualOptionsActivity()
    ]

    assert len(strategies) == 4

    for strategy in strategies:
        assert strategy.name is not None
        assert strategy.enabled
        assert hasattr(strategy, 'analyze')
        assert hasattr(strategy, 'should_exit')

    strategy_names = [s.name for s in strategies]
    print(f"✅ All 4 strategies loaded: {strategy_names}")


def test_options_signal():
    """Test OptionsSignal creation."""
    from src.strategies.base import OptionsSignal, SignalDirection
    from src.risk.options_greeks import OptionGreeks

    greeks = OptionGreeks(0.5, 0.02, -0.05, 0.15, 0.03, 0.30)

    signal = OptionsSignal(
        symbol="AAPL",
        direction=SignalDirection.SHORT,
        confidence=0.75,
        strategy="covered_call",
        contract_symbol="AAPL240315C00180000",
        contract_type="call",
        strike=180.0,
        expiration=date(2024, 3, 15),
        premium=3.50,
        max_risk=1000.0,
        max_profit=350.0,
        greeks=greeks
    )

    assert signal.is_actionable(threshold=0.6)
    assert signal.contract_symbol == "AAPL240315C00180000"
    assert signal.strike == 180.0

    signal_dict = signal.to_dict()
    assert 'contract_symbol' in signal_dict
    assert 'strike' in signal_dict

    print("✅ OptionsSignal working correctly")


def test_main_integration():
    """Test that main.py can load with options enabled."""
    from config.settings import settings

    # Temporarily enable options
    original = settings.OPTIONS_ENABLED
    try:
        settings.OPTIONS_ENABLED = True

        # Import main components
        from src.main import TradingBot

        # This would normally require broker connection
        # Just verify the class loads
        assert TradingBot is not None

        print("✅ Main integration successful - TradingBot with options ready")

    finally:
        settings.OPTIONS_ENABLED = original


def run_all_tests():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("OPTIONS TRADING INTEGRATION TESTS")
    print("="*60 + "\n")

    tests = [
        ("Module Imports", test_imports),
        ("Greeks Calculator", test_greeks_calculator),
        ("Option Contract", test_option_contract),
        ("Options Chain", test_options_chain),
        ("Database Schema", test_database_schema),
        ("Position Sizer", test_position_sizer),
        ("Covered Call Strategy", test_covered_call_strategy),
        ("All Strategies", test_all_strategies_load),
        ("Options Signal", test_options_signal),
        ("Main Integration", test_main_integration),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\nTesting: {name}")
            print("-" * 60)
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {name}")
            print(f"   Error: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
