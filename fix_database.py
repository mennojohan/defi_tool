"""
Fix corrupted `volume_usd` values in the database.

This script recalculates `volume_usd` for all swaps using the correct scaling:
- amount0 = USDC (6 decimals)
- amount1 = WETH (18 decimals)
"""

import sqlite3
from decimal import Decimal


def fix_database(db_path: str):
    """Fix corrupted `volume_usd` values in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Fetch all swaps
    cursor.execute("SELECT id, amount0, amount1, price FROM swaps")
    swaps = cursor.fetchall()
    
    print(f"🔍 Found {len(swaps)} swaps to fix.")
    
    for swap in swaps:
        swap_id, amount0, amount1, price = swap
        
        # Recalculate volume_usd
        if amount0 and price:
            volume_usd = abs(Decimal(str(amount0)) / Decimal("1e6"))  # USDC
        elif amount1 and price:
            volume_usd = abs(Decimal(str(amount1)) / Decimal("1e18")) * Decimal(str(price))  # WETH
        else:
            volume_usd = Decimal("0")
        
        # Update the swap
        cursor.execute(
            "UPDATE swaps SET volume_usd = ? WHERE id = ?",
            (str(volume_usd), swap_id)
        )
        print(f"✅ Fixed swap {swap_id}: volume_usd = {volume_usd}")
    
    # Commit changes
    conn.commit()
    conn.close()
    print("🎉 Database fixed successfully!")


if __name__ == "__main__":
    fix_database("./defi_tracker_v3.db")