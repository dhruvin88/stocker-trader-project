import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """Central configuration for the trading bot."""

    # Broker - Alpaca
    ALPACA_API_KEY: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    ALPACA_SECRET_KEY: str = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    ALPACA_BASE_URL: str = field(
        default_factory=lambda: os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    )
    PAPER_TRADING: bool = True

    # Risk Management
    MAX_RISK_PER_TRADE: float = 0.02  # 2% max risk per trade
    DAILY_LOSS_LIMIT: float = 0.03  # 3% daily loss limit
    WEEKLY_LOSS_LIMIT: float = 0.07  # 7% weekly loss limit
    MAX_DRAWDOWN_HALT: float = 0.10  # 10% drawdown triggers halt
    MAX_POSITION_SIZE: float = 0.10  # 10% max per symbol
    MAX_POSITIONS: int = 10  # Max concurrent positions
    MAX_TRADES_PER_DAY: int = 10  # Max trades per day

    # PDT Rules
    MAX_DAY_TRADES: int = 3  # PDT rule limit
    PDT_ROLLING_DAYS: int = 5  # Rolling window for PDT
    HIGH_CONVICTION_THRESHOLD: float = 0.8  # Reserve day trades for high scores

    # Trading Hours (ET)
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 30
    MARKET_CLOSE_HOUR: int = 16
    MARKET_CLOSE_MINUTE: int = 0
    AVOID_FIRST_MINUTES: int = 30  # Avoid trading first 30 min
    AVOID_LAST_MINUTES: int = 30  # Avoid trading last 30 min

    # Scanner Settings
    MIN_VOLUME: int = 1_000_000  # Minimum average daily volume
    MIN_PRICE: float = 5.0  # Minimum stock price
    MAX_PRICE: float = 500.0  # Maximum stock price
    UNIVERSE_SIZE: int = 50  # Number of stocks to track
    MIN_ATR_PERCENT: float = 0.02  # Minimum ATR as % of price
    MAX_ATR_PERCENT: float = 0.08  # Maximum ATR as % of price

    # Strategy Settings
    MIN_WIN_RATE: float = 0.40  # Minimum win rate before disabling
    ROLLING_TRADES: int = 20  # Trades for rolling performance
    GRADUAL_REENTRY_START: float = 0.25  # Start weight for re-enabled strategies
    SIGNAL_THRESHOLD: float = 0.6  # Minimum score to execute trade

    # Order Settings
    ORDER_TIMEOUT_SECONDS: int = 60  # Timeout for limit orders
    LIMIT_ORDER_OFFSET: float = 0.001  # 0.1% offset from current price
    MAX_RETRIES: int = 3  # Max retries for failed orders
    RETRY_DELAY_SECONDS: int = 5  # Delay between retries

    # Exit Rules
    DEFAULT_STOP_LOSS: float = 0.02  # 2% default stop loss
    DEFAULT_TAKE_PROFIT: float = 0.04  # 4% default take profit
    TRAILING_STOP_ACTIVATION: float = 0.02  # Activate trailing at 2% profit
    TRAILING_STOP_DISTANCE: float = 0.01  # 1% trailing distance

    # Data Storage
    DATABASE_PATH: str = "data/stocker_trader.db"
    LOG_PATH: str = "logs"
    LOG_LEVEL: str = "INFO"

    # Notifications
    SMTP_SERVER: str = field(default_factory=lambda: os.getenv("SMTP_SERVER", ""))
    SMTP_PORT: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    SMTP_USER: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    SMTP_PASSWORD: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    NOTIFICATION_EMAIL: str = field(default_factory=lambda: os.getenv("NOTIFICATION_EMAIL", ""))

    # Twilio
    TWILIO_ACCOUNT_SID: str = field(default_factory=lambda: os.getenv("TWILIO_ACCOUNT_SID", ""))
    TWILIO_AUTH_TOKEN: str = field(default_factory=lambda: os.getenv("TWILIO_AUTH_TOKEN", ""))
    TWILIO_FROM_NUMBER: str = field(default_factory=lambda: os.getenv("TWILIO_FROM_NUMBER", ""))
    TWILIO_TO_NUMBER: str = field(default_factory=lambda: os.getenv("TWILIO_TO_NUMBER", ""))

    def is_paper_trading(self) -> bool:
        """Check if currently in paper trading mode."""
        return self.PAPER_TRADING or "paper" in self.ALPACA_BASE_URL.lower()

    def validate(self) -> list[str]:
        """Validate settings and return list of errors."""
        errors = []
        if not self.ALPACA_API_KEY:
            errors.append("ALPACA_API_KEY is required")
        if not self.ALPACA_SECRET_KEY:
            errors.append("ALPACA_SECRET_KEY is required")
        if self.MAX_RISK_PER_TRADE > 0.05:
            errors.append("MAX_RISK_PER_TRADE should not exceed 5%")
        if self.MAX_POSITIONS < 1:
            errors.append("MAX_POSITIONS must be at least 1")
        return errors


# Global settings instance
settings = Settings()
