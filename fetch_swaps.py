"""
Fetch swaps data for the Streamlit dashboard.

This module provides a function to fetch raw swap data from the database
and transform it into a pandas DataFrame with scaled token amounts for visualization.
"""

import sqlite3
import pandas as pd
from typing import Optional


def fetch_swaps_data(db_path: str, days: int = 7) -> pd.DataFrame:
    """
    Fetch swaps data for the dashboard.

    Args:
        db_path: Path to the SQLite database file.
        days: Number of days to fetch data for (default: 7).

    Returns:
        pd.DataFrame: Swaps data with columns:
            - timestamp
            - tx_hash
            - sender
            - price
            - amount0 (raw WETH amount, 18 decimals)
            - amount1 (raw USDC amount, 6 decimals)
            - amount0_eth (scaled WETH amount)
            - amount1_usdc (scaled USDC amount)
            - volume_usd (hotfix: absolute USDC amount)
            - price_impact_bps (initialized as None)
            - implied_density (initialized as None)
    """
    query = f"""
    SELECT 
        timestamp,
        tx_hash,
        sender,
        price,
        amount0,
        amount1
    FROM 
        swaps
    WHERE 
        timestamp >= datetime('now', '-{days} days')
    ORDER BY 
        timestamp DESC
    LIMIT 1000;
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)
    
    # Scale raw token amounts to human-readable values
    if not df.empty:
        # WETH (token0) has 18 decimals
        df["amount0_eth"] = df["amount0"].astype(float) / 1e18
        
        # USDC (token1) has 6 decimals
        df["amount1_usdc"] = df["amount1"].astype(float) / 1e6
        
        # Hotfix: Override volume_usd with the absolute USDC amount
        df["volume_usd"] = df["amount1_usdc"].abs()
        
        # Initialize missing columns for compatibility with app.py
        df["price_impact_bps"] = None
        df["implied_density"] = None
    
    return df