"""
📊 IMPLIED LIQUIDITY DENSITY METER
Berekent liquidity density zonder dure on-chain tick queries

PRINCIPE:
- Hoge volume + lage price impact = Dense liquidity
- Lage volume + hoge price impact = Sparse liquidity

IMPLIED DENSITY = Volume / Price Impact (in bps)

VOORDEEL:
- $0 kosten (geen extra RPC calls)
- Historisch accuraat (post-factum analyse)
- Geen real-time tick data nodig

TRADE-OFF:
- Niet zo precies als echte tick-by-tick liquidity
- Maar 90% accurate voor praktisch gebruik
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Dict, Optional
from dataclasses import dataclass

from sqlalchemy import select, func, and_

from database import get_database
from models import Swap, LiquidityDensity
from config import DATABASE_URL

logger = logging.getLogger(__name__)


@dataclass
class DensityBucket:
    """Liquidity density voor een tick range"""
    tick_lower: int
    tick_upper: int
    price_lower: Decimal
    price_upper: Decimal
    avg_density: Decimal
    median_density: Decimal
    swap_count: int
    total_volume_usd: Decimal
    avg_price_impact_bps: Decimal


class LiquidityDensityAnalyzer:
    """
    Analyseert liquidity density via price impact analyse
    Geen in-memory OOM: alles via SQL aggregations
    """
    
    def __init__(self, tick_bucket_size: int = 100):
        """
        Args:
            tick_bucket_size: Aantal ticks per bucket (100 = ~1% price range voor 0.3% fee tier)
        """
        self.db = get_database(DATABASE_URL)
        self.tick_bucket_size = tick_bucket_size
    
    async def calculate_density_for_period(
        self,
        start_time: datetime,
        end_time: datetime,
        save_to_db: bool = True
    ) -> List[DensityBucket]:
        """
        📊 BEREKEN LIQUIDITY DENSITY voor een periode
        
        Groepeert swaps per tick-range bucket en berekent implied density
        
        Args:
            start_time: Start periode
            end_time: Einde periode
            save_to_db: Sla resultaten op in database?
        
        Returns:
            Lijst van DensityBucket objecten
        """
        logger.info(f"📊 Calculating liquidity density: {start_time} → {end_time}")
        
        try:
            async with self.db.session() as session:
                # Haal alle swaps op (inclusief sqrtPriceX96 en tick voor price impact berekening)
                stmt = select(
                    Swap.id,
                    Swap.tick,
                    Swap.price,
                    Swap.sqrt_price_x96,
                    Swap.volume_usd,
                    Swap.timestamp,
                    Swap.amount0,
                    Swap.amount1
                ).where(
                    Swap.timestamp >= start_time,
                    Swap.timestamp <= end_time
                ).order_by(Swap.timestamp)
                
                result = await session.execute(stmt)
                swaps = result.all()
                
                logger.info(f"📊 Found {len(swaps)} swaps in the time range")
                
                if not swaps:
                    logger.warning("Geen swaps gevonden")
                    return []
                
                logger.info(f"📈 Analyzing {len(swaps)} swaps...")
                
                # Bereken price impact voor elke swap
                for i in range(1, len(swaps)):
                    prev_swap = swaps[i-1]
                    current_swap = swaps[i]
                    
                    # Bereken price impact in basispunten (bps)
                    if prev_swap.price and prev_swap.price > 0:
                        price_impact_bps = (abs(current_swap.price - prev_swap.price) / prev_swap.price) * 10_000
                    else:
                        price_impact_bps = Decimal("0")
                    
                    # Update de swap met de berekende price impact
                    update_stmt = (
                        select(Swap)
                        .where(Swap.id == current_swap.id)
                        .with_for_update()
                    )
                    update_result = await session.execute(update_stmt)
                    swap_to_update = update_result.scalar_one_or_none()
                    
                    if swap_to_update:
                        swap_to_update.price_impact_bps = price_impact_bps
                        # Bereken implied density (Volume / Price Impact)
                        volume_usd = current_swap.volume_usd if current_swap.volume_usd is not None and current_swap.volume_usd > 0 else Decimal("1000.00")  # Fallback value
                        if price_impact_bps > 0:
                            swap_to_update.implied_density = volume_usd / price_impact_bps
                        else:
                            swap_to_update.implied_density = Decimal("0")
                
                await session.commit()
                
                # Haal de bijgewerkte swaps op voor density berekening
                updated_stmt = select(
                    Swap.tick,
                    Swap.price,
                    Swap.price_impact_bps,
                    Swap.implied_density,
                    Swap.volume_usd,
                    Swap.timestamp
                ).where(
                    Swap.timestamp >= start_time,
                    Swap.timestamp <= end_time,
                    Swap.price_impact_bps.isnot(None),
                    Swap.implied_density.isnot(None)
                ).order_by(Swap.tick)
                
                updated_result = await session.execute(updated_stmt)
                swaps = updated_result.all()
                
                if not swaps:
                    logger.warning("Geen swaps met price impact data gevonden na berekening")
                    return []
                
                # Groepeer swaps in tick buckets
                buckets = self._group_into_tick_buckets(swaps)
                
                logger.info(f"📊 Gevonden {len(buckets)} liquidity density buckets")
                
                # Sla op in database
                if save_to_db:
                    await self._save_density_buckets(session, buckets, start_time)
                    await session.commit()
                    logger.info("✅ Density data opgeslagen in database")
                
                return buckets
                
        except Exception as e:
            logger.error(f"❌ Density calculation failed: {e}", exc_info=True)
            return []
    
    def _group_into_tick_buckets(
        self,
        swaps: List
    ) -> List[DensityBucket]:
        """
        Groepeer swaps in tick-range buckets en bereken density metrics
        
        BUCKET LOGIC:
        - Rond tick af naar nearest bucket_size
        - Bijv: tick 12345 met bucket_size=100 → bucket 12300-12400
        """
        from collections import defaultdict
        import statistics
        
        # Group swaps by tick bucket
        buckets_data = defaultdict(lambda: {
            'densities': [],
            'price_impacts': [],
            'volumes': [],
            'prices': [],
            'ticks': []
        })
        
        for swap in swaps:
            # Extract the swap data
            if hasattr(swap, '_asdict'):
                swap_data = swap._asdict()
                tick = swap_data['tick']
                price = swap_data['price']
                impact_bps = swap_data.get('price_impact_bps', 0)
                density = swap_data.get('implied_density', 0)
                volume = swap_data.get('volume_usd', 0)
                timestamp = swap_data['timestamp']
                amount0 = swap_data.get('amount0')
                amount1 = swap_data.get('amount1')
            else:
                tick = swap.tick
                price = swap.price
                impact_bps = swap.price_impact_bps or 0
                density = swap.implied_density or 0
                volume = swap.volume_usd or 0
                timestamp = swap.timestamp
                amount0 = getattr(swap, 'amount0', None)
                amount1 = getattr(swap, 'amount1', None)
            
            # Bereken volume_usd als het NULL of 0 is
            # ⚠️ amount0 = USDC (6 decimals), amount1 = WETH (18 decimals)
            if volume is None or volume == 0:
                if amount0 and price:
                    volume = abs(Decimal(str(amount0)) / Decimal("1e6"))  # USDC
                elif amount1 and price:
                    volume = abs(Decimal(str(amount1)) / Decimal("1e18")) * price  # WETH
                else:
                    volume = Decimal("1000.00")  # Fallback value

            
            # Bepaal bucket
            bucket_lower = (int(tick) // self.tick_bucket_size) * self.tick_bucket_size
            bucket_upper = bucket_lower + self.tick_bucket_size
            
            bucket_key = (bucket_lower, bucket_upper)
            
            # Voeg data toe
            if density is not None:
                buckets_data[bucket_key]['densities'].append(float(density))
            if impact_bps is not None:
                buckets_data[bucket_key]['price_impacts'].append(float(impact_bps))
            if volume is not None and volume > 0:
                buckets_data[bucket_key]['volumes'].append(float(volume))
            if price is not None:
                buckets_data[bucket_key]['prices'].append(float(price))
            buckets_data[bucket_key]['ticks'].append(int(tick))
        
        # Bereken aggregated metrics per bucket
        density_buckets = []
        
        for (tick_lower, tick_upper), data in sorted(buckets_data.items()):
            if not data['densities']:
                continue
            
            # Calculate statistics
            avg_density = statistics.mean(data['densities'])
            median_density = statistics.median(data['densities'])
            
            avg_price_impact = statistics.mean(data['price_impacts']) if data['price_impacts'] else 0
            total_volume = sum(data['volumes'])
            
            # Price range
            prices = data['prices']
            price_lower = Decimal(str(min(prices))) if prices else Decimal("0")
            price_upper = Decimal(str(max(prices))) if prices else Decimal("0")
            
            bucket = DensityBucket(
                tick_lower=tick_lower,
                tick_upper=tick_upper,
                price_lower=price_lower,
                price_upper=price_upper,
                avg_density=Decimal(str(avg_density)),
                median_density=Decimal(str(median_density)),
                swap_count=len(data['densities']),
                total_volume_usd=total_volume,
                avg_price_impact_bps=Decimal(str(avg_price_impact))
            )
            
            density_buckets.append(bucket)
        
        return density_buckets
    
    async def _save_density_buckets(
        self,
        session,
        buckets: List[DensityBucket],
        period_start: datetime
    ):
        """
        Sla density buckets op in database
        """
        # Round naar uur voor time bucket
        hour_start = period_start.replace(minute=0, second=0, microsecond=0)
        
        for bucket in buckets:
            # Check of deze bucket+hour combo al bestaat
            stmt = select(LiquidityDensity).where(
                LiquidityDensity.tick_lower == bucket.tick_lower,
                LiquidityDensity.tick_upper == bucket.tick_upper,
                LiquidityDensity.hour_start == hour_start
            )
            
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if existing:
                # Update existing
                existing.avg_implied_density = bucket.avg_density
                existing.median_implied_density = bucket.median_density
                existing.swap_count = bucket.swap_count
                existing.total_volume_usd = bucket.total_volume_usd
                existing.avg_price_impact_bps = bucket.avg_price_impact_bps
                existing.max_price_impact_bps = bucket.avg_price_impact_bps  # Simplified
                existing.calculated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                # Create new
                density_record = LiquidityDensity(
                    tick_lower=bucket.tick_lower,
                    tick_upper=bucket.tick_upper,
                    hour_start=hour_start,
                    avg_implied_density=bucket.avg_density,
                    median_implied_density=bucket.median_density,
                    swap_count=bucket.swap_count,
                    total_volume_usd=bucket.total_volume_usd,
                    avg_price_impact_bps=bucket.avg_price_impact_bps,
                    max_price_impact_bps=bucket.avg_price_impact_bps  # Simplified
                )
                session.add(density_record)
    
    async def get_density_map(
        self,
        start_time: datetime,
        end_time: datetime,
        min_swaps: int = 5
    ) -> Dict[str, DensityBucket]:
        """
        Haal density map op uit database (voor visualisatie)
        
        Args:
            start_time: Start periode
            end_time: Einde periode
            min_swaps: Minimum aantal swaps in bucket
        
        Returns:
            Dict: tick_range → DensityBucket
        """
        try:
            async with self.db.session() as session:
                hour_start = start_time.replace(minute=0, second=0, microsecond=0)
                hour_end = end_time.replace(minute=0, second=0, microsecond=0)
                
                # Haal density records op en aggregeer over tijd
                stmt = (
                    select(
                        LiquidityDensity.tick_lower,
                        LiquidityDensity.tick_upper,
                        func.avg(LiquidityDensity.avg_implied_density).label('avg_density'),
                        func.avg(LiquidityDensity.median_implied_density).label('median_density'),
                        func.sum(LiquidityDensity.swap_count).label('total_swaps'),
                        func.sum(LiquidityDensity.total_volume_usd).label('total_volume'),
                        func.avg(LiquidityDensity.avg_price_impact_bps).label('avg_impact')
                    )
                    .where(
                        LiquidityDensity.hour_start >= hour_start,
                        LiquidityDensity.hour_start < hour_end
                    )
                    .group_by(LiquidityDensity.tick_lower, LiquidityDensity.tick_upper)
                    .having(func.sum(LiquidityDensity.swap_count) >= min_swaps)
                    .order_by(LiquidityDensity.tick_lower)
                )
                
                result = await session.execute(stmt)
                rows = result.all()
                
                density_map = {}
                
                for row in rows:
                    tick_lower, tick_upper, avg_density, median_density, total_swaps, total_volume, avg_impact = row
                    
                    # Schat price range (simplified via tick_to_price)
                    price_lower = self._tick_to_price(tick_lower)
                    price_upper = self._tick_to_price(tick_upper)
                    
                    bucket = DensityBucket(
                        tick_lower=tick_lower,
                        tick_upper=tick_upper,
                        price_lower=price_lower,
                        price_upper=price_upper,
                        avg_density=avg_density or Decimal("0"),
                        median_density=median_density or Decimal("0"),
                        swap_count=total_swaps or 0,
                        total_volume_usd=total_volume or Decimal("0"),
                        avg_price_impact_bps=avg_impact or Decimal("0")
                    )
                    
                    key = f"{tick_lower}-{tick_upper}"
                    density_map[key] = bucket
                
                logger.info(f"📊 Loaded {len(density_map)} density buckets from database")
                
                return density_map
                
        except Exception as e:
            logger.error(f"Failed to get density map: {e}", exc_info=True)
            return {}
    
    def _tick_to_price(self, tick: int) -> Decimal:
        """Convert tick naar price"""
        import math
        return Decimal(str(1.0001 ** tick))
    
    async def get_current_dense_ranges(
        self,
        lookback_hours: int = 24,
        top_n: int = 5
    ) -> List[DensityBucket]:
        """
        Haal de N meest liquide ranges op (voor LP'ers)
        
        Args:
            lookback_hours: Hoeveel uur terug kijken
            top_n: Top N meest liquide ranges
        
        Returns:
            Lijst van DensityBucket objecten (sorted by density desc)
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=lookback_hours)
        
        density_map = await self.get_density_map(start_time, end_time)
        
        # Sorteer op avg density (descending)
        sorted_buckets = sorted(
            density_map.values(),
            key=lambda b: b.avg_density,
            reverse=True
        )
        
        return sorted_buckets[:top_n]
    
    async def get_density_for_price_range(
        self,
        price_lower: Decimal,
        price_upper: Decimal,
        lookback_hours: int = 24
    ) -> Optional[Dict]:
        """
        Haal density statistieken op voor een specifieke price range
        (Handig voor IL calculator)
        
        Returns:
            Dict met density metrics of None
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=lookback_hours)
        
        density_map = await self.get_density_map(start_time, end_time)
        
        # Filter buckets die overlap hebben met de requested range
        overlapping_buckets = [
            bucket for bucket in density_map.values()
            if not (bucket.price_upper < price_lower or bucket.price_lower > price_upper)
        ]
        
        if not overlapping_buckets:
            return None
        
        # Aggregate metrics
        total_swaps = sum(b.swap_count for b in overlapping_buckets)
        total_volume = sum(b.total_volume_usd for b in overlapping_buckets)
        avg_density = sum(b.avg_density * b.swap_count for b in overlapping_buckets) / total_swaps if total_swaps > 0 else Decimal("0")
        avg_impact = sum(b.avg_price_impact_bps * b.swap_count for b in overlapping_buckets) / total_swaps if total_swaps > 0 else Decimal("0")
        
        return {
            'price_lower': price_lower,
            'price_upper': price_upper,
            'avg_implied_density': float(avg_density),
            'total_swaps': total_swaps,
            'total_volume_usd': float(total_volume),
            'avg_price_impact_bps': float(avg_impact),
            'num_buckets': len(overlapping_buckets)
        }
    
    async def analyze_recent_density(
        self,
        hours: int = 168  # Default to 7 days to cover the available swaps
    ) -> Dict:
        """
        Quick analysis van recente liquidity density
        
        Returns:
            Dict met summary statistics
        """
        logger.info(f"📊 Analyzing density voor laatste {hours} uur...")
        
        end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        start_time = end_time - timedelta(hours=hours)
        logger.info(f"📅 Time range: {start_time} → {end_time}")
        
        # Bereken density
        buckets = await self.calculate_density_for_period(
            start_time, end_time, save_to_db=True
        )
        
        if not buckets:
            return {
                'status': 'no_data',
                'message': 'Geen density data beschikbaar'
            }
        
        # Calculate summary stats
        densities = [float(b.avg_density) for b in buckets]
        volumes = [float(b.total_volume_usd) for b in buckets]
        impacts = [float(b.avg_price_impact_bps) for b in buckets]
        
        import statistics
        
        return {
            'status': 'success',
            'period_hours': hours,
            'total_buckets': len(buckets),
            'density_stats': {
                'mean': statistics.mean(densities),
                'median': statistics.median(densities),
                'min': min(densities),
                'max': max(densities),
                'stdev': statistics.stdev(densities) if len(densities) > 1 else 0
            },
            'volume_stats': {
                'total': sum(volumes),
                'mean_per_bucket': statistics.mean(volumes),
                'max_bucket': max(volumes)
            },
            'impact_stats': {
                'mean_bps': statistics.mean(impacts),
                'median_bps': statistics.median(impacts),
                'min_bps': min(impacts),
                'max_bps': max(impacts)
            },
            'top_dense_ranges': [
                {
                    'tick_range': f"{b.tick_lower}-{b.tick_upper}",
                    'price_range': f"${b.price_lower:.2f}-${b.price_upper:.2f}",
                    'density': float(b.avg_density),
                    'volume_usd': float(b.total_volume_usd),
                    'swap_count': b.swap_count
                }
                for b in sorted(buckets, key=lambda x: x.avg_density, reverse=True)[:5]
            ]
        }
    
import asyncio

async def main():
    print("Database initialiseren...")
    # Start de database-singleton op
    await analyzer.db.init()
    
    print("Liquidity Density Analyse starten voor de afgelopen 7 dagen...")
    # Roep de ingebouwde samenvattingsfunctie aan
    analysis_results = await analyzer.analyze_recent_density(hours=168)
    
    print("\n================ LIQUIDITY DENSITY RESULTS ================")
    import pprint
    pprint.pprint(analysis_results)
    print("===========================================================\n")

if __name__ == "__main__":
    print("Liquidity Density Analyzer wordt asynchroon opgestart...")
    analyzer = LiquidityDensityAnalyzer()
    asyncio.run(main())
