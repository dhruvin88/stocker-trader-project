# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the trading bot
python -m src.main

# Run tests
pytest tests/ -v

# Run a single test file
pytest tests/test_strategies.py -v
```

## Environment Setup

Copy `.env.example` to `.env` and configure:
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` - Required for broker connection
- `ALPACA_BASE_URL` - Use `https://paper-api.alpaca.markets` for paper trading
- Optional: SMTP and Twilio settings for notifications

## Architecture Overview

### Entry Point
`src/main.py` - `TradingBot` class orchestrates all components:
- Initializes broker client, strategies, risk managers
- Runs scheduled tasks (1min position checks, 5min signal scans, hourly status, daily summaries)
- Main loop executes during market hours (10:00-15:30 ET by default)

### Core Layers

**Broker Layer** (`src/broker/`)
- `AlpacaClient`: Alpaca API wrapper with rate limiting and retry logic
- `OrderManager`: Executes bracket orders (entry + stop loss + take profit)
- `PDTTracker`: Enforces Pattern Day Trader rules (<$25k accounts get 3 day trades per 5-day window)

**Strategy Layer** (`src/strategies/`)
- `BaseStrategy`: Abstract base class defining `analyze()`, `get_signal()`, `should_exit()`
- Strategies return `Signal` objects with symbol, direction, confidence, entry/stop/target prices
- Currently implemented: `RSIStrategy` (multi-timeframe RSI with EMA trend confirmation)

**Risk Layer** (`src/risk/`)
- `PositionSizer`: Calculates shares based on 1-2% risk rule, enforces position limits
- `StopManager`: Manages hard stops, trailing stops, and take-profit exits

**Storage Layer** (`src/storage/`)
- `Database`: SQLite wrapper for trades, signals, daily_performance, strategy_metrics

### Configuration
`config/settings.py` - Dataclass-based settings with environment variable loading. Key parameters:
- Risk: `MAX_RISK_PER_TRADE` (2%), `DAILY_LOSS_LIMIT` (3%), `MAX_DRAWDOWN_HALT` (10%)
- PDT: `MAX_DAY_TRADES` (3), `HIGH_CONVICTION_THRESHOLD` (0.8)
- Trading: `MAX_POSITIONS` (10), `SIGNAL_THRESHOLD` (0.6)

### Signal Flow
1. Strategies analyze watchlist symbols → generate Signals
2. Signals with confidence >= threshold are processed
3. PDTTracker checks if day trade available (reserves for confidence > 0.8)
4. PositionSizer calculates position size respecting risk limits
5. OrderManager executes bracket order via Alpaca
6. Trade recorded to database, notifications sent
