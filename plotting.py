import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


REPORT_METRICS = [
    "hours_covered",
    "final_cash",
    "final_inventory",
    "realized_pnl",
    "max_drawdown",
    "mean_abs_inventory",
    "inventory_turnover",
    "fill_count",
    "fill_ratio",
    "total_fees_paid",
    "gross_traded_notional",
    "return_mean",
    "return_std",
    "return_ir",
]


def _time_axis_minutes(timestampms: pd.Series, origin_timestampms: int | float | None = None) -> np.ndarray:
    if origin_timestampms is None:
        origin_timestampms = timestampms.iloc[0]
    return ((timestampms - origin_timestampms) / 1000.0 / 60.0).to_numpy(dtype=float)


def _save_figure(fig: plt.Figure, save_path) -> None:
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)


def _compute_pnl_series(state_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    time_axis = _time_axis_minutes(state_df["timestampms"])
    pnl_mtm_series = (
        state_df["total_pnl_mtm"]
        if "total_pnl_mtm" in state_df.columns
        else state_df["equity_mtm"] - state_df["equity_mtm"].iloc[0]
    )
    pnl_liquidation_series = (
        state_df["total_pnl_liquidation"]
        if "total_pnl_liquidation" in state_df.columns
        else state_df["equity_liquidation"] - state_df["equity_liquidation"].iloc[0]
    )
    return (
        time_axis,
        pnl_mtm_series.to_numpy(dtype=float),
        pnl_liquidation_series.to_numpy(dtype=float),
    )


def _compute_minute_pnl_bars(state_df: pd.DataFrame, pnl_mtm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(pnl_mtm) == 0:
        return np.array([], dtype=float), np.array([], dtype=float)

    minute_bins = ((state_df["timestampms"] - state_df["timestampms"].iloc[0]) // 60_000).to_numpy(dtype=int)
    pnl_interval = np.diff(pnl_mtm, prepend=pnl_mtm[0])
    minute_pnl = pd.Series(pnl_interval).groupby(minute_bins).sum()
    bar_positions = minute_pnl.index.to_numpy(dtype=float) + 0.5
    return bar_positions, minute_pnl.to_numpy(dtype=float)


def _plot_pnl_ax(ax: plt.Axes, state_df: pd.DataFrame) -> None:
    time_axis, pnl_mtm, pnl_liquidation = _compute_pnl_series(state_df)
    bar_positions, minute_pnl = _compute_minute_pnl_bars(state_df, pnl_mtm)
    bar_colors = np.where(minute_pnl >= 0.0, "#2ca02c", "#d62728")

    ax.bar(bar_positions, minute_pnl, width=0.9, color=bar_colors, alpha=0.35, label="PnL per minute")
    ax.plot(time_axis, pnl_mtm, label="Cumulative PnL MTM", linewidth=1.2)
    ax.plot(time_axis, pnl_liquidation, label="Cumulative PnL Liquidation", linewidth=1.0, alpha=0.8)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("PnL")
    ax.set_title("Cumulative PnL")
    ax.legend(loc="best")


def _plot_mid_and_total_pnl_ax(ax: plt.Axes, state_df: pd.DataFrame) -> None:
    time_axis = _time_axis_minutes(state_df["timestampms"])
    mid = state_df["mid"].to_numpy(dtype=float)
    total_pnl = (
        state_df["total_pnl_mtm"].to_numpy(dtype=float)
        if "total_pnl_mtm" in state_df.columns
        else state_df["equity_mtm"].to_numpy(dtype=float) - state_df["equity_mtm"].iloc[0]
    )

    twin_ax = ax.twinx()
    ax.plot(time_axis, mid, color="#1f77b4", label="Mid Price", linewidth=1.2)
    twin_ax.plot(time_axis, total_pnl, color="#2ca02c", label="Total PnL", linewidth=1.2)

    ax.set_xlabel("Minutes")
    ax.set_ylabel("Mid Price")
    twin_ax.set_ylabel("Total PnL")
    ax.set_title("Mid Price and Total PnL")

    lines_1, labels_1 = ax.get_legend_handles_labels()
    lines_2, labels_2 = twin_ax.get_legend_handles_labels()
    ax.legend(lines_1 + lines_2, labels_1 + labels_2, loc="best")


def _plot_realized_unrealized_pnl_ax(ax: plt.Axes, state_df: pd.DataFrame) -> None:
    time_axis = _time_axis_minutes(state_df["timestampms"])
    realized = state_df["realized_pnl"].to_numpy(dtype=float)
    unrealized = (
        state_df["unrealized_pnl"].to_numpy(dtype=float)
        if "unrealized_pnl" in state_df.columns
        else (state_df["equity_mtm"] - state_df["equity_mtm"].iloc[0] - state_df["realized_pnl"]).to_numpy(dtype=float)
    )

    ax.plot(time_axis, realized, label="Realized PnL", linewidth=1.2)
    ax.plot(time_axis, unrealized, label="Unrealized PnL", linewidth=1.2, alpha=0.85)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("PnL")
    ax.set_title("Realized vs Unrealized PnL")
    ax.legend(loc="best")


def _plot_inventory_ax(ax: plt.Axes, state_df: pd.DataFrame) -> None:
    time_axis = _time_axis_minutes(state_df["timestampms"])
    ax.plot(time_axis, state_df["inventory"], color="#1f77b4", linewidth=1.0)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Inventory (BTC)")
    ax.set_title("Inventory Path")


def _plot_drawdown_ax(ax: plt.Axes, state_df: pd.DataFrame) -> None:
    equity = state_df["equity_mtm"].to_numpy(dtype=float)
    running_peak = np.maximum.accumulate(equity)
    drawdown = equity / np.maximum(running_peak, 1e-12) - 1.0
    time_axis = _time_axis_minutes(state_df["timestampms"])
    ax.fill_between(time_axis, drawdown, 0.0, color="#d62728", alpha=0.35)
    ax.set_xlabel("Minutes")
    ax.set_ylabel("Drawdown")
    ax.set_title("Drawdown")


def _plot_fill_activity_ax(ax: plt.Axes, fill_df: pd.DataFrame, state_df: pd.DataFrame | None = None) -> None:
    has_state = state_df is not None and not state_df.empty
    has_fills = not fill_df.empty

    if not has_state and not has_fills:
        ax.set_title("Fill Activity")
        ax.set_xlabel("Minutes")
        ax.set_ylabel("Fill Price")
        ax.text(0.5, 0.5, "No market data", ha="center", va="center", transform=ax.transAxes)
        return

    origin_timestampms = None
    if has_state:
        origin_timestampms = state_df["timestampms"].iloc[0]
    if has_fills:
        fill_origin = fill_df["timestampms"].iloc[0]
        origin_timestampms = fill_origin if origin_timestampms is None else min(origin_timestampms, fill_origin)

    if has_state:
        state_time_axis = _time_axis_minutes(state_df["timestampms"], origin_timestampms=origin_timestampms)
        ax.plot(
            state_time_axis,
            state_df["mid"],
            color="#1f77b4",
            linewidth=1.0,
            alpha=0.85,
            label="Mid Price",
            zorder=1,
        )

    if has_fills:
        time_axis = _time_axis_minutes(fill_df["timestampms"], origin_timestampms=origin_timestampms)
        bid_mask = fill_df["quote_side"].eq("BID")
        ask_mask = fill_df["quote_side"].eq("ASK")
        ax.scatter(
            time_axis[bid_mask],
            fill_df.loc[bid_mask, "fill_price"],
            s=42,
            c="#00a651",
            marker="^",
            alpha=0.95,
            edgecolors="white",
            linewidths=0.7,
            label="BID (buy)",
            zorder=3,
        )
        ax.scatter(
            time_axis[ask_mask],
            fill_df.loc[ask_mask, "fill_price"],
            s=42,
            c="#d62728",
            marker="v",
            alpha=0.95,
            edgecolors="white",
            linewidths=0.7,
            label="ASK (sell)",
            zorder=3,
        )
    else:
        ax.text(0.5, 0.5, "No fills", ha="center", va="center", transform=ax.transAxes)

    ax.set_xlabel("Minutes")
    ax.set_ylabel("Fill Price")
    ax.set_title("Fill Activity")
    ax.legend(loc="best")


def _format_metric_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (np.integer, int)):
        return f"{int(value):,}"
    if isinstance(value, (np.floating, float)):
        value = float(value)
        if value.is_integer():
            return f"{int(value):,}"
        magnitude = abs(value)
        if magnitude >= 1_000:
            formatted = f"{value:,.2f}"
        elif magnitude >= 1:
            formatted = f"{value:,.6f}"
        else:
            formatted = f"{value:.8f}"
        return formatted.rstrip("0").rstrip(".")
    return str(value)


def _plot_metrics_table_ax(ax: plt.Axes, metrics_csv_path) -> None:
    ax.axis("off")

    metrics_df = pd.read_csv(metrics_csv_path)
    if metrics_df.empty:
        ax.text(0.5, 0.5, "No metrics available", ha="center", va="center", transform=ax.transAxes)
        return

    metrics_row = metrics_df.iloc[0]
    metric_names = [name for name in REPORT_METRICS if name in metrics_row.index]
    metric_values = [_format_metric_value(metrics_row[name]) for name in metric_names]

    table = ax.table(
        cellText=[metric_names, metric_values],
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.4)

    for (row, _), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#e8eef7")
            cell.set_text_props(weight="bold")

    ax.set_title("Strategy Metrics", pad=10)


def plot_pnl(state_df: pd.DataFrame, save_path) -> None:
    """Plot cumulative PnL, with interval PnL bars aligned to time.

    Adds a bar layer showing PnL per interval (delta cumulative PnL) in green/red.

    Args:
        state_df (pd.DataFrame): State timeseries with columns:
            timestampms, total_pnl_mtm, total_pnl_liquidation
        save_path: Path to save PNG output

    Returns:
        None (saves plot to file)
    """
    if state_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    _plot_pnl_ax(ax, state_df)
    _save_figure(fig, save_path)


def plot_mid_and_total_pnl(state_df: pd.DataFrame, save_path) -> None:
    """Plot mid price and total PnL (realized + unrealized) over time.

    Args:
        state_df (pd.DataFrame): State timeseries with columns: timestampms, mid, total_pnl_mtm
        save_path: Path to save PNG output

    Returns:
        None (saves plot to file)
    """
    if state_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    _plot_mid_and_total_pnl_ax(ax, state_df)
    _save_figure(fig, save_path)


def plot_realized_unrealized_pnl(state_df: pd.DataFrame, save_path) -> None:
    """Plot realized and unrealized PnL over time.

    Unrealized PnL is computed as total MTM PnL minus realized PnL.

    Args:
        state_df (pd.DataFrame): State timeseries with columns:
            timestampms, realized_pnl, unrealized_pnl
        save_path: Path to save PNG output

    Returns:
        None (saves plot to file)
    """
    if state_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 5))
    _plot_realized_unrealized_pnl_ax(ax, state_df)
    _save_figure(fig, save_path)


def plot_inventory(state_df: pd.DataFrame, save_path) -> None:
    """
    Plot inventory position over time.
    
    Args:
        state_df (pd.DataFrame): State timeseries with columns: timestampms, inventory
        save_path: Path to save PNG output
        
    Returns:
        None (saves plot to file)
    """
    if state_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    _plot_inventory_ax(ax, state_df)
    _save_figure(fig, save_path)


def plot_drawdown(state_df: pd.DataFrame, save_path) -> None:
    """
    Plot equity drawdown from running peak.
    
    Drawdown = (equity / running_peak) - 1, shown as filled area.
    
    Args:
        state_df (pd.DataFrame): State timeseries with column: timestampms, equity_mtm
        save_path: Path to save PNG output
        
    Returns:
        None (saves plot to file)
    """
    if state_df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    _plot_drawdown_ax(ax, state_df)
    _save_figure(fig, save_path)


def plot_fill_activity(fill_df: pd.DataFrame, state_df: pd.DataFrame, save_path) -> None:
    """Plot fills together with the mid-price path.

    Colors fills by quote side with high-contrast markers layered above the
    state mid-price reference curve.

    Args:
        fill_df (pd.DataFrame): Fill log with columns: timestampms, fill_price, quote_side
        state_df (pd.DataFrame): State timeseries with columns: timestampms, mid
        save_path: Path to save PNG output

    Returns:
        None (saves plot to file)
    """
    fig, ax = plt.subplots(figsize=(12, 4))
    _plot_fill_activity_ax(ax, fill_df, state_df)
    _save_figure(fig, save_path)


def plot_summary_pdf(state_df: pd.DataFrame, fill_df: pd.DataFrame, metrics_csv_path, save_path) -> None:
    """Save a single-page PDF containing the six core plots and a metrics table."""
    if state_df.empty:
        return

    fig = plt.figure(figsize=(18, 20), constrained_layout=True)
    grid = fig.add_gridspec(nrows=4, ncols=2, height_ratios=[1.0, 1.0, 1.0, 0.42])

    _plot_pnl_ax(fig.add_subplot(grid[0, 0]), state_df)
    _plot_drawdown_ax(fig.add_subplot(grid[0, 1]), state_df)
    _plot_fill_activity_ax(fig.add_subplot(grid[1, 0]), fill_df, state_df)
    _plot_inventory_ax(fig.add_subplot(grid[1, 1]), state_df)
    _plot_mid_and_total_pnl_ax(fig.add_subplot(grid[2, 0]), state_df)
    _plot_realized_unrealized_pnl_ax(fig.add_subplot(grid[2, 1]), state_df)
    _plot_metrics_table_ax(fig.add_subplot(grid[3, :]), metrics_csv_path)

    fig.suptitle("Market-Making Backtest Summary", fontsize=16)
    fig.savefig(save_path, format="pdf")
    plt.close(fig)
