"""
Streamlit dashboard for WETH/USDC swap analytics.

This app visualizes key metrics from Uniswap V3 swaps, including:
- Price impact (bps)
- Volume (USD)
- Implied liquidity density
- Token amounts (ETH/USDC)
"""

import streamlit as st
import pandas as pd
from fetch_swaps import fetch_swaps_data


# Configure the dashboard
st.set_page_config(layout="wide")
st.title("WETH/USDC Swap Analytics")
st.write("Real-time data for Uniswap V3 swaps.")

# Sidebar for user input
with st.sidebar:
    st.header("Filters")
    days = st.slider("Days of data", 1, 30, 7)
    min_volume = st.number_input("Minimum Volume (USD)", min_value=0.0, value=0.0)
    min_impact = st.number_input("Minimum Price Impact (bps)", min_value=0.0, value=0.0)

# Fetch data
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_data(days: int) -> pd.DataFrame:
    return fetch_swaps_data(db_path="./defi_tracker_v3.db", days=days)

df = load_data(days)

# Apply filters
if min_volume > 0:
    df = df[df["volume_usd"] >= min_volume]
if min_impact > 0:
    df = df[df["price_impact_bps"] >= min_impact]

# Display metrics
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Swaps", len(df))
col2.metric("Avg Volume (USD)", f"${df['volume_usd'].mean():,.2f}")
col3.metric("Avg Price Impact (bps)", f"{df['price_impact_bps'].mean():.2f}")
col4.metric("Current Price (USD)", f"${df['price'].iloc[0]:,.2f}")

# Display data
tab1, tab2 = st.tabs(["Data", "Charts"])

with tab1:
    # Format token amounts for display
    df_display = df.copy()
    df_display["amount0_usdc"] = df["amount0_usdc"].apply(lambda x: f"{x:,.6f} USDC")
    df_display["amount1_eth"] = df["amount1_eth"].apply(lambda x: f"{x:,.6f} WETH")
    df_display["volume_usd"] = df["volume_usd"].apply(lambda x: f"${x:,.2f}")
    df_display["price"] = df["price"].apply(lambda x: f"${x:,.2f}")
    
    st.dataframe(df_display, use_container_width=True)

with tab2:
    st.subheader("Price Impact vs Volume")
    st.scatter_chart(
        df,
        x="volume_usd",
        y="price_impact_bps",
        color="price",
        size="volume_usd"
    )

    st.subheader("Price Over Time")
    st.line_chart(df.set_index("timestamp")["price"])

    st.subheader("Price Impact Distribution")
    st.bar_chart(df["price_impact_bps"].value_counts().sort_index())