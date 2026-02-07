# Quick Start: Enable Aggressive Strategies

## Fastest Way to Get More Signals (2 minutes)

### Step 1: Update src/main.py

Find these lines around line 26:

```python
from src.strategies.technical.rsi_strategy import RSIStrategy
```

Replace with:

```python
from src.strategies.technical.rsi_strategy import RSIStrategy
from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.technical.vwap_bounce_strategy import VWAPBounceStrategy
```

Find these lines around line 44-46:

```python
self.strategies = [
    RSIStrategy()
]
```

Replace with ONE of these options:

**Option A - Maximum Signals (Recommended for Testing)**
```python
self.strategies = [
    MomentumBreakoutStrategy(),
    VWAPBounceStrategy()
]
```

**Option B - Moderate Increase**
```python
self.strategies = [
    RSIStrategy(),
    MomentumBreakoutStrategy()
]
```

**Option C - Test Momentum Only**
```python
self.strategies = [
    MomentumBreakoutStrategy()
]
```

### Step 2: Lower Signal Threshold (Optional)

Edit `config/settings.py` line 66:

```python
# Change from 0.6 to 0.5
SIGNAL_THRESHOLD: float = 0.5  # Was 0.6
```

### Step 3: Run the Bot

```bash
python -m src.main
```

You should now see messages like:
```
[momentum_breakout] Signal generated: LONG AAPL @ 0.75 confidence
[vwap_bounce] Signal: SHORT TSLA @ 0.68 - vwap_rejection_short
```

---

## What Changed?

### Before (RSI Strategy)
- Required RSI < 35 (stocks) or < 30 (crypto) - rare condition
- Required daily uptrend confirmation - filtered out many opportunities
- Generated 0-2 signals per day
- Long-only bias

### After (New Strategies)

**Momentum Breakout:**
- Requires 3 of 5 factors: MACD momentum, above VWAP, volume surge, above EMA9, RSI 40-70
- No daily trend confirmation needed
- Generates 2-4 signals per day
- Both long and short

**VWAP Bounce:**
- Requires 3 of 5 factors: Near VWAP, volume surge, momentum shift, crosses VWAP, trend filter
- Intraday-focused (15min bars)
- Generates 3-6 signals per day
- Both long and short

**Expected Total:** 5-10 signals per day across your watchlist

---

## If You Want Even More Signals

### 1. Expand Watchlist

In `src/main.py` around line 48-51, add more symbols:

```python
self.watchlist = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "AMD", "NFLX", "SPY",
    "QQQ", "COIN", "SHOP", "SQ", "ROKU"  # Add 5 more
]
```

### 2. Add More Crypto (if enabled)

In `config/settings.py` line 41:

```python
CRYPTO_SYMBOLS: tuple = ("BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD")
```

### 3. Make Strategies More Aggressive

**For Momentum Breakout:**

In `src/main.py` where you added the strategy:

```python
self.strategies = [
    MomentumBreakoutStrategy(
        volume_multiplier=1.1,  # Lower from default 1.2
        min_confidence=0.45     # Lower from default 0.5
    )
]
```

**For VWAP Bounce:**

```python
self.strategies = [
    VWAPBounceStrategy(
        vwap_touch_threshold=0.01,  # Wider from default 0.005
        volume_multiplier=1.2,       # Lower from default 1.3
        min_confidence=0.45          # Lower from default 0.5
    )
]
```

---

## Recommended Risk Adjustments

Since you're generating more signals, lower risk per trade:

In `config/settings.py`:

```python
# Line 22: Lower from 2% to 1.5%
MAX_RISK_PER_TRADE: float = 0.015

# Line 27: Increase from 10 to 15 positions
MAX_POSITIONS: int = 15

# Line 28: Increase from 10 to 15 trades per day
MAX_TRADES_PER_DAY: int = 15
```

---

## Monitoring Your Results

Watch the logs for:

1. **Signal Generation:**
   ```
   [momentum_breakout] Signal generated: LONG AAPL @ 0.75 confidence
   ```

2. **Signal Execution:**
   ```
   Signal: LONG AAPL (confidence: 0.75, strategy: momentum_breakout)
   Trade executed: LONG 50 AAPL @ $150.25
   ```

3. **Signal Rejection (and why):**
   ```
   Skipping AAPL - would use day trade for low confidence signal
   Invalid position size for TSLA: Max positions reached
   ```

After 1 week, check your database:

```bash
sqlite3 data/stocker_trader.db

SELECT strategy, COUNT(*), AVG(pnl)
FROM trades
WHERE exit_time IS NOT NULL
GROUP BY strategy;
```

This shows trades and average P&L per strategy.

---

## Troubleshooting

**"Still no signals"**
- Check market is open (stocks trade 9:30am-4pm ET, crypto 24/7)
- Check logs: `tail -f logs/stocker_trader.log`
- Verify Alpaca connection: Check for API errors
- Lower `SIGNAL_THRESHOLD` to 0.4 temporarily

**"Too many signals to handle"**
- Raise `SIGNAL_THRESHOLD` to 0.65
- Enable only one strategy
- Reduce watchlist size
- Increase `min_confidence` parameters

**"Signals generated but not executed"**
- Check PDT limits (3 day trades per 5 days)
- Check daily trade limit (default 10)
- Check risk limits
- Check wash sale restrictions

---

That's it! Start the bot and you should see significantly more trading activity.
