"""
SQLAlchemy models voor DeFi Pool Tracker - Uniswap V3 Upgrade
Ondersteunt concentrated liquidity, MEV detection, en liquidity density metrics
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Index, Integer,
    Numeric, String, Text, UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    """Base class voor alle models met async support"""
    pass


class Swap(Base):
    """
    Raw swap events van de pool
    Elke rij = 1 swap transaction
    """
    __tablename__ = 'swaps'
    
    # Primary Key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Transaction Info
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    log_index: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 🆕 Voor MEV detection
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    # Swap Participants
    sender: Mapped[str] = mapped_column(String(42), nullable=False, index=True)  # Wie initiated de swap
    recipient: Mapped[str] = mapped_column(String(42), nullable=False)  # Wie ontvangt
    
    # Swap Amounts (gebruik Numeric voor precisie)
    amount0: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)  # Token0 delta
    amount1: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)  # Token1 delta
    
    # Price & Liquidity State
    sqrt_price_x96: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)  # Human-readable prijs
    tick: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 🆕 Index voor range queries
    liquidity: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    
    # 🆕 USD Values (optional, requires price oracle)
    amount0_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    amount1_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    volume_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    
    # 🆕 IMPLIED LIQUIDITY DENSITY - Berekend uit swap impact
    price_impact_bps: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)  # Basis points
    implied_density: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4), nullable=True)  # Volume / price_impact
    
    # 🆕 MEV FLAGS
    is_potential_mev: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # Geflagged door detector
    mev_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'sandwich', 'frontrun', 'backrun'
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Composite unique constraint (geen dubbele events)
    __table_args__ = (
        UniqueConstraint('tx_hash', 'log_index', name='uq_tx_log'),
        Index('ix_swaps_timestamp_desc', timestamp.desc()),
        Index('ix_swaps_block_txindex', 'block_number', 'transaction_index'),  # 🆕 Voor MEV detection
        Index('ix_swaps_tick_time', 'tick', 'timestamp'),  # 🆕 Voor liquidity density analysis
    )
    
    def __repr__(self) -> str:
        return f"<Swap(tx={self.tx_hash[:10]}..., price={self.price}, tick={self.tick}, mev={self.is_potential_mev})>"


class MEVSandwich(Base):
    """
    🆕 POST-FACTUM MEV SANDWICH ATTACKS
    Detecteert sandwich attacks op basis van transaction ordering binnen hetzelfde blok
    """
    __tablename__ = 'mev_sandwiches'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Blok info
    block_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    block_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Sandwich structuur: frontrun → victim → backrun
    frontrun_tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    frontrun_tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    frontrun_sender: Mapped[str] = mapped_column(String(42), nullable=False, index=True)
    
    victim_tx_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    victim_tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    victim_sender: Mapped[str] = mapped_column(String(42), nullable=False)
    
    backrun_tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    backrun_tx_index: Mapped[int] = mapped_column(Integer, nullable=False)
    backrun_sender: Mapped[str] = mapped_column(String(42), nullable=False)
    
    # Profit metrics (geschat)
    estimated_profit_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    victim_loss_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    
    # Detection metadata
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=1.0)  # 0-1 score
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('block_number', 'victim_tx_hash', name='uq_sandwich_victim'),
        CheckConstraint('frontrun_tx_index < victim_tx_index', name='ck_frontrun_before_victim'),
        CheckConstraint('victim_tx_index < backrun_tx_index', name='ck_victim_before_backrun'),
    )
    
    def __repr__(self) -> str:
        return f"<MEVSandwich(block={self.block_number}, victim={self.victim_tx_hash[:10]}..., profit=${self.estimated_profit_usd})>"


class LiquidityDensity(Base):
    """
    🆕 IMPLIED LIQUIDITY DENSITY PER TICK RANGE
    Berekend uit swap price impact (geen dure on-chain queries nodig)
    """
    __tablename__ = 'liquidity_density'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Tick range (100 tick buckets = 1% price movement voor 0.3% fee tier)
    tick_lower: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tick_upper: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    
    # Time bucket (hourly snapshots)
    hour_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    # Density metrics (higher = more liquidity, less slippage)
    avg_implied_density: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    median_implied_density: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    swap_count: Mapped[int] = mapped_column(Integer, default=0)
    total_volume_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    
    # Price impact metrics
    avg_price_impact_bps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_price_impact_bps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    
    # Metadata
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('tick_lower', 'tick_upper', 'hour_start', name='uq_density_range_hour'),
        CheckConstraint('tick_lower < tick_upper', name='ck_valid_tick_range'),
    )
    
    def __repr__(self) -> str:
        return f"<LiquidityDensity(ticks=[{self.tick_lower}, {self.tick_upper}], density={self.avg_implied_density}, hour={self.hour_start})>"


class PoolState(Base):
    """
    Hourly snapshots van pool state
    Voor time-series grafieken en trending analysis
    """
    __tablename__ = 'pool_states'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Timestamp (rounded to hour)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, unique=True, index=True)
    
    # Pool State Snapshot
    sqrt_price_x96: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    tick: Mapped[int] = mapped_column(Integer, nullable=False)
    liquidity: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    
    # Aggregate stats for this hour
    swap_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_traders: Mapped[int] = mapped_column(Integer, default=0)
    
    # 🆕 MEV stats
    mev_sandwich_count: Mapped[int] = mapped_column(Integer, default=0)
    mev_affected_swaps: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<PoolState(time={self.snapshot_time}, price={self.price}, swaps={self.swap_count}, mev={self.mev_sandwich_count})>"


class AggregatedMetrics(Base):
    """
    Hourly aggregated metrics
    Pre-computed voor snelle dashboard queries
    """
    __tablename__ = 'aggregated_metrics'
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Time bucket
    hour_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, unique=True, index=True)
    
    # Volume Metrics
    swap_count: Mapped[int] = mapped_column(Integer, default=0)
    volume_token0: Mapped[Decimal] = mapped_column(Numeric(78, 0), default=0)
    volume_token1: Mapped[Decimal] = mapped_column(Numeric(78, 0), default=0)
    volume_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    
    # Fee Revenue (0.3% voor Uniswap V3, adjust voor Aerodrome)
    fee_revenue_token0: Mapped[Decimal] = mapped_column(Numeric(78, 0), default=0)
    fee_revenue_token1: Mapped[Decimal] = mapped_column(Numeric(78, 0), default=0)
    fee_revenue_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    
    # Trader Metrics
    unique_traders: Mapped[int] = mapped_column(Integer, default=0)
    unique_senders: Mapped[int] = mapped_column(Integer, default=0)
    unique_recipients: Mapped[int] = mapped_column(Integer, default=0)
    
    # OHLC Price Data (voor candlestick charts)
    price_open: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    price_high: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    price_low: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    price_close: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    
    # Liquidity Range
    liquidity_avg: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    liquidity_min: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    liquidity_max: Mapped[Decimal] = mapped_column(Numeric(78, 0), nullable=False)
    
    # 🆕 Tick Range (V3 specific)
    tick_min: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_max: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_avg: Mapped[int] = mapped_column(Integer, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<Metrics(hour={self.hour_start}, vol_usd={self.volume_usd}, swaps={self.swap_count}, tick_range=[{self.tick_min}, {self.tick_max}])>"
