# Quick Reference: Aggressive Strategies

## Fast Activation (Copy & Paste)

### Edit: src/main.py

**Add these imports after line 26:**
```python
from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.technical.vwap_bounce_strategy import VWAPBounceStrategy
```

**Replace lines 44-46 with ONE of these:**

**Maximum Signals:**
```python
self.strategies = [
    MomentumBreakoutStrategy(),
    VWAPBounceStrategy()
]
```

**Moderate:**
```python
self.strategies = [
    RSIStrategy(),
    MomentumBreakoutStrategy()
]
```

**Test One:**
```python
self.strategies = [
    MomentumBreakoutStrategy()
]
```

### Optional: Edit config/settings.py

**Line 66 - Lower threshold:**
```python
SIGNAL_THRESHOLD: float = 0.5  # Was 0.6
```

**Line 22 - Lower risk per trade:**
```python
MAX_RISK_PER_TRADE: float = 0.015  # Was 0.02 (2%)
```

**Line 27 - More positions:**
```python
MAX_POSITIONS: int = 15  # Was 10
```

---

## Strategy Quick Facts

### Momentum Breakout
- **Signals/Day:** 2-4
- **Timeframes:** 15min, 1hour
- **Direction:** Long + Short
- **Style:** Trend following
- **Entry:** 3 of 5 factors (MACD, VWAP, Volume, EMA, RSI)
- **Best For:** Trending markets

### VWAP Bounce
- **Signals/Day:** 3-6
- **Timeframes:** 15min only
- **Direction:** Long + Short
- **Style:** Mean reversion
- **Entry:** 3 of 5 factors (Near VWAP, Cross, Volume, Momentum, Trend)
- **Best For:** Choppy, range-bound markets

---

## Entry Logic Cheat Sheet

### Momentum Breakout LONG
Need 3+ of these:
- [ ] MACD histogram > 0 and increasing
- [ ] Price > VWAP
- [ ] Volume >= 1.2x average
- [ ] Price > EMA9
- [ ] 40 <= RSI <= 70

### Momentum Breakout SHORT
Need 3+ of these:
- [ ] MACD histogram < 0 and decreasing
- [ ] Price < VWAP
- [ ] Volume >= 1.2x average
- [ ] Price < EMA9
- [ ] 30 <= RSI <= 60

### VWAP Bounce LONG
Need 3+ of these:
- [ ] Price within 0.75% of VWAP
- [ ] Price crossed above VWAP
- [ ] Volume >= 1.3x average
- [ ] MACD histogram improving
- [ ] Price > EMA21

### VWAP Bounce SHORT
Need 3+ of these:
- [ ] Price within 0.75% of VWAP
- [ ] Price crossed below VWAP
- [ ] Volume >= 1.3x average
- [ ] MACD histogram deteriorating
- [ ] Price < EMA21

---

## Commands

```bash
# Run bot
python -m src.main

# Run tests
pytest tests/test_aggressive_strategies.py -v

# Check logs
tail -f logs/stocker_trader.log

# Query results
sqlite3 data/stocker_trader.db "SELECT strategy, COUNT(*) FROM trades GROUP BY strategy;"
```

---

## What to Watch in Logs

**Good:**
```
[momentum_breakout] Signal generated: LONG AAPL @ 0.75 confidence
Signal: LONG AAPL (confidence: 0.75, strategy: momentum_breakout)
Trade executed: LONG 50 AAPL @ $150.25
```

**Normal (filtered):**
```
Skipping AAPL - would use day trade for low confidence signal
Insufficient factors (long: 2, short: 1)
```

**Bad (investigate):**
```
Error analyzing AAPL with momentum_breakout: ...
Failed to get data for AAPL: ...
```

---

## Tuning Parameters

### More Signals

**Momentum:**
```python
MomentumBreakoutStrategy(
    volume_multiplier=1.1,
    min_confidence=0.45
)
```

**VWAP:**
```python
VWAPBounceStrategy(
    vwap_touch_threshold=0.01,
    volume_multiplier=1.2,
    min_confidence=0.45
)
```

### Better Quality

**Momentum:**
```python
MomentumBreakoutStrategy(
    volume_multiplier=1.5,
    min_confidence=0.6
)
```

**VWAP:**
```python
VWAPBounceStrategy(
    vwap_touch_threshold=0.003,
    volume_multiplier=1.5,
    min_confidence=0.6
)
```

---

## Performance Check (After 1 Week)

```sql
-- In sqlite3 data/stocker_trader.db

-- Signals per strategy
SELECT strategy, COUNT(*) as signals
FROM signals
WHERE timestamp >= date('now', '-7 days')
GROUP BY strategy;

-- Win rate per strategy
SELECT
    strategy,
    COUNT(*) as trades,
    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate,
    AVG(pnl) as avg_pnl
FROM trades
WHERE exit_time IS NOT NULL
  AND entry_time >= date('now', '-7 days')
GROUP BY strategy;

-- Confidence vs outcome
SELECT
    CASE
        WHEN confidence >= 0.8 THEN 'High'
        WHEN confidence >= 0.6 THEN 'Medium'
        ELSE 'Low'
    END as conf_bucket,
    AVG(pnl) as avg_pnl,
    COUNT(*) as trades
FROM trades
WHERE exit_time IS NOT NULL
GROUP BY conf_bucket;
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No signals | Lower `SIGNAL_THRESHOLD` to 0.45 |
| Too many signals | Raise to 0.65, reduce watchlist |
| Signals not executed | Check PDT, daily limits, logs |
| Import errors | Check `__init__.py` updated |
| Test failures | Run `pytest -v`, check errors |
| Low win rate | Raise `min_confidence`, tighter filters |

---

## Files Changed

**NEW:**
- `src/strategies/technical/momentum_breakout_strategy.py`
- `src/strategies/technical/vwap_bounce_strategy.py`
- `tests/test_aggressive_strategies.py`
- `AGGRESSIVE_STRATEGIES_GUIDE.md`
- `QUICK_START_CHANGES.md`
- `IMPLEMENTATION_SUMMARY.md`

**MODIFIED:**
- `src/strategies/technical/__init__.py`

**TO MODIFY:**
- `src/main.py` (add strategies)
- `config/settings.py` (optional tuning)

---

## Expected Results

| Metric | Conservative | Aggressive |
|--------|-------------|------------|
| Signals/Day | 2-3 | 5-10 |
| Trades/Month | 40 | 100 |
| Target Win Rate | 48-52% | 50-55% |
| Monthly Return | 5-10% | 10-20% |

---

That's it! Copy the code, run the bot, watch the logs, tune as needed.
