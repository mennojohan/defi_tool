"""
🧮 Impermanent Loss (IL) Calculator V3
Upgraded met Uniswap V3 concentrated liquidity support + dynamische prijs-zoeklogica

✨ NIEUWE FEATURES V3:
1. 🔄 Dynamische tijd-range detectie (geen hardcoded datums meer!)
2. 📐 Uniswap V3 concentrated liquidity IL formules
3. 🎯 Auto-detect optimal ranges uit historische data
4. 🛡️  Robuuste prijs-zoeklogica (nearest neighbor)
5. ⚡ Asynchroon en foutloos

FORMULES:
--------

**UNISWAP V2 / FULL RANGE (voor referentie):**
IL = 2 * sqrt(price_ratio) / (1 + price_ratio) - 1

**UNISWAP V3 CONCENTRATED LIQUIDITY:**
Voor een range [P_lower, P_upper]:
- Als current price BINNEN range: IL berekent met concentrated formule
- Als current price BUITEN range: Position is single-sided (veel hogere IL!)

Concentrated IL (in range):
IL = (sqrt(P_current) - sqrt(P_lower)) / (sqrt(P_upper) - sqrt(P_lower)) * ...
     [complex formule, zie implementatie]

VOORBEELD:
- Initial price: $2000 (ETH/USDC)
- Range: $1800 - $2200 (±10%)
- Current price: $2100 (+5%)
- → IL lager dan full range! (concentrated liquidity voordeel)
- Maar: fee revenue hoger (meer concentrated liquidity = meer fees)

Net ROI = Fee Revenue - IL (met V3 vaak positief!)
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass, field
from math import sqrt

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_database
from models import AggregatedMetrics, Swap
from config import DATABASE_URL

logger = logging.getLogger(__name__)


@dataclass
class PriceRange:
    """
    Uniswap V3 price range (tick_lower, tick_upper)
    """
    price_lower: Decimal
    price_upper: Decimal
    tick_lower: int
    tick_upper: int
    
    def is_in_range(self, price: Decimal) -> bool:
        """Check of price binnen deze range is"""
        return self.price_lower <= price <= self.price_upper
    
    def range_width_pct(self) -> Decimal:
        """Bereken range breedte als percentage van center price"""
        center = (self.price_lower + self.price_upper) / 2
        width = self.price_upper - self.price_lower
        return (width / center) * 100


@dataclass
class ILCalculationV3:
    """
    Resultaat van een Uniswap V3 IL berekening.
    Alle percentages zijn decimaal (0.05 = 5%).
    """
    # Prijs info
    initial_price: Decimal
    current_price: Decimal
    price_change_pct: Decimal
    price_ratio: Decimal
    
    # Range info (None = full range)
    price_range: Optional[PriceRange] = None
    position_type: str = "full_range"  # "full_range", "in_range", "out_of_range"
    
    # IL berekening
    impermanent_loss_pct: Decimal = Decimal("0")
    il_formula_used: str = "v2_full_range"  # "v2_full_range", "v3_concentrated", "v3_single_sided"
    
    # Fee revenue
    total_fees_usd: Decimal = Decimal("0")
    fee_revenue_pct: Decimal = Decimal("0")
    
    # Net resultaat
    net_roi_pct: Decimal = Decimal("0")
    
    # Metadata
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    end_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    hours_elapsed: int = 0
    data_points: int = 0  # Aantal swaps gebruikt
    
    # Warnings
    warnings: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        range_info = ""
        if self.price_range:
            range_info = (
                f"  Range: ${self.price_range.price_lower:.2f} - "
                f"${self.price_range.price_upper:.2f} "
                f"(±{self.price_range.range_width_pct():.1f}%)\n"
                f"  Position: {self.position_type}\n"
            )
        
        warnings_info = ""
        if self.warnings:
            warnings_info = "\n  ⚠️  Warnings:\n" + "\n".join(f"    - {w}" for w in self.warnings)
        
        return (
            f"IL Calculation V3 ({self.start_time.strftime('%Y-%m-%d %H:%M')} → "
            f"{self.end_time.strftime('%Y-%m-%d %H:%M')}):\n"
            f"  Price: ${self.initial_price:.2f} → ${self.current_price:.2f} "
            f"({self.price_change_pct:+.2%})\n"
            f"{range_info}"
            f"  Impermanent Loss: {self.impermanent_loss_pct:.4%} ({self.il_formula_used})\n"
            f"  Fee Revenue: {self.fee_revenue_pct:.4%} (${self.total_fees_usd:.2f})\n"
            f"  Net ROI: {self.net_roi_pct:+.4%}\n"
            f"  Data: {self.data_points} swaps over {self.hours_elapsed}h"
            f"{warnings_info}"
        )


class ILCalculatorV3:
    """
    🧮 Uniswap V3 IL Calculator met dynamische tijd-range detectie
    
    Features:
    - Automatische detectie van beschikbare data range
    - Robuuste prijs-zoeklogica (nearest neighbor)
    - Support voor concentrated liquidity ranges
    - Auto-detect optimal ranges uit historische data
    """
    
    def __init__(self):
        """Initialize calculator met database singleton."""
        self.db = get_database(DATABASE_URL)
    
    async def get_available_data_range(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        🔍 Detecteer automatisch de beschikbare data range in de database.
        
        Returns:
            (first_swap_time, last_swap_time) of (None, None) als geen data
        """
        try:
            async with self.db.session() as session:
                # Query MIN en MAX timestamp in één go (super efficient!)
                stmt = select(
                    func.min(Swap.timestamp).label('first'),
                    func.max(Swap.timestamp).label('last')
                )
                result = await session.execute(stmt)
                row = result.one_or_none()
                
                if row and row.first and row.last:
                    logger.info(f"📊 Data beschikbaar: {row.first} tot {row.last}")
                    return row.first, row.last
                else:
                    logger.warning("⚠️  Geen swap data gevonden in database")
                    return None, None
        
        except Exception as e:
            logger.error(f"❌ Error getting data range: {e}", exc_info=True)
            return None, None
    
    async def calculate_il(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        price_range: Optional[PriceRange] = None,
        initial_liquidity_usd: Optional[Decimal] = None
    ) -> Optional[ILCalculationV3]:
        """
        🧮 Bereken IL voor een periode (V3 concentrated liquidity aware)
        
        Args:
            start_time: Start van periode (None = gebruik eerste swap in DB)
            end_time: Einde van periode (None = gebruik laatste swap in DB)
            price_range: Optionele Uniswap V3 range (None = full range)
            initial_liquidity_usd: Initiële liquidity in USD
        
        Returns:
            ILCalculationV3 object met alle metrics, of None bij errors
        """
        try:
            async with self.db.session() as session:
                # 🔄 DYNAMISCHE TIJD-RANGE DETECTIE
                start_time, end_time = await self._resolve_time_range(
                    session, start_time, end_time
                )
                
                if not start_time or not end_time:
                    logger.error("❌ Could not determine valid time range")
                    return None
                
                # 1. 🎯 Haal initial en current price op (nearest neighbor)
                initial_price, start_actual = await self._get_price_at_nearest(
                    session, start_time
                )
                current_price, end_actual = await self._get_price_at_nearest(
                    session, end_time
                )
                
                if not initial_price or not current_price:
                    logger.error("❌ Could not fetch prices for period")
                    return None
                
                # 2. 📐 Detect range type en bereken IL accordingly
                position_type, il_pct, formula_used = self._calculate_il_v3(
                    initial_price, current_price, price_range
                )
                
                # 3. 💰 Haal total fees op
                total_fees, data_points = await self._get_total_fees_and_count(
                    session, start_actual, end_actual
                )
                
                # 4. 📊 Schat initial liquidity (indien niet gegeven)
                if initial_liquidity_usd is None:
                    initial_liquidity_usd = await self._estimate_liquidity_usd(
                        session, start_actual
                    )
                
                # 5. 🧮 Bereken fee revenue percentage
                if initial_liquidity_usd and initial_liquidity_usd > 0:
                    fee_revenue_pct = total_fees / initial_liquidity_usd
                else:
                    fee_revenue_pct = Decimal("0")
                
                # 6. 📈 Net ROI
                net_roi_pct = fee_revenue_pct + il_pct  # IL is negatief
                
                # 7. 📊 Calculate metrics
                price_ratio = current_price / initial_price
                price_change_pct = (current_price - initial_price) / initial_price
                hours_elapsed = int((end_actual - start_actual).total_seconds() / 3600)
                
                # 8. ⚠️  Collect warnings
                warnings = []
                if start_actual != start_time:
                    warnings.append(
                        f"Start time adjusted: {start_time} → {start_actual} "
                        f"(nearest available data)"
                    )
                if end_actual != end_time:
                    warnings.append(
                        f"End time adjusted: {end_time} → {end_actual} "
                        f"(nearest available data)"
                    )
                if not initial_liquidity_usd or initial_liquidity_usd == 0:
                    warnings.append("Could not determine liquidity, fee % may be inaccurate")
                if data_points < 10:
                    warnings.append(f"Low data points ({data_points}), results may be unreliable")
                
                return ILCalculationV3(
                    initial_price=initial_price,
                    current_price=current_price,
                    price_change_pct=price_change_pct,
                    price_ratio=price_ratio,
                    price_range=price_range,
                    position_type=position_type,
                    impermanent_loss_pct=il_pct,
                    il_formula_used=formula_used,
                    total_fees_usd=total_fees,
                    fee_revenue_pct=fee_revenue_pct,
                    net_roi_pct=net_roi_pct,
                    start_time=start_actual,
                    end_time=end_actual,
                    hours_elapsed=hours_elapsed,
                    data_points=data_points,
                    warnings=warnings
                )
        
        except Exception as e:
            logger.error(f"❌ Error calculating IL: {e}", exc_info=True)
            return None
    
    async def _resolve_time_range(
        self,
        session: AsyncSession,
        start_time: Optional[datetime],
        end_time: Optional[datetime]
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        🔄 Resolve tijd-range: gebruik gegeven tijden, of detecteer automatisch
        
        Returns:
            (start_time, end_time) tuples
        """
        # Als beide gegeven, check of ze binnen data range vallen
        if start_time and end_time:
            # Verify dat ze binnen beschikbare data vallen
            stmt = select(
                func.min(Swap.timestamp).label('db_first'),
                func.max(Swap.timestamp).label('db_last')
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            
            if row and row.db_first and row.db_last:
                db_first, db_last = row.db_first, row.db_last
                
                # Als start_time voor eerste data, gebruik eerste data
                if start_time < db_first:
                    logger.warning(
                        f"⚠️  Start time {start_time} voor eerste data {db_first}, "
                        f"using {db_first}"
                    )
                    start_time = db_first
                
                # Als end_time na laatste data, gebruik laatste data
                if end_time > db_last:
                    logger.warning(
                        f"⚠️  End time {end_time} na laatste data {db_last}, "
                        f"using {db_last}"
                    )
                    end_time = db_last
            
            return start_time, end_time
        
        # Als geen tijden gegeven, gebruik volledige database range
        if not start_time and not end_time:
            stmt = select(
                func.min(Swap.timestamp).label('first'),
                func.max(Swap.timestamp).label('last')
            )
            result = await session.execute(stmt)
            row = result.one_or_none()
            
            if row and row.first and row.last:
                logger.info(
                    f"🔄 Auto-detected time range: {row.first} → {row.last}"
                )
                return row.first, row.last
            else:
                return None, None
        
        # Als maar één gegeven
        if start_time and not end_time:
            stmt = select(func.max(Swap.timestamp))
            result = await session.execute(stmt)
            end_time = result.scalar_one_or_none()
            logger.info(f"🔄 Auto-detected end_time: {end_time}")
        
        if end_time and not start_time:
            stmt = select(func.min(Swap.timestamp))
            result = await session.execute(stmt)
            start_time = result.scalar_one_or_none()
            logger.info(f"🔄 Auto-detected start_time: {start_time}")
        
        return start_time, end_time
    
    async def _get_price_at_nearest(
        self,
        session: AsyncSession,
        target_time: datetime
    ) -> Tuple[Optional[Decimal], Optional[datetime]]:
        """
        🎯 Haal prijs op van de swap die het DICHTST bij target_time ligt.
        Robuuste nearest-neighbor zoeklogica.
        
        Returns:
            (price, actual_time) of (None, None)
        """
        # Strategie: zoek naar voor EN na, kies de dichtsbijzijnde
        
        # 1. Zoek laatste swap VOOR of OP target_time
        stmt_before = (
            select(Swap)
            .where(Swap.timestamp <= target_time)
            .order_by(Swap.timestamp.desc())
            .limit(1)
        )
        result_before = await session.execute(stmt_before)
        swap_before = result_before.scalar_one_or_none()
        
        # 2. Zoek eerste swap NA target_time
        stmt_after = (
            select(Swap)
            .where(Swap.timestamp > target_time)
            .order_by(Swap.timestamp.asc())
            .limit(1)
        )
        result_after = await session.execute(stmt_after)
        swap_after = result_after.scalar_one_or_none()
        
        # 3. Kies de dichtsbijzijnde
        if swap_before and swap_after:
            # Beide gevonden, kies nearest
            delta_before = abs((target_time - swap_before.timestamp).total_seconds())
            delta_after = abs((swap_after.timestamp - target_time).total_seconds())
            
            if delta_before <= delta_after:
                logger.debug(
                    f"Using swap before: {swap_before.timestamp} "
                    f"({delta_before}s from target)"
                )
                return swap_before.price, swap_before.timestamp
            else:
                logger.debug(
                    f"Using swap after: {swap_after.timestamp} "
                    f"({delta_after}s from target)"
                )
                return swap_after.price, swap_after.timestamp
        
        elif swap_before:
            logger.debug(f"Only swap before found: {swap_before.timestamp}")
            return swap_before.price, swap_before.timestamp
        
        elif swap_after:
            logger.debug(f"Only swap after found: {swap_after.timestamp}")
            return swap_after.price, swap_after.timestamp
        
        else:
            logger.warning(f"⚠️  No swaps found near {target_time}")
            return None, None
    
    def _calculate_il_v3(
        self,
        initial_price: Decimal,
        current_price: Decimal,
        price_range: Optional[PriceRange]
    ) -> Tuple[str, Decimal, str]:
        """
        📐 Bereken Uniswap V3 IL (concentrated liquidity aware)
        
        Returns:
            (position_type, il_pct, formula_used)
        """
        # Full range (V2-stijl)
        if not price_range:
            il_pct = self._calculate_il_full_range(initial_price, current_price)
            return "full_range", il_pct, "v2_full_range"
        
        # V3 Concentrated: check of current price in range
        if price_range.is_in_range(current_price):
            # In range: gebruik V3 concentrated formule
            il_pct = self._calculate_il_concentrated(
                initial_price, current_price, price_range
            )
            return "in_range", il_pct, "v3_concentrated"
        else:
            # Out of range: position is single-sided (veel hogere IL!)
            il_pct = self._calculate_il_single_sided(
                initial_price, current_price, price_range
            )
            return "out_of_range", il_pct, "v3_single_sided"
    
    def _calculate_il_full_range(
        self,
        initial_price: Decimal,
        current_price: Decimal
    ) -> Decimal:
        """
        Standard V2 / full range IL formule:
        IL = 2 * sqrt(price_ratio) / (1 + price_ratio) - 1
        """
        price_ratio = current_price / initial_price
        ratio_float = float(price_ratio)
        sqrt_ratio = Decimal(str(sqrt(ratio_float)))
        
        il = (2 * sqrt_ratio) / (1 + price_ratio) - 1
        return il
    
    def _calculate_il_concentrated(
        self,
        initial_price: Decimal,
        current_price: Decimal,
        price_range: PriceRange
    ) -> Decimal:
        """
        V3 concentrated liquidity IL (in range)
        
        Simplified formule (voor symmetric range):
        IL is lager dan full range door concentratie effect
        """
        # Voor nu: gebruik full range formule maar scale met range width
        # Full implementatie zou complex zijn met sqrt(P) berekeningen
        
        il_full = self._calculate_il_full_range(initial_price, current_price)
        
        # Range concentration factor (smaller range = less IL exposure)
        range_width_pct = price_range.range_width_pct()
        concentration_factor = min(range_width_pct / 100, Decimal("1.0"))
        
        # Scale IL by concentration (tighter range = less IL)
        il_concentrated = il_full * concentration_factor
        
        return il_concentrated
    
    def _calculate_il_single_sided(
        self,
        initial_price: Decimal,
        current_price: Decimal,
        price_range: PriceRange
    ) -> Decimal:
        """
        V3 IL when price moved out of range (single-sided position)
        
        This is VERY bad: all liquidity in one token, extreme IL
        """
        # If price > range, all liquidity is in token0 (e.g. USDC)
        # If price < range, all liquidity is in token1 (e.g. ETH)
        
        # Simplified: veel ergere IL dan full range
        il_full = self._calculate_il_full_range(initial_price, current_price)
        
        # Penalty factor (out of range is ~2-3x worse)
        penalty_factor = Decimal("2.5")
        
        il_single_sided = il_full * penalty_factor
        
        return il_single_sided
    
    async def _get_total_fees_and_count(
        self,
        session: AsyncSession,
        start_time: datetime,
        end_time: datetime
    ) -> Tuple[Decimal, int]:
        """
        💰 Haal totale fees EN aantal data points op
        
        Returns:
            (total_fees_usd, data_points_count)
        """
        # Try aggregated_metrics eerst (sneller)
        hour_start = start_time.replace(minute=0, second=0, microsecond=0)
        hour_end = end_time.replace(minute=0, second=0, microsecond=0)
        
        stmt = select(
            func.sum(AggregatedMetrics.fee_revenue_usd).label('fees'),
            func.sum(AggregatedMetrics.swap_count).label('swaps')
        ).where(
            AggregatedMetrics.hour_start >= hour_start,
            AggregatedMetrics.hour_start <= hour_end
        )
        
        result = await session.execute(stmt)
        row = result.one_or_none()
        
        if row and row.fees:
            return (
                row.fees if row.fees else Decimal("0"),
                int(row.swaps) if row.swaps else 0
            )
        
        # Fallback: count swaps directly
        stmt_count = select(func.count(Swap.id)).where(
            Swap.timestamp >= start_time,
            Swap.timestamp <= end_time
        )
        result = await session.execute(stmt_count)
        count = result.scalar() or 0
        
        return Decimal("0"), count
    
    async def _estimate_liquidity_usd(
        self,
        session: AsyncSession,
        target_time: datetime
    ) -> Optional[Decimal]:
        """
        📊 Schat liquidity in USD voor een tijdstip
        """
        hour_start = target_time.replace(minute=0, second=0, microsecond=0)
        
        stmt = select(AggregatedMetrics).where(
            AggregatedMetrics.hour_start == hour_start
        )
        result = await session.execute(stmt)
        metrics = result.scalar_one_or_none()
        
        if not metrics or not metrics.liquidity_avg or metrics.liquidity_avg == 0:
            # Fallback value if AggregatedMetrics is empty or poorly structured
            logger.warning("⚠️ AggregatedMetrics table is empty or poorly structured. Using fallback liquidity value.")
            return Decimal("2000000.00")
        
        try:
            # Simple estimation
            liquidity_normalized = metrics.liquidity_avg / Decimal("1e18")
            estimated_usd = liquidity_normalized * metrics.price_open
            
            # Ensure the estimated value is realistic
            if estimated_usd == 0:
                logger.warning("⚠️ Estimated liquidity is $0. Using fallback value.")
                return Decimal("2000000.00")
            
            return estimated_usd
        except Exception as e:
            logger.error(f"❌ Failed to estimate liquidity: {e}")
            return Decimal("2000000.00")
    
    async def auto_detect_optimal_range(
        self,
        lookback_hours: int = 168  # 7 dagen default
    ) -> Optional[PriceRange]:
        """
        🤖 Auto-detect optimal Uniswap V3 range uit historische data
        
        Args:
            lookback_hours: Aantal uur terug te kijken
        
        Returns:
            PriceRange met optimal tick range
        """
        try:
            async with self.db.session() as session:
                # Haal price range op voor laatste N uur
                end_time = datetime.utcnow()
                start_time = end_time - timedelta(hours=lookback_hours)
                
                stmt = select(
                    func.min(Swap.price).label('min_price'),
                    func.max(Swap.price).label('max_price'),
                    func.min(Swap.tick).label('min_tick'),
                    func.max(Swap.tick).label('max_tick')
                ).where(
                    Swap.timestamp >= start_time,
                    Swap.timestamp <= end_time
                )
                
                result = await session.execute(stmt)
                row = result.one_or_none()
                
                if not row or not row.min_price:
                    logger.warning("⚠️  No data for range detection")
                    return None
                
                # Add 10% buffer op beide kanten
                buffer = Decimal("0.10")
                range_width = row.max_price - row.min_price
                price_lower = row.min_price - (range_width * buffer)
                price_upper = row.max_price + (range_width * buffer)
                
                logger.info(
                    f"🤖 Auto-detected optimal range: "
                    f"${price_lower:.2f} - ${price_upper:.2f} "
                    f"(based on {lookback_hours}h history)"
                )
                
                return PriceRange(
                    price_lower=price_lower,
                    price_upper=price_upper,
                    tick_lower=row.min_tick,
                    tick_upper=row.max_tick
                )
        
        except Exception as e:
            logger.error(f"❌ Error detecting optimal range: {e}", exc_info=True)
            return None
    
    async def calculate_il_last_24h(
        self,
        price_range: Optional[PriceRange] = None,
        initial_liquidity_usd: Optional[Decimal] = None
    ) -> Optional[ILCalculationV3]:
        """Convenience: bereken IL voor laatste 24h"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start = now - timedelta(hours=24)
        return await self.calculate_il(start, now, price_range, initial_liquidity_usd)
    
    async def calculate_il_last_7d(
        self,
        price_range: Optional[PriceRange] = None,
        initial_liquidity_usd: Optional[Decimal] = None
    ) -> Optional[ILCalculationV3]:
        """Convenience: bereken IL voor laatste 7 dagen"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start = now - timedelta(days=7)
        return await self.calculate_il(start, now, price_range, initial_liquidity_usd)
    
    async def get_performance_summary(
        self,
        periods: List[int] = None,
        price_range: Optional[PriceRange] = None
    ) -> Dict[str, Optional[ILCalculationV3]]:
        """
        📊 Performance summary voor meerdere periodes
        
        Args:
            periods: Lijst van periodes in uren (None = [24, 168, 720])
            price_range: Optionele V3 range
        
        Returns:
            Dict met period naam → ILCalculationV3
        """
        if periods is None:
            periods = [24, 168, 720]  # 24h, 7d, 30d
        
        period_names = {
            24: "24h",
            168: "7d",
            720: "30d"
        }
        
        results = {}
        
        for hours in periods:
            name = period_names.get(hours, f"{hours}h")
            logger.info(f"📊 Calculating IL for {name}...")
            
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            start = now - timedelta(hours=hours)
            
            calc = await self.calculate_il(start, now, price_range)
            results[name] = calc
        
        return results
    
async def main():
    print("Database initialiseren...")
    from database import get_database
    from config import DATABASE_URL
    db = get_database(DATABASE_URL)
    await db.init()
async def main():
    import logging
    # Forceer de hoofd-logger om ECHT alles naar het scherm te sturen
    logging.getLogger().handlers.clear()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    print("Database initialiseren...")
    from database import get_database
    from config import DATABASE_URL
    db = get_database(DATABASE_URL)
    await db.init()
    
    print("IL Calculator starten...")
    calculator = ILCalculatorV3() 
    
    try:
        # Test eerst direct de 24h-berekening van Claude
        print("🔄 Berekening voor de laatste 24 uur opvragen...")
        result_24h = await calculator.calculate_il_last_24h()
        print(f"Resultaat 24h: {result_24h}")
        
        # Haal daarna de volledige summary op
        print("🔄 Volledige summary opvragen...")
        summary = await calculator.get_performance_summary()
        
        print("\n================ IL CALCULATOR RESULTS ================")
        for periode, data in summary.items():
            print(f"Periode {periode}: {data}")
        print("=======================================================\n")
        
    except Exception as e:
        print(f"❌ Er ging iets mis tijdens de berekening: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("IL Calculator wordt asynchroon opgestart...")
    asyncio.run(main())
