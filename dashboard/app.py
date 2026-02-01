"""
Streamlit Dashboard for Stocker Trader Bot

Run with: streamlit run dashboard/app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.database import get_database
from src.broker.alpaca_client import get_alpaca_client
from src.broker.pdt_tracker import PDTTracker

st.set_page_config(
    page_title="Stocker Trader Dashboard",
    page_icon="📈",
    layout="wide"
)

st.title("Stocker Trader Bot Dashboard")


@st.cache_resource
def get_db():
    return get_database()


@st.cache_resource
def get_client():
    try:
        return get_alpaca_client()
    except Exception:
        return None


def display_account_info():
    """Display account information."""
    st.subheader("Account Overview")

    client = get_client()
    if client is None:
        st.warning("Unable to connect to Alpaca. Check your API credentials.")
        return

    try:
        account = client.get_account()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Portfolio Value", f"${account.portfolio_value:,.2f}")

        with col2:
            st.metric("Cash", f"${account.cash:,.2f}")

        with col3:
            st.metric("Buying Power", f"${account.buying_power:,.2f}")

        with col4:
            pdt = PDTTracker(client)
            status = pdt.get_pdt_status()
            st.metric(
                "Day Trades Remaining",
                f"{status['day_trades_remaining']}/{status['max_day_trades']}"
            )

    except Exception as e:
        st.error(f"Error fetching account info: {e}")


def display_positions():
    """Display current positions."""
    st.subheader("Current Positions")

    client = get_client()
    if client is None:
        return

    try:
        positions = client.get_positions()

        if not positions:
            st.info("No open positions")
            return

        data = []
        for p in positions:
            data.append({
                "Symbol": p.symbol,
                "Qty": p.qty,
                "Entry Price": f"${p.avg_entry_price:.2f}",
                "Current Price": f"${p.current_price:.2f}",
                "Market Value": f"${p.market_value:,.2f}",
                "Unrealized P&L": f"${p.unrealized_pl:+,.2f}",
                "P&L %": f"{p.unrealized_plpc * 100:+.2f}%"
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)

        total_unrealized = sum(p.unrealized_pl for p in positions)
        st.metric("Total Unrealized P&L", f"${total_unrealized:+,.2f}")

    except Exception as e:
        st.error(f"Error fetching positions: {e}")


def display_recent_trades():
    """Display recent trades from database."""
    st.subheader("Recent Trades")

    db = get_db()

    try:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        trades = db.get_trades_by_date_range(start_date, end_date)

        if not trades:
            st.info("No trades in the last 30 days")
            return

        data = []
        for t in trades:
            data.append({
                "Symbol": t.symbol,
                "Direction": t.direction.upper(),
                "Qty": t.quantity,
                "Entry": f"${t.entry_price:.2f}",
                "Exit": f"${t.exit_price:.2f}" if t.exit_price else "Open",
                "P&L": f"${t.pnl:+,.2f}" if t.pnl else "-",
                "Strategy": t.strategy,
                "Date": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "-"
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)

        closed_trades = [t for t in trades if t.pnl is not None]
        if closed_trades:
            total_pnl = sum(t.pnl for t in closed_trades)
            wins = len([t for t in closed_trades if t.pnl > 0])
            win_rate = (wins / len(closed_trades)) * 100 if closed_trades else 0

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total P&L", f"${total_pnl:+,.2f}")
            with col2:
                st.metric("Win Rate", f"{win_rate:.1f}%")
            with col3:
                st.metric("Total Trades", len(closed_trades))

    except Exception as e:
        st.error(f"Error fetching trades: {e}")


def display_performance_chart():
    """Display performance chart."""
    st.subheader("Performance")

    db = get_db()

    try:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        trades = db.get_trades_by_date_range(start_date, end_date)

        closed_trades = [t for t in trades if t.pnl is not None and t.exit_time]

        if not closed_trades:
            st.info("No closed trades for performance chart")
            return

        sorted_trades = sorted(closed_trades, key=lambda x: x.exit_time)

        cumulative_pnl = []
        running_total = 0
        dates = []

        for t in sorted_trades:
            running_total += t.pnl
            cumulative_pnl.append(running_total)
            dates.append(t.exit_time)

        df = pd.DataFrame({
            "Date": dates,
            "Cumulative P&L": cumulative_pnl
        })

        fig = px.line(
            df,
            x="Date",
            y="Cumulative P&L",
            title="Cumulative P&L Over Time"
        )

        fig.add_hline(y=0, line_dash="dash", line_color="gray")

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error creating performance chart: {e}")


def display_strategy_performance():
    """Display strategy performance breakdown."""
    st.subheader("Strategy Performance")

    db = get_db()

    try:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        trades = db.get_trades_by_date_range(start_date, end_date)

        closed_trades = [t for t in trades if t.pnl is not None]

        if not closed_trades:
            st.info("No closed trades for strategy analysis")
            return

        strategy_stats = {}
        for t in closed_trades:
            if t.strategy not in strategy_stats:
                strategy_stats[t.strategy] = {"trades": 0, "wins": 0, "pnl": 0}

            strategy_stats[t.strategy]["trades"] += 1
            strategy_stats[t.strategy]["pnl"] += t.pnl
            if t.pnl > 0:
                strategy_stats[t.strategy]["wins"] += 1

        data = []
        for strategy, stats in strategy_stats.items():
            win_rate = (stats["wins"] / stats["trades"]) * 100 if stats["trades"] > 0 else 0
            data.append({
                "Strategy": strategy,
                "Trades": stats["trades"],
                "Wins": stats["wins"],
                "Win Rate": f"{win_rate:.1f}%",
                "Total P&L": f"${stats['pnl']:+,.2f}"
            })

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)

        pnl_data = pd.DataFrame([
            {"Strategy": s, "P&L": stats["pnl"]}
            for s, stats in strategy_stats.items()
        ])

        fig = px.bar(
            pnl_data,
            x="Strategy",
            y="P&L",
            title="P&L by Strategy",
            color="P&L",
            color_continuous_scale=["red", "green"]
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error analyzing strategies: {e}")


def main():
    """Main dashboard layout."""
    display_account_info()

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        display_positions()

    with col2:
        display_recent_trades()

    st.divider()

    display_performance_chart()

    st.divider()

    display_strategy_performance()

    st.sidebar.header("Controls")

    if st.sidebar.button("Refresh Data"):
        st.cache_resource.clear()
        st.rerun()

    st.sidebar.divider()

    st.sidebar.header("Bot Status")
    st.sidebar.info("Bot status monitoring coming soon")

    st.sidebar.divider()

    st.sidebar.caption("Stocker Trader Bot v1.0.0")
    st.sidebar.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
