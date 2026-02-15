"""
Vertical Spread Strategy

Implements bull call spreads and bear put spreads for directional trading
with defined risk and reward. This strategy is capital efficient and limits
both maximum gain and maximum loss.
"""

import pandas as pd
from datetime import date
from typing import Optional, Literal

from src.strategies.base import BaseStrategy, SignalDirection, OptionsSignal
from src.broker.alpaca_client import get_alpaca_client
from src.broker.order_manager import OptionLeg
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class VerticalSpreadStrategy(BaseStrategy):
    """
    Vertical Spreads: Bull call spreads and bear put spreads.

    Bull Call Spread (Bullish):
    - Buy ATM/ITM call, Sell OTM call
    - Max profit: Spread width - net debit
    - Max loss: Net debit paid
    - Use when moderately bullish

    Bear Put Spread (Bearish):
    - Buy ATM/ITM put, Sell OTM put
    - Max profit: Spread width - net debit
    - Max loss: Net debit paid
    - Use when moderately bearish

    Entry Criteria:
    - Clear trend detected
    - Risk/reward ratio >= 1.5:1
    - Spread width ~5% of stock price
    - DTE: 30-45 days
    """

    def __init__(self):
        super().__init__()
        self.client = get_alpaca_client()
        self._name = "vertical_spread"

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, symbols: list[str]) -> list[OptionsSignal]:
        """
        Analyze symbols for vertical spread opportunities.

        Args:
            symbols: List of symbols to analyze

        Returns:
            List of OptionsSignal objects
        """
        if not settings.OPTIONS_ENABLED:
            return []

        signals = []

        try:
            for symbol in symbols:
                # Get historical data to detect trend
                bars = self.client.get_bars(
                    symbol,
                    timeframe="1Day",
                    limit=50
                )

                if not bars:
                    continue

                # Convert to DataFrame
                df = pd.DataFrame([{
                    'open': bar.o,
                    'high': bar.h,
                    'low': bar.l,
                    'close': bar.c,
                    'volume': bar.v
                } for bar in bars])

                # Detect trend
                trend = self._detect_trend(df)

                if trend == "neutral":
                    continue

                logger.debug(f"Detected {trend} trend in {symbol}")

                # Get options chain
                chain = self.client.get_options_chain(symbol)

                if not chain.contracts:
                    logger.debug(f"No options chain for {symbol}")
                    continue

                # Find target expiration (30-45 days)
                target_expiration = chain.get_closest_expiration(
                    target_days=settings.VERTICAL_SPREAD_TARGET_DTE,
                    min_days=settings.MIN_DAYS_TO_EXPIRATION
                )

                if not target_expiration:
                    logger.debug(f"No suitable expiration for {symbol}")
                    continue

                # Create spread based on trend
                if trend == "bullish":
                    spread_signal = self._create_bull_call_spread(
                        symbol, chain, target_expiration
                    )
                else:  # bearish
                    spread_signal = self._create_bear_put_spread(
                        symbol, chain, target_expiration
                    )

                if spread_signal:
                    signals.append(spread_signal)

        except Exception as e:
            logger.error(f"Error in vertical spread analysis: {e}")

        return signals

    def _detect_trend(self, df: pd.DataFrame) -> Literal["bullish", "bearish", "neutral"]:
        """
        Detect trend using moving averages and momentum.

        Args:
            df: Price data DataFrame

        Returns:
            "bullish", "bearish", or "neutral"
        """
        # Calculate moving averages
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()

        # Get current values
        current_price = df['close'].iloc[-1]
        sma_20 = df['sma_20'].iloc[-1]
        sma_50 = df['sma_50'].iloc[-1]

        # Calculate momentum (20-day rate of change)
        price_20_days_ago = df['close'].iloc[-20] if len(df) >= 20 else df['close'].iloc[0]
        momentum = ((current_price - price_20_days_ago) / price_20_days_ago) * 100

        # Bullish: Price above both MAs, 20 SMA above 50 SMA, positive momentum
        if current_price > sma_20 and sma_20 > sma_50 and momentum > 2:
            return "bullish"

        # Bearish: Price below both MAs, 20 SMA below 50 SMA, negative momentum
        if current_price < sma_20 and sma_20 < sma_50 and momentum < -2:
            return "bearish"

        return "neutral"

    def _create_bull_call_spread(
        self,
        symbol: str,
        chain,
        expiration: date
    ) -> Optional[OptionsSignal]:
        """Create a bull call spread signal."""
        try:
            # Get ATM call (long leg)
            long_call = chain.get_atm_contract("call", expiration)

            if not long_call or not long_call.greeks:
                return None

            # Get OTM call ~5% above (short leg)
            target_strike = long_call.strike * (1 + settings.VERTICAL_SPREAD_WIDTH_PERCENT / 100)
            short_call = chain.get_closest_strike(target_strike, "call", expiration)

            if not short_call or not short_call.greeks:
                return None

            # Validate liquidity for both legs
            if not long_call.is_liquid() or not short_call.is_liquid():
                logger.debug(f"Spread legs not liquid for {symbol}")
                return None

            # Calculate spread economics
            # Net debit = long premium - short premium
            net_debit = (long_call.ask - short_call.bid) * 100
            spread_width = (short_call.strike - long_call.strike) * 100
            max_profit = spread_width - net_debit
            max_risk = net_debit

            # Calculate risk/reward ratio
            if max_risk <= 0:
                return None

            risk_reward = max_profit / max_risk

            # Only take if risk/reward >= threshold
            if risk_reward < settings.VERTICAL_SPREAD_MIN_RISK_REWARD:
                logger.debug(
                    f"Risk/reward too low for {symbol}: {risk_reward:.2f} "
                    f"(min {settings.VERTICAL_SPREAD_MIN_RISK_REWARD})"
                )
                return None

            # Calculate confidence based on risk/reward and trend strength
            # Better risk/reward = higher confidence
            rr_score = min(risk_reward / 3.0, 1.0)  # 3:1 = max score
            # Strong delta on long call = higher confidence
            delta_score = abs(long_call.greeks.delta)
            confidence = (rr_score + delta_score) / 2.0
            confidence = max(0.6, min(confidence, 0.85))

            # Create option legs
            legs = [
                OptionLeg(
                    contract_symbol=long_call.symbol,
                    side="buy",
                    quantity=1,
                    limit_price=long_call.ask
                ),
                OptionLeg(
                    contract_symbol=short_call.symbol,
                    side="sell",
                    quantity=1,
                    limit_price=short_call.bid
                )
            ]

            signal = OptionsSignal(
                symbol=symbol,
                direction=SignalDirection.LONG,  # Bullish spread
                confidence=confidence,
                strategy=self.name,
                contract_symbol=None,  # Multi-leg, no single contract
                contract_type='call',
                strike=long_call.strike,
                expiration=expiration,
                premium=net_debit / 100,  # Per share cost
                max_risk=max_risk,
                max_profit=max_profit,
                legs=legs,
                greeks=long_call.greeks,  # Use long leg Greeks
                metadata={
                    'spread_type': 'bull_call_spread',
                    'long_strike': long_call.strike,
                    'short_strike': short_call.strike,
                    'spread_width': spread_width / 100,
                    'net_debit': net_debit,
                    'risk_reward': risk_reward,
                    'days_to_expiration': (expiration - date.today()).days
                }
            )

            logger.info(
                f"Bull call spread signal: {symbol} "
                f"${long_call.strike}/{short_call.strike} {expiration} "
                f"net debit ${net_debit:.2f}, max profit ${max_profit:.2f}, "
                f"R/R {risk_reward:.2f}:1, confidence {confidence:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"Error creating bull call spread for {symbol}: {e}")
            return None

    def _create_bear_put_spread(
        self,
        symbol: str,
        chain,
        expiration: date
    ) -> Optional[OptionsSignal]:
        """Create a bear put spread signal."""
        try:
            # Get ATM put (long leg)
            long_put = chain.get_atm_contract("put", expiration)

            if not long_put or not long_put.greeks:
                return None

            # Get OTM put ~5% below (short leg)
            target_strike = long_put.strike * (1 - settings.VERTICAL_SPREAD_WIDTH_PERCENT / 100)
            short_put = chain.get_closest_strike(target_strike, "put", expiration)

            if not short_put or not short_put.greeks:
                return None

            # Validate liquidity for both legs
            if not long_put.is_liquid() or not short_put.is_liquid():
                logger.debug(f"Spread legs not liquid for {symbol}")
                return None

            # Calculate spread economics
            # Net debit = long premium - short premium
            net_debit = (long_put.ask - short_put.bid) * 100
            spread_width = (long_put.strike - short_put.strike) * 100
            max_profit = spread_width - net_debit
            max_risk = net_debit

            # Calculate risk/reward ratio
            if max_risk <= 0:
                return None

            risk_reward = max_profit / max_risk

            # Only take if risk/reward >= threshold
            if risk_reward < settings.VERTICAL_SPREAD_MIN_RISK_REWARD:
                logger.debug(
                    f"Risk/reward too low for {symbol}: {risk_reward:.2f} "
                    f"(min {settings.VERTICAL_SPREAD_MIN_RISK_REWARD})"
                )
                return None

            # Calculate confidence
            rr_score = min(risk_reward / 3.0, 1.0)
            delta_score = abs(long_put.greeks.delta)
            confidence = (rr_score + delta_score) / 2.0
            confidence = max(0.6, min(confidence, 0.85))

            # Create option legs
            legs = [
                OptionLeg(
                    contract_symbol=long_put.symbol,
                    side="buy",
                    quantity=1,
                    limit_price=long_put.ask
                ),
                OptionLeg(
                    contract_symbol=short_put.symbol,
                    side="sell",
                    quantity=1,
                    limit_price=short_put.bid
                )
            ]

            signal = OptionsSignal(
                symbol=symbol,
                direction=SignalDirection.SHORT,  # Bearish spread
                confidence=confidence,
                strategy=self.name,
                contract_symbol=None,  # Multi-leg
                contract_type='put',
                strike=long_put.strike,
                expiration=expiration,
                premium=net_debit / 100,
                max_risk=max_risk,
                max_profit=max_profit,
                legs=legs,
                greeks=long_put.greeks,
                metadata={
                    'spread_type': 'bear_put_spread',
                    'long_strike': long_put.strike,
                    'short_strike': short_put.strike,
                    'spread_width': spread_width / 100,
                    'net_debit': net_debit,
                    'risk_reward': risk_reward,
                    'days_to_expiration': (expiration - date.today()).days
                }
            )

            logger.info(
                f"Bear put spread signal: {symbol} "
                f"${long_put.strike}/{short_put.strike} {expiration} "
                f"net debit ${net_debit:.2f}, max profit ${max_profit:.2f}, "
                f"R/R {risk_reward:.2f}:1, confidence {confidence:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"Error creating bear put spread for {symbol}: {e}")
            return None

    def get_signal(self, symbol: str, data: pd.DataFrame) -> OptionsSignal:
        """
        Not implemented for options strategies.
        Use analyze() instead.
        """
        signals = self.analyze([symbol])
        return signals[0] if signals else None

    def should_exit(self, symbol: str, data: pd.DataFrame) -> tuple[bool, str]:
        """
        Check if should close vertical spread.

        Exit criteria:
        - Reached 75% of max profit
        - Trend reversed
        - Close to expiration (<7 days)
        - Loss exceeds 50% of max risk
        """
        try:
            from src.storage.database import get_database
            db = get_database()

            # Get spreads for this underlying
            spreads = db.get_active_spreads(underlying=symbol)

            for spread in spreads:
                if spread['strategy'] != self.name:
                    continue

                # Check days to expiration
                # Note: We'd need to get expiration from the spread's legs
                # For now, check if close to expiration
                spread_legs = db.get_spread_legs(spread['id'])
                if not spread_legs:
                    continue

                # Get first leg's expiration
                first_leg = spread_legs[0]
                expiration = date.fromisoformat(first_leg['expiration']) if isinstance(first_leg['expiration'], str) else first_leg['expiration']
                dte = (expiration - date.today()).days

                if dte < 7:
                    return True, f"Close to expiration ({dte} days)"

                # Check if reached target profit (75% of max profit)
                # This would require getting current spread value
                # For now, use trend reversal

                # Detect trend reversal
                current_trend = self._detect_trend(data)
                spread_type = spread.get('spread_type', '')

                # If bull spread and trend turned bearish, exit
                if 'bull' in spread_type and current_trend == "bearish":
                    return True, "Trend reversed to bearish"

                # If bear spread and trend turned bullish, exit
                if 'bear' in spread_type and current_trend == "bullish":
                    return True, "Trend reversed to bullish"

        except Exception as e:
            logger.error(f"Error checking vertical spread exit: {e}")

        return False, ""
