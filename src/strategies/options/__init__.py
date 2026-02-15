"""
Options trading strategies module.

This module contains options-specific trading strategies including:
- Covered Call: Sell calls against long stock positions
- Protective Put: Buy puts to protect long positions
- Vertical Spread: Bull/bear call/put spreads
- Unusual Activity: Trade based on unusual options volume/OI
"""

from src.strategies.options.covered_call import CoveredCallStrategy
from src.strategies.options.protective_put import ProtectivePutStrategy
from src.strategies.options.vertical_spread import VerticalSpreadStrategy
from src.strategies.options.unusual_activity import UnusualOptionsActivity

__all__ = [
    'CoveredCallStrategy',
    'ProtectivePutStrategy',
    'VerticalSpreadStrategy',
    'UnusualOptionsActivity',
]
