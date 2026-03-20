# Crypto Market Making Research Stack

Event-driven backtesting framework for passive crypto market making on raw exchange event data.

This project reconstructs a local order book from level updates and trade prints, computes microstructure features, generates inventory-aware quotes, simulates passive fills with queue-aware logic, and produces metrics, logs, plots, and a PDF summary report.

## Highlights

- Local order book reconstruction from `INITIAL_SNAPSHOT`, `PLACE`, `CANCEL`, `FILL_UPDATE`, and `TRADE`
- Passive market-making logic with fair-value estimation, alpha signals, inventory skew, and participation filters
- Conservative execution simulator with queue-ahead tracking and passive-only fills
- Configurable backtests across different assets and time windows
- Built-in random search workflow for parameter tuning
- Automatic export of metrics, fill logs, quote logs, time series, charts, and summary PDFs

## Strategy Pipeline

1. Load raw market events from Parquet or CSV.
2. Rebuild top-of-book and depth state in sequence order.
3. Compute microstructure features such as spread, microprice, imbalance, flow, and volatility.
4. Estimate a reservation price from market state and short-horizon alpha.
5. Generate bid/ask quotes with inventory-aware skew and sizing.
6. Gate quoting when edge, volatility, or flow conditions are unfavorable.
7. Simulate passive fills using trade events plus queue-ahead depletion logic.
8. Track inventory, cash, realized PnL, MTM equity, liquidation equity, and drawdown.
9. Save diagnostics and performance artifacts under `output/`.

## Repository Layout

```text
mm_code/
  input/                  # raw market event files (ignored by git)
  output/                 # generated backtest artifacts (ignored by git)
  backtester.py           # event loop and portfolio accounting
  config.py               # default backtest configuration
  cons_config.py          # alternate configuration variant
  data_loader.py          # schema inspection and event streaming
  execution_simulator.py  # quote state, queue logic, fill simulation
  feature_engine.py       # rolling market microstructure features
  metrics.py              # summary performance metrics
  order_book.py           # local order book reconstruction
  plotting.py             # PNG charts and summary PDF
  quote_engine.py         # quote generation and gating
  random_search_v2.py     # discrete parameter search
  risk_manager.py         # inventory and size adjustments
  signal_engine.py        # fair value and alpha logic
  utils.py                # file and serialization helpers
  README.md
```

## Data Format

The loader expects exchange event data with these columns:

| Column | Description |
| --- | --- |
| `ts` | Event timestamp in milliseconds. Snapshot rows may be blank. |
| `seq` | Monotone sequence id. |
| `action` | `INITIAL_SNAPSHOT`, `PLACE`, `CANCEL`, `FILL_UPDATE`, or `TRADE`. |
| `side` | `BID`/`ASK` for book events, `BUY`/`SELL` for trade aggressor side. |
| `price` | Event price. |
| `amount` | Event size. |
| `remaining` | Remaining resting size after a book update. `TRADE` rows do not use it. |

Validation thresholds such as min/max price and amount are controlled in [`config.py`](./config.py).

## Core Components

- `data_loader.py`: reads Parquet or CSV input, validates rows, and streams normalized events
- `order_book.py`: maintains local bid/ask depth from event updates
- `feature_engine.py`: computes spread, microprice, imbalance, trade flow, book flow, and volatility windows
- `signal_engine.py`: converts features into a fair-value estimate and directional alpha
- `risk_manager.py`: adjusts quoting behavior based on inventory and soft limits
- `quote_engine.py`: sets quote prices and sizes, applies spread logic, edge filters, and unwind behavior
- `execution_simulator.py`: maintains working quotes and simulates passive fills using queue depletion
- `backtester.py`: coordinates the full event loop and records state, fills, quotes, and summary metrics
- `plotting.py`: renders plots plus a single-page PDF summary report
- `random_search_v2.py`: runs discrete parallel search over high-leverage strategy parameters

## Installation

Python 3.11+ is recommended.

```bash
pip install numpy pandas matplotlib pyarrow
```

`pyarrow` is required when reading Parquet input files.

## Quick Start

The default entrypoint uses [`config.py`](./config.py):

```bash
python main.py
```

The script will:

- load the configured market event file
- run the full market-making backtest
- save CSV, PNG, JSON, and PDF artifacts to `output/`
- print the summary metrics table to the console

## Configuration

The main parameters live in [`config.py`](./config.py). Important groups include:

- Data and logging: `RAW_EVENT_CSV`, `MAX_EVENTS`, `STATE_LOG_INTERVAL_MS`, `QUOTE_REFRESH_MS`
- Portfolio and fees: `INITIAL_CASH`, `MAKER_FEE_RATE`, `LIQUIDATION_FEE_RATE`
- Quoting and risk: `BASE_ORDER_SIZE`, `MAX_INVENTORY`, `INVENTORY_SKEW_TICKS`
- Spread logic: `MIN_HALF_SPREAD_TICKS`, `MARKET_SPREAD_MULTIPLIER`, `VOLATILITY_SPREAD_MULTIPLIER`
- Participation filters: `MIN_REQUIRED_EDGE_BUFFER_BPS`, `MAX_VOLATILITY_TO_QUOTE_BPS`, `MAX_FLOW_RATIO_TO_QUOTE`
- Quote persistence: `QUOTE_REPRICE_THRESHOLD_TICKS`, `QUOTE_MAX_AGE_MS`
- Inventory unwind: `INVENTORY_UNWIND_THRESHOLD_FRACTION`, `INVENTORY_UNWIND_SIZE_MULTIPLIER`

The repo also contains [`cons_config.py`](./cons_config.py) as an alternate parameter set for experimentation.

## Parameter Search

The project includes a discrete random-search runner for tuning a selected set of high-leverage parameters:

```bash
python random_search_v2.py --trials 40 --max-events 24000000 --workers 8
```

This search:

- samples from a fixed discrete space of quoting and inventory parameters
- runs trials in parallel with `ProcessPoolExecutor`
- writes ranked results to `output/random_search/random_search_results.csv`
- writes the current best parameter set to `output/random_search/best_params.json`

## Output Artifacts

Each backtest run writes a versioned set of artifacts to `output/`, including:

- `schema_summary*.json`
- `strategy_metrics*.csv`
- `state_timeseries*.csv`
- `fill_log*.csv`
- `quote_log*.csv`
- `cumulative_pnl*.png`
- `mid_total_pnl*.png`
- `realized_unrealized_pnl*.png`
- `inventory*.png`
- `drawdown*.png`
- `fill_activity*.png`
- `strategy_summary*.pdf`

## Metrics Tracked

The metrics export includes:

- final cash, inventory, and mid price
- mark-to-market and liquidation equity
- realized PnL
- max drawdown
- inventory utilization and turnover
- fill count and fill ratio
- total fees paid and traded notional
- equity return and return dispersion statistics
- processed event count

## Model Assumptions

- The strategy is passive-only. There is no taker execution path.
- True exchange queue position is unavailable, so queue-ahead is approximated from displayed depth changes.
- Snapshot rows are buffered until the first real-time timestamped event.
- MTM equity is marked at the mid price; liquidation equity uses the inside market plus liquidation fees.
- Results are highly sensitive to fee assumptions, quote persistence, and data quality.

## Current State of the Project

Compared with the earlier version of the project, the current codebase now supports:

- Parquet as a first-class input format
- richer output reporting, including dual-PnL plots and summary PDFs
- multiple config variants for research
- a scalable random-search tuner for parameter sweeps
- more explicit accounting for realized and unrealized PnL

## Notes

- Large raw datasets and generated output artifacts are intentionally git-ignored.
- This is a research backtester, not a live execution system.
- A positive short-window MTM result is not enough to validate a market-making strategy; inventory path, liquidation equity, fees, and fill quality matter more.
