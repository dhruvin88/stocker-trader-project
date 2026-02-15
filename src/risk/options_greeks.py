"""
Options Greeks calculator using Black-Scholes model.

This module provides Greek calculations (delta, gamma, theta, vega, rho)
for option pricing and risk management.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from py_vollib.black_scholes import black_scholes
from py_vollib.black_scholes.greeks import analytical


@dataclass
class OptionGreeks:
    """
    Greeks for an option contract.

    Attributes:
        delta: Price sensitivity to underlying movement (-1 to 1)
               Calls: 0 to 1, Puts: -1 to 0
        gamma: Rate of delta change (acceleration)
        theta: Time decay per day (usually negative)
        vega: Sensitivity to IV changes (per 1% IV move)
        rho: Interest rate sensitivity (usually small)
        iv: Implied volatility used for calculation
    """
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    iv: float


class GreeksCalculator:
    """Calculate option Greeks using Black-Scholes model."""

    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize calculator.

        Args:
            risk_free_rate: Annual risk-free rate (default 5%)
        """
        self.risk_free_rate = risk_free_rate

    def calculate_greeks(
        self,
        option_type: Literal['call', 'put'],
        spot_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None
    ) -> OptionGreeks:
        """
        Calculate all Greeks using Black-Scholes analytical formulas.

        Args:
            option_type: 'call' or 'put'
            spot_price: Current underlying price
            strike: Option strike price
            time_to_expiry: Time to expiration in years
            volatility: Implied volatility (e.g., 0.25 for 25%)
            risk_free_rate: Override default risk-free rate

        Returns:
            OptionGreeks with all calculated values

        Example:
            >>> calc = GreeksCalculator()
            >>> greeks = calc.calculate_greeks('call', 100, 105, 0.25, 0.30)
            >>> print(f"Delta: {greeks.delta:.3f}")
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate

        # Ensure minimum time to expiry to avoid division by zero
        tte = max(time_to_expiry, 0.001)

        # Ensure positive volatility
        vol = max(volatility, 0.01)

        # Map option type to py_vollib format
        flag = 'c' if option_type == 'call' else 'p'

        # Calculate Greeks using analytical formulas
        delta = analytical.delta(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        gamma = analytical.gamma(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        theta = analytical.theta(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        vega = analytical.vega(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        rho = analytical.rho(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        return OptionGreeks(
            delta=delta,
            gamma=gamma,
            theta=theta / 365.0,  # Convert to per-day theta
            vega=vega / 100.0,    # Convert to per 1% IV move
            rho=rho / 100.0,      # Convert to per 1% rate move
            iv=volatility
        )

    def calculate_option_price(
        self,
        option_type: Literal['call', 'put'],
        spot_price: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = None
    ) -> float:
        """
        Calculate theoretical option price using Black-Scholes.

        Args:
            option_type: 'call' or 'put'
            spot_price: Current underlying price
            strike: Option strike price
            time_to_expiry: Time to expiration in years
            volatility: Implied volatility
            risk_free_rate: Override default risk-free rate

        Returns:
            Theoretical option price
        """
        if risk_free_rate is None:
            risk_free_rate = self.risk_free_rate

        # Ensure minimum time to expiry
        tte = max(time_to_expiry, 0.001)

        # Ensure positive volatility
        vol = max(volatility, 0.01)

        flag = 'c' if option_type == 'call' else 'p'

        price = black_scholes(
            flag, spot_price, strike, tte, risk_free_rate, vol
        )

        return price

    @staticmethod
    def time_to_expiry_years(expiration: date, current: date = None) -> float:
        """
        Calculate time to expiration in years.

        Args:
            expiration: Expiration date
            current: Current date (defaults to today)

        Returns:
            Time to expiration in years (minimum 0.001)
        """
        if current is None:
            from datetime import date as datetime_date
            current = datetime_date.today()

        days = (expiration - current).days
        years = max(days / 365.0, 0.001)  # Minimum to avoid zero

        return years
