<<<<<<< HEAD
<<<<<<< HEAD
# Market-Making Research Stack

This folder contains a modular baseline market-making framework built directly on the raw event stream in `mm_code/input/gemini_24h_analysis.csv`.

## Folder Structure

- `config.py`: paths, data filters, strategy parameters, fill-model assumptions
- `main.py`: entrypoint that runs the backtest and saves outputs
- `data_loader.py`: raw CSV schema inspection, normalization, and streaming event loader
- `order_book.py`: local book reconstruction from snapshot and delta events
- `feature_engine.py`: rolling microstructure features from the evolving book and event flow
- `signal_engine.py`: fair-price and alpha adjustment logic
- `quote_engine.py`: reservation price and inventory-aware bid/ask generation
- `risk_manager.py`: inventory limit and size-skew controls
- `execution_simulator.py`: passive quote state, queue-ahead approximation, and fill simulation
- `backtester.py`: event-driven backtest loop, PnL state, logging, and result assembly
- `metrics.py`: summary metrics
- `plotting.py`: saved plots
- `output/`: generated metrics, time series, logs, and plots

## Inferred Data Schema

The raw CSV is interpreted as:

- `ts`: event timestamp in milliseconds; blank for `INITIAL_SNAPSHOT`
- `seq`: monotone sequence id
- `action`: one of `INITIAL_SNAPSHOT`, `PLACE`, `CANCEL`, `FILL_UPDATE`, `TRADE`
- `side`:
  - `BID` / `ASK` for book updates
  - `BUY` / `SELL` for trade aggressor side
- `price`: event price level
- `amount`: event size
- `remaining`: resting size after the event for book updates; `N/A` for trades

## Simulation Assumptions

- The local order book is reconstructed from `INITIAL_SNAPSHOT` plus `PLACE/CANCEL/FILL_UPDATE`.
- `TRADE` is treated as the aggressive print and is processed before the following `FILL_UPDATE`.
- Passive fills are simulated only on `TRADE` events.
- Exact queue position is not available, so fills use a conservative queue-ahead approximation:
  - joining an existing level starts behind displayed size at that price
  - `CANCEL/FILL_UPDATE` at our price reduce queue-ahead
  - when a trade prints at our price, only the portion beyond queue-ahead is eligible to fill
  - when our quote is better than the printed trade price, fill participation is capped by a conservative fraction
- The strategy is passive-only and inventory-aware.
- Rows with impossible prices or amounts are filtered before simulation.

## Strategy Design

- Fair price blends mid and microprice and then adds a small alpha from imbalance, trade flow, and book flow.
- Reservation price shifts away from fair value as inventory drifts from target.
- Quote width expands with market spread, short-term volatility, order-flow pressure, and inventory stress.
- Inventory control reduces same-direction quoting and can switch to reduce-only behavior near the soft limit.

## Running the Backtest

From the repository root:

```powershell
python mm_code/main.py
```

By default the research run is capped at `MAX_EVENTS = 1_000_000` in `config.py` so iteration stays practical. Set `MAX_EVENTS = None` if you want to process the full 24-hour file.

## Generated Outputs

- `schema_summary.json`
- `strategy_metrics.csv`
- `state_timeseries.csv`
- `fill_log.csv`
- `quote_log.csv`
- `cumulative_pnl.png`
- `inventory_path.png`
- `drawdown.png`
- `fill_activity.png`
=======
# Market-Maker-for-Bitcoin-in-HFT
>>>>>>> b370b149c02b713a45e52d4b1f73c6a8245cabf4
=======
# Market-Maker-for-Bitcoin-in-HFT
>>>>>>> b370b149c02b713a45e52d4b1f73c6a8245cabf4
