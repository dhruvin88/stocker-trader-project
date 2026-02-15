import sqlite3
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Any
from contextlib import contextmanager
from dataclasses import dataclass

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Trade:
    """Represents a completed trade."""
    id: Optional[int]
    symbol: str
    direction: str  # 'long' or 'short'
    entry_time: datetime
    entry_price: float
    quantity: int
    exit_time: Optional[datetime]
    exit_price: Optional[float]
    pnl: Optional[float]
    pnl_percent: Optional[float]
    strategy: str
    is_day_trade: bool
    notes: Optional[str]


@dataclass
class Signal:
    """Represents a trading signal."""
    id: Optional[int]
    symbol: str
    direction: str
    confidence: float
    strategy: str
    timestamp: datetime
    taken: bool
    reason: Optional[str]


class Database:
    """SQLite database wrapper for the trading bot."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    exit_time TIMESTAMP,
                    exit_price REAL,
                    pnl REAL,
                    pnl_percent REAL,
                    strategy TEXT NOT NULL,
                    is_day_trade BOOLEAN DEFAULT 0,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    taken BOOLEAN DEFAULT 0,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL UNIQUE,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    portfolio_value REAL,
                    day_trades_used INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategy_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    date DATE NOT NULL,
                    trades INTEGER DEFAULT 0,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    avg_win REAL,
                    avg_loss REAL,
                    win_rate REAL,
                    expectancy REAL,
                    weight REAL,
                    enabled BOOLEAN DEFAULT 1,
                    UNIQUE(strategy, date)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pdt_tracker (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date DATE NOT NULL,
                    symbol TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    trailing_stop REAL,
                    strategy TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wash_sale_tracker (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    exit_date DATE NOT NULL,
                    exit_price REAL NOT NULL,
                    loss_amount REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Options tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_symbol TEXT UNIQUE NOT NULL,
                    underlying TEXT NOT NULL,
                    contract_type TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiration DATE NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    current_delta REAL,
                    current_theta REAL,
                    strategy TEXT,
                    spread_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (spread_id) REFERENCES option_spreads(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_spreads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    underlying TEXT NOT NULL,
                    spread_type TEXT NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    net_premium REAL NOT NULL,
                    max_risk REAL NOT NULL,
                    max_profit REAL NOT NULL,
                    strategy TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_symbol TEXT NOT NULL,
                    underlying TEXT NOT NULL,
                    contract_type TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiration DATE NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_time TIMESTAMP NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_time TIMESTAMP,
                    exit_price REAL,
                    pnl REAL,
                    pnl_percent REAL,
                    exit_reason TEXT,
                    strategy TEXT,
                    spread_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (spread_id) REFERENCES option_spreads(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS options_chain_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    underlying TEXT NOT NULL,
                    contract_symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    expiration DATE NOT NULL,
                    contract_type TEXT NOT NULL,
                    bid REAL,
                    ask REAL,
                    volume INTEGER,
                    open_interest INTEGER,
                    implied_volatility REAL,
                    delta REAL,
                    gamma REAL,
                    theta REAL,
                    vega REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(contract_symbol, timestamp)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pdt_date ON pdt_tracker(trade_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wash_sale_symbol ON wash_sale_tracker(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wash_sale_date ON wash_sale_tracker(exit_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chain_cache_symbol ON options_chain_cache(underlying, expiration)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_option_positions_underlying ON option_positions(underlying)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_option_trades_underlying ON option_trades(underlying)")

        logger.info(f"Database initialized at {self.db_path}")

    def insert_trade(self, trade: Trade) -> int:
        """Insert a new trade record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    symbol, direction, entry_time, entry_price, quantity,
                    exit_time, exit_price, pnl, pnl_percent, strategy,
                    is_day_trade, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.symbol, trade.direction, trade.entry_time, trade.entry_price,
                trade.quantity, trade.exit_time, trade.exit_price, trade.pnl,
                trade.pnl_percent, trade.strategy, trade.is_day_trade, trade.notes
            ))
            return cursor.lastrowid

    def update_trade_exit(
        self,
        trade_id: int,
        exit_time: datetime,
        exit_price: float,
        pnl: float,
        pnl_percent: float
    ) -> None:
        """Update a trade with exit information."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE trades
                SET exit_time = ?, exit_price = ?, pnl = ?, pnl_percent = ?
                WHERE id = ?
            """, (exit_time, exit_price, pnl, pnl_percent, trade_id))

    def get_open_trades(self) -> list[Trade]:
        """Get all trades without an exit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades WHERE exit_time IS NULL
            """)
            rows = cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    def get_trades_by_strategy(
        self,
        strategy: str,
        limit: int = 20
    ) -> list[Trade]:
        """Get recent trades for a specific strategy."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades
                WHERE strategy = ? AND exit_time IS NOT NULL
                ORDER BY exit_time DESC
                LIMIT ?
            """, (strategy, limit))
            rows = cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    def get_trades_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> list[Trade]:
        """Get trades within a date range."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades
                WHERE DATE(entry_time) >= ? AND DATE(entry_time) <= ?
                ORDER BY entry_time DESC
            """, (start_date, end_date))
            rows = cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    def _row_to_trade(self, row: sqlite3.Row) -> Trade:
        """Convert a database row to a Trade object."""
        return Trade(
            id=row["id"],
            symbol=row["symbol"],
            direction=row["direction"],
            entry_time=datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else None,
            entry_price=row["entry_price"],
            quantity=row["quantity"],
            exit_time=datetime.fromisoformat(row["exit_time"]) if row["exit_time"] else None,
            exit_price=row["exit_price"],
            pnl=row["pnl"],
            pnl_percent=row["pnl_percent"],
            strategy=row["strategy"],
            is_day_trade=bool(row["is_day_trade"]),
            notes=row["notes"]
        )

    def insert_signal(self, signal: Signal) -> int:
        """Insert a new signal record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO signals (
                    symbol, direction, confidence, strategy, timestamp, taken, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.symbol, signal.direction, signal.confidence,
                signal.strategy, signal.timestamp, signal.taken, signal.reason
            ))
            return cursor.lastrowid

    def record_day_trade(self, symbol: str, trade_date: date) -> None:
        """Record a day trade for PDT tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pdt_tracker (trade_date, symbol)
                VALUES (?, ?)
            """, (trade_date, symbol))

    def get_day_trades_in_window(self, days: int = 5) -> int:
        """Get the count of day trades in the rolling window."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM pdt_tracker
                WHERE trade_date >= DATE('now', ?)
            """, (f"-{days} days",))
            row = cursor.fetchone()
            return row["count"] if row else 0

    def get_day_trade_dates(self, days: int = 5) -> list[date]:
        """Get dates of day trades in the rolling window."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT trade_date FROM pdt_tracker
                WHERE trade_date >= DATE('now', ?)
                ORDER BY trade_date DESC
            """, (f"-{days} days",))
            rows = cursor.fetchall()
            return [date.fromisoformat(row["trade_date"]) for row in rows]

    def record_wash_sale(
        self,
        symbol: str,
        exit_date: date,
        exit_price: float,
        loss_amount: float
    ) -> None:
        """Record a wash sale (symbol sold at a loss)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO wash_sale_tracker (symbol, exit_date, exit_price, loss_amount)
                VALUES (?, ?, ?, ?)
            """, (symbol, exit_date, exit_price, loss_amount))

    def get_wash_sales_in_window(self, days: int = 30) -> list[dict]:
        """Get all wash sales within the specified window."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM wash_sale_tracker
                WHERE exit_date >= DATE('now', ?)
                ORDER BY exit_date DESC
            """, (f"-{days} days",))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def is_symbol_in_wash_window(self, symbol: str, days: int = 30) -> bool:
        """Check if a symbol was sold at a loss within the window."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM wash_sale_tracker
                WHERE symbol = ? AND exit_date >= DATE('now', ?)
            """, (symbol, f"-{days} days"))
            row = cursor.fetchone()
            return row["count"] > 0 if row else False

    def cleanup_old_wash_sales(self, days: int = 30) -> int:
        """Remove wash sale records older than the specified window."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM wash_sale_tracker
                WHERE exit_date < DATE('now', ?)
            """, (f"-{days} days",))
            return cursor.rowcount

    def update_daily_performance(
        self,
        day: date,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_pnl: float,
        portfolio_value: float,
        day_trades_used: int
    ) -> None:
        """Update or insert daily performance record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_performance (
                    date, total_trades, winning_trades, losing_trades,
                    total_pnl, portfolio_value, day_trades_used
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total_trades = ?,
                    winning_trades = ?,
                    losing_trades = ?,
                    total_pnl = ?,
                    portfolio_value = ?,
                    day_trades_used = ?
            """, (
                day, total_trades, winning_trades, losing_trades,
                total_pnl, portfolio_value, day_trades_used,
                total_trades, winning_trades, losing_trades,
                total_pnl, portfolio_value, day_trades_used
            ))

    def get_daily_performance(self, day: date) -> Optional[dict]:
        """Get performance for a specific day."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM daily_performance WHERE date = ?
            """, (day,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_strategy_metrics(
        self,
        strategy: str,
        day: date,
        trades: int,
        wins: int,
        losses: int,
        total_pnl: float,
        weight: float,
        enabled: bool
    ) -> None:
        """Update strategy metrics for a day."""
        win_rate = wins / trades if trades > 0 else 0
        avg_win = total_pnl / wins if wins > 0 and total_pnl > 0 else 0
        avg_loss = abs(total_pnl / losses) if losses > 0 and total_pnl < 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if trades > 0 else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO strategy_metrics (
                    strategy, date, trades, wins, losses, total_pnl,
                    avg_win, avg_loss, win_rate, expectancy, weight, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy, date) DO UPDATE SET
                    trades = ?, wins = ?, losses = ?, total_pnl = ?,
                    avg_win = ?, avg_loss = ?, win_rate = ?, expectancy = ?,
                    weight = ?, enabled = ?
            """, (
                strategy, day, trades, wins, losses, total_pnl,
                avg_win, avg_loss, win_rate, expectancy, weight, enabled,
                trades, wins, losses, total_pnl,
                avg_win, avg_loss, win_rate, expectancy, weight, enabled
            ))

    def get_strategy_performance(self, strategy: str, days: int = 30) -> list[dict]:
        """Get strategy performance over recent days."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM strategy_metrics
                WHERE strategy = ? AND date >= DATE('now', ?)
                ORDER BY date DESC
            """, (strategy, f"-{days} days"))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def save_position(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        entry_time: datetime,
        stop_loss: Optional[float],
        take_profit: Optional[float],
        strategy: str
    ) -> None:
        """Save or update a position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO positions (
                    symbol, quantity, entry_price, entry_time,
                    stop_loss, take_profit, strategy
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = ?, entry_price = ?, entry_time = ?,
                    stop_loss = ?, take_profit = ?, strategy = ?,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                symbol, quantity, entry_price, entry_time,
                stop_loss, take_profit, strategy,
                quantity, entry_price, entry_time,
                stop_loss, take_profit, strategy
            ))

    def remove_position(self, symbol: str) -> None:
        """Remove a position from tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))

    def get_positions(self) -> list[dict]:
        """Get all tracked positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get a specific position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_position_stops(
        self,
        symbol: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop: Optional[float] = None
    ) -> None:
        """Update stop levels for a position."""
        updates = []
        params = []
        if stop_loss is not None:
            updates.append("stop_loss = ?")
            params.append(stop_loss)
        if take_profit is not None:
            updates.append("take_profit = ?")
            params.append(take_profit)
        if trailing_stop is not None:
            updates.append("trailing_stop = ?")
            params.append(trailing_stop)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(symbol)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"UPDATE positions SET {', '.join(updates)} WHERE symbol = ?",
                    params
                )

    # Options trading methods

    def save_option_position(
        self,
        contract_symbol: str,
        underlying: str,
        contract_type: str,
        strike: float,
        expiration: date,
        quantity: int,
        entry_price: float,
        entry_time: datetime,
        strategy: str,
        spread_id: Optional[int] = None,
        current_delta: Optional[float] = None,
        current_theta: Optional[float] = None
    ) -> int:
        """Save or update an option position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO option_positions (
                    contract_symbol, underlying, contract_type, strike, expiration,
                    quantity, entry_price, entry_time, strategy, spread_id,
                    current_delta, current_theta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contract_symbol) DO UPDATE SET
                    quantity = ?, entry_price = ?, entry_time = ?,
                    current_delta = ?, current_theta = ?,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                contract_symbol, underlying, contract_type, strike, expiration,
                quantity, entry_price, entry_time, strategy, spread_id,
                current_delta, current_theta,
                quantity, entry_price, entry_time, current_delta, current_theta
            ))
            return cursor.lastrowid

    def get_option_positions(self, underlying: Optional[str] = None) -> list[dict]:
        """Get all option positions, optionally filtered by underlying."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if underlying:
                cursor.execute(
                    "SELECT * FROM option_positions WHERE underlying = ?",
                    (underlying,)
                )
            else:
                cursor.execute("SELECT * FROM option_positions")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_option_position(self, contract_symbol: str) -> Optional[dict]:
        """Get a specific option position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM option_positions WHERE contract_symbol = ?",
                (contract_symbol,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def remove_option_position(self, contract_symbol: str) -> None:
        """Remove an option position from tracking."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM option_positions WHERE contract_symbol = ?",
                (contract_symbol,)
            )

    def update_option_greeks(
        self,
        contract_symbol: str,
        delta: float,
        theta: float
    ) -> None:
        """Update Greeks for an option position."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE option_positions
                SET current_delta = ?, current_theta = ?, updated_at = CURRENT_TIMESTAMP
                WHERE contract_symbol = ?
            """, (delta, theta, contract_symbol))

    def insert_option_trade(
        self,
        contract_symbol: str,
        underlying: str,
        contract_type: str,
        strike: float,
        expiration: date,
        quantity: int,
        entry_time: datetime,
        entry_price: float,
        exit_time: Optional[datetime],
        exit_price: Optional[float],
        pnl: Optional[float],
        pnl_percent: Optional[float],
        exit_reason: Optional[str],
        strategy: str,
        spread_id: Optional[int] = None
    ) -> int:
        """Insert a completed option trade."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO option_trades (
                    contract_symbol, underlying, contract_type, strike, expiration,
                    quantity, entry_time, entry_price, exit_time, exit_price,
                    pnl, pnl_percent, exit_reason, strategy, spread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                contract_symbol, underlying, contract_type, strike, expiration,
                quantity, entry_time, entry_price, exit_time, exit_price,
                pnl, pnl_percent, exit_reason, strategy, spread_id
            ))
            return cursor.lastrowid

    def get_option_trades(
        self,
        underlying: Optional[str] = None,
        days: int = 30
    ) -> list[dict]:
        """Get option trades, optionally filtered by underlying and days."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if underlying:
                cursor.execute("""
                    SELECT * FROM option_trades
                    WHERE underlying = ? AND entry_time >= DATE('now', ?)
                    ORDER BY entry_time DESC
                """, (underlying, f"-{days} days"))
            else:
                cursor.execute("""
                    SELECT * FROM option_trades
                    WHERE entry_time >= DATE('now', ?)
                    ORDER BY entry_time DESC
                """, (f"-{days} days",))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def create_spread(
        self,
        underlying: str,
        spread_type: str,
        entry_time: datetime,
        net_premium: float,
        max_risk: float,
        max_profit: float,
        strategy: str
    ) -> int:
        """Create a new option spread record."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO option_spreads (
                    underlying, spread_type, entry_time, net_premium,
                    max_risk, max_profit, strategy
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (underlying, spread_type, entry_time, net_premium,
                  max_risk, max_profit, strategy))
            return cursor.lastrowid

    def get_active_spreads(self, underlying: Optional[str] = None) -> list[dict]:
        """Get all active spreads, optionally filtered by underlying."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if underlying:
                cursor.execute("""
                    SELECT * FROM option_spreads
                    WHERE status = 'open' AND underlying = ?
                    ORDER BY entry_time DESC
                """, (underlying,))
            else:
                cursor.execute("""
                    SELECT * FROM option_spreads
                    WHERE status = 'open'
                    ORDER BY entry_time DESC
                """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_spread(self, spread_id: int) -> Optional[dict]:
        """Get a specific spread."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM option_spreads WHERE id = ?",
                (spread_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_spread_status(self, spread_id: int, status: str) -> None:
        """Update spread status (open, closed, expired, assigned)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE option_spreads
                SET status = ?
                WHERE id = ?
            """, (status, spread_id))

    def get_spread_legs(self, spread_id: int) -> list[dict]:
        """Get all option positions that are part of a spread."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM option_positions
                WHERE spread_id = ?
            """, (spread_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def cache_options_chain(
        self,
        underlying: str,
        contract_symbol: str,
        strike: float,
        expiration: date,
        contract_type: str,
        bid: float,
        ask: float,
        volume: int,
        open_interest: int,
        implied_volatility: float,
        delta: float,
        gamma: float,
        theta: float,
        vega: float
    ) -> None:
        """Cache options chain data for historical analysis."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO options_chain_cache (
                    underlying, contract_symbol, strike, expiration, contract_type,
                    bid, ask, volume, open_interest, implied_volatility,
                    delta, gamma, theta, vega
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                underlying, contract_symbol, strike, expiration, contract_type,
                bid, ask, volume, open_interest, implied_volatility,
                delta, gamma, theta, vega
            ))

    def get_cached_chain(
        self,
        underlying: str,
        max_age_minutes: int = 15
    ) -> list[dict]:
        """Get cached options chain data."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM options_chain_cache
                WHERE underlying = ?
                AND timestamp >= DATETIME('now', ?)
                ORDER BY timestamp DESC
            """, (underlying, f"-{max_age_minutes} minutes"))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_historical_option_volume(
        self,
        contract_symbol: str,
        days: int = 20
    ) -> list[dict]:
        """Get historical volume data for an option contract."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, volume, open_interest
                FROM options_chain_cache
                WHERE contract_symbol = ?
                AND timestamp >= DATETIME('now', ?)
                ORDER BY timestamp ASC
            """, (contract_symbol, f"-{days} days"))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


_db_instance: Optional[Database] = None


def get_database() -> Database:
    """Get the singleton database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
