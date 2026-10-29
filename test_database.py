"""
Test database setup
"""
import asyncio
import logging
from datetime import datetime
from decimal import Decimal
import secrets

from database import init_database
from models import Swap
from config import DATABASE_URL

logging.basicConfig(level=logging.INFO)


async def main():
    # Initialize database
    db = await init_database(DATABASE_URL, echo=True)
    
    # Genereer unieke waarden voor elke test-run
    unique_tx_hash = "0x" + secrets.token_hex(32)  # 64 hex chars (32 bytes)
    unique_log_index = secrets.randbelow(1000000)  # Willekeurige log_index
    
    # Test: insert een dummy swap
    async with db.session() as session:
        swap = Swap(
            # Transaction identificatie (uniek)
            tx_hash=unique_tx_hash,
            block_number=123456 + secrets.randbelow(10000),  # Variërend block number
            log_index=unique_log_index,
            timestamp=datetime.utcnow(),
            
            # Addresses
            sender="0x" + "a" * 40,
            recipient="0x" + "b" * 40,
            
            # Swap amounts
            amount0=Decimal("1000000000000000000"),  # 1 ETH
            amount1=Decimal("-2000000000"),  # -2000 USDC (negatief = uitgaand)
            
            # Price data
            sqrt_price_x96=Decimal("79228162514264337593543950336"),  # ~1 ETH = 2000 USDC
            price=Decimal("2000.50"),
            tick=85176,  # Tick voor ~2000 prijs
            liquidity=Decimal("1000000000000000000"),
            
            # USD waarden (optioneel maar aanbevolen)
            amount0_usd=Decimal("2000.50"),  # 1 ETH * 2000.50 USD
            amount1_usd=Decimal("2000.00"),  # 2000 USDC
            volume_usd=Decimal("4000.50"),   # Totale swap volume
        )
        
        session.add(swap)
        await session.commit()
        print(f"✅ Inserted swap: {swap}")
        print(f"   TX Hash: {swap.tx_hash}")
        print(f"   Log Index: {swap.log_index}")
    
    # Test: query
    async with db.session() as session:
        from sqlalchemy import select
        result = await session.execute(select(Swap).limit(5))
        swaps = result.scalars().all()
        print(f"\n📊 Found {len(swaps)} swaps:")
        for s in swaps:
            print(f"  Block: {s.block_number}, "
                  f"Price: ${s.price}, "
                  f"Volume: ${s.volume_usd if s.volume_usd else 'N/A'}")
    
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
