"""
Uniswap V3 price en tick wiskunde
Gebaseerd op de officiële Uniswap V3 whitepaper formules

BELANGRIJKE NOTITIES:
- sqrtPriceX96 encodeert de prijs als: sqrt(token1/token0) * 2^96
- De token volgorde (token0 vs token1) bepaalt of je de prijs of 1/prijs krijgt
- Voor ETH/USDC pools: check of WETH token0 of token1 is!
"""
import math
from config import Q96, TOKEN0_DECIMALS, TOKEN1_DECIMALS


def sqrt_price_x96_to_price(sqrt_price_x96: int, token0_decimals: int = TOKEN0_DECIMALS, token1_decimals: int = TOKEN1_DECIMALS, invert: bool = False) -> float:
    """
    Converteer sqrtPriceX96 naar een leesbare prijs.
    
    Uniswap V3 formule:
    sqrtPriceX96 = sqrt(price) * 2^96
    waarbij price = reserve1 / reserve0 (in raw token units)
    
    Args:
        sqrt_price_x96: De sqrtPriceX96 waarde uit het event
        token0_decimals: Aantal decimalen van token0
        token1_decimals: Aantal decimalen van token1
        invert: Als True, retourneer token0/token1 ipv token1/token0
    
    Returns:
        float: De prijs
        
    Voorbeeld ETH/USDC waar WETH=token0, USDC=token1:
        sqrtPriceX96 geeft USDC/ETH (bijv. 2500)
    
    Voorbeeld ETH/USDC waar USDC=token0, WETH=token1:
        sqrtPriceX96 geeft ETH/USDC (bijv. 0.0004)
        → gebruik invert=True om 2500 te krijgen
    """
    # Stap 1: Converteer sqrtPriceX96 naar echte prijs ratio
    # price = (sqrtPriceX96 / 2^96)^2
    sqrt_price = sqrt_price_x96 / Q96
    price = sqrt_price ** 2
    
    # Stap 2: Corrigeer voor decimalen
    # price is nu: (amount_token1_raw / amount_token0_raw)
    # We willen: (amount_token1_human / amount_token0_human)
    # = (amount_token1_raw / 10^decimals1) / (amount_token0_raw / 10^decimals0)
    # = price * (10^decimals0 / 10^decimals1)
    decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
    adjusted_price = price * decimal_adjustment
    
    # Stap 3: Inverteer als nodig
    if invert:
        adjusted_price = 1 / adjusted_price if adjusted_price != 0 else 0
    
    return adjusted_price


def tick_to_price(tick: int, token0_decimals: int = TOKEN0_DECIMALS, token1_decimals: int = TOKEN1_DECIMALS, invert: bool = False) -> float:
    """
    Converteer een tick naar een prijs.
    
    Formule: price = 1.0001^tick
    
    Args:
        tick: De tick waarde uit het event
        token0_decimals: Aantal decimalen van token0
        token1_decimals: Aantal decimalen van token1
        invert: Als True, retourneer token0/token1 ipv token1/token0
    
    Returns:
        float: De prijs corresponderende met deze tick
    """
    price = 1.0001 ** tick
    decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
    adjusted_price = price * decimal_adjustment
    
    if invert:
        adjusted_price = 1 / adjusted_price if adjusted_price != 0 else 0
    
    return adjusted_price


def price_to_tick(price: float, token0_decimals: int = TOKEN0_DECIMALS, token1_decimals: int = TOKEN1_DECIMALS, invert: bool = False) -> int:
    """
    Converteer een prijs naar de dichtstbijzijnde tick.
    Handig voor range calculaties.
    
    Args:
        price: De prijs (token1 per token0 tenzij invert=True)
        token0_decimals: Aantal decimalen van token0
        token1_decimals: Aantal decimalen van token1
        invert: Als True, interpreteer price als token0/token1
    
    Returns:
        int: De tick waarde
    """
    if invert and price != 0:
        price = 1 / price
    
    decimal_adjustment = 10 ** (token0_decimals - token1_decimals)
    adjusted_price = price / decimal_adjustment
    
    if adjusted_price <= 0:
        raise ValueError(f"Price moet positief zijn, got {adjusted_price}")
    
    tick = math.log(adjusted_price) / math.log(1.0001)
    return int(round(tick))


def get_pool_price_from_sqrt(sqrt_price_x96: int, token0_symbol: str, token1_symbol: str, token0_decimals: int = 18, token1_decimals: int = 6) -> dict:
    """
    Helper functie die de prijs in beide richtingen berekent.
    Handig als je niet zeker weet welke token0/token1 is.
    
    Returns:
        dict met beide price interpretaties
    """
    price_0_per_1 = sqrt_price_x96_to_price(sqrt_price_x96, token0_decimals, token1_decimals, invert=False)
    price_1_per_0 = sqrt_price_x96_to_price(sqrt_price_x96, token0_decimals, token1_decimals, invert=True)
    
    return {
        f"{token1_symbol}_per_{token0_symbol}": price_0_per_1,
        f"{token0_symbol}_per_{token1_symbol}": price_1_per_0,
        "sqrt_price_x96": sqrt_price_x96
    }


def calculate_liquidity_at_price(liquidity: int, sqrt_price_x96: int, tick_lower: int, tick_upper: int) -> dict:
    """
    Bereken de verdeling van token0 en token1 binnen een LP positie op een gegeven prijs.
    Dit is de basis voor IL berekening.
    
    Args:
        liquidity: De liquidity waarde uit het event
        sqrt_price_x96: Huidige sqrtPriceX96
        tick_lower: Ondergrens van de LP range
        tick_upper: Bovengrens van de LP range
    
    Returns:
        dict: {"amount0": float, "amount1": float, "in_range": bool}
    """
    current_tick = price_to_tick(sqrt_price_x96_to_price(sqrt_price_x96))
    
    in_range = tick_lower <= current_tick <= tick_upper
    
    # Dit is een simplificatie - voor productie heb je de exacte formules nodig
    # uit de Uniswap V3 SDK of whitepaper sectie 6.29
    return {
        "liquidity": liquidity,
        "current_tick": current_tick,
        "in_range": in_range,
        "note": "Voor volledige IL calc: implementeer getAmount0/getAmount1 formules"
    }


if __name__ == "__main__":
    print("🧮 Uniswap V3 Price Math Test")
    print("=" * 70)
    
    # Test met ECHTE data: laten we beide scenario's testen
    # omdat we niet zeker weten welke token0/token1 is
    
    print("\n📊 Test: Interpreteer sqrtPriceX96 in beide richtingen")
    print("(Nuttig als je de token volgorde niet kent)")
    
    # Voorbeeld sqrtPriceX96 - we weten niet of dit WETH/USDC of USDC/WETH is
    test_sqrt = 1984220389013850534116927646361
    
    result = get_pool_price_from_sqrt(
        test_sqrt,
        token0_symbol="TOKEN0",
        token1_symbol="TOKEN1",
        token0_decimals=18,
        token1_decimals=6
    )
    
    print(f"\nsqrtPriceX96: {test_sqrt}")
    print(f"  → TOKEN1 per TOKEN0: {result['TOKEN1_per_TOKEN0']:.6f}")
    print(f"  → TOKEN0 per TOKEN1: {result['TOKEN0_per_TOKEN1']:.10f}")
    
    print("\n💡 Interpretatie:")
    print(f"  Als TOKEN0=WETH en TOKEN1=USDC:")
    print(f"    → ETH prijs = ${result['TOKEN1_per_TOKEN0']:.2f}")
    print(f"  Als TOKEN0=USDC en TOKEN1=WETH:")
    print(f"    → ETH prijs = ${result['TOKEN0_per_TOKEN1']:.2f}")
    
    print("\n" + "=" * 70)
    print("✅ Test compleet!")
    print("\n💡 TIP: Check de pool contract op Basescan om te zien")
    print("   welke token0 en token1 zijn, dan gebruik je de juiste prijs!")
