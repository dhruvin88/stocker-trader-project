from typing import Optional
from dataclasses import dataclass

from src.broker.alpaca_client import AlpacaClient, get_alpaca_client
from src.utils.logger import get_logger
from config.settings import settings

logger = get_logger(__name__)


@dataclass
class PositionSize:
    """Result of position sizing calculation."""
    shares: int
    position_value: float
    risk_amount: float
    risk_percent: float
    stop_loss: float
    take_profit: float
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

            if stop_loss_price is None:
                if direction == "long":
                    stop_loss_price = entry_price * (1 - self.default_stop_loss)
                else:
                    stop_loss_price = entry_price * (1 + self.default_stop_loss)

            if take_profit_price is None:
                if direction == "long":
                    take_profit_price = entry_price * (1 + self.default_take_profit)
                else:
                    take_profit_price = entry_price * (1 - self.default_take_profit)

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
            shares_by_risk = int(risk_amount / risk_per_share)

            max_position_value = portfolio_value * self.max_position_size
            shares_by_position = int(max_position_value / entry_price)

            shares_by_cash = int(available_cash / entry_price)

            shares = min(shares_by_risk, shares_by_position, shares_by_cash)

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
