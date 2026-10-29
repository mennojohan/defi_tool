"""
Fetch swaps data for the Streamlit dashboard.

This module provides a function to fetch key swap metrics from the database
and return them as a pandas DataFrame for visualization.
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
            - amount0_usdc (USDC amount in USDC)
            - amount1_eth (WETH amount in ETH)
            - volume_usd
            - price_impact_bps
            - implied_density
    """
    query = f"""
    SELECT 
        timestamp,
        tx_hash,
        sender,
        price,
        amount0 / 1e6 AS amount0_usdc,  # USDC (6 decimals)
        amount1 / 1e18 AS amount1_eth,  # WETH (18 decimals)
        volume_usd,
        price_impact_bps,
        implied_density
    FROM 
        swaps
    WHERE 
        timestamp >= datetime('now', '-{days} days')
    ORDER BY 
        timestamp DESC;
    """

    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(query, conn)

    return df