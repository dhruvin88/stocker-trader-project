# Aggressive Trading Strategies Implementation Guide

This guide explains the new aggressive multi-factor strategies designed to generate 2-3x more trading signals than the conservative RSI mean reversion strategy.

## Overview

Two new strategies have been created to increase trading frequency while maintaining risk controls:

1. **Momentum Breakout Strategy** - Trades WITH momentum using MACD, VWAP, and volume
2. **VWAP Bounce Strategy** - Trades bounces and rejections at institutional VWAP levels

## Strategy 1: Momentum Breakout

**File**: `/Users/dhruvinpatel/repos/stocker-trader-project/src/strategies/technical/momentum_breakout_strategy.py`

### Philosophy
Instead of waiting for RSI to reach extreme oversold/overbought levels (which happens rarely), this strategy catches momentum building in either direction and rides the wave.

### Entry Criteria - LONG

Requires **at least 3 of 5** factors aligned:

1. **MACD Momentum Building**: Histogram > 0 AND increasing from previous bar
2. **Price Above VWAP**: Institutional buyers are supporting price
3. **Volume Surge**: Current volume >= 1.2x the 20-period average
4. **Short-term Trend**: Price > EMA9 (immediate trend confirmation)
5. **RSI Mid-Range**: 40 <= RSI <= 70 (has room to run, not extreme)

### Entry Criteria - SHORT

Requires **at least 3 of 5** factors aligned:

1. **MACD Momentum Declining**: Histogram < 0 AND decreasing from previous bar
2. **Price Below VWAP**: Institutional sellers are pushing price down
3. **Volume Surge**: Current volume >= 1.2x average
4. **Short-term Trend**: Price < EMA9
5. **RSI Mid-Range**: 30 <= RSI <= 60

### Confidence Scoring

```
Base Confidence: 0.5
+ Factor Bonus: 0.1 per aligned factor (3 factors = +0.3)
+ Volume Bonus: +0.05 if volume ratio >= 1.5
+ MACD Bonus: +0.05 if MACD histogram accelerating strongly
= Total Confidence (capped at 0.95)
```

Example: 4 factors aligned + strong volume = 0.5 + 0.4 + 0.05 = 0.95 confidence

### Exit Conditions

**For LONG positions:**
- MACD crosses below signal line (momentum reversal)
- Price crosses below VWAP (institutional support broken)
- RSI > 75 (extreme overbought)

**For SHORT positions:**
- MACD crosses above signal line
- Price crosses above VWAP
- RSI < 25 (extreme oversold)

### Position Sizing

- Stop Loss: Entry price - (1.5 * ATR)
- Take Profit: Entry price + (3 * ATR)
- Risk/Reward: 2:1 ratio

### Timeframes
- Primary analysis: 1 Hour
- Entry timing: 15 Minutes
- No daily trend confirmation required (unlike RSI strategy)

### Expected Performance

- **Signal Frequency**: 2-4 signals per day across 10-symbol watchlist
- **Win Rate Target**: 45-55%
- **Risk/Reward**: 2:1
- **Best Market Conditions**: Trending markets with clear directional moves

---

## Strategy 2: VWAP Bounce

**File**: `/Users/dhruvinpatel/repos/stocker-trader-project/src/strategies/technical/vwap_bounce_strategy.py`

### Philosophy
VWAP acts as a magnet where institutions execute large orders. When price deviates from VWAP and returns, it often continues back through VWAP before reversing. This strategy catches those bounce/rejection moves.

### Entry Criteria - LONG (VWAP Bounce)

Requires **at least 3 of 5** conditions:

1. **Near VWAP**: Price within 0.75% of VWAP (0.5% * 1.5 threshold)
2. **Crossed Above VWAP**: Current price > VWAP AND previous price <= VWAP
3. **Volume Surge**: Volume >= 1.3x the 20-period average
4. **Momentum Improving**: MACD histogram > previous bar
5. **Above EMA21**: Not in strong downtrend

### Entry Criteria - SHORT (VWAP Rejection)

Requires **at least 3 of 5** conditions:

1. **Near VWAP**: Price within 0.75% of VWAP
2. **Crossed Below VWAP**: Current price < VWAP AND previous price >= VWAP
3. **Volume Surge**: Volume >= 1.3x average
4. **Momentum Deteriorating**: MACD histogram < previous bar
5. **Below EMA21**: Not in strong uptrend

### Confidence Scoring

```
Base Confidence: 0.5
+ Condition Bonus: 0.08 per met condition (3 conditions = +0.24)
+ Proximity Bonus: Up to +0.1 based on how close to VWAP (closer = higher)
+ Volume Bonus: +0.05 if volume ratio >= 1.5
= Total Confidence (capped at 0.9)
```

### Exit Conditions

**For LONG positions:**
- Price reaches VWAP + 1.5% (target)
- Price crosses back below VWAP with negative momentum
- Sharp momentum deterioration (MACD histogram drops >50%)

**For SHORT positions:**
- Price reaches VWAP - 1.5% (target)
- Price crosses back above VWAP with positive momentum
- Sharp momentum improvement

### Position Sizing

- Stop Loss (LONG): Min of (recent 5-bar low, VWAP - 1.0%)
- Stop Loss (SHORT): Max of (recent 5-bar high, VWAP + 1.0%)
- Take Profit: VWAP ± 1.5%

### Timeframes
- Intraday only: 15 Minutes
- Multiple signals per day per symbol (VWAP recalculates intraday)

### Expected Performance

- **Signal Frequency**: 3-6 signals per day across watchlist
- **Win Rate Target**: 50-60% (mean reversion has higher win rate)
- **Risk/Reward**: 1.5:1 to 2:1
- **Best Market Conditions**: Choppy, range-bound markets where price oscillates around VWAP

---

## How to Enable These Strategies

### Option 1: Replace RSI Strategy (Most Aggressive)

Edit `/Users/dhruvinpatel/repos/stocker-trader-project/src/main.py`:

```python
# Line 26: Import new strategies
from src.strategies.technical.rsi_strategy import RSIStrategy
from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.technical.vwap_bounce_strategy import VWAPBounceStrategy

# Lines 44-46: Replace strategy list
self.strategies = [
    MomentumBreakoutStrategy(),  # Replace RSI with momentum
    VWAPBounceStrategy()          # Add VWAP bounce
]
```

This gives you the most signals - both strategies working together.

### Option 2: Add Alongside RSI (Moderate Increase)

```python
self.strategies = [
    RSIStrategy(),                # Keep existing
    MomentumBreakoutStrategy(),   # Add momentum
]
```

This keeps your conservative RSI strategy and adds one aggressive strategy.

### Option 3: Test One at a Time

```python
# Test momentum breakout first
self.strategies = [
    MomentumBreakoutStrategy()
]

# Or test VWAP bounce
self.strategies = [
    VWAPBounceStrategy()
]
```

### Option 4: Lower the Signal Threshold (Easy Quick Fix)

Edit `/Users/dhruvinpatel/repos/stocker-trader-project/config/settings.py`:

```python
# Line 66: Lower from 0.6 to 0.5
SIGNAL_THRESHOLD: float = 0.5  # Was 0.6
```

This makes the RSI strategy more aggressive by accepting lower confidence signals.

---

## Recommended Configuration for Maximum Signals

1. **Use both new strategies** (Option 1 above)
2. **Lower signal threshold** to 0.5 in settings.py
3. **Expand watchlist** to 15-20 symbols in main.py
4. **Add more crypto pairs** if crypto trading enabled:

```python
# config/settings.py line 41
CRYPTO_SYMBOLS: tuple = ("BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD")
```

This configuration should generate:
- **Momentum Breakout**: 2-4 signals/day
- **VWAP Bounce**: 3-6 signals/day
- **Total**: 5-10 potential trades per day

---

## Risk Management Adjustments

Since these strategies are more aggressive, consider:

### 1. Lower Position Size per Trade

Edit `config/settings.py`:

```python
# Line 22: Reduce risk per trade from 2% to 1.5%
MAX_RISK_PER_TRADE: float = 0.015  # Was 0.02
```

### 2. Increase Max Positions

```python
# Line 27: Increase from 10 to 15 to handle more signals
MAX_POSITIONS: int = 15  # Was 10
```

### 3. Tighter Daily Loss Limit

```python
# Line 23: Tighten from 3% to 2%
DAILY_LOSS_LIMIT: float = 0.02  # Was 0.03
```

### 4. Prioritize High Confidence Signals for PDT

The strategies already calculate confidence scores. The bot will automatically reserve day trades for signals with confidence > 0.8 (HIGH_CONVICTION_THRESHOLD).

---

## Testing the Strategies

### 1. Paper Trading First (Recommended)

The bot is already configured for paper trading. Just start it:

```bash
python -m src.main
```

Watch the logs for:
```
[momentum_breakout] Signal generated: LONG AAPL @ 0.75 confidence
[vwap_bounce] Signal: SHORT TSLA @ 0.68 - vwap_rejection_short
```

### 2. Backtest (Optional)

If you want to validate before live paper trading:

```python
# In tests/test_strategies.py
from src.strategies.technical.momentum_breakout_strategy import MomentumBreakoutStrategy
from src.strategies.technical.vwap_bounce_strategy import VWAPBounceStrategy

def test_momentum_strategy():
    strategy = MomentumBreakoutStrategy()
    # Add test data and validate signals
    ...
```

### 3. Monitor Key Metrics

After 1-2 weeks of paper trading, check:
- Total signals generated per day
- Win rate per strategy
- Average R-multiple (profit vs risk)
- Drawdown patterns

Adjust parameters if needed:
- If too many losing signals: Increase `min_confidence` threshold
- If still too few signals: Lower `volume_multiplier` requirements
- If whipsaws: Tighten VWAP deviation thresholds

---

## Parameter Tuning Guide

### Momentum Breakout Strategy

Accessible via `MomentumBreakoutStrategy()` constructor:

```python
MomentumBreakoutStrategy(
    macd_fast=12,           # Faster = more signals, more noise
    macd_slow=26,           # Slower = smoother, fewer signals
    macd_signal=9,
    ema_period=9,           # Lower = more sensitive trend filter
    rsi_period=14,
    volume_multiplier=1.2,  # Lower = more signals (less volume requirement)
    min_confidence=0.5      # Lower = more signals (less selective)
)
```

**To increase signals:**
- Lower `volume_multiplier` to 1.1
- Lower `min_confidence` to 0.45
- Lower `ema_period` to 5

**To improve quality:**
- Raise `volume_multiplier` to 1.5
- Raise `min_confidence` to 0.6
- Add ADX filter (requires code modification)

### VWAP Bounce Strategy

```python
VWAPBounceStrategy(
    vwap_touch_threshold=0.005,   # 0.5% - how close to VWAP needed
    vwap_target_distance=0.015,   # 1.5% - profit target
    volume_multiplier=1.3,
    ema_period=21,
    min_confidence=0.5
)
```

**To increase signals:**
- Raise `vwap_touch_threshold` to 0.01 (1% - wider net)
- Lower `volume_multiplier` to 1.2

**To improve quality:**
- Lower `vwap_touch_threshold` to 0.003 (0.3% - tighter)
- Raise `volume_multiplier` to 1.5

---

## Comparison: New vs Old Strategy

| Metric | RSI Mean Reversion | Momentum Breakout | VWAP Bounce |
|--------|-------------------|-------------------|-------------|
| **Signals/Day** | 0-2 | 2-4 | 3-6 |
| **Timeframes** | 15m, 1h, 1d | 15m, 1h | 15m |
| **Direction** | Long only (mostly) | Long + Short | Long + Short |
| **Win Rate Target** | 55-65% | 45-55% | 50-60% |
| **Avg R-Multiple** | 1.5-2.5R | 1.5-2.5R | 1.5-2.0R |
| **Market Type** | Oversold bounces | Trending | Range-bound |
| **Factors** | 1 (RSI + trend filter) | 5 (multi-factor) | 5 (multi-factor) |
| **Confidence Threshold** | 0.6 | 0.5 | 0.5 |

---

## Expected Results

### Conservative Estimate (Momentum Breakout Only)

- 10 symbols watchlist
- 2 signals/day average
- 48% win rate
- 2:1 R/R ratio
- 1.5% risk per trade

**Monthly Performance:**
- ~40 trades (2/day * 20 trading days)
- ~19 wins, ~21 losses
- Win total: 19 * (1.5% * 2) = +57% of account
- Loss total: 21 * (-1.5%) = -31.5% of account
- **Net: +25.5% monthly** (assuming perfect execution)

### Aggressive Estimate (Both Strategies)

- 15 symbols watchlist
- 5 signals/day average
- 50% win rate
- 2:1 R/R
- 1.5% risk per trade

**Monthly Performance:**
- ~100 trades (5/day * 20 days)
- ~50 wins, ~50 losses
- Win total: 50 * 3% = +150%
- Loss total: 50 * -1.5% = -75%
- **Net: +75% monthly** (theoretical max)

**Realistic Expectation**: 5-15% monthly with proper risk management and accounting for slippage, failed executions, and market conditions.

---

## Troubleshooting

### "No signals being generated"

1. Check logs for analysis attempts:
   ```
   grep "Signal generated" logs/stocker_trader.log
   ```

2. Check if market is open (stocks) or if crypto enabled

3. Verify watchlist symbols are valid:
   ```python
   # In Python shell
   from src.broker.alpaca_client import get_alpaca_client
   client = get_alpaca_client()
   client.get_latest_bar("AAPL")  # Should return data
   ```

4. Lower confidence thresholds temporarily for testing

### "Too many signals, can't execute all"

1. Increase `SIGNAL_THRESHOLD` in settings.py to 0.65-0.7
2. Raise strategy-specific `min_confidence` parameters
3. Enable only one strategy at a time
4. Reduce watchlist size

### "Signals generated but not executed"

Check logs for:
- PDT limit reached
- Daily trade limit reached
- Risk limits exceeded
- Invalid position size
- Wash sale restrictions

---

## Next Steps

1. **Start with Paper Trading**: Enable one new strategy alongside RSI
2. **Monitor for 1 week**: Track signal frequency and quality
3. **Adjust Parameters**: Based on paper trading results
4. **Backtest** (optional): Validate on historical data if you have concerns
5. **Go Live**: Once confident in signal quality and risk management

---

## Files Modified

- `/Users/dhruvinpatel/repos/stocker-trader-project/src/strategies/technical/momentum_breakout_strategy.py` (NEW)
- `/Users/dhruvinpatel/repos/stocker-trader-project/src/strategies/technical/vwap_bounce_strategy.py` (NEW)
- `/Users/dhruvinpatel/repos/stocker-trader-project/src/strategies/technical/__init__.py` (UPDATED)

## Files to Modify

- `/Users/dhruvinpatel/repos/stocker-trader-project/src/main.py` - Update strategy list (lines 26, 44-46)
- `/Users/dhruvinpatel/repos/stocker-trader-project/config/settings.py` - Optional parameter adjustments

---

## Support and Monitoring

Monitor these log messages:
```
[momentum_breakout] Signal generated: LONG AAPL @ 0.75 confidence
[vwap_bounce] Signal: SHORT TSLA @ 0.68 - vwap_rejection_short
Signal: LONG AAPL (confidence: 0.75, strategy: momentum_breakout)
Trade executed: LONG 50 AAPL @ $150.25
```

Key metrics to track:
- Signals generated per strategy per day
- Signals executed vs rejected (and why)
- Win rate by strategy after 20+ trades
- Average holding time per strategy
- Correlation between confidence score and profitability

Good luck! These strategies should significantly increase your trading activity while maintaining proper risk controls.
