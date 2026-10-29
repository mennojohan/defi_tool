"""
Test script om de sqrtPriceX96 conversies te valideren.
Run dit om te checken of de wiskunde klopt voordat je live gaat.
"""
from utils.price_math import (
    sqrt_price_x96_to_price, 
    tick_to_price, 
    price_to_tick,
    get_pool_price_from_sqrt
)

print("🧮 Testing Price Math Conversies")
print("=" * 60)

# Test case 1: Simuleer verschillende ETH prijzen en bereken de sqrtPriceX96
print("\n📊 Test 1: Prijs ↔ sqrtPriceX96 conversie")
print("Scenario: WETH (token0, 18 dec) / USDC (token1, 6 dec)\n")

Q96 = 2 ** 96

for eth_price_usd in [1500, 2000, 2500, 3000, 3500]:
    # Bereken wat de sqrtPriceX96 ZOU MOETEN zijn
    # price in raw units = (USDC amount * 1e6) / (WETH amount * 1e18)
    # Voor 1 WETH = X USDC: price_raw = (X * 1e6) / (1 * 1e18) = X / 1e12
    price_raw = eth_price_usd / 1e12
    sqrt_price = price_raw ** 0.5
    sqrt_price_x96_expected = int(sqrt_price * Q96)
    
    # Nu converteer terug
    price_back = sqrt_price_x96_to_price(
        sqrt_price_x96_expected, 
        token0_decimals=18, 
        token1_decimals=6
    )
    
    tick = price_to_tick(price_back, token0_decimals=18, token1_decimals=6)
    price_from_tick = tick_to_price(tick, token0_decimals=18, token1_decimals=6)
    
    print(f"ETH @ ${eth_price_usd}")
    print(f"  sqrtPriceX96: {sqrt_price_x96_expected}")
    print(f"  → Prijs terug: ${price_back:.2f}")
    print(f"  → Tick: {tick}")
    print(f"  → Tick→Prijs: ${price_from_tick:.2f}")
    error = abs(price_back - eth_price_usd)
    print(f"  ✅ Error: ${error:.6f}" if error < 1 else f"  ❌ Error: ${error:.2f}")
    print()

# Test case 2: Wat als de token volgorde OMGEKEERD is?
print("\n📊 Test 2: Omgekeerde token volgorde")
print("Scenario: USDC (token0, 6 dec) / WETH (token1, 18 dec)\n")

for eth_price_usd in [2000, 2500, 3000]:
    # Nu is price_raw = (WETH amount * 1e18) / (USDC amount * 1e6)
    # Voor 1 WETH = X USDC: price_raw = (1 * 1e18) / (X * 1e6) = 1e12 / X
    price_raw = 1e12 / eth_price_usd
    sqrt_price = price_raw ** 0.5
    sqrt_price_x96_expected = int(sqrt_price * Q96)
    
    # Converteer met invert=True om de ETH prijs te krijgen
    price_back = sqrt_price_x96_to_price(
        sqrt_price_x96_expected,
        token0_decimals=6,  # USDC
        token1_decimals=18,  # WETH
        invert=True  # We willen USDC per WETH (niet WETH per USDC)
    )
    
    print(f"ETH @ ${eth_price_usd}")
    print(f"  sqrtPriceX96: {sqrt_price_x96_expected}")
    print(f"  → Prijs (met invert): ${price_back:.2f}")
    error = abs(price_back - eth_price_usd)
    print(f"  ✅ Error: ${error:.6f}" if error < 1 else f"  ❌ Error: ${error:.2f}")
    print()

# Test case 3: Helper functie voor beide interpretaties
print("\n📊 Test 3: Auto-detect met get_pool_price_from_sqrt()")
print("Als je de token volgorde niet weet, zie je beide opties:\n")

# Simuleer ETH @ $2500
eth_price = 2500
price_raw = eth_price / 1e12  # WETH=token0 scenario
sqrt_price_x96_test = int((price_raw ** 0.5) * Q96)

result = get_pool_price_from_sqrt(
    sqrt_price_x96_test,
    token0_symbol="WETH",
    token1_symbol="USDC",
    token0_decimals=18,
    token1_decimals=6
)

print(f"sqrtPriceX96: {sqrt_price_x96_test}")
print(f"  → USDC per WETH: ${result['USDC_per_WETH']:.2f}")
print(f"  → WETH per USDC: {result['WETH_per_USDC']:.10f}")
print(f"\n  ✅ De eerste waarde klopt voor ETH @ ${eth_price}!")

# Test case 4: Tick spacing test (voor LP ranges)
print("\n📊 Test 4: Tick Spacing (voor LP range calculaties)")
print("Uniswap V3 gebruikt tick spacing (10, 60, of 200)\n")

base_price = 2500
base_tick = price_to_tick(base_price, token0_decimals=18, token1_decimals=6)
spacing = 60  # Common voor 0.3% fee tier

print(f"Base prijs: ${base_price} → Tick {base_tick}")
print(f"Tick spacing: {spacing}\n")

for i in range(-2, 3):
    tick = base_tick + (i * spacing)
    price = tick_to_price(tick, token0_decimals=18, token1_decimals=6)
    percentage = ((price - base_price) / base_price) * 100
    print(f"  Tick {tick:>6}: ${price:>8.2f} ({percentage:>+6.2f}%)")

print("\n" + "=" * 60)
print("✅ Price math test compleet!")
print("\n💡 BELANGRIJK:")
print("   1. Check op Basescan welke token0/token1 zijn in je pool")
print("   2. Als WETH=token0: gebruik gewone prijs")
print("   3. Als USDC=token0: gebruik invert=True parameter")
print("\n💡 Voorbeeld real pool check:")
print("   → Ga naar basescan.org/address/[POOL_ADDRESS]")
print("   → Read Contract → token0() en token1()")
print("   → Vergelijk adressen met bekende tokens")
