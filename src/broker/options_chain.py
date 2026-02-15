"""
Options chain data structures and utilities.

This module provides data classes for representing options contracts
and complete options chains with filtering and search capabilities.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.risk.options_greeks import OptionGreeks


@dataclass
class OptionContract:
    """
    Represents a single option contract with pricing and Greeks.

    Attributes:
        symbol: Full option contract symbol (e.g., "AAPL230120C00150000")
        underlying: Underlying symbol (e.g., "AAPL")
        contract_type: "call" or "put"
        strike: Strike price
        expiration: Expiration date
        bid: Current bid price per share
        ask: Current ask price per share
        last: Last traded price
        volume: Trading volume
        open_interest: Total open contracts
        implied_volatility: Implied volatility (e.g., 0.25 for 25%)
        greeks: Calculated Greeks for this contract
    """
    symbol: str
    underlying: str
    contract_type: str
    strike: float
    expiration: date
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float
    greeks: Optional[OptionGreeks] = None

    @property
    def mid_price(self) -> float:
        """Calculate mid-point between bid and ask."""
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def bid_ask_spread(self) -> float:
        """Calculate bid-ask spread."""
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def spread_percentage(self) -> float:
        """Calculate bid-ask spread as percentage of mid price."""
        mid = self.mid_price
        if mid > 0:
            return (self.bid_ask_spread / mid) * 100.0
        return 0.0

    def is_liquid(self, max_spread_pct: float = 10.0, min_oi: int = 100) -> bool:
        """
        Check if contract has sufficient liquidity.

        Args:
            max_spread_pct: Maximum acceptable spread percentage
            min_oi: Minimum open interest

        Returns:
            True if contract meets liquidity criteria
        """
        return (
            self.spread_percentage <= max_spread_pct and
            self.open_interest >= min_oi
        )


@dataclass
class OptionsChain:
    """
    Complete options chain for an underlying symbol.

    Attributes:
        underlying: Underlying symbol
        underlying_price: Current price of underlying
        expirations: List of available expiration dates
        contracts: Dictionary of contracts keyed by contract symbol
    """
    underlying: str
    underlying_price: float
    expirations: list[date]
    contracts: dict[str, OptionContract] = field(default_factory=dict)

    def get_contracts_by_expiration(
        self,
        expiration: date,
        contract_type: Optional[str] = None
    ) -> list[OptionContract]:
        """
        Filter contracts by expiration date.

        Args:
            expiration: Target expiration date
            contract_type: Optional filter for 'call' or 'put'

        Returns:
            List of matching contracts sorted by strike
        """
        contracts = [
            c for c in self.contracts.values()
            if c.expiration == expiration
        ]

        if contract_type:
            contracts = [c for c in contracts if c.contract_type == contract_type]

        return sorted(contracts, key=lambda x: x.strike)

    def get_closest_strike(
        self,
        target_strike: float,
        contract_type: str,
        expiration: date
    ) -> Optional[OptionContract]:
        """
        Find contract with strike closest to target.

        Args:
            target_strike: Desired strike price
            contract_type: 'call' or 'put'
            expiration: Expiration date

        Returns:
            Contract closest to target strike, or None if not found
        """
        candidates = self.get_contracts_by_expiration(expiration, contract_type)

        if not candidates:
            return None

        # Find closest by absolute difference
        return min(candidates, key=lambda c: abs(c.strike - target_strike))

    def get_atm_contract(
        self,
        contract_type: str,
        expiration: date
    ) -> Optional[OptionContract]:
        """
        Get at-the-money contract.

        Args:
            contract_type: 'call' or 'put'
            expiration: Expiration date

        Returns:
            Contract with strike closest to current underlying price
        """
        return self.get_closest_strike(
            self.underlying_price,
            contract_type,
            expiration
        )

    def get_otm_contract(
        self,
        contract_type: str,
        expiration: date,
        percent_otm: float = 5.0
    ) -> Optional[OptionContract]:
        """
        Get out-of-the-money contract.

        Args:
            contract_type: 'call' or 'put'
            expiration: Expiration date
            percent_otm: Percentage out of the money (default 5%)

        Returns:
            OTM contract at specified distance
        """
        if contract_type == 'call':
            # OTM call is above current price
            target_strike = self.underlying_price * (1 + percent_otm / 100.0)
        else:
            # OTM put is below current price
            target_strike = self.underlying_price * (1 - percent_otm / 100.0)

        return self.get_closest_strike(target_strike, contract_type, expiration)

    def get_itm_contract(
        self,
        contract_type: str,
        expiration: date,
        percent_itm: float = 5.0
    ) -> Optional[OptionContract]:
        """
        Get in-the-money contract.

        Args:
            contract_type: 'call' or 'put'
            expiration: Expiration date
            percent_itm: Percentage in the money (default 5%)

        Returns:
            ITM contract at specified distance
        """
        if contract_type == 'call':
            # ITM call is below current price
            target_strike = self.underlying_price * (1 - percent_itm / 100.0)
        else:
            # ITM put is above current price
            target_strike = self.underlying_price * (1 + percent_itm / 100.0)

        return self.get_closest_strike(target_strike, contract_type, expiration)

    def filter_by_delta(
        self,
        min_delta: float,
        max_delta: float,
        contract_type: str,
        expiration: Optional[date] = None
    ) -> list[OptionContract]:
        """
        Filter contracts by delta range.

        Args:
            min_delta: Minimum delta (absolute value)
            max_delta: Maximum delta (absolute value)
            contract_type: 'call' or 'put'
            expiration: Optional expiration filter

        Returns:
            List of contracts within delta range
        """
        contracts = [
            c for c in self.contracts.values()
            if c.contract_type == contract_type
            and c.greeks is not None
            and min_delta <= abs(c.greeks.delta) <= max_delta
        ]

        if expiration:
            contracts = [c for c in contracts if c.expiration == expiration]

        return sorted(contracts, key=lambda x: x.strike)

    def filter_liquid(
        self,
        max_spread_pct: float = 10.0,
        min_oi: int = 100
    ) -> list[OptionContract]:
        """
        Filter for liquid contracts only.

        Args:
            max_spread_pct: Maximum acceptable spread percentage
            min_oi: Minimum open interest

        Returns:
            List of liquid contracts
        """
        return [
            c for c in self.contracts.values()
            if c.is_liquid(max_spread_pct, min_oi)
        ]

    def get_closest_expiration(
        self,
        target_days: int,
        min_days: int = 7
    ) -> Optional[date]:
        """
        Find expiration closest to target number of days out.

        Args:
            target_days: Target days to expiration
            min_days: Minimum acceptable days (default 7)

        Returns:
            Closest expiration date meeting criteria
        """
        from datetime import date as datetime_date

        today = datetime_date.today()

        # Filter expirations meeting minimum days requirement
        valid_exps = [
            exp for exp in self.expirations
            if (exp - today).days >= min_days
        ]

        if not valid_exps:
            return None

        # Find closest to target
        return min(
            valid_exps,
            key=lambda exp: abs((exp - today).days - target_days)
        )
