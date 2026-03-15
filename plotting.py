import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot_pnl(state_df: pd.DataFrame, save_path) -> None:
    if state_df.empty:
        return
    time_axis = (state_df["timestampms"] - state_df["timestampms"].iloc[0]) / 1000.0 / 60.0
    plt.figure(figsize=(12, 5))
    plt.plot(time_axis, state_df["equity_mtm"], label="Equity MTM", linewidth=1.2)
    plt.plot(time_axis, state_df["equity_liquidation"], label="Equity Liquidation", linewidth=1.0, alpha=0.8)
    plt.xlabel("Minutes")
    plt.ylabel("Equity")
    plt.title("Market-Making Equity Curve")
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_inventory(state_df: pd.DataFrame, save_path) -> None:
    if state_df.empty:
        return
    time_axis = (state_df["timestampms"] - state_df["timestampms"].iloc[0]) / 1000.0 / 60.0
    plt.figure(figsize=(12, 4))
    plt.plot(time_axis, state_df["inventory"], color="#1f77b4", linewidth=1.0)
    plt.xlabel("Minutes")
    plt.ylabel("Inventory (BTC)")
    plt.title("Inventory Path")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_drawdown(state_df: pd.DataFrame, save_path) -> None:
    if state_df.empty:
        return
    equity = state_df["equity_mtm"].to_numpy(dtype=float)
    running_peak = np.maximum.accumulate(equity)
    drawdown = equity / np.maximum(running_peak, 1e-12) - 1.0
    time_axis = (state_df["timestampms"] - state_df["timestampms"].iloc[0]) / 1000.0 / 60.0
    plt.figure(figsize=(12, 4))
    plt.fill_between(time_axis, drawdown, 0.0, color="#d62728", alpha=0.35)
    plt.xlabel("Minutes")
    plt.ylabel("Drawdown")
    plt.title("Drawdown")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()


def plot_fill_activity(fill_df: pd.DataFrame, save_path) -> None:
    if fill_df.empty:
        return
    time_axis = (fill_df["timestampms"] - fill_df["timestampms"].iloc[0]) / 1000.0 / 60.0
    colors = np.where(fill_df["quote_side"].eq("BID"), "#2ca02c", "#ff7f0e")
    plt.figure(figsize=(12, 4))
    plt.scatter(time_axis, fill_df["fill_price"], s=12, c=colors, alpha=0.75)
    plt.xlabel("Minutes")
    plt.ylabel("Fill Price")
    plt.title("Fill Activity")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
