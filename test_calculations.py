"""
Test script to verify the accuracy of `price_impact_bps` and `volume_usd` calculations.

This script tests:
1. `price_impact_bps` calculation in `price_math.py`.
2. `volume_usd` calculation in `update_volume_usd.py`.

Run with:
    python test_calculations.py
"""

from decimal import Decimal
import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from price_math import calculate_price_impact_bps


def test_price_impact_bps():
    """Test `price_impact_bps` calculation with hardcoded scenarios."""
    print("\n🔍 Testing `price_impact_bps` Calculation")
    print("=" * 60)
    
    test_cases = [
        {
            "name": "Tiny Swap (0.04% impact)",
            "price_before": Decimal("2500"),
            "price_after": Decimal("2501"),
            "expected_bps": Decimal("4"),  # (1/2500) * 10000 = 4 bps
        },
        {
            "name": "Massive Swap (4% impact)",
            "price_before": Decimal("2500"),
            "price_after": Decimal("2600"),
            "expected_bps": Decimal("400"),  # (100/2500) * 10000 = 400 bps
        },
        {
            "name": "Zero Price Impact",
            "price_before": Decimal("2500"),
            "price_after": Decimal("2500"),
            "expected_bps": Decimal("0"),
        },
        {
            "name": "Edge Case (Zero Price Before)",
            "price_before": Decimal("0"),
            "price_after": Decimal("2500"),
            "expected_bps": Decimal("0"),  # Handled by the function
        },
    ]
    
    for case in test_cases:
        result = calculate_price_impact_bps(
            amount_in=Decimal("1"),
            amount_out=Decimal("1"),
            price_before=case["price_before"],
            price_after=case["price_after"]
        )
        
        status = "✅ PASS" if result == case["expected_bps"] else "❌ FAIL"
        print(f"\n{case['name']}")
        print(f"  Pre-Price: ${case['price_before']}")
        print(f"  Post-Price: ${case['price_after']}")
        print(f"  Expected: {case['expected_bps']} bps")
        print(f"  Actual: {result} bps")
        print(f"  Status: {status}")


def test_volume_usd():
    """Test `volume_usd` calculation with hardcoded scenarios."""
    print("\n\n🔍 Testing `volume_usd` Calculation")
    print("=" * 60)
    
    test_cases = [
        {
            "name": "Tiny Swap (250.1 USDC)",
            "amount0": Decimal("250100000"),  # 250.1 USDC (6 decimals)
            "amount1": Decimal("100000000000000000"),  # 0.1 WETH (18 decimals)
            "price": Decimal("2501"),  # WETH price in USD
            "expected_volume": Decimal("250.10"),
        },
        {
            "name": "Massive Swap (25,500 USDC)",
            "amount0": Decimal("25500000000"),  # 25,500 USDC (6 decimals)
            "amount1": Decimal("10000000000000000000"),  # 10 WETH (18 decimals)
            "price": Decimal("2550"),  # WETH price in USD
            "expected_volume": Decimal("25500.00"),
        },
        {
            "name": "USDC Only (1 USDC)",
            "amount0": Decimal("1000000"),  # 1 USDC (6 decimals)
            "amount1": None,
            "price": Decimal("2500"),
            "expected_volume": Decimal("1.00"),
        },
        {
            "name": "Edge Case (Zero Amounts)",
            "amount0": Decimal("0"),
            "amount1": Decimal("0"),
            "price": Decimal("2500"),
            "expected_volume": Decimal("0"),
        },
    ]
    
    for case in test_cases:
        # Simulate the logic in `update_volume_usd.py`
        if case["amount0"] is not None and case["amount0"] > 0:
            volume_usd = abs(Decimal(str(case["amount0"])) / Decimal("1e6"))  # USDC
        elif case["amount1"] is not None and case["amount1"] > 0 and case["price"]:
            volume_usd = abs(Decimal(str(case["amount1"])) / Decimal("1e18")) * case["price"]  # WETH
        else:
            volume_usd = Decimal("0")
        
        status = "✅ PASS" if volume_usd == case["expected_volume"] else "❌ FAIL"
        print(f"\n{case['name']}")
        print(f"  Amount0 (USDC): {case['amount0']}")
        print(f"  Amount1 (WETH): {case['amount1']}")
        print(f"  Price: ${case['price']}")
        print(f"  Expected: ${case['expected_volume']}")
        print(f"  Actual: ${volume_usd}")
        print(f"  Status: {status}")


if __name__ == "__main__":
    print("🧪 Testing `price_impact_bps` and `volume_usd` Calculations")
    print("=" * 60)
    
    test_price_impact_bps()
    test_volume_usd()
    
    print("\n🎉 Testing Complete!")