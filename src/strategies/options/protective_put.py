"""
Protective Put Strategy

Buys put options to protect long stock positions from downside risk.
This is an insurance strategy that limits losses while maintaining upside potential.
"""

import pandas as pd
from datetime import date
from typing import Optional

from src.strategies.base import BaseStrategy, SignalDirection, OptionsSignal
from src.broker.alpaca_client import get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class ProtectivePutStrategy(BaseStrategy):
    """
    Protective Put: Buy OTM puts to protect long stock positions.

    Entry Criteria:
    - Must have existing long position
    - Buy put 5-10% OTM
    - Cost <= 2% of position value
    - Delta between -0.2 and -0.4 (absolute value 0.2-0.4)
    - DTE: 30-60 days
    - Use when expecting increased volatility or protecting gains
    """

    def __init__(self):
        super().__init__()
        self.client = get_alpaca_client()
        from src.storage.database import get_database
        self.db = get_database()
        self._name = "protective_put"

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, symbols: list[str]) -> list[OptionsSignal]:
        """
        Analyze symbols for protective put opportunities.

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

                logger.debug(f"Analyzing protective put for {position.symbol}")

                # Check if we already have protective put for this position
                existing_puts = self.db.get_option_positions(underlying=position.symbol)
                has_protective_put = any(
                    pos['contract_type'] == 'put' and pos['strategy'] == self.name
                    for pos in existing_puts
                )

                if has_protective_put:
                    logger.debug(f"Already have protective put for {position.symbol}")
                    continue

                # Get options chain
                chain = self.client.get_options_chain(position.symbol)

                if not chain.contracts:
                    logger.debug(f"No options chain for {position.symbol}")
                    continue

                # Find target expiration (30-60 days)
                target_expiration = chain.get_closest_expiration(
                    target_days=45,  # Target 45 days
                    min_days=settings.MIN_DAYS_TO_EXPIRATION
                )

                if not target_expiration:
                    logger.debug(f"No suitable expiration for {position.symbol}")
                    continue

                # Find OTM put (5-10% below current price)
                otm_put = chain.get_otm_contract(
                    contract_type='put',
                    expiration=target_expiration,
                    percent_otm=settings.PROTECTIVE_PUT_OTM_PERCENT
                )

                if not otm_put:
                    logger.debug(f"No OTM put found for {position.symbol}")
                    continue

                # Validate liquidity
                if not otm_put.is_liquid(
                    settings.MAX_BID_ASK_SPREAD_PCT,
                    settings.MIN_OPTION_OPEN_INTEREST
                ):
                    logger.debug(
                        f"Put not liquid for {position.symbol}: "
                        f"spread {otm_put.spread_percentage:.1f}%, OI {otm_put.open_interest}"
                    )
                    continue

                # Check if cost is acceptable (<2% of position value)
                position_value = position.current_price * position.qty
                put_cost = otm_put.ask * 100  # Cost per contract
                cost_pct = (put_cost / position_value) * 100

                if cost_pct > settings.PROTECTIVE_PUT_MAX_COST_PCT:
                    logger.debug(
                        f"Put too expensive for {position.symbol}: {cost_pct:.2f}% "
                        f"(max {settings.PROTECTIVE_PUT_MAX_COST_PCT}%)"
                    )
                    continue

                # Validate Greeks (Delta -0.2 to -0.4 for protective puts)
                if not otm_put.greeks:
                    logger.debug(f"No Greeks for {position.symbol}")
                    continue

                delta = abs(otm_put.greeks.delta)
                if not (settings.PROTECTIVE_PUT_MIN_DELTA <= delta <= settings.PROTECTIVE_PUT_MAX_DELTA):
                    logger.debug(
                        f"Delta out of range for {position.symbol}: {delta:.2f}"
                    )
                    continue

                # Calculate protection details
                # Max loss if stock drops to strike
                protected_value = otm_put.strike * position.qty
                current_value = position.current_price * position.qty
                max_loss = current_value - protected_value + put_cost

                # Calculate confidence based on cost efficiency and delta
                # Lower cost = higher confidence
                cost_score = 1.0 - (cost_pct / settings.PROTECTIVE_PUT_MAX_COST_PCT)
                # Delta closer to -0.3 = ideal
                delta_score = 1.0 - abs(delta - 0.3) / 0.2
                confidence = (cost_score + delta_score) / 2.0

                # Ensure confidence is reasonable for insurance strategy
                confidence = max(0.6, min(confidence, 0.85))

                # Calculate how many contracts needed (1 per 100 shares)
                contracts_needed = int(position.qty / 100)

                signal = OptionsSignal(
                    symbol=position.symbol,
                    direction=SignalDirection.LONG,  # Buying put
                    confidence=confidence,
                    strategy=self.name,
                    contract_symbol=otm_put.symbol,
                    contract_type='put',
                    strike=otm_put.strike,
                    expiration=otm_put.expiration,
                    premium=otm_put.ask,
                    max_risk=put_cost * contracts_needed,  # Premium paid
                    max_profit=float('inf'),  # Unlimited if stock goes to zero
                    greeks=otm_put.greeks,
                    metadata={
                        'cost_pct': cost_pct,
                        'delta': otm_put.greeks.delta,
                        'theta': otm_put.greeks.theta,
                        'days_to_expiration': (otm_put.expiration - date.today()).days,
                        'stock_position_qty': position.qty,
                        'stock_price': position.current_price,
                        'contracts_needed': contracts_needed,
                        'protected_value': protected_value,
                        'max_loss': max_loss
                    }
                )

                signals.append(signal)

                logger.info(
                    f"Protective put signal: {position.symbol} "
                    f"${otm_put.strike} {otm_put.expiration} "
                    f"cost ${otm_put.ask:.2f} ({cost_pct:.2f}% of position) "
                    f"delta {otm_put.greeks.delta:.2f} confidence {confidence:.2f}"
                )

        except Exception as e:
            logger.error(f"Error in protective put analysis: {e}")

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
        Check if should close protective put.

        Exit criteria:
        - Stock recovered significantly (>10% above entry)
        - Put value < 20% of premium paid (insurance no longer needed)
        - Close to expiration (<7 days)
        - Stock approaching strike (within 5%)
        """
        try:
            from src.storage.database import get_database
            db = get_database()

            # Get protective put positions for this underlying
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

                # Get current stock price
                stock_price = data['close'].iloc[-1]
                strike = pos['strike']

                # If stock approaching strike (within 5%), keep the protection
                # But if stock recovered significantly, can close
                stock_change_pct = ((stock_price - pos['metadata'].get('stock_price', stock_price)) /
                                   pos['metadata'].get('stock_price', stock_price)) * 100

                if stock_change_pct > 10:
                    return True, f"Stock recovered {stock_change_pct:.1f}%, protection no longer needed"

                # If put lost most of its value, consider closing
                entry_premium = pos['entry_price']
                current_premium = contract.bid

                if current_premium < entry_premium * 0.20:
                    return True, f"Put value dropped to {current_premium/entry_premium:.1%} of original"

                # If stock close to strike, consider rolling to lower strike
                if stock_price <= strike * 1.05:
                    return True, f"Stock at ${stock_price:.2f} approaching strike ${strike:.2f}"

        except Exception as e:
            logger.error(f"Error checking protective put exit: {e}")

        return False, ""
