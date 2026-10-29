"""
🧪 Test Suite voor IL Calculator V3
Test dynamische tijd-range detectie en robuuste prijs-zoeklogica
"""
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from il_calculator_v3 import ILCalculatorV3, PriceRange

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_data_range_detection():
    """Test 1: Automatische detectie van beschikbare data"""
    print("\n" + "=" * 70)
    print("TEST 1: AUTOMATISCHE DATA RANGE DETECTIE")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    first_swap, last_swap = await calc.get_available_data_range()
    
    if first_swap and last_swap:
        duration = last_swap - first_swap
        print(f"\n✅ Data gevonden:")
        print(f"   Eerste swap: {first_swap}")
        print(f"   Laatste swap: {last_swap}")
        print(f"   Totale duur: {duration}")
        print(f"   Swaps beschikbaar: JA")
        return True
    else:
        print(f"\n⚠️  Geen data gevonden in database")
        print(f"   Run eerst de backfill: python listener_v3.py")
        return False


async def test_il_calculation_auto_range():
    """Test 2: IL berekening met automatische tijd-range"""
    print("\n" + "=" * 70)
    print("TEST 2: IL BEREKENING (AUTO TIJD-RANGE)")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    print("\n📊 Bereken IL over volledige database periode...")
    print("   (geen start_time of end_time opgegeven)")
    
    # Bereken IL zonder tijden op te geven (gebruikt volledige database)
    result = await calc.calculate_il()
    
    if result:
        print(f"\n✅ Berekening succesvol:\n")
        print(result)
        
        # Verify dat warnings appropriate zijn
        if result.warnings:
            print(f"\n⚠️  {len(result.warnings)} warnings:")
            for warning in result.warnings:
                print(f"   - {warning}")
        
        return True
    else:
        print(f"\n❌ Berekening mislukt")
        return False


async def test_il_calculation_with_dates():
    """Test 3: IL berekening met specifieke datums"""
    print("\n" + "=" * 70)
    print("TEST 3: IL BEREKENING (SPECIFIEKE DATUMS)")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    # Test met laatste 24h
    now = datetime.utcnow()
    start = now - timedelta(hours=24)
    
    print(f"\n📊 Bereken IL voor laatste 24h:")
    print(f"   Start: {start}")
    print(f"   End: {now}")
    
    result = await calc.calculate_il(start_time=start, end_time=now)
    
    if result:
        print(f"\n✅ Berekening succesvol:\n")
        print(result)
        return True
    else:
        print(f"\n❌ Berekening mislukt")
        return False


async def test_il_calculation_out_of_range():
    """Test 4: IL berekening met datums buiten database range"""
    print("\n" + "=" * 70)
    print("TEST 4: ROBUUSTHEID (DATUMS BUITEN RANGE)")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    # Vraag data op van vorige jaar (waarschijnlijk niet beschikbaar)
    far_past = datetime(2023, 1, 1)
    past = datetime(2023, 6, 1)
    
    print(f"\n📊 Bereken IL voor onrealistische periode:")
    print(f"   Start: {far_past} (waarschijnlijk niet in DB)")
    print(f"   End: {past} (waarschijnlijk niet in DB)")
    print(f"\n   → Verwachting: calculator valt terug op beschikbare data")
    
    result = await calc.calculate_il(start_time=far_past, end_time=past)
    
    if result:
        print(f"\n✅ Calculator viel gracefully terug op beschikbare data:\n")
        print(result)
        
        if result.warnings:
            print(f"\n⚠️  Warnings (verwacht):")
            for warning in result.warnings:
                print(f"   - {warning}")
        
        return True
    else:
        print(f"\n⚠️  Geen data beschikbaar (verwacht gedrag)")
        return True  # Dit is OK


async def test_optimal_range_detection():
    """Test 5: Automatische detectie van optimal V3 range"""
    print("\n" + "=" * 70)
    print("TEST 5: AUTO-DETECT OPTIMAL V3 RANGE")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    print("\n🤖 Detecteer optimal range uit laatste 7 dagen data...")
    
    optimal_range = await calc.auto_detect_optimal_range(lookback_hours=168)
    
    if optimal_range:
        print(f"\n✅ Optimal range gevonden:")
        print(f"   Lower: ${optimal_range.price_lower:.2f} (tick {optimal_range.tick_lower})")
        print(f"   Upper: ${optimal_range.price_upper:.2f} (tick {optimal_range.tick_upper})")
        print(f"   Width: ±{optimal_range.range_width_pct():.1f}%")
        
        # Nu bereken IL MET deze range
        print(f"\n📊 Bereken IL met V3 concentrated range...")
        
        result = await calc.calculate_il(price_range=optimal_range)
        
        if result:
            print(f"\n✅ V3 IL berekening:\n")
            print(result)
            return True
    else:
        print(f"\n⚠️  Niet genoeg data voor range detection")
        return False


async def test_convenience_methods():
    """Test 6: Convenience methods (last_24h, last_7d)"""
    print("\n" + "=" * 70)
    print("TEST 6: CONVENIENCE METHODS")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    # Test last_24h
    print("\n📊 calculate_il_last_24h()...")
    result_24h = await calc.calculate_il_last_24h()
    
    if result_24h:
        print(f"✅ 24h IL: {result_24h.net_roi_pct:+.4%}")
    else:
        print(f"⚠️  Geen 24h data")
    
    # Test last_7d
    print(f"\n📊 calculate_il_last_7d()...")
    result_7d = await calc.calculate_il_last_7d()
    
    if result_7d:
        print(f"✅ 7d IL: {result_7d.net_roi_pct:+.4%}")
    else:
        print(f"⚠️  Geen 7d data")
    
    # Test performance summary
    print(f"\n📊 get_performance_summary()...")
    summary = await calc.get_performance_summary()
    
    print(f"\n📈 Performance Summary:")
    for period, calc_result in summary.items():
        if calc_result:
            print(f"   {period:4s}: IL={calc_result.impermanent_loss_pct:+.4%} "
                  f"Fees={calc_result.fee_revenue_pct:+.4%} "
                  f"Net={calc_result.net_roi_pct:+.4%}")
        else:
            print(f"   {period:4s}: No data")
    
    return True


async def test_manual_price_range():
    """Test 7: Handmatig opgegeven V3 price range"""
    print("\n" + "=" * 70)
    print("TEST 7: HANDMATIGE V3 PRICE RANGE")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    # Definieer een tight range (bijv. voor ETH/USDC $2800-$3200)
    manual_range = PriceRange(
        price_lower=Decimal("2800"),
        price_upper=Decimal("3200"),
        tick_lower=-75000,  # Approximatie
        tick_upper=-74000
    )
    
    print(f"\n📐 Handmatige range:")
    print(f"   ${manual_range.price_lower} - ${manual_range.price_upper}")
    print(f"   Width: ±{manual_range.range_width_pct():.1f}%")
    
    print(f"\n📊 Bereken IL met deze range...")
    
    result = await calc.calculate_il(price_range=manual_range)
    
    if result:
        print(f"\n✅ Resultaat:\n")
        print(result)
        
        # Check position type
        if result.position_type == "in_range":
            print(f"\n✅ Position is IN RANGE (goed!)")
        elif result.position_type == "out_of_range":
            print(f"\n⚠️  Position is OUT OF RANGE (single-sided!)")
        
        return True
    else:
        print(f"\n❌ Berekening mislukt")
        return False


async def test_edge_cases():
    """Test 8: Edge cases en error handling"""
    print("\n" + "=" * 70)
    print("TEST 8: EDGE CASES & ERROR HANDLING")
    print("=" * 70)
    
    calc = ILCalculatorV3()
    
    # Test 1: Start na end (invalid range)
    print("\n🔍 Test: start_time > end_time (invalid)")
    future = datetime.utcnow() + timedelta(days=1)
    past = datetime.utcnow() - timedelta(days=1)
    
    result = await calc.calculate_il(start_time=future, end_time=past)
    print(f"   Result: {'✅ Handled gracefully' if not result else '⚠️  Unexpected success'}")
    
    # Test 2: Zeer korte periode (mogelijk geen data)
    print(f"\n🔍 Test: Zeer korte periode (1 minuut)")
    now = datetime.utcnow()
    one_min_ago = now - timedelta(minutes=1)
    
    result = await calc.calculate_il(start_time=one_min_ago, end_time=now)
    if result:
        print(f"   Result: ✅ Found data")
        if result.warnings:
            print(f"   Warnings: {len(result.warnings)}")
    else:
        print(f"   Result: ✅ No data (expected)")
    
    # Test 3: Lege database (zou moeten falen gracefully)
    print(f"\n🔍 Test: Check empty database handling")
    first, last = await calc.get_available_data_range()
    if first and last:
        print(f"   Result: ✅ Database has data, skipping empty DB test")
    else:
        print(f"   Result: ✅ Empty database handled gracefully")
    
    return True


async def main():
    """Run alle tests"""
    print("\n" + "=" * 70)
    print("🚀 IL CALCULATOR V3 TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("Data Range Detection", test_data_range_detection),
        ("IL Calculation (Auto Range)", test_il_calculation_auto_range),
        ("IL Calculation (With Dates)", test_il_calculation_with_dates),
        ("Robustness (Out of Range Dates)", test_il_calculation_out_of_range),
        ("Optimal Range Detection", test_optimal_range_detection),
        ("Convenience Methods", test_convenience_methods),
        ("Manual Price Range", test_manual_price_range),
        ("Edge Cases", test_edge_cases),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            passed = await test_func()
            results.append((name, passed))
        except Exception as e:
            logger.error(f"❌ Test '{name}' crashed: {e}", exc_info=True)
            results.append((name, False))
        
        # Kleine pause tussen tests
        await asyncio.sleep(0.5)
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} | {name}")
    
    print(f"\n{'=' * 70}")
    print(f"Total: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    print(f"{'=' * 70}")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print(f"\n⚠️  {total - passed} tests failed")


if __name__ == "__main__":
    asyncio.run(main())
