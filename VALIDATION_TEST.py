#!/usr/bin/env python3
"""
Quick validation test for options trading implementation.
Tests all critical components without requiring live data.
"""

import sys

def test_imports():
    """Test all critical imports work."""
    print("\n1. Testing Imports...")
    print("-" * 60)

    try:
        from src.risk.options_greeks import GreeksCalculator, OptionGreeks
        print("  ✅ Greeks Calculator")

        from src.broker.options_chain import OptionContract, OptionsChain
        print("  ✅ Options Chain")

        from src.broker.alpaca_client import AlpacaClient
        print("  ✅ Alpaca Client")

        from src.strategies.options import (
            CoveredCallStrategy,
            ProtectivePutStrategy,
            VerticalSpreadStrategy,
            UnusualOptionsActivity
        )
        print("  ✅ All 4 Strategies")

        from src.strategies.base import OptionsSignal
        print("  ✅ Options Signal")

        from src.broker.order_manager import OptionLeg, OptionsOrderResult
        print("  ✅ Order Manager Options")

        from src.risk.position_sizer import OptionsPositionSize
        print("  ✅ Position Sizer Options")

        return True
    except Exception as e:
        print(f"  ❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_greeks():
    """Test Greeks calculation."""
    print("\n2. Testing Greeks Calculation...")
    print("-" * 60)

    try:
        from src.risk.options_greeks import GreeksCalculator

        calc = GreeksCalculator()
        greeks = calc.calculate_greeks(
            option_type='call',
            spot_price=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            volatility=0.30
        )

        print(f"  Delta: {greeks.delta:.4f} (expected ~0.5 for ATM)")
        print(f"  Gamma: {greeks.gamma:.4f}")
        print(f"  Theta: {greeks.theta:.4f} (should be negative)")
        print(f"  Vega: {greeks.vega:.4f}")

        assert 0.4 < greeks.delta < 0.6, f"ATM delta should be ~0.5, got {greeks.delta}"
        assert greeks.theta < 0, "Theta should be negative"
        assert greeks.gamma > 0, "Gamma should be positive"

        print("  ✅ Greeks calculation correct")
        return True
    except Exception as e:
        print(f"  ❌ Greeks test failed: {e}")
        return False


def test_database():
    """Test database schema."""
    print("\n3. Testing Database Schema...")
    print("-" * 60)

    try:
        from src.storage.database import Database
        from datetime import datetime, date
        import tempfile
        import os

        # Create temp database
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name

        try:
            db = Database(db_path)

            # Test option position
            db.save_option_position(
                contract_symbol="TEST240315C00100000",
                underlying="TEST",
                contract_type="call",
                strike=100.0,
                expiration=date(2024, 3, 15),
                quantity=1,
                entry_price=5.0,
                entry_time=datetime.now(),
                strategy="test"
            )

            positions = db.get_option_positions()
            assert len(positions) == 1
            print(f"  ✅ Option positions table ({len(positions)} record)")

            # Test spread
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
            print(f"  ✅ Spreads table ({len(spreads)} record)")

            # Test trade
            trade_id = db.insert_option_trade(
                contract_symbol="TEST240315C00100000",
                underlying="TEST",
                contract_type="call",
                strike=100.0,
                expiration=date(2024, 3, 15),
                quantity=1,
                entry_time=datetime.now(),
                entry_price=5.0,
                exit_time=datetime.now(),
                exit_price=7.0,
                pnl=200.0,
                pnl_percent=40.0,
                exit_reason="profit_target",
                strategy="test"
            )

            trades = db.get_option_trades()
            assert len(trades) == 1
            print(f"  ✅ Option trades table ({len(trades)} record)")

            print("  ✅ All database tables working")
            return True

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    except Exception as e:
        print(f"  ❌ Database test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_strategies():
    """Test strategy instantiation."""
    print("\n4. Testing Strategy Instantiation...")
    print("-" * 60)

    try:
        from src.strategies.options import (
            CoveredCallStrategy,
            ProtectivePutStrategy,
            VerticalSpreadStrategy,
            UnusualOptionsActivity
        )

        strategies = {
            'covered_call': CoveredCallStrategy(),
            'protective_put': ProtectivePutStrategy(),
            'vertical_spread': VerticalSpreadStrategy(),
            'unusual_activity': UnusualOptionsActivity()
        }

        for name, strategy in strategies.items():
            assert strategy.name == name
            assert strategy.enabled
            assert hasattr(strategy, 'analyze')
            assert hasattr(strategy, 'should_exit')
            print(f"  ✅ {name:20s} - ready")

        print(f"  ✅ All 4 strategies initialized")
        return True
    except Exception as e:
        print(f"  ❌ Strategy test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_signal_creation():
    """Test OptionsSignal creation."""
    print("\n5. Testing Signal Creation...")
    print("-" * 60)

    try:
        from src.strategies.base import OptionsSignal, SignalDirection
        from src.risk.options_greeks import OptionGreeks
        from datetime import date

        greeks = OptionGreeks(
            delta=0.5,
            gamma=0.02,
            theta=-0.05,
            vega=0.15,
            rho=0.03,
            iv=0.30
        )

        # Single leg signal
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
        print("  ✅ Single-leg signal created")

        # Multi-leg signal (spread)
        from src.broker.order_manager import OptionLeg

        legs = [
            OptionLeg("TEST240315C00100000", "buy", 1, 5.0),
            OptionLeg("TEST240315C00105000", "sell", 1, 3.0)
        ]

        spread_signal = OptionsSignal(
            symbol="TEST",
            direction=SignalDirection.LONG,
            confidence=0.70,
            strategy="vertical_spread",
            contract_symbol=None,
            contract_type="call",
            strike=100.0,
            expiration=date(2024, 3, 15),
            premium=2.0,
            max_risk=200.0,
            max_profit=300.0,
            legs=legs,
            greeks=greeks
        )

        assert len(spread_signal.legs) == 2
        print("  ✅ Multi-leg signal created")

        print("  ✅ Signal creation working")
        return True
    except Exception as e:
        print(f"  ❌ Signal test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_configuration():
    """Test configuration settings."""
    print("\n6. Testing Configuration...")
    print("-" * 60)

    try:
        from config.settings import settings

        # Check options settings exist
        assert hasattr(settings, 'OPTIONS_ENABLED')
        assert hasattr(settings, 'MAX_OPTIONS_POSITIONS')
        assert hasattr(settings, 'MAX_CONTRACTS_PER_POSITION')
        assert hasattr(settings, 'MIN_DAYS_TO_EXPIRATION')
        assert hasattr(settings, 'MAX_DELTA_EXPOSURE')

        print(f"  OPTIONS_ENABLED: {settings.OPTIONS_ENABLED}")
        print(f"  MAX_OPTIONS_POSITIONS: {settings.MAX_OPTIONS_POSITIONS}")
        print(f"  MAX_CONTRACTS_PER_POSITION: {settings.MAX_CONTRACTS_PER_POSITION}")
        print(f"  MIN_DAYS_TO_EXPIRATION: {settings.MIN_DAYS_TO_EXPIRATION}")
        print(f"  MAX_DELTA_EXPOSURE: {settings.MAX_DELTA_EXPOSURE}")

        print("  ✅ All settings present")
        return True
    except Exception as e:
        print(f"  ❌ Configuration test failed: {e}")
        return False


def main():
    """Run all validation tests."""
    print("="*60)
    print("OPTIONS TRADING VALIDATION TEST")
    print("="*60)

    tests = [
        test_imports,
        test_greeks,
        test_database,
        test_strategies,
        test_signal_creation,
        test_configuration
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n❌ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"\n🎉 ALL TESTS PASSED ({passed}/{total})")
        print("\n✅ Options trading implementation is WORKING!")
        print("\nNext steps:")
        print("  1. Set OPTIONS_ENABLED=true in .env")
        print("  2. Start the bot: python -m src.main")
        print("  3. Watch for options signals in logs")
        return 0
    else:
        print(f"\n⚠️  SOME TESTS FAILED ({passed}/{total} passed)")
        print("\nFailed tests need attention before going live.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
