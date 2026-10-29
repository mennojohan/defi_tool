"""
Utility modules voor DeFi Pool Tracker
"""
from .pool_info import (
    AERODROME_FEES,
    UNISWAP_V3_FEES,
    calculate_fee_amount,
    format_fee_percentage,
    get_fee_percentage,
)

# Maak functies beschikbaar via: from utils import calculate_fee_amount
__all__ = [
    "calculate_fee_amount",
    "get_fee_percentage",
    "format_fee_percentage",
    "UNISWAP_V3_FEES",
    "AERODROME_FEES",
]
