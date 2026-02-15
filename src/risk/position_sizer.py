from typing import Optional
from dataclasses import dataclass

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


@dataclass
class PositionSize:
    """Result of position sizing calculation."""
    shares: float  # Can be fractional for crypto
    position_value: float
    risk_amount: float
    risk_percent: float
    stop_loss: float
    take_profit: float
    valid: bool
    reason: str


@dataclass
class OptionsPositionSize:
    """Position sizing result for options."""
    contracts: int              # Number of contracts
    premium_per_contract: float
    total_premium: float        # Total cost
    max_risk: float            # For spreads
    delta_exposure: float      # Stock equivalent exposure
    theta_per_day: float       # Time decay
    valid: bool
    reason: str


class PositionSizer:
    """
    Calculates position sizes based on risk management rules.

    Uses the 1-2% risk rule: Never risk more than 1-2% of portfolio on a single trade.
    Position size = (Portfolio * Risk%) / (Entry - Stop)
    """

    def __init__(self, client: Optional[AlpacaClient] = None):
        self.client = client or get_alpaca_client()
        self.max_risk_per_trade = settings.MAX_RISK_PER_TRADE
        self.max_position_size = settings.MAX_POSITION_SIZE
        self.max_positions = settings.MAX_POSITIONS
        self.default_stop_loss = settings.DEFAULT_STOP_LOSS
        self.default_take_profit = settings.DEFAULT_TAKE_PROFIT

    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        direction: str = "long",
        risk_percent: Optional[float] = None
    ) -> PositionSize:
        """
        Calculate the appropriate position size based on risk parameters.

        Args:
            symbol: Stock symbol
            entry_price: Planned entry price
            stop_loss_price: Stop loss price (if None, uses default %)
            take_profit_price: Take profit price (if None, uses default %)
            direction: 'long' or 'short'
            risk_percent: Override risk percentage (default uses settings)

        Returns:
            PositionSize with calculated values
        """
        try:
            account = self.client.get_account()
            portfolio_value = account.portfolio_value
            available_cash = account.buying_power

            positions = self.client.get_positions()
            current_position_count = len(positions)

            if current_position_count >= self.max_positions:
                return PositionSize(
                    shares=0,
                    position_value=0,
                    risk_amount=0,
                    risk_percent=0,
                    stop_loss=0,
                    take_profit=0,
                    valid=False,
                    reason=f"Max positions ({self.max_positions}) reached"
                )

            risk_pct = risk_percent or self.max_risk_per_trade

            # Use crypto-specific risk parameters if applicable
            is_crypto = settings.is_crypto_symbol(symbol)
            stop_loss_pct = settings.CRYPTO_STOP_LOSS if is_crypto else self.default_stop_loss
            take_profit_pct = settings.CRYPTO_TAKE_PROFIT if is_crypto else self.default_take_profit
            max_position = settings.CRYPTO_MAX_POSITION_SIZE if is_crypto else self.max_position_size

            if stop_loss_price is None:
                if direction == "long":
                    stop_loss_price = entry_price * (1 - stop_loss_pct)
                else:
                    stop_loss_price = entry_price * (1 + stop_loss_pct)

            if take_profit_price is None:
                if direction == "long":
                    take_profit_price = entry_price * (1 + take_profit_pct)
                else:
                    take_profit_price = entry_price * (1 - take_profit_pct)

            if direction == "long":
                risk_per_share = entry_price - stop_loss_price
            else:
                risk_per_share = stop_loss_price - entry_price

            if risk_per_share <= 0:
                return PositionSize(
                    shares=0,
                    position_value=0,
                    risk_amount=0,
                    risk_percent=0,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                    valid=False,
                    reason="Invalid stop loss (no risk per share)"
                )

            risk_amount = portfolio_value * risk_pct
            shares_by_risk = risk_amount / risk_per_share

            max_position_value = portfolio_value * max_position
            shares_by_position = max_position_value / entry_price

            shares_by_cash = available_cash / entry_price

            shares_raw = min(shares_by_risk, shares_by_position, shares_by_cash)

            # Crypto supports fractional quantities, stocks require whole shares
            if is_crypto:
                shares = round(shares_raw, 6)  # 6 decimal places for crypto
            else:
                shares = int(shares_raw)

            if shares <= 0:
                return PositionSize(
                    shares=0,
                    position_value=0,
                    risk_amount=0,
                    risk_percent=0,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                    valid=False,
                    reason="Insufficient capital for minimum position"
                )

            position_value = shares * entry_price
            actual_risk = shares * risk_per_share
            actual_risk_pct = actual_risk / portfolio_value

            logger.info(
                f"Position size for {symbol}: {shares} shares @ ${entry_price:.2f} = ${position_value:.2f} "
                f"(Risk: ${actual_risk:.2f} = {actual_risk_pct:.2%})"
            )

            return PositionSize(
                shares=shares,
                position_value=position_value,
                risk_amount=actual_risk,
                risk_percent=actual_risk_pct,
                stop_loss=round(stop_loss_price, 2),
                take_profit=round(take_profit_price, 2),
                valid=True,
                reason="OK"
            )

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return PositionSize(
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_percent=0,
                stop_loss=0,
                take_profit=0,
                valid=False,
                reason=str(e)
            )

    def calculate_stop_loss(
        self,
        entry_price: float,
        atr: Optional[float] = None,
        direction: str = "long",
        multiplier: float = 2.0
    ) -> float:
        """
        Calculate stop loss price.

        Args:
            entry_price: Entry price
            atr: Average True Range (if available, uses ATR-based stop)
            direction: 'long' or 'short'
            multiplier: ATR multiplier for stop distance

        Returns:
            Stop loss price
        """
        if atr:
            stop_distance = atr * multiplier
        else:
            stop_distance = entry_price * self.default_stop_loss

        if direction == "long":
            return round(entry_price - stop_distance, 2)
        else:
            return round(entry_price + stop_distance, 2)

    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: str = "long",
        risk_reward_ratio: float = 2.0
    ) -> float:
        """
        Calculate take profit price based on risk/reward ratio.

        Args:
            entry_price: Entry price
            stop_loss_price: Stop loss price
            direction: 'long' or 'short'
            risk_reward_ratio: Desired risk/reward ratio

        Returns:
            Take profit price
        """
        risk = abs(entry_price - stop_loss_price)
        reward = risk * risk_reward_ratio

        if direction == "long":
            return round(entry_price + reward, 2)
        else:
            return round(entry_price - reward, 2)

    def get_portfolio_risk_status(self) -> dict:
        """Get current portfolio risk status."""
        try:
            account = self.client.get_account()
            positions = self.client.get_positions()

            total_position_value = sum(p.market_value for p in positions)
            total_unrealized_pnl = sum(p.unrealized_pl for p in positions)

            position_concentration = {}
            for p in positions:
                pct = abs(p.market_value) / account.portfolio_value
                position_concentration[p.symbol] = pct

            return {
                "portfolio_value": account.portfolio_value,
                "cash": account.cash,
                "buying_power": account.buying_power,
                "total_position_value": total_position_value,
                "total_unrealized_pnl": total_unrealized_pnl,
                "position_count": len(positions),
                "max_positions": self.max_positions,
                "position_concentration": position_concentration,
                "max_risk_per_trade": self.max_risk_per_trade,
                "max_position_size": self.max_position_size
            }

        except Exception as e:
            logger.error(f"Error getting portfolio risk status: {e}")
            return {"error": str(e)}

    def validate_trade(
        self,
        symbol: str,
        shares: int,
        entry_price: float,
        stop_loss_price: float
    ) -> tuple[bool, str]:
        """
        Validate a proposed trade against risk rules.

        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            account = self.client.get_account()
            position_value = shares * entry_price
            risk_amount = shares * abs(entry_price - stop_loss_price)

            if position_value > account.buying_power:
                return False, "Insufficient buying power"

            position_pct = position_value / account.portfolio_value
            if position_pct > self.max_position_size:
                return False, f"Position size {position_pct:.1%} exceeds max {self.max_position_size:.1%}"

            risk_pct = risk_amount / account.portfolio_value
            if risk_pct > self.max_risk_per_trade:
                return False, f"Risk {risk_pct:.1%} exceeds max {self.max_risk_per_trade:.1%}"

            positions = self.client.get_positions()
            if len(positions) >= self.max_positions:
                existing = any(p.symbol == symbol for p in positions)
                if not existing:
                    return False, f"Max positions ({self.max_positions}) reached"

            return True, "OK"

        except Exception as e:
            return False, str(e)

    def calculate_option_position_size(
        self,
        contract: 'OptionContract',  # Forward reference
        is_debit: bool = True,
        spread_width: Optional[float] = None
    ) -> OptionsPositionSize:
        """
        Calculate position size for options using risk-based approach.

        Args:
            contract: OptionContract object
            is_debit: True if buying options, False if selling
            spread_width: For spreads, the width between strikes

        Returns:
            OptionsPositionSize with calculated values
        """
        try:
            account = self.client.get_account()
            buying_power = account.buying_power
            portfolio_value = account.portfolio_value

            # Get current options positions count
            from src.storage.database import get_database
            db = get_database()
            current_options = len(db.get_option_positions())

            # Check max options positions
            if current_options >= settings.MAX_OPTIONS_POSITIONS:
                return OptionsPositionSize(
                    contracts=0,
                    premium_per_contract=0,
                    total_premium=0,
                    max_risk=0,
                    delta_exposure=0,
                    theta_per_day=0,
                    valid=False,
                    reason=f"Max options positions ({settings.MAX_OPTIONS_POSITIONS}) reached"
                )

            # Risk-based sizing
            max_risk_dollars = portfolio_value * settings.MAX_RISK_PER_TRADE

            if is_debit:
                # Buying options: risk = premium paid
                risk_per_contract = contract.ask * 100
                max_contracts_by_risk = int(max_risk_dollars / risk_per_contract)
            else:
                # Selling options: risk = potential loss
                if spread_width:
                    # Defined risk spread
                    risk_per_contract = spread_width * 100
                else:
                    # Naked options - use margin requirement estimate
                    risk_per_contract = contract.strike * 100 * 0.2  # Rough margin
                max_contracts_by_risk = int(max_risk_dollars / risk_per_contract)

            # Apply position size limit
            max_position_dollars = portfolio_value * settings.MAX_OPTIONS_POSITION_SIZE
            max_contracts_by_position = int(max_position_dollars / (contract.ask * 100))

            # Apply absolute limit
            max_contracts_by_limit = settings.MAX_CONTRACTS_PER_POSITION

            # Take minimum of all constraints
            contracts = min(
                max_contracts_by_risk,
                max_contracts_by_position,
                max_contracts_by_limit
            )

            # Validate
            if contracts <= 0:
                return OptionsPositionSize(
                    contracts=0,
                    premium_per_contract=0,
                    total_premium=0,
                    max_risk=0,
                    delta_exposure=0,
                    theta_per_day=0,
                    valid=False,
                    reason="Insufficient capital for option position"
                )

            # Calculate exposure
            premium_per_contract = contract.ask
            total_premium = contracts * premium_per_contract * 100

            # Validate against buying power
            if total_premium > buying_power:
                contracts = int(buying_power / (premium_per_contract * 100))
                if contracts <= 0:
                    return OptionsPositionSize(
                        contracts=0,
                        premium_per_contract=0,
                        total_premium=0,
                        max_risk=0,
                        delta_exposure=0,
                        theta_per_day=0,
                        valid=False,
                        reason="Insufficient buying power"
                    )
                total_premium = contracts * premium_per_contract * 100

            # Calculate Greeks exposure
            if contract.greeks:
                delta_exposure = contracts * 100 * abs(contract.greeks.delta)
                theta_per_day = contracts * contract.greeks.theta
            else:
                delta_exposure = 0
                theta_per_day = 0

            # Calculate max risk
            if is_debit:
                max_risk = total_premium
            elif spread_width:
                max_risk = spread_width * 100 * contracts
            else:
                max_risk = contract.strike * 100 * contracts  # Worst case

            logger.info(
                f"Options position size for {contract.symbol}: {contracts} contracts @ ${premium_per_contract:.2f} = ${total_premium:.2f} "
                f"(Delta exposure: {delta_exposure:.0f} shares, Max risk: ${max_risk:.2f})"
            )

            return OptionsPositionSize(
                contracts=contracts,
                premium_per_contract=premium_per_contract,
                total_premium=total_premium,
                max_risk=max_risk,
                delta_exposure=delta_exposure,
                theta_per_day=theta_per_day,
                valid=True,
                reason="OK"
            )

        except Exception as e:
            logger.error(f"Error calculating options position size: {e}")
            return OptionsPositionSize(
                contracts=0,
                premium_per_contract=0,
                total_premium=0,
                max_risk=0,
                delta_exposure=0,
                theta_per_day=0,
                valid=False,
                reason=str(e)
            )

    def validate_options_greeks(
        self,
        contracts: int,
        contract: 'OptionContract'  # Forward reference
    ) -> tuple[bool, str]:
        """
        Validate that options Greeks are within acceptable limits.

        Args:
            contracts: Number of contracts
            contract: OptionContract object

        Returns:
            Tuple of (is_valid, reason)
        """
        if not contract.greeks:
            return False, "Greeks not available"

        # Check delta exposure
        delta_exposure = contracts * 100 * abs(contract.greeks.delta)

        try:
            account = self.client.get_account()
            max_delta_dollars = account.portfolio_value * settings.MAX_DELTA_EXPOSURE

            if delta_exposure > max_delta_dollars:
                return False, f"Delta exposure ${delta_exposure:.0f} exceeds max ${max_delta_dollars:.0f}"

            # Check theta decay
            theta_per_day = contracts * contract.greeks.theta
            position_value = contracts * contract.ask * 100

            if position_value > 0:
                theta_ratio = abs(theta_per_day) / position_value
                if theta_ratio > abs(settings.MIN_THETA_RATIO):
                    return False, f"Theta decay {theta_ratio:.2%}/day exceeds limit {settings.MIN_THETA_RATIO:.2%}"

            return True, "OK"

        except Exception as e:
            return False, str(e)
