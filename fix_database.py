"""
Fix corrupted swap data in the database.

This script:
1. Recalculates `volume_usd` for all swaps using the correct scaling:
   - amount0 = USDC (6 decimals)
   - amount1 = WETH (18 decimals)
2. Fixes corrupted `amount0` and `amount1` values (e.g., swaps where the tokens were swapped).
"""

import sqlite3
from decimal import Decimal


def fix_database(db_path: str):
    """Fix corrupted swap data in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Fetch all swaps
    cursor.execute("SELECT id, amount0, amount1, price FROM swaps")
    swaps = cursor.fetchall()
    
    print(f"🔍 Found {len(swaps)} swaps to fix.")
    fixed_count = 0
    
    for swap in swaps:
        swap_id, amount0, amount1, price = swap
        
        # Check if the swap is corrupted (e.g., amount0 is too large for USDC)
        is_corrupted = False
        if abs(amount0) > 1_000_000_000:  # USDC should never exceed $1B in raw form
            is_corrupted = True
            # Swap amount0 and amount1 (fix the corruption)
            amount0, amount1 = amount1, amount0
            print(f"🔄 Swap {swap_id} was corrupted. Fixed token order.")
        
        # Recalculate volume_usd
        if amount0 and price:
            volume_usd = abs(Decimal(str(amount0)) / Decimal("1e6"))  # USDC
        elif amount1 and price:
            volume_usd = abs(Decimal(str(amount1)) / Decimal("1e18")) * Decimal(str(price))  # WETH
        else:
            volume_usd = Decimal("0")
        
        # Update the swap
        cursor.execute(
            "UPDATE swaps SET amount0 = ?, amount1 = ?, volume_usd = ? WHERE id = ?",
            (amount0, amount1, str(volume_usd), swap_id)
        )
        if is_corrupted:
            fixed_count += 1
            print(f"✅ Fixed swap {swap_id}: amount0={amount0}, amount1={amount1}, volume_usd={volume_usd}")
    
    # Commit changes
    conn.commit()
    conn.close()
    print(f"🎉 Database fixed successfully! Fixed {fixed_count} corrupted swaps.")


if __name__ == "__main__":
    fix_database("./defi_tracker_v3.db")