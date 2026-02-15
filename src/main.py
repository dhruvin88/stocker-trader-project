#!/usr/bin/env python3
"""
Stocker Trader Bot - Main Entry Point

An automated stock trading system with conservative risk management,
PDT compliance, and multi-strategy support.
"""

import sys
import signal
import time
from datetime import datetime, timedelta
from typing import Optional
import schedule

from config.settings import settings
from src.utils.logger import setup_logger, get_logger
from src.utils.notifications import notifications
from src.storage.database import get_database
from src.broker.alpaca_client import get_alpaca_client
from src.broker.order_manager import OrderManager
from src.broker.pdt_tracker import PDTTracker
from src.broker.wash_sale_tracker import WashSaleTracker
from src.risk.position_sizer import PositionSizer
from src.risk.stop_manager import StopManager
from src.strategies.technical.rsi_strategy import RSIStrategy
from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.base import OptionsSignal

logger = get_logger(__name__)


class TradingBot:
    """Main trading bot controller."""

    def __init__(self):
        self.running = False
        self.client = get_alpaca_client()
        self.db = get_database()
        self.wash_sale_tracker = WashSaleTracker()
        self.order_manager = OrderManager(self.client, self.wash_sale_tracker)
        self.pdt_tracker = PDTTracker(self.client)
        self.position_sizer = PositionSizer(self.client)
        self.stop_manager = StopManager(self.client, self.order_manager)

        self.strategies = [
            MomentumBreakoutStrategy(),  # Primary: 239 trades/year, +$1,766 in backtest
            RSIStrategy()                 # Backup: Mean reversion on extreme RSI
        ]

        # Options strategies (if enabled)
        self.options_strategies = []
        if settings.OPTIONS_ENABLED:
            from src.strategies.options import (
                CoveredCallStrategy,
                ProtectivePutStrategy,
                VerticalSpreadStrategy,
                UnusualOptionsActivity
            )
            self.options_strategies = [
                CoveredCallStrategy(),      # Income: Sell calls on long positions
                ProtectivePutStrategy(),    # Protection: Buy puts for downside insurance
                VerticalSpreadStrategy(),   # Directional: Bull/bear spreads
                UnusualOptionsActivity()    # Momentum: Trade unusual volume/OI
            ]
            logger.info(f"Options trading enabled with {len(self.options_strategies)} strategies")

        self.watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "NVDA", "TSLA", "AMD", "NFLX", "SPY"
        ]

        # Add crypto symbols if enabled
        if settings.CRYPTO_ENABLED:
            self.watchlist.extend(settings.CRYPTO_SYMBOLS)
            logger.info(f"Crypto trading enabled: {settings.CRYPTO_SYMBOLS}")

        self._peak_portfolio_value: Optional[float] = None
        self._daily_starting_value: Optional[float] = None
        self._weekly_starting_value: Optional[float] = None
        self._trades_today: int = 0

    def start(self) -> None:
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info("Stocker Trader Bot Starting")
        logger.info("=" * 60)

        errors = settings.validate()
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            sys.exit(1)

        mode = "PAPER" if settings.is_paper_trading() else "LIVE"
        logger.info(f"Trading Mode: {mode}")

        try:
            account = self.client.get_account()
            logger.info(f"Account Connected: ${account.portfolio_value:,.2f}")
            logger.info(f"Buying Power: ${account.buying_power:,.2f}")
            logger.info(f"Day Trade Count: {account.day_trade_count}")

            self._peak_portfolio_value = account.portfolio_value
            self._daily_starting_value = account.portfolio_value
            self._weekly_starting_value = account.portfolio_value

        except Exception as e:
            logger.error(f"Failed to connect to broker: {e}")
            sys.exit(1)

        pdt_status = self.pdt_tracker.get_pdt_status()
        logger.info(f"PDT Status: {pdt_status['day_trades_remaining']} day trades remaining")

        logger.info(f"Active Strategies: {[s.name for s in self.strategies if s.enabled]}")
        if settings.OPTIONS_ENABLED:
            logger.info(f"Options Strategies: {[s.name for s in self.options_strategies if s.enabled]}")
        logger.info(f"Watchlist: {len(self.watchlist)} symbols")

        self._setup_schedule()

        self.running = True
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        logger.info("Bot initialized successfully")
        self._run_loop()

    def _setup_schedule(self) -> None:
        """Set up scheduled tasks."""
        schedule.every(1).minutes.do(self._check_positions)
        schedule.every(5).minutes.do(self._scan_for_signals)
        schedule.every(1).hours.do(self._log_status)
        schedule.every().day.at("16:05").do(self._end_of_day_summary)
        schedule.every().monday.at("09:00").do(self._weekly_reset)

    def _run_loop(self) -> None:
        """Main trading loop."""
        logger.info("Entering main trading loop")

        while self.running:
            try:
                schedule.run_pending()

                if self._is_trading_time():
                    pass

                time.sleep(10)

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(30)

    def _is_trading_time(self) -> bool:
        """Check if we're in valid trading hours."""
        if not self.client.is_market_open():
            return False

        now = datetime.now()

        # Calculate start time with proper hour overflow
        open_total_minutes = settings.MARKET_OPEN_HOUR * 60 + settings.MARKET_OPEN_MINUTE + settings.AVOID_FIRST_MINUTES
        market_open = now.replace(
            hour=open_total_minutes // 60,
            minute=open_total_minutes % 60,
            second=0
        )

        # Calculate close time with proper hour underflow
        close_total_minutes = settings.MARKET_CLOSE_HOUR * 60 + settings.MARKET_CLOSE_MINUTE - settings.AVOID_LAST_MINUTES
        market_close = now.replace(
            hour=close_total_minutes // 60,
            minute=close_total_minutes % 60,
            second=0
        )

        return market_open <= now <= market_close

    def _check_positions(self) -> None:
        """Check existing positions for stop conditions."""
        # Check if we have any crypto positions that need 24/7 monitoring
        has_crypto_positions = any(
            settings.is_crypto_symbol(p["symbol"])
            for p in self.db.get_positions()
        )

        # Only skip if market closed AND no crypto positions
        if not self.client.is_market_open() and not has_crypto_positions:
            return

        try:
            self.stop_manager.execute_stop_exits()

            # Check options positions for expiration and exit criteria
            if settings.OPTIONS_ENABLED:
                self._check_options_positions()

            if not self._check_risk_limits():
                self._halt_trading("Risk limit breached")

        except Exception as e:
            logger.error(f"Error checking positions: {e}")

    def _check_options_positions(self) -> None:
        """Monitor options positions for expiration and exit criteria."""
        try:
            from datetime import date

            option_positions = self.db.get_option_positions()

            for position in option_positions:
                contract_symbol = position['contract_symbol']
                expiration = date.fromisoformat(position['expiration']) if isinstance(position['expiration'], str) else position['expiration']
                strategy_name = position['strategy']

                # Check days to expiration
                dte = (expiration - date.today()).days

                # Auto-close if expiring within 3 days
                if dte <= 3:
                    logger.info(f"Auto-closing {contract_symbol} - expiring in {dte} days")
                    result = self.order_manager.execute_option_exit(
                        contract_symbol=contract_symbol,
                        reason="approaching_expiration"
                    )
                    if result.success:
                        logger.info(f"Closed {contract_symbol}: {result.message}")
                    continue

                # Check strategy-specific exit criteria
                # Find the strategy that owns this position
                for strategy in self.options_strategies:
                    if strategy.name == strategy_name:
                        # Get current price data for the underlying
                        bars = self.client.get_bars(
                            position['underlying'],
                            timeframe="1Day",
                            limit=50
                        )

                        if bars:
                            import pandas as pd
                            df = pd.DataFrame([{
                                'open': bar.o,
                                'high': bar.h,
                                'low': bar.l,
                                'close': bar.c,
                                'volume': bar.v
                            } for bar in bars])

                            should_exit, reason = strategy.should_exit(position['underlying'], df)

                            if should_exit:
                                logger.info(f"Strategy exit signal for {contract_symbol}: {reason}")
                                result = self.order_manager.execute_option_exit(
                                    contract_symbol=contract_symbol,
                                    reason=reason
                                )
                                if result.success:
                                    logger.info(f"Closed {contract_symbol}: {result.message}")

        except Exception as e:
            logger.error(f"Error checking options positions: {e}")

    def _scan_for_signals(self) -> None:
        """Scan watchlist for trading signals."""
        is_stock_trading_time = self._is_trading_time()

        if self._trades_today >= settings.MAX_TRADES_PER_DAY:
            logger.info("Max daily trades reached, skipping scan")
            return

        try:
            for strategy in self.strategies:
                if not strategy.enabled:
                    continue

                # Scan stocks only during market hours, crypto 24/7
                symbols_to_scan = []
                for symbol in self.watchlist:
                    if settings.is_crypto_symbol(symbol):
                        symbols_to_scan.append(symbol)  # Crypto: always scan
                    elif is_stock_trading_time:
                        symbols_to_scan.append(symbol)  # Stocks: only during market hours

                if not symbols_to_scan:
                    continue

                signals = strategy.analyze(symbols_to_scan)

                for signal in signals:
                    if signal.is_actionable(settings.SIGNAL_THRESHOLD):
                        self._process_signal(signal)

            # Scan for options signals (only during market hours for now)
            if is_stock_trading_time and settings.OPTIONS_ENABLED:
                self._scan_for_options_signals()

        except Exception as e:
            logger.error(f"Error scanning for signals: {e}")

    def _process_signal(self, signal) -> None:
        """Process and potentially execute a trading signal."""
        is_crypto = settings.is_crypto_symbol(signal.symbol)

        logger.info(
            f"Signal: {signal.direction.value.upper()} {signal.symbol} "
            f"(confidence: {signal.confidence:.2f}, strategy: {signal.strategy})"
            f"{' [CRYPTO]' if is_crypto else ''}"
        )

        existing_position = self.client.get_position(signal.symbol)
        if existing_position:
            logger.info(f"Already have position in {signal.symbol}, skipping")
            return

        # PDT rules don't apply to crypto
        if not is_crypto and signal.direction.value == "long":
            is_day_trade = self._would_be_day_trade(signal.symbol)
            if is_day_trade and not self.pdt_tracker.can_day_trade(signal.confidence):
                logger.info(f"Skipping {signal.symbol} - would use day trade for low confidence signal")
                return

        # Wash sale rules don't apply to crypto
        if not is_crypto and settings.WASH_SALE_ENABLED:
            can_enter, reason = self.wash_sale_tracker.can_enter(signal.symbol)
            if not can_enter:
                logger.info(f"Skipping {signal.symbol} - {reason}")
                return

        position_size = self.position_sizer.calculate_position_size(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_loss_price=signal.stop_loss,
            take_profit_price=signal.take_profit,
            direction=signal.direction.value
        )

        if not position_size.valid:
            logger.warning(f"Invalid position size for {signal.symbol}: {position_size.reason}")
            return

        result = self.order_manager.execute_entry(
            symbol=signal.symbol,
            quantity=position_size.shares,
            direction=signal.direction.value,
            strategy=signal.strategy,
            stop_loss=position_size.stop_loss,
            take_profit=position_size.take_profit
        )

        if result.success:
            self._trades_today += 1
            logger.info(
                f"Trade executed: {signal.direction.value.upper()} {result.filled_qty} "
                f"{signal.symbol} @ ${result.filled_price:.2f}"
            )

            from src.storage.database import Signal as DBSignal
            db_signal = DBSignal(
                id=None,
                symbol=signal.symbol,
                direction=signal.direction.value,
                confidence=signal.confidence,
                strategy=signal.strategy,
                timestamp=signal.timestamp,
                taken=True,
                reason=None
            )
            self.db.insert_signal(db_signal)
        else:
            logger.warning(f"Trade failed for {signal.symbol}: {result.message}")

    def _scan_for_options_signals(self) -> None:
        """Scan for options trading opportunities."""
        try:
            for strategy in self.options_strategies:
                if not strategy.enabled:
                    continue

                # Options strategies analyze all watchlist symbols
                signals = strategy.analyze(self.watchlist)

                for signal in signals:
                    if isinstance(signal, OptionsSignal) and signal.is_actionable(settings.SIGNAL_THRESHOLD):
                        self._process_options_signal(signal)

        except Exception as e:
            logger.error(f"Error scanning for options signals: {e}")

    def _process_options_signal(self, signal: OptionsSignal) -> None:
        """Process and potentially execute an options trading signal."""

        # Check if this is a multi-leg spread or single-leg option
        is_spread = signal.legs is not None and len(signal.legs) > 1

        if is_spread:
            spread_type = signal.metadata.get('spread_type', 'spread')
            logger.info(
                f"Options Spread Signal: {spread_type.upper()} {signal.symbol} "
                f"exp {signal.expiration} "
                f"(confidence: {signal.confidence:.2f}, strategy: {signal.strategy})"
            )
        else:
            logger.info(
                f"Options Signal: {signal.direction.value.upper()} {signal.symbol} "
                f"{signal.contract_type} ${signal.strike} exp {signal.expiration} "
                f"(confidence: {signal.confidence:.2f}, strategy: {signal.strategy})"
            )

        # Check max options positions
        current_options = len(self.db.get_option_positions())
        if current_options >= settings.MAX_OPTIONS_POSITIONS:
            logger.info(f"Max options positions ({settings.MAX_OPTIONS_POSITIONS}) reached, skipping")
            return

        # Handle spread orders differently
        if is_spread:
            self._execute_spread_signal(signal)
        else:
            self._execute_single_leg_signal(signal)

    def _execute_single_leg_signal(self, signal: OptionsSignal) -> None:
        """Execute a single-leg option signal."""
        # Check if we already have this exact option position
        existing_option = self.db.get_option_position(signal.contract_symbol)
        if existing_option:
            logger.info(f"Already have option position {signal.contract_symbol}, skipping")
            return

        # Get the contract details
        contract = self.client.get_option_quote(signal.contract_symbol)
        if not contract:
            logger.warning(f"Could not get quote for {signal.contract_symbol}")
            return

        # Calculate position size
        position_size = self.position_sizer.calculate_option_position_size(
            contract=contract,
            is_debit=(signal.direction.value == "long")  # Buying = debit
        )

        if not position_size.valid:
            logger.warning(f"Invalid options position size: {position_size.reason}")
            return

        # Validate Greeks
        if contract.greeks:
            greeks_valid, greeks_reason = self.position_sizer.validate_options_greeks(
                position_size.contracts,
                contract
            )
            if not greeks_valid:
                logger.warning(f"Greeks validation failed: {greeks_reason}")
                return

        # Execute the options trade
        result = self.order_manager.execute_option_entry(
            contract=contract,
            quantity=position_size.contracts,
            strategy=signal.strategy
        )

        if result.success:
            self._trades_today += 1
            logger.info(
                f"Options trade executed: {position_size.contracts} contracts "
                f"{signal.contract_symbol} @ ${result.filled_legs[0]['price']:.2f} "
                f"(premium: ${position_size.total_premium:.2f})"
            )

            # Record signal
            from src.storage.database import Signal as DBSignal
            db_signal = DBSignal(
                id=None,
                symbol=signal.symbol,
                direction=signal.direction.value,
                confidence=signal.confidence,
                strategy=signal.strategy,
                timestamp=signal.timestamp,
                taken=True,
                reason=f"options_{signal.contract_type}"
            )
            self.db.insert_signal(db_signal)
        else:
            logger.warning(f"Options trade failed for {signal.contract_symbol}: {result.message}")

    def _execute_spread_signal(self, signal: OptionsSignal) -> None:
        """Execute a multi-leg spread signal."""
        spread_type = signal.metadata.get('spread_type', 'vertical_spread')

        # Execute spread order
        result = self.order_manager.execute_spread_entry(
            legs=signal.legs,
            spread_type=spread_type,
            strategy=signal.strategy
        )

        if result.success:
            self._trades_today += 1
            logger.info(
                f"Spread executed: {spread_type} on {signal.symbol} "
                f"net premium ${result.net_premium:.2f} "
                f"max risk ${signal.max_risk:.2f} max profit ${signal.max_profit:.2f}"
            )

            # Record signal
            from src.storage.database import Signal as DBSignal
            db_signal = DBSignal(
                id=None,
                symbol=signal.symbol,
                direction=signal.direction.value,
                confidence=signal.confidence,
                strategy=signal.strategy,
                timestamp=signal.timestamp,
                taken=True,
                reason=f"options_spread_{spread_type}"
            )
            self.db.insert_signal(db_signal)
        else:
            logger.warning(f"Spread execution failed for {signal.symbol}: {result.message}")

    def _would_be_day_trade(self, symbol: str) -> bool:
        """Check if closing a position today would be a day trade."""
        return self.pdt_tracker.is_position_from_today(symbol)

    def _check_risk_limits(self) -> bool:
        """
        Check if risk limits have been breached.

        Returns:
            True if within limits, False if breached
        """
        try:
            account = self.client.get_account()
            current_value = account.portfolio_value

            if self._peak_portfolio_value and self._peak_portfolio_value > 0:
                if current_value > self._peak_portfolio_value:
                    self._peak_portfolio_value = current_value

                drawdown = (self._peak_portfolio_value - current_value) / self._peak_portfolio_value
                if drawdown >= settings.MAX_DRAWDOWN_HALT:
                    logger.error(f"Max drawdown breached: {drawdown:.1%}")
                    notifications.notify_drawdown_warning(drawdown, settings.MAX_DRAWDOWN_HALT)
                    return False

            if self._daily_starting_value and self._daily_starting_value > 0:
                daily_pnl = (current_value - self._daily_starting_value) / self._daily_starting_value
                if daily_pnl <= -settings.DAILY_LOSS_LIMIT:
                    logger.error(f"Daily loss limit breached: {daily_pnl:.1%}")
                    return False

            if self._weekly_starting_value and self._weekly_starting_value > 0:
                weekly_pnl = (current_value - self._weekly_starting_value) / self._weekly_starting_value
                if weekly_pnl <= -settings.WEEKLY_LOSS_LIMIT:
                    logger.error(f"Weekly loss limit breached: {weekly_pnl:.1%}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error checking risk limits: {e}")
            return True

    def _halt_trading(self, reason: str) -> None:
        """Halt all trading activity."""
        logger.error(f"TRADING HALTED: {reason}")
        notifications.notify_trading_halted(reason)

        for strategy in self.strategies:
            strategy.enabled = False

    def _log_status(self) -> None:
        """Log current status."""
        try:
            account = self.client.get_account()
            positions = self.client.get_positions()
            pdt_status = self.pdt_tracker.get_pdt_status()
            wash_sale_status = self.wash_sale_tracker.get_wash_sale_status()

            logger.info("-" * 40)
            logger.info(f"Portfolio: ${account.portfolio_value:,.2f}")
            logger.info(f"Positions: {len(positions)}")

            # Options positions summary
            if settings.OPTIONS_ENABLED:
                option_positions = self.db.get_option_positions()
                if option_positions:
                    logger.info(f"Options Positions: {len(option_positions)}/{settings.MAX_OPTIONS_POSITIONS}")
                    total_option_premium = sum(
                        pos['entry_price'] * pos['quantity'] * 100
                        for pos in option_positions
                    )
                    logger.info(f"Options Premium: ${total_option_premium:,.2f}")

            logger.info(f"Day Trades Used: {pdt_status['day_trades_used']}/{settings.MAX_DAY_TRADES}")
            logger.info(f"Trades Today: {self._trades_today}")
            if wash_sale_status['restricted_count'] > 0:
                logger.info(f"Wash Sale Restricted: {wash_sale_status['restricted_symbols']}")
            logger.info("-" * 40)

        except Exception as e:
            logger.error(f"Error logging status: {e}")

    def _end_of_day_summary(self) -> None:
        """Generate end of day summary."""
        try:
            account = self.client.get_account()
            trades = self.db.get_trades_by_date_range(
                datetime.now().date(),
                datetime.now().date()
            )

            closed_trades = [t for t in trades if t.exit_time]
            winning_trades = len([t for t in closed_trades if t.pnl and t.pnl > 0])
            total_pnl = sum(t.pnl for t in closed_trades if t.pnl) or 0

            logger.info("=" * 40)
            logger.info("END OF DAY SUMMARY")
            logger.info("=" * 40)
            logger.info(f"Total Trades: {len(closed_trades)}")
            logger.info(f"Winning Trades: {winning_trades}")
            logger.info(f"Daily P&L: ${total_pnl:+,.2f}")
            logger.info(f"Portfolio Value: ${account.portfolio_value:,.2f}")
            logger.info("=" * 40)

            self.db.update_daily_performance(
                day=datetime.now().date(),
                total_trades=len(closed_trades),
                winning_trades=winning_trades,
                losing_trades=len(closed_trades) - winning_trades,
                total_pnl=total_pnl,
                portfolio_value=account.portfolio_value,
                day_trades_used=self.pdt_tracker.get_day_trades_used()
            )

            notifications.notify_daily_summary(
                total_trades=len(closed_trades),
                winning_trades=winning_trades,
                total_pnl=total_pnl,
                portfolio_value=account.portfolio_value
            )

            self._trades_today = 0
            self._daily_starting_value = account.portfolio_value

        except Exception as e:
            logger.error(f"Error generating daily summary: {e}")

    def _weekly_reset(self) -> None:
        """Reset weekly tracking."""
        try:
            account = self.client.get_account()
            self._weekly_starting_value = account.portfolio_value
            logger.info(f"Weekly reset. Starting value: ${account.portfolio_value:,.2f}")

            for strategy in self.strategies:
                strategy.enabled = True
                strategy.weight = 0.25

        except Exception as e:
            logger.error(f"Error in weekly reset: {e}")

    def _handle_shutdown(self, signum, frame) -> None:
        """Handle shutdown signal."""
        logger.info("Shutdown signal received")
        self.running = False

        logger.info("Cancelling open orders...")
        self.order_manager.cancel_open_orders()

        logger.info("Bot shutdown complete")

    def stop(self) -> None:
        """Stop the trading bot."""
        self.running = False


def main():
    """Main entry point."""
    setup_logger()

    logger.info("Stocker Trader Bot v1.0.0")
    logger.info(f"Mode: {'PAPER' if settings.is_paper_trading() else 'LIVE'}")

    bot = TradingBot()

    try:
        bot.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
