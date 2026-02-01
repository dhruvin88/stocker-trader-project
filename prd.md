# Stocker Trader Bot - Product Requirements Document

## 1. Product Overview

**Product Name:** Stocker Trader Bot
**Version:** 1.0.0
**Goal:** Automated stock and options trading system with multiple strategy support, conservative risk management, and comprehensive monitoring.

### Key Constraints
- Under $10k capital → Must respect PDT rules (max 3 day trades per 5 rolling days)
- Conservative risk → Max 1-2% risk per trade, auto-halt on drawdowns
- MVP approach → Get core working first, iterate

---

## 2. Summary of Requirements

| Category | Decision |
|----------|----------|
| Broker | Alpaca API |
| Language | Python 3.11+ |
| Capital | Under $10,000 (PDT rules apply) |
| Risk Level | Conservative (1-2% per trade) |
| Deployment | Local Machine |
| Initial Mode | Paper Trading |
| Strategy Types | Technical, Options, ML, Momentum |
| Conflict Resolution | Weighted Voting (performance-based auto-adjust) |
| Trading Frequency | Mixed (intraday + swing) |
| Market Hours | Regular only (9:30 AM - 4:00 PM ET) |
| PDT Handling | Hybrid (reserve day trades for high-conviction) |
| Stock Universe | Dynamic Scanner (multi-factor) |
| Options Approach | Debit Spreads |
| Order Type | Limit Orders |
| ML Prediction | 5-day direction, Ensemble models |
| ML Features | Price, Sentiment, Fundamentals, Macro |
| Volatility Events | Pause Trading |
| Max Trades | 5-10 per day |
| Timeframes | Multi-Timeframe analysis |
| Backtest Period | 1 Year |
| Storage | SQLite Database |
| Dashboard | Streamlit |
| Monitoring | Terminal + Web + Mobile Notifications |
| Error Handling | Retry & Continue |
| Losing Streaks | Strategy Rotation |
| Open/Close Avoidance | First & last 30 min |
| Exit Rules | Hybrid (fixed targets + trailing + indicators) |
| Account Support | Paper + Live switching |
| Dev Approach | MVP First |

---

## 3. Architecture

```
stocker-trader-project/
├── prd.md                      # This document
├── README.md                   # Setup & usage guide
├── requirements.txt            # Dependencies
├── .env.example                # API key template
├── config/
│   ├── __init__.py
│   ├── settings.py             # All configuration
│   └── strategy_weights.json   # Strategy weight config
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point & scheduler
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── alpaca_client.py    # Alpaca API wrapper
│   │   ├── order_manager.py    # Order execution
│   │   └── pdt_tracker.py      # Pattern Day Trader tracking
│   ├── scanner/
│   │   ├── __init__.py
│   │   └── universe_scanner.py # Dynamic stock scanner
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract strategy class
│   │   ├── orchestrator.py     # Weighted voting system
│   │   ├── technical/
│   │   │   ├── __init__.py
│   │   │   ├── rsi_strategy.py
│   │   │   ├── macd_strategy.py
│   │   │   └── ma_crossover.py
│   │   ├── momentum/
│   │   │   ├── __init__.py
│   │   │   └── trend_follower.py
│   │   ├── ml/
│   │   │   ├── __init__.py
│   │   │   ├── ensemble.py     # Ensemble model
│   │   │   ├── features.py     # Feature engineering
│   │   │   └── trainer.py      # Model training pipeline
│   │   └── options/
│   │       ├── __init__.py
│   │       └── debit_spread.py
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_sizer.py   # 1-2% rule sizing
│   │   ├── stop_manager.py     # Hybrid exit rules
│   │   ├── portfolio_guard.py  # Daily/weekly limits
│   │   └── strategy_rotator.py # Disable/enable strategies
│   ├── data/
│   │   ├── __init__.py
│   │   ├── market_data.py      # Real-time from Alpaca
│   │   ├── historical.py       # Historical data
│   │   ├── sentiment/
│   │   │   ├── __init__.py
│   │   │   ├── news.py         # News sentiment
│   │   │   ├── social.py       # Reddit/Twitter
│   │   │   └── sec_filings.py  # SEC analysis
│   │   └── fundamentals.py     # Fundamental data
│   ├── analysis/
│   │   ├── __init__.py
│   │   └── indicators.py       # Technical indicators
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite wrapper
│   │   └── models.py           # DB schema
│   └── utils/
│       ├── __init__.py
│       ├── logger.py           # Logging config
│       └── notifications.py    # Email/SMS/Push alerts
├── dashboard/
│   ├── __init__.py
│   └── app.py                  # Streamlit dashboard
├── backtesting/
│   ├── __init__.py
│   └── engine.py               # Backtesting framework
├── tests/
│   ├── __init__.py
│   ├── test_strategies.py
│   ├── test_risk.py
│   └── test_broker.py
├── data/                       # SQLite DB & cached data
└── logs/                       # Log files
```

---

## 4. Core Features (MVP)

### 4.1 Broker Integration
- Connect to Alpaca paper/live accounts
- Switch between paper and live via config
- Handle limit orders with timeout fallback
- Retry failed API calls with exponential backoff
- Rate limit handling with priority queue

### 4.2 PDT Tracker
- Track rolling 5-day window of day trades
- Block new day trades if at limit (3)
- Reserve day trades for high-conviction signals (score > threshold)
- Force overnight holds when day trades exhausted

### 4.3 Dynamic Scanner
Multi-factor scoring:
- Volume: Minimum 1M avg daily volume
- Volatility: ATR between 2-8% (tradeable range)
- Technical Setup: RSI, MACD, MA alignment
- Momentum: Relative strength vs SPY
- Combined weighted score → top N stocks

### 4.4 Strategy Orchestrator
- Each strategy produces signal: {symbol, direction, confidence 0-1}
- Performance-based weights auto-adjust weekly
- Weighted vote: if combined score > threshold → trade
- Conflicting signals cancel out

### 4.5 Risk Management

| Rule | Value |
|------|-------|
| Max risk per trade | 1-2% of portfolio |
| Daily loss limit | 3% of portfolio |
| Weekly loss limit | 7% of portfolio |
| Max position size | 10% per symbol |
| Max concurrent positions | 10 |
| Auto-halt drawdown | 10% from peak |
| Avoid open/close | First & last 30 min |

### 4.6 Exit Rules (Hybrid)
Priority order:
1. Hard stop-loss hit → exit immediately
2. Trailing stop triggered → exit
3. Take-profit target reached → scale out 50%
4. Indicator reversal (RSI overbought) → exit remaining

### 4.7 Strategy Rotation
- Track 20-trade rolling performance per strategy
- If win rate < 40% or expectancy negative → disable
- Gradual re-entry: start at 25% weight, increase if profitable

---

## 5. Technical Strategies (Phase 1)

### RSI Strategy
- Timeframes: 15m, 1h, Daily (multi-TF confirmation)
- Entry: RSI < 30 (oversold) + higher TF uptrend
- Exit: RSI > 70 or trailing stop

### MACD Strategy
- Timeframes: 1h, 4h, Daily
- Entry: MACD crossover + histogram increasing
- Exit: MACD crossunder or fixed target

### Moving Average Crossover
- Short: 9 EMA, Long: 21 EMA
- Entry: Golden cross with volume confirmation
- Exit: Death cross or trailing stop

---

## 6. ML Strategy (Phase 2)

**Prediction Target:** 5-day direction (up/down/sideways)

**Ensemble Model:**
- Random Forest (baseline, interpretable)
- XGBoost (performance)
- LSTM (sequence patterns)
- Final: Weighted average of predictions

**Features:**
- Price/Volume: OHLCV, returns, volatility, volume ratios
- Technical: RSI, MACD, Bollinger, ATR (multiple timeframes)
- Sentiment: News score, Reddit/Twitter sentiment, SEC filing tone
- Fundamentals: P/E, revenue growth, earnings surprise
- Macro: VIX, sector ETF performance, interest rates

**Training:**
- 1 year historical data
- Walk-forward validation (train on N months, test on next month)
- Retrain weekly

---

## 7. Options Strategy (Phase 3)

**Focus:** Debit Spreads (defined risk)

**Bull Call Spread:**
- Buy ITM call, sell OTM call
- Max loss = debit paid
- Use when: Strong bullish signal + low IV

**Bear Put Spread:**
- Buy ITM put, sell OTM put
- Use when: Strong bearish signal + low IV

**Entry Criteria:**
- Underlying strategy generates high-confidence directional signal
- IV rank < 50 (avoid expensive options)
- At least 14 DTE

---

## 8. Monitoring & Notifications

**Terminal:** Real-time log output with loguru

**Streamlit Dashboard:**
- Current positions & P&L
- Strategy performance chart
- Signal history
- Risk metrics display

**Notifications (Full Verbosity):**
- Trade entries/exits
- Errors and retries
- Strategy enabled/disabled
- Daily summary
- Drawdown warnings

---

## 9. Data Storage (SQLite)

**Tables:**
- `trades`: All executed trades with P&L
- `signals`: All generated signals (taken or not)
- `daily_performance`: Daily P&L by strategy
- `strategy_metrics`: Rolling performance stats
- `market_data_cache`: Cached historical data

---

## 10. Implementation Phases

### Phase 1: MVP Foundation
Basic bot that can paper trade with one strategy

### Phase 2: Multi-Strategy + Risk
- Add MACD, MA crossover strategies
- Build orchestrator with weighted voting
- Implement portfolio guard
- Add strategy rotation

### Phase 3: Scanner + ML
- Build dynamic universe scanner
- Implement feature engineering
- Train ensemble model
- Integrate ML predictions

### Phase 4: Options + Sentiment
- Add debit spread strategy
- Implement sentiment analysis
- Integrate all data sources

### Phase 5: Dashboard + Polish
- Build Streamlit dashboard
- Add all notifications
- Comprehensive testing
- Documentation

---

## 11. Verification Plan

1. **Unit Tests:** `pytest tests/` - Test all components in isolation
2. **Integration Test:** Paper trade for 1 week, verify:
   - Orders execute correctly in Alpaca
   - PDT tracking works
   - Risk limits trigger appropriately
3. **Backtest vs Paper:** Compare strategy performance
4. **Forward Test:** After paper success, test with $100 real money for 1 week
5. **Risk Verification:** Manually trigger loss limits to confirm auto-halt
