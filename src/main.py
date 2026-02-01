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
from src.risk.position_sizer import PositionSizer
from src.risk.stop_manager import StopManager
from src.strategies.technical.rsi_strategy import RSIStrategy

logger = get_logger(__name__)


class TradingBot:
    """Main trading bot controller."""

    def __init__(self):
        self.running = False
        self.client = get_alpaca_client()
        self.db = get_database()
        self.order_manager = OrderManager(self.client)
        self.pdt_tracker = PDTTracker(self.client)
        self.position_sizer = PositionSizer(self.client)
        self.stop_manager = StopManager(self.client, self.order_manager)

        self.strategies = [
            RSIStrategy()
        ]

        self.watchlist = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "NVDA", "TSLA", "AMD", "NFLX", "SPY"
        ]

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
        market_open = now.replace(
            hour=settings.MARKET_OPEN_HOUR,
            minute=settings.MARKET_OPEN_MINUTE + settings.AVOID_FIRST_MINUTES,
            second=0
        )
        market_close = now.replace(
            hour=settings.MARKET_CLOSE_HOUR,
            minute=settings.MARKET_CLOSE_MINUTE - settings.AVOID_LAST_MINUTES,
            second=0
        )

        return market_open <= now <= market_close

    def _check_positions(self) -> None:
        """Check existing positions for stop conditions."""
        if not self.client.is_market_open():
            return

        try:
            self.stop_manager.execute_stop_exits()

            if not self._check_risk_limits():
                self._halt_trading("Risk limit breached")

        except Exception as e:
            logger.error(f"Error checking positions: {e}")

    def _scan_for_signals(self) -> None:
        """Scan watchlist for trading signals."""
        if not self._is_trading_time():
            return

        if self._trades_today >= settings.MAX_TRADES_PER_DAY:
            logger.info("Max daily trades reached, skipping scan")
            return

        try:
            for strategy in self.strategies:
                if not strategy.enabled:
                    continue

                signals = strategy.analyze(self.watchlist)

                for signal in signals:
                    if signal.is_actionable(settings.SIGNAL_THRESHOLD):
                        self._process_signal(signal)

        except Exception as e:
            logger.error(f"Error scanning for signals: {e}")

    def _process_signal(self, signal) -> None:
        """Process and potentially execute a trading signal."""
        logger.info(
            f"Signal: {signal.direction.value.upper()} {signal.symbol} "
            f"(confidence: {signal.confidence:.2f}, strategy: {signal.strategy})"
        )

        existing_position = self.client.get_position(signal.symbol)
        if existing_position:
            logger.info(f"Already have position in {signal.symbol}, skipping")
            return

        if signal.direction.value == "long":
            is_day_trade = self._would_be_day_trade(signal.symbol)
            if is_day_trade and not self.pdt_tracker.can_day_trade(signal.confidence):
                logger.info(f"Skipping {signal.symbol} - would use day trade for low confidence signal")
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

            logger.info("-" * 40)
            logger.info(f"Portfolio: ${account.portfolio_value:,.2f}")
            logger.info(f"Positions: {len(positions)}")
            logger.info(f"Day Trades Used: {pdt_status['day_trades_used']}/{settings.MAX_DAY_TRADES}")
            logger.info(f"Trades Today: {self._trades_today}")
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
