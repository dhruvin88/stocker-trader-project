"""
Backtesting Engine for Stocker Trader Bot

Provides a framework for backtesting trading strategies on historical data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np

from src.strategies.base import BaseStrategy, Signal, SignalDirection
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestTrade:
    """Represents a trade during backtesting."""
    symbol: str
    direction: str
    entry_time: datetime
    entry_price: float
    quantity: int
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    strategy: str = ""
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: list[BacktestTrade]
    equity_curve: pd.Series


class BacktestEngine:
    """
    Backtesting engine for trading strategies.

    Usage:
        engine = BacktestEngine(initial_capital=10000)
        engine.add_strategy(RSIStrategy())
        result = engine.run(data, start_date, end_date)
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_position_size: float = 0.1,
        max_risk_per_trade: float = 0.02,
        commission: float = 0.0
    ):
        self.initial_capital = initial_capital
        self.max_position_size = max_position_size
        self.max_risk_per_trade = max_risk_per_trade
        self.commission = commission

        self.strategies: list[BaseStrategy] = []
        self.capital = initial_capital
        self.positions: dict[str, BacktestTrade] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[float] = []
        self.equity_dates: list[datetime] = []

    def add_strategy(self, strategy: BaseStrategy) -> None:
        """Add a strategy to backtest."""
        self.strategies.append(strategy)
        logger.info(f"Added strategy: {strategy.name}")

    def run(
        self,
        data: dict[str, pd.DataFrame],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            data: Dict mapping symbol to DataFrame with OHLCV data
            start_date: Start of backtest period
            end_date: End of backtest period

        Returns:
            BacktestResult with performance metrics
        """
        if not self.strategies:
            raise ValueError("No strategies added")

        if not data:
            raise ValueError("No data provided")

        self._reset()

        first_df = list(data.values())[0]
        all_dates = first_df["datetime"].sort_values().unique()

        if start_date:
            all_dates = [d for d in all_dates if d >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d <= end_date]

        logger.info(f"Running backtest from {all_dates[0]} to {all_dates[-1]}")
        logger.info(f"Symbols: {list(data.keys())}")

        for current_date in all_dates:
            self._check_exits(data, current_date)
            self._check_entries(data, current_date)

            current_equity = self._calculate_equity(data, current_date)
            self.equity_curve.append(current_equity)
            self.equity_dates.append(current_date)

        self._close_all_positions(data, all_dates[-1])

        return self._calculate_results(all_dates[0], all_dates[-1])

    def _reset(self) -> None:
        """Reset engine state for a new backtest."""
        self.capital = self.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self.equity_dates = []

    def _check_entries(
        self,
        data: dict[str, pd.DataFrame],
        current_date: datetime
    ) -> None:
        """Check for entry signals."""
        for symbol, df in data.items():
            if symbol in self.positions:
                continue

            historical = df[df["datetime"] <= current_date]
            if len(historical) < 50:
                continue

            for strategy in self.strategies:
                if not strategy.enabled:
                    continue

                signal = strategy.get_signal(symbol, {"1Hour": historical})

                if signal.is_actionable():
                    self._execute_entry(signal, current_date, historical)
                    break

    def _check_exits(
        self,
        data: dict[str, pd.DataFrame],
        current_date: datetime
    ) -> None:
        """Check positions for exit conditions."""
        symbols_to_exit = []

        for symbol, position in self.positions.items():
            if symbol not in data:
                continue

            df = data[symbol]
            current_data = df[df["datetime"] == current_date]

            if current_data.empty:
                continue

            current_price = float(current_data["close"].iloc[0])

            should_exit, reason = self._check_stop_conditions(
                position, current_price
            )

            if should_exit:
                symbols_to_exit.append((symbol, current_price, reason, current_date))

        for symbol, price, reason, date in symbols_to_exit:
            self._execute_exit(symbol, price, reason, date)

    def _check_stop_conditions(
        self,
        position: BacktestTrade,
        current_price: float
    ) -> tuple[bool, str]:
        """Check if stop conditions are met."""
        if position.direction == "long":
            pnl_pct = (current_price - position.entry_price) / position.entry_price

            stop_loss = position.entry_price * 0.98
            if current_price <= stop_loss:
                return True, "stop_loss"

            take_profit = position.entry_price * 1.04
            if current_price >= take_profit:
                return True, "take_profit"

        else:  # short
            pnl_pct = (position.entry_price - current_price) / position.entry_price

            stop_loss = position.entry_price * 1.02
            if current_price >= stop_loss:
                return True, "stop_loss"

            take_profit = position.entry_price * 0.96
            if current_price <= take_profit:
                return True, "take_profit"

        return False, ""

    def _execute_entry(
        self,
        signal: Signal,
        current_date: datetime,
        data: pd.DataFrame
    ) -> None:
        """Execute an entry trade."""
        current_price = float(data["close"].iloc[-1])

        position_value = self.capital * self.max_position_size
        quantity = int(position_value / current_price)

        if quantity <= 0:
            return

        cost = quantity * current_price * (1 + self.commission)
        if cost > self.capital:
            return

        self.capital -= cost

        trade = BacktestTrade(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_time=current_date,
            entry_price=current_price,
            quantity=quantity,
            strategy=signal.strategy
        )

        self.positions[signal.symbol] = trade
        logger.debug(
            f"Entry: {signal.direction.value.upper()} {quantity} {signal.symbol} "
            f"@ ${current_price:.2f}"
        )

    def _execute_exit(
        self,
        symbol: str,
        exit_price: float,
        reason: str,
        exit_date: datetime
    ) -> None:
        """Execute an exit trade."""
        position = self.positions.pop(symbol)

        proceeds = position.quantity * exit_price * (1 - self.commission)

        if position.direction == "long":
            pnl = (exit_price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - exit_price) * position.quantity

        pnl_pct = pnl / (position.entry_price * position.quantity)

        self.capital += proceeds

        position.exit_time = exit_date
        position.exit_price = exit_price
        position.pnl = pnl
        position.pnl_percent = pnl_pct
        position.exit_reason = reason

        self.trades.append(position)

        logger.debug(
            f"Exit: {symbol} @ ${exit_price:.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2%}) | {reason}"
        )

    def _close_all_positions(
        self,
        data: dict[str, pd.DataFrame],
        final_date: datetime
    ) -> None:
        """Close all remaining positions at end of backtest."""
        for symbol in list(self.positions.keys()):
            if symbol in data:
                df = data[symbol]
                final_data = df[df["datetime"] == final_date]

                if not final_data.empty:
                    final_price = float(final_data["close"].iloc[0])
                    self._execute_exit(symbol, final_price, "end_of_backtest", final_date)

    def _calculate_equity(
        self,
        data: dict[str, pd.DataFrame],
        current_date: datetime
    ) -> float:
        """Calculate current portfolio equity."""
        equity = self.capital

        for symbol, position in self.positions.items():
            if symbol in data:
                df = data[symbol]
                current_data = df[df["datetime"] == current_date]

                if not current_data.empty:
                    current_price = float(current_data["close"].iloc[0])
                    equity += position.quantity * current_price

        return equity

    def _calculate_results(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResult:
        """Calculate final backtest results."""
        final_capital = self.capital + sum(
            pos.quantity * pos.entry_price for pos in self.positions.values()
        )

        total_return = final_capital - self.initial_capital
        total_return_pct = total_return / self.initial_capital

        completed_trades = [t for t in self.trades if t.pnl is not None]
        winning = [t for t in completed_trades if t.pnl > 0]
        losing = [t for t in completed_trades if t.pnl <= 0]

        win_rate = len(winning) / len(completed_trades) if completed_trades else 0
        avg_win = np.mean([t.pnl for t in winning]) if winning else 0
        avg_loss = abs(np.mean([t.pnl for t in losing])) if losing else 0

        gross_profit = sum(t.pnl for t in winning) if winning else 0
        gross_loss = abs(sum(t.pnl for t in losing)) if losing else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        equity_series = pd.Series(self.equity_curve, index=self.equity_dates)
        rolling_max = equity_series.cummax()
        drawdown = equity_series - rolling_max
        max_drawdown = abs(drawdown.min())
        max_drawdown_pct = max_drawdown / rolling_max[drawdown.idxmin()] if len(drawdown) > 0 else 0

        returns = equity_series.pct_change().dropna()
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252) if len(returns) > 1 and returns.std() > 0 else 0

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            total_trades=len(completed_trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades,
            equity_curve=equity_series
        )

    def print_results(self, result: BacktestResult) -> None:
        """Print backtest results."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"Period: {result.start_date} to {result.end_date}")
        print(f"Initial Capital: ${result.initial_capital:,.2f}")
        print(f"Final Capital: ${result.final_capital:,.2f}")
        print(f"Total Return: ${result.total_return:+,.2f} ({result.total_return_pct:+.2%})")
        print("-" * 60)
        print(f"Total Trades: {result.total_trades}")
        print(f"Winning Trades: {result.winning_trades}")
        print(f"Losing Trades: {result.losing_trades}")
        print(f"Win Rate: {result.win_rate:.2%}")
        print("-" * 60)
        print(f"Average Win: ${result.avg_win:,.2f}")
        print(f"Average Loss: ${result.avg_loss:,.2f}")
        print(f"Profit Factor: {result.profit_factor:.2f}")
        print("-" * 60)
        print(f"Max Drawdown: ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.2%})")
        print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print("=" * 60 + "\n")
