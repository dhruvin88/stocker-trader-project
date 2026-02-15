"""
Covered Call Strategy

Sells call options against existing long stock positions to generate income.
This is a conservative strategy that caps upside but provides premium income.
"""

import pandas as pd
from datetime import date
from typing import Optional

from src.strategies.base import BaseStrategy, SignalDirection, OptionsSignal
from src.broker.alpaca_client import get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class CoveredCallStrategy(BaseStrategy):
    """
    Covered Call: Sell OTM calls against long stock positions.

    Entry Criteria:
    - Must have existing long position
    - Sell call 5-10% OTM
    - Premium >= 1% of stock value
    - Delta between 0.2-0.4
    - DTE: 30-45 days
    """

    def __init__(self):
        super().__init__()
        self.client = get_alpaca_client()
        self._name = "covered_call"

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, symbols: list[str]) -> list[OptionsSignal]:
        """
        Analyze symbols for covered call opportunities.

        Args:
            symbols: List of symbols to analyze

        Returns:
            List of OptionsSignal objects
        """
        if not settings.OPTIONS_ENABLED:
            return []

        signals = []

        try:
            # Get all long stock positions
            positions = self.client.get_positions()

            for position in positions:
                # Only consider long positions
                if position.side != "long" or position.qty <= 0:
                    continue

                # Skip if not in our watchlist
                if position.symbol not in symbols:
                    continue

                logger.debug(f"Analyzing covered call for {position.symbol}")

                # Get options chain
                chain = self.client.get_options_chain(position.symbol)

                if not chain.contracts:
                    logger.debug(f"No options chain for {position.symbol}")
                    continue

                # Find target expiration (30-45 days)
                target_expiration = chain.get_closest_expiration(
                    target_days=settings.COVERED_CALL_TARGET_DTE,
                    min_days=settings.MIN_DAYS_TO_EXPIRATION
                )

                if not target_expiration:
                    logger.debug(f"No suitable expiration for {position.symbol}")
                    continue

                # Find OTM call (5-10% above current price)
                otm_call = chain.get_otm_contract(
                    contract_type='call',
                    expiration=target_expiration,
                    percent_otm=settings.COVERED_CALL_OTM_PERCENT
                )

                if not otm_call:
                    logger.debug(f"No OTM call found for {position.symbol}")
                    continue

                # Validate liquidity
                if not otm_call.is_liquid(
                    settings.MAX_BID_ASK_SPREAD_PCT,
                    settings.MIN_OPTION_OPEN_INTEREST
                ):
                    logger.debug(
                        f"Call not liquid for {position.symbol}: "
                        f"spread {otm_call.spread_percentage:.1f}%, OI {otm_call.open_interest}"
                    )
                    continue

                # Check if premium is attractive (>1% of stock value)
                stock_value_per_share = position.current_price
                premium_pct = (otm_call.bid / stock_value_per_share) * 100

                if premium_pct < settings.COVERED_CALL_MIN_PREMIUM_PCT:
                    logger.debug(
                        f"Premium too low for {position.symbol}: {premium_pct:.2f}%"
                    )
                    continue

                # Validate Greeks (Delta 0.2-0.4 for covered calls)
                if not otm_call.greeks:
                    logger.debug(f"No Greeks for {position.symbol}")
                    continue

                delta = abs(otm_call.greeks.delta)
                if not (settings.COVERED_CALL_MIN_DELTA <= delta <= settings.COVERED_CALL_MAX_DELTA):
                    logger.debug(
                        f"Delta out of range for {position.symbol}: {delta:.2f}"
                    )
                    continue

                # Calculate max profit (premium collected)
                max_profit = otm_call.bid * 100  # Premium per contract

                # Max risk is theoretically unlimited (stock could go to zero)
                # But realistically it's the unrealized gain if assigned
                max_risk = (otm_call.strike - position.current_price) * 100 if otm_call.strike > position.current_price else 0

                # Calculate confidence based on premium yield and delta
                # Higher premium = higher confidence
                # Delta closer to 0.3 = ideal
                premium_score = min(premium_pct / 2.0, 1.0)  # 2% premium = max score
                delta_score = 1.0 - abs(delta - 0.3) / 0.2  # Closer to 0.3 = better
                confidence = (premium_score + delta_score) / 2.0

                # Ensure confidence is reasonable for income strategy
                confidence = max(0.6, min(confidence, 0.85))

                signal = OptionsSignal(
                    symbol=position.symbol,
                    direction=SignalDirection.SHORT,  # Selling call
                    confidence=confidence,
                    strategy=self.name,
                    contract_symbol=otm_call.symbol,
                    contract_type='call',
                    strike=otm_call.strike,
                    expiration=otm_call.expiration,
                    premium=otm_call.bid,
                    max_risk=max_risk,
                    max_profit=max_profit,
                    greeks=otm_call.greeks,
                    metadata={
                        'premium_pct': premium_pct,
                        'delta': delta,
                        'theta': otm_call.greeks.theta,
                        'days_to_expiration': (otm_call.expiration - date.today()).days,
                        'stock_position_qty': position.qty,
                        'stock_price': position.current_price
                    }
                )

                signals.append(signal)

                logger.info(
                    f"Covered call signal: {position.symbol} "
                    f"${otm_call.strike} {otm_call.expiration} "
                    f"premium ${otm_call.bid:.2f} ({premium_pct:.2f}%) "
                    f"delta {delta:.2f} confidence {confidence:.2f}"
                )

        except Exception as e:
            logger.error(f"Error in covered call analysis: {e}")

        return signals

    def get_signal(self, symbol: str, data: pd.DataFrame) -> OptionsSignal:
        """
        Not implemented for options strategies.
        Use analyze() instead.
        """
        signals = self.analyze([symbol])
        return signals[0] if signals else None

    def should_exit(self, symbol: str, data: pd.DataFrame) -> tuple[bool, str]:
        """
        Check if should close covered call.

        Exit criteria:
        - Stock approaching strike (within 2%)
        - Option value < 10% of premium received
        - Close to expiration (<7 days)
        """
        try:
            from src.storage.database import get_database
            db = get_database()

            # Get covered call positions for this underlying
            positions = db.get_option_positions(underlying=symbol)

            for pos in positions:
                if pos['strategy'] != self.name:
                    continue

                # Get current option value
                contract = self.client.get_option_quote(pos['contract_symbol'])
                if not contract:
                    continue

                # Check days to expiration
                dte = (contract.expiration - date.today()).days
                if dte < 7:
                    return True, f"Close to expiration ({dte} days)"

                # Check if profitable to close (option lost most of its value)
                entry_premium = pos['entry_price']
                current_premium = contract.ask

                if current_premium < entry_premium * 0.10:
                    return True, f"Option value dropped to {current_premium/entry_premium:.1%} of original"

                # Check if stock approaching strike (assignment risk)
                stock_price = data['close'].iloc[-1]
                strike = pos['strike']

                if stock_price >= strike * 0.98:  # Within 2% of strike
                    return True, f"Stock at ${stock_price:.2f} approaching strike ${strike:.2f}"

        except Exception as e:
            logger.error(f"Error checking covered call exit: {e}")

        return False, ""
