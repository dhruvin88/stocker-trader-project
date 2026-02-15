"""
Unusual Options Activity Scanner

Detects unusual options volume and open interest to identify potential
trading opportunities. Large institutional orders often precede significant
price moves.
"""

import pandas as pd
from datetime import date, datetime
from typing import Optional

from src.strategies.base import BaseStrategy, SignalDirection, OptionsSignal
from src.broker.alpaca_client import get_alpaca_client
from src.storage.database import get_database
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


class UnusualOptionsActivity(BaseStrategy):
    """
    Unusual Activity Scanner: Trade based on unusual volume/OI.

    Entry Criteria:
    - Volume >= 3x average (20-day)
    - OI change >= 50% (from previous day)
    - Large block trades detected
    - Call/put ratio indicates direction
    - Contract must be liquid

    Signal Interpretation:
    - Unusual call volume = Bullish signal
    - Unusual put volume = Bearish signal
    - Mixed signals = Skip (no clear direction)
    """

    def __init__(self):
        super().__init__()
        self.client = get_alpaca_client()
        self.db = get_database()
        self._name = "unusual_activity"
        self.volume_threshold = settings.UNUSUAL_VOLUME_THRESHOLD
        self.oi_change_threshold = settings.UNUSUAL_OI_CHANGE_THRESHOLD

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, symbols: list[str]) -> list[OptionsSignal]:
        """
        Scan for unusual options activity.

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
                logger.debug(f"Scanning unusual activity for {symbol}")

                # Get options chain
                chain = self.client.get_options_chain(symbol)

                if not chain.contracts:
                    continue

                # Cache current chain for future analysis
                self._cache_chain(symbol, chain)

                # Find contracts with unusual activity
                unusual_contracts = self._find_unusual_activity(symbol, chain)

                if not unusual_contracts:
                    continue

                # Determine overall sentiment (calls vs puts)
                sentiment = self._determine_sentiment(unusual_contracts)

                if sentiment == "neutral":
                    logger.debug(f"Mixed signals for {symbol}, skipping")
                    continue

                # Select best contract to trade
                best_contract = self._select_best_contract(unusual_contracts, sentiment)

                if not best_contract:
                    continue

                # Generate signal
                signal = self._create_signal(symbol, best_contract, sentiment)

                if signal:
                    signals.append(signal)

        except Exception as e:
            logger.error(f"Error scanning unusual activity: {e}")

        return signals

    def _cache_chain(self, symbol: str, chain) -> None:
        """Cache options chain data for historical analysis."""
        try:
            for contract in chain.contracts.values():
                if not contract.greeks:
                    continue

                self.db.cache_options_chain(
                    underlying=symbol,
                    contract_symbol=contract.symbol,
                    strike=contract.strike,
                    expiration=contract.expiration,
                    contract_type=contract.contract_type,
                    bid=contract.bid,
                    ask=contract.ask,
                    volume=contract.volume,
                    open_interest=contract.open_interest,
                    implied_volatility=contract.implied_volatility,
                    delta=contract.greeks.delta,
                    gamma=contract.greeks.gamma,
                    theta=contract.greeks.theta,
                    vega=contract.greeks.vega
                )
        except Exception as e:
            logger.debug(f"Error caching chain for {symbol}: {e}")

    def _find_unusual_activity(self, symbol: str, chain) -> list:
        """Find contracts with unusual volume or OI."""
        unusual = []

        for contract in chain.contracts.values():
            # Skip if not liquid
            if not contract.is_liquid():
                continue

            # Skip if DTE too short or too long
            dte = (contract.expiration - date.today()).days
            if dte < settings.MIN_DAYS_TO_EXPIRATION or dte > settings.MAX_DAYS_TO_EXPIRATION:
                continue

            # Get historical average volume
            avg_volume = self._get_average_volume(contract.symbol, days=20)

            if avg_volume == 0:
                continue  # No historical data yet

            # Calculate volume ratio
            volume_ratio = contract.volume / avg_volume if avg_volume > 0 else 0

            # Check for unusual volume
            if volume_ratio >= self.volume_threshold:
                unusual.append({
                    'contract': contract,
                    'volume_ratio': volume_ratio,
                    'type': 'volume',
                    'score': min(volume_ratio / self.volume_threshold, 3.0)  # Cap at 3x threshold
                })

                logger.debug(
                    f"Unusual volume in {contract.symbol}: "
                    f"{contract.volume:,} (avg: {avg_volume:,.0f}, "
                    f"ratio: {volume_ratio:.1f}x)"
                )

            # Check for unusual OI change
            # This requires historical OI data
            oi_change_pct = self._get_oi_change(contract.symbol)
            if oi_change_pct and oi_change_pct >= self.oi_change_threshold:
                unusual.append({
                    'contract': contract,
                    'oi_change_pct': oi_change_pct,
                    'type': 'oi_change',
                    'score': min(oi_change_pct / self.oi_change_threshold, 2.0)
                })

                logger.debug(
                    f"Unusual OI change in {contract.symbol}: "
                    f"{oi_change_pct:.1f}% increase"
                )

        return unusual

    def _get_average_volume(self, contract_symbol: str, days: int = 20) -> float:
        """Get average volume from historical data."""
        try:
            history = self.db.get_historical_option_volume(contract_symbol, days=days)

            if not history:
                return 0.0

            volumes = [h['volume'] for h in history if h['volume'] is not None]

            if not volumes:
                return 0.0

            return sum(volumes) / len(volumes)

        except Exception as e:
            logger.debug(f"Error getting average volume: {e}")
            return 0.0

    def _get_oi_change(self, contract_symbol: str) -> Optional[float]:
        """Calculate OI change from yesterday."""
        try:
            history = self.db.get_historical_option_volume(contract_symbol, days=2)

            if len(history) < 2:
                return None

            # Sort by timestamp
            history = sorted(history, key=lambda x: x['timestamp'])

            yesterday_oi = history[-2]['open_interest']
            today_oi = history[-1]['open_interest']

            if yesterday_oi == 0:
                return None

            change_pct = ((today_oi - yesterday_oi) / yesterday_oi) * 100

            return change_pct if change_pct > 0 else None

        except Exception as e:
            logger.debug(f"Error calculating OI change: {e}")
            return None

    def _determine_sentiment(self, unusual_contracts: list) -> str:
        """Determine overall sentiment from unusual activity."""
        call_score = 0.0
        put_score = 0.0

        for item in unusual_contracts:
            contract = item['contract']
            score = item['score']

            if contract.contract_type == 'call':
                call_score += score
            else:
                put_score += score

        # If scores are similar, it's neutral/unclear
        total = call_score + put_score
        if total == 0:
            return "neutral"

        call_pct = call_score / total
        put_pct = put_score / total

        # Need clear dominance (>60%) to generate signal
        if call_pct > 0.60:
            return "bullish"
        elif put_pct > 0.60:
            return "bearish"
        else:
            return "neutral"

    def _select_best_contract(self, unusual_contracts: list, sentiment: str) -> Optional:
        """Select the best contract to trade based on sentiment."""
        # Filter by sentiment
        if sentiment == "bullish":
            candidates = [
                item for item in unusual_contracts
                if item['contract'].contract_type == 'call'
            ]
        elif sentiment == "bearish":
            candidates = [
                item for item in unusual_contracts
                if item['contract'].contract_type == 'put'
            ]
        else:
            return None

        if not candidates:
            return None

        # Sort by score (highest first)
        candidates.sort(key=lambda x: x['score'], reverse=True)

        # Return contract from top candidate
        return candidates[0]['contract']

    def _create_signal(
        self,
        symbol: str,
        contract,
        sentiment: str
    ) -> Optional[OptionsSignal]:
        """Create options signal from unusual activity."""
        try:
            # Validate contract has Greeks
            if not contract.greeks:
                return None

            # Calculate confidence based on activity level
            # Higher volume ratio or OI change = higher confidence
            avg_volume = self._get_average_volume(contract.symbol)
            volume_ratio = contract.volume / avg_volume if avg_volume > 0 else 1.0

            # Base confidence on volume spike magnitude
            confidence = 0.5 + min((volume_ratio - self.volume_threshold) * 0.1, 0.35)
            confidence = max(0.6, min(confidence, 0.90))

            # Determine direction
            direction = SignalDirection.LONG if sentiment == "bullish" else SignalDirection.SHORT

            # Calculate max risk/profit
            if direction == SignalDirection.LONG:
                # Buying option
                max_risk = contract.ask * 100
                max_profit = float('inf')  # Theoretically unlimited for calls
            else:
                # Shorting option (selling)
                max_risk = contract.strike * 100 if contract.contract_type == 'put' else float('inf')
                max_profit = contract.bid * 100

            signal = OptionsSignal(
                symbol=symbol,
                direction=direction,
                confidence=confidence,
                strategy=self.name,
                contract_symbol=contract.symbol,
                contract_type=contract.contract_type,
                strike=contract.strike,
                expiration=contract.expiration,
                premium=contract.ask if direction == SignalDirection.LONG else contract.bid,
                max_risk=max_risk,
                max_profit=max_profit,
                greeks=contract.greeks,
                metadata={
                    'volume': contract.volume,
                    'avg_volume': avg_volume,
                    'volume_ratio': volume_ratio,
                    'open_interest': contract.open_interest,
                    'sentiment': sentiment,
                    'days_to_expiration': (contract.expiration - date.today()).days
                }
            )

            logger.info(
                f"Unusual activity signal: {sentiment.upper()} {symbol} "
                f"{contract.contract_type} ${contract.strike} {contract.expiration} "
                f"volume {contract.volume:,} ({volume_ratio:.1f}x avg) "
                f"confidence {confidence:.2f}"
            )

            return signal

        except Exception as e:
            logger.error(f"Error creating unusual activity signal: {e}")
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
        Check if should exit unusual activity position.

        Exit criteria:
        - Volume normalized (no longer unusual)
        - Profit target reached (100% gain)
        - Close to expiration (<7 days)
        - Stop loss (50% loss)
        """
        try:
            # Get positions from this strategy
            positions = self.db.get_option_positions(underlying=symbol)

            for pos in positions:
                if pos['strategy'] != self.name:
                    continue

                # Get current contract value
                contract = self.client.get_option_quote(pos['contract_symbol'])
                if not contract:
                    continue

                # Check days to expiration
                dte = (contract.expiration - date.today()).days
                if dte < 7:
                    return True, f"Close to expiration ({dte} days)"

                # Calculate P&L
                entry_price = pos['entry_price']
                current_price = contract.bid

                pnl_pct = ((current_price - entry_price) / entry_price) * 100

                # Take profit at 100% gain
                if pnl_pct >= 100:
                    return True, f"Profit target reached ({pnl_pct:.1f}%)"

                # Stop loss at 50% loss
                if pnl_pct <= -50:
                    return True, f"Stop loss triggered ({pnl_pct:.1f}%)"

                # Exit if volume normalized
                current_volume = contract.volume
                avg_volume = self._get_average_volume(contract.symbol, days=5)

                if avg_volume > 0:
                    volume_ratio = current_volume / avg_volume
                    if volume_ratio < 1.5:  # Back to normal
                        return True, "Volume normalized, unusual activity ended"

        except Exception as e:
            logger.error(f"Error checking unusual activity exit: {e}")

        return False, ""
