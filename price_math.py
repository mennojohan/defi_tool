"""
Uniswap V3 Price Mathematics
Convert between sqrtPriceX96, tick, en human-readable price
"""
from decimal import Decimal
import math


def sqrt_price_x96_to_price(sqrt_price_x96: int) -> Decimal:
    """
    Convert Uniswap V3 sqrtPriceX96 naar human-readable price
    
    Formula:
    price = (sqrtPriceX96 / 2^96)^2
    
    Args:
        sqrt_price_x96: Square root of price in Q96 format
    
    Returns:
        Price als Decimal (bijv. 2345.67 voor ETH/USDC)
    """
    # Convert naar float voor berekening
    sqrt_price = float(sqrt_price_x96) / (2 ** 96)
    price = sqrt_price ** 2
    
    return Decimal(str(price))


def tick_to_price(tick: int) -> Decimal:
    """
    Convert tick naar price
    
    Formula:
    price = 1.0001^tick
    
    Args:
        tick: Tick number (int24)
    
    Returns:
        Price als Decimal
    """
    price = 1.0001 ** tick
    return Decimal(str(price))


def price_to_tick(price: float) -> int:
    """
    Convert price naar nearest tick
    
    Formula:
    tick = floor(log_1.0001(price))
    
    Args:
        price: Price als float
    
    Returns:
        Tick number (int)
    """
    if price <= 0:
        return -887272  # MIN_TICK
    
    tick = int(math.floor(math.log(price) / math.log(1.0001)))
    
    # Clamp naar valid range
    MIN_TICK = -887272
    MAX_TICK = 887272
    
    return max(MIN_TICK, min(MAX_TICK, tick))


def price_to_sqrt_price_x96(price: float) -> int:
    """
    Convert price naar sqrtPriceX96
    
    Args:
        price: Price als float
    
    Returns:
        sqrtPriceX96 als int
    """
    sqrt_price = math.sqrt(price)
    sqrt_price_x96 = int(sqrt_price * (2 ** 96))
    
    return sqrt_price_x96


def calculate_liquidity(
    amount0: Decimal,
    amount1: Decimal,
    price_lower: Decimal,
    price_upper: Decimal,
    current_price: Decimal
) -> Decimal:
    """
    Bereken liquidity voor een V3 positie
    
    Simplified formula voor estimation
    
    Args:
        amount0: Amount of token0
        amount1: Amount of token1
        price_lower: Lower price bound
        price_upper: Upper price bound
        current_price: Current price
    
    Returns:
        Liquidity als Decimal
    """
    if current_price <= price_lower:
        # Only token0
        sqrt_p_lower = Decimal(str(math.sqrt(float(price_lower))))
        sqrt_p_upper = Decimal(str(math.sqrt(float(price_upper))))
        liquidity = amount0 / (sqrt_p_upper - sqrt_p_lower)
    
    elif current_price >= price_upper:
        # Only token1
        sqrt_p_lower = Decimal(str(math.sqrt(float(price_lower))))
        sqrt_p_upper = Decimal(str(math.sqrt(float(price_upper))))
        liquidity = amount1 * (sqrt_p_upper - sqrt_p_lower)
    
    else:
        # Mixed position
        sqrt_p = Decimal(str(math.sqrt(float(current_price))))
        sqrt_p_lower = Decimal(str(math.sqrt(float(price_lower))))
        sqrt_p_upper = Decimal(str(math.sqrt(float(price_upper))))
        
        # Use token1 side for calculation
        liquidity = amount1 * (sqrt_p - sqrt_p_lower)
    
    return liquidity


def get_amounts_for_liquidity(
    liquidity: Decimal,
    price_lower: Decimal,
    price_upper: Decimal,
    current_price: Decimal
) -> tuple[Decimal, Decimal]:
    """
    Bereken hoeveel token0 en token1 nodig zijn voor een liquidity amount
    
    Args:
        liquidity: Desired liquidity
        price_lower: Lower price bound
        price_upper: Upper price bound
        current_price: Current price
    
    Returns:
        (amount0, amount1) tuple
    """
    sqrt_p = Decimal(str(math.sqrt(float(current_price))))
    sqrt_p_lower = Decimal(str(math.sqrt(float(price_lower))))
    sqrt_p_upper = Decimal(str(math.sqrt(float(price_upper))))
    
    if current_price <= price_lower:
        # Only token0
        amount0 = liquidity * (sqrt_p_upper - sqrt_p_lower)
        amount1 = Decimal("0")
    
    elif current_price >= price_upper:
        # Only token1
        amount0 = Decimal("0")
        amount1 = liquidity / (sqrt_p_upper - sqrt_p_lower)
    
    else:
        # Mixed
        amount0 = liquidity * (sqrt_p_upper - sqrt_p) / (sqrt_p * sqrt_p_upper)
        amount1 = liquidity * (sqrt_p - sqrt_p_lower)
    
    return (amount0, amount1)


def calculate_price_impact_bps(
    amount_in: Decimal,
    amount_out: Decimal,
    price_before: Decimal,
    price_after: Decimal
) -> Decimal:
    """
    Bereken price impact in basis points
    
    Args:
        amount_in: Input amount
        amount_out: Output amount
        price_before: Price before swap
        price_after: Price after swap
    
    Returns:
        Price impact in basis points (1 bp = 0.01%)
    """
    if price_before == 0:
        return Decimal("0")
    
    price_change = abs(price_after - price_before) / price_before
    price_impact_bps = price_change * Decimal("10000")
    
    return price_impact_bps
