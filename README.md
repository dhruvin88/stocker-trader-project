# Stocker Trader Bot

An automated stock trading system with conservative risk management, PDT compliance, and multi-strategy support.

## Features

- **Multiple Trading Strategies**: RSI, MACD, Moving Average Crossover (with more to come)
- **Conservative Risk Management**: 1-2% risk per trade, position sizing, daily/weekly loss limits
- **PDT Rule Compliance**: Smart day trade tracking for accounts under $25k
- **Paper Trading Support**: Safe testing with Alpaca paper trading
- **Real-time Monitoring**: Terminal logging, notifications, and (coming soon) Streamlit dashboard

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Copy the example environment file and add your Alpaca API credentials:

```bash
cp .env.example .env
```

Edit `.env` with your keys:
```
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

### 3. Run the Bot

```bash
python -m src.main
```

## Configuration

All settings are in `config/settings.py`. Key parameters:

| Setting | Default | Description |
|---------|---------|-------------|
| `PAPER_TRADING` | True | Use paper trading mode |
| `MAX_RISK_PER_TRADE` | 2% | Maximum risk per trade |
| `DAILY_LOSS_LIMIT` | 3% | Maximum daily loss before halt |
| `MAX_POSITIONS` | 10 | Maximum concurrent positions |
| `MAX_DAY_TRADES` | 3 | PDT limit (for accounts < $25k) |

## Project Structure

```
stocker-trader-project/
├── config/
│   ├── settings.py          # All configuration
│   └── strategy_weights.json # Strategy weight config
├── src/
│   ├── main.py              # Entry point
│   ├── broker/              # Alpaca integration
│   ├── strategies/          # Trading strategies
│   ├── risk/                # Risk management
│   ├── storage/             # Database
│   └── utils/               # Logging, notifications
├── tests/                   # Unit tests
├── data/                    # SQLite database
└── logs/                    # Log files
```

## Trading Strategies

### RSI Strategy (Implemented)
- Multi-timeframe RSI analysis (15m, 1h, Daily)
- Entry: RSI < 30 (oversold) with higher timeframe uptrend confirmation
- Exit: RSI > 70 (overbought) or trailing stop

### Coming Soon
- MACD Strategy
- Moving Average Crossover
- Momentum/Trend Following
- ML-based predictions
- Options (Debit Spreads)

## Risk Management

The bot implements multiple layers of risk protection:

1. **Position Sizing**: 1-2% risk rule automatically sizes positions
2. **Stop Losses**: Hard stops + trailing stops
3. **Daily/Weekly Limits**: Trading halts on excessive losses
4. **PDT Tracking**: Smart day trade management for small accounts
5. **Max Positions**: Limits concentration risk

## Testing

Run the test suite:

```bash
pytest tests/ -v
```

## Notifications

Configure email/SMS notifications in `.env`:

- Trade entries and exits
- Daily summaries
- Error alerts
- Drawdown warnings

## Development Roadmap

- [x] Phase 1: MVP with RSI strategy
- [ ] Phase 2: Multi-strategy orchestrator
- [ ] Phase 3: ML predictions
- [ ] Phase 4: Options trading
- [ ] Phase 5: Streamlit dashboard

## Disclaimer

This software is for educational purposes only. Trading stocks and options involves significant risk of loss. Past performance does not guarantee future results. Always use paper trading to test strategies before risking real capital.

## License

MIT License
