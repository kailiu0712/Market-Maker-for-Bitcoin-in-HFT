import numpy as np
import pandas as pd


def build_metrics(state_df: pd.DataFrame, fill_df: pd.DataFrame, quote_df: pd.DataFrame, maker_fee_rate: float) -> pd.DataFrame:
    if state_df.empty:
        return pd.DataFrame([{"error": "state_df is empty"}])

    equity = state_df["equity_mtm"].to_numpy(dtype=float)
    running_peak = np.maximum.accumulate(equity)
    drawdown = equity / np.maximum(running_peak, 1e-12) - 1.0
    returns = np.diff(equity) / np.maximum(equity[:-1], 1e-12) if len(equity) >= 2 else np.zeros(0, dtype=float)

    metrics = {
        "rows": float(len(state_df)),
        "start_timestampms": float(state_df["timestampms"].iloc[0]),
        "end_timestampms": float(state_df["timestampms"].iloc[-1]),
        "hours_covered": float((state_df["timestampms"].iloc[-1] - state_df["timestampms"].iloc[0]) / 1000.0 / 3600.0),
        "final_cash": float(state_df["cash"].iloc[-1]),
        "final_inventory": float(state_df["inventory"].iloc[-1]),
        "final_mid": float(state_df["mid"].iloc[-1]),
        "final_equity_mtm": float(state_df["equity_mtm"].iloc[-1]),
        "final_equity_liquidation": float(state_df["equity_liquidation"].iloc[-1]),
        "realized_pnl": float(state_df["realized_pnl"].iloc[-1]),
        "max_drawdown": float(np.min(drawdown)),
        "mean_abs_inventory": float(np.mean(np.abs(state_df["inventory"]))),
        "max_abs_inventory": float(np.max(np.abs(state_df["inventory"]))),
        "inventory_turnover": float(fill_df["fill_size"].sum()) if not fill_df.empty else 0.0,
        "quote_updates": float(len(quote_df)),
        "fill_count": float(len(fill_df)),
        "maker_fee_rate": float(maker_fee_rate),
        "fill_ratio": float(len(fill_df) / max(len(quote_df), 1)),
        "total_fees_paid": float(fill_df["fee"].sum()) if "fee" in fill_df.columns and not fill_df.empty else 0.0,
        "gross_traded_notional": float(fill_df["notional"].sum()) if "notional" in fill_df.columns and not fill_df.empty else 0.0,
        "equity_return": float(state_df["equity_mtm"].iloc[-1] / max(state_df["equity_mtm"].iloc[0], 1e-12) - 1.0),
        "return_mean": float(np.mean(returns)) if len(returns) else 0.0,
        "return_std": float(np.std(returns)) if len(returns) else 0.0,
        "return_ir": float(np.mean(returns) / (np.std(returns) + 1e-12)) if len(returns) else 0.0,
    }
    return pd.DataFrame([metrics])
