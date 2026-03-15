from pathlib import Path

import config
from backtester import MarketMakingBacktester
from plotting import plot_drawdown, plot_fill_activity, plot_inventory, plot_pnl
from utils import ensure_dir, json_dump


def main() -> None:
    ensure_dir(config.OUTPUT_DIR)

    print("Running market-making backtest")
    print(f"Input CSV: {config.RAW_EVENT_CSV}")
    print(f"Output dir: {config.OUTPUT_DIR}")
    print(f"Max events: {config.MAX_EVENTS}")

    backtester = MarketMakingBacktester(config)
    result = backtester.run()

    json_dump(result["schema_summary"], config.SCHEMA_SUMMARY_JSON)
    result["metrics_df"].to_csv(config.METRICS_CSV, index=False)
    result["state_df"].to_csv(config.STATE_TIMESERIES_CSV, index=False)
    result["fill_df"].to_csv(config.FILL_LOG_CSV, index=False)
    result["quote_df"].to_csv(config.QUOTE_LOG_CSV, index=False)

    plot_pnl(result["state_df"], config.PNL_PNG)
    plot_inventory(result["state_df"], config.INVENTORY_PNG)
    plot_drawdown(result["state_df"], config.DRAWDOWN_PNG)
    plot_fill_activity(result["fill_df"], config.FILL_ACTIVITY_PNG)

    print(result["metrics_df"].to_string(index=False))
    print("Saved outputs:")
    for path in [
        config.SCHEMA_SUMMARY_JSON,
        config.METRICS_CSV,
        config.STATE_TIMESERIES_CSV,
        config.FILL_LOG_CSV,
        config.QUOTE_LOG_CSV,
        config.PNL_PNG,
        config.INVENTORY_PNG,
        config.DRAWDOWN_PNG,
        config.FILL_ACTIVITY_PNG,
    ]:
        print(f" - {path}")


if __name__ == "__main__":
    main()
