"""
Pool info utilities - fee calculations en metadata
Business logica voor DeFi pool fee berekeningen
"""
import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# === BEKENDE FEE TIERS ===

# Basis points naar percentage mapping
# 1 basis point (bps) = 0.01% = 0.0001 als multiplier

UNISWAP_V3_FEES = {
    100: 0.01,    # 0.01%
    500: 0.05,    # 0.05%
    3000: 0.3,    # 0.3%
    10000: 1.0,   # 1%
}

AERODROME_FEES = {
    100: 0.01,    # 0.01%
    500: 0.05,    # 0.05%
    2000: 0.2,    # 0.2% (Aerodrome custom tier)
    3000: 0.3,    # 0.3%
}


def calculate_fee_amount(
    volume: Decimal,
    fee_tier: int,
    protocol: str = "uniswap_v3"
) -> Decimal:
    """
    Bereken fee revenue uit trade volume
    
    Formule: fee = volume × (fee_tier / 10000)
    
    Args:
        volume: Trade volume in token units (bijv. wei voor ETH)
        fee_tier: Fee tier in basis points (bijv. 3000 = 0.3%)
        protocol: DEX protocol ("uniswap_v3" of "aerodrome")
    
    Returns:
        Fee amount in dezelfde units als volume
        
    Examples:
        >>> calculate_fee_amount(Decimal("1000"), 3000)
        Decimal('3')  # 0.3% van 1000 = 3
        
        >>> calculate_fee_amount(Decimal("1000000000000000000"), 500)  # 1 ETH
        Decimal('5000000000000000')  # 0.05% = 0.005 ETH
        
    Note:
        Basis points conversie:
        - 1 bps = 1/10,000 = 0.0001
        - 3000 bps = 3000/10,000 = 0.3% = 0.003 als multiplier
        
        We gebruiken Decimal voor precisie bij grote getallen (wei/gwei).
    """
    # Converteer fee tier naar multiplier
    # 3000 bps → 3000/10000 = 0.3% = 0.003
    fee_multiplier = Decimal(str(fee_tier)) / Decimal("1000000")
    
    return volume * fee_multiplier


def get_fee_percentage(fee_tier: int, protocol: str = "uniswap_v3") -> float:
    """
    Vertaal fee tier naar human-readable percentage
    
    Args:
        fee_tier: Fee tier in basis points
        protocol: DEX protocol naam ("uniswap_v3" of "aerodrome")
    
    Returns:
        Fee percentage als float (bijv. 0.3 voor 0.3%)
        
    Examples:
        >>> get_fee_percentage(3000)
        0.3  # 0.3%
        
        >>> get_fee_percentage(2000, "aerodrome")
        0.2  # 0.2% (Aerodrome custom)
        
        >>> get_fee_percentage(12345)  # Unknown tier
        1.2345  # Berekend als 12345/10000
    """
    # Probeer eerst de lookup table
    fee_map = AERODROME_FEES if protocol == "aerodrome" else UNISWAP_V3_FEES
    
    if fee_tier in fee_map:
        return fee_map[fee_tier]
    
    # Fallback: bereken handmatig met dezelfde formule
    logger.warning(
        f"Unknown fee tier {fee_tier} for {protocol}, "
        f"calculating as {fee_tier}/10000"
    )
    return fee_tier / 10000


def format_fee_percentage(fee_tier: int, protocol: str = "uniswap_v3") -> str:
    """
    Format fee tier als leesbare string
    
    Args:
        fee_tier: Fee tier in basis points
        protocol: DEX protocol naam
    
    Returns:
        Formatted string (bijv. "0.3%" of "0.05%")
        
    Example:
        >>> format_fee_percentage(3000)
        "0.3%"
    """
    percentage = get_fee_percentage(fee_tier, protocol)
    
    # Format met juiste aantal decimalen
    if percentage >= 1.0:
        return f"{percentage:.1f}%"
    elif percentage >= 0.1:
        return f"{percentage:.1f}%"
    else:
        return f"{percentage:.2f}%"


# === TODO: PRODUCTIE FEATURES ===

# async def get_pool_fee_tier(
#     pool_address: str,
#     web3_provider
# ) -> int:
#     """
#     Haal de actuele fee tier op van een pool contract
#     
#     Args:
#         pool_address: Pool contract address
#         web3_provider: Web3 provider instance
#     
#     Returns:
#         Fee tier in basis points
#         
#     Example:
#         provider = Web3(Web3.HTTPProvider(...))
#         fee_tier = await get_pool_fee_tier("0x...", provider)
#         # → 3000 (0.3%)
#     """
#     # Implement met web3.py:
#     # pool_contract = web3.eth.contract(address=pool_address, abi=POOL_ABI)
#     # return pool_contract.functions.fee().call()
#     pass
