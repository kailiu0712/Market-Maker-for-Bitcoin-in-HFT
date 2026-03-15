# Bitcoin HFT Market Making Research Stack

Event-driven, selective passive market-making research framework for raw Bitcoin microstructure data.

This project reconstructs a local order book from exchange event data, computes microstructure features, generates inventory-aware quotes, simulates passive fills with a conservative queue model, and produces backtest metrics, logs, and plots.

## Overview

The strategy is designed as a realistic baseline for crypto market making rather than a toy spread-capture example.

Core ideas:

- Rebuild the book from `INITIAL_SNAPSHOT`, `PLACE`, `CANCEL`, and `FILL_UPDATE`
- Estimate fair value from midprice, microprice, imbalance, and short-horizon order flow
- Generate passive bid/ask quotes around a reservation price
- Skew quotes and sizes based on inventory
- Filter participation when expected edge does not clear fees and basic toxicity checks
- Simulate fills conservatively using trade prints plus queue-ahead approximation

## Repository Structure

```text
mm_code/
  input/
    gemini_24h_analysis.csv
  output/
    ...
  backtester.py
  config.py
  data_loader.py
  execution_simulator.py
  feature_engine.py
  main.py
  metrics.py
  order_book.py
  plotting.py
  quote_engine.py
  risk_manager.py
  signal_engine.py
  utils.py
  README.md
```

Module summary:

- `config.py`: paths, filters, strategy settings, and simulation assumptions
- `data_loader.py`: schema inspection, normalization, and event streaming
- `order_book.py`: local order book reconstruction
- `feature_engine.py`: rolling microstructure features
- `signal_engine.py`: fair value and alpha adjustment
- `risk_manager.py`: inventory limits and skew logic
- `quote_engine.py`: quote placement, edge gating, calm-market tightening, and inventory unwind logic
- `execution_simulator.py`: working quote state, queue-ahead handling, and fill simulation
- `backtester.py`: event loop, state updates, PnL accounting, and output assembly
- `metrics.py`: summary performance metrics
- `plotting.py`: saved charts
- `main.py`: entrypoint

## Data Schema

The raw CSV is inferred directly from `input/gemini_24h_analysis.csv`.

Observed columns:

- `ts`: event timestamp in milliseconds; blank for `INITIAL_SNAPSHOT`
- `seq`: monotone sequence id
- `action`: `INITIAL_SNAPSHOT`, `PLACE`, `CANCEL`, `FILL_UPDATE`, `TRADE`
- `side`:
  - `BID` / `ASK` for book updates
  - `BUY` / `SELL` for trade aggressor side
- `price`: event price
- `amount`: event size
- `remaining`: remaining size after book update; `N/A` for `TRADE`

The code also filters clearly invalid rows using configurable price/size bounds in [`config.py`](./config.py).

## Strategy Logic

### 1. Book Reconstruction

The local order book is updated sequentially from the event stream. `INITIAL_SNAPSHOT` seeds the initial state, and subsequent `PLACE`, `CANCEL`, and `FILL_UPDATE` rows modify depth at each level.

### 2. Feature Construction

The strategy computes:

- midprice
- spread
- microprice
- top-of-book and top-5 depth
- level-1 and level-5 imbalance
- recent trade flow
- recent book flow
- short-horizon and longer-horizon volatility

### 3. Fair Price and Alpha

Fair value is a blend of midprice and microprice, then adjusted by:

- imbalance signal
- recent signed trade flow
- recent signed book flow

This produces a small directional alpha in basis points.

### 4. Inventory-Aware Quoting

Quotes are generated around a reservation price:

- inventory shifts the reservation price away from accumulating more risk
- quote width expands with spread, volatility, flow pressure, and inventory stress
- when inventory is nonzero, the strategy can bias toward unwind on the flattening side

### 5. Participation Filters

The strategy does not quote blindly. It can refuse or reduce quoting when:

- expected edge does not clear fees and buffer
- short-horizon volatility is too high
- flow pressure is too one-sided
- inventory is already stressed

### 6. Fill Simulation

Fills are simulated passively only:

- trades are treated as aggressive prints
- a quote joining an existing level starts behind displayed size at that price
- `CANCEL` and `FILL_UPDATE` at that same price reduce queue-ahead
- a fill can occur when a trade reaches the quote price or trades through it

This is intentionally conservative and does not assume perfect queue priority.

## Simulation Assumptions

Important assumptions:

- No order IDs or true queue position are available
- No hidden liquidity modeling
- No taker execution; this is passive market making in spirit
- Mark-to-market equity uses the midprice
- Liquidation equity uses the inside market plus configured liquidation fee
- Results are path-dependent and sensitive to fee assumptions

## Current Research Focus

The current strategy emphasizes:

- selective participation over constant quoting
- stronger inventory unwind behavior
- reduced quote churn through hysteresis and maximum quote age
- realistic fee-aware edge filtering

This makes it a better research framework for studying realized passive trading quality, not just MTM noise.

## Configuration

Key parameters live in [`config.py`](./config.py).

Examples:

- `MAKER_FEE_RATE`
- `INITIAL_CASH`
- `BASE_ORDER_SIZE`
- `MAX_INVENTORY`
- `QUOTE_REFRESH_MS`
- `QUOTE_REPRICE_THRESHOLD_TICKS`
- `MIN_REQUIRED_EDGE_BUFFER_BPS`
- `INVENTORY_UNWIND_THRESHOLD_FRACTION`

By default, the backtest runs on the first `1_000_000` events for faster iteration:

```python
MAX_EVENTS = 1_000_000
```

Set `MAX_EVENTS = None` to process the full file.

## How To Run

From the repository root:

```powershell
python mm_code/main.py
```

## Outputs

The backtest saves the following files under `mm_code/output/`:

- `schema_summary.json`
- `strategy_metrics.csv`
- `state_timeseries.csv`
- `fill_log.csv`
- `quote_log.csv`
- `cumulative_pnl.png`
- `inventory_path.png`
- `drawdown.png`
- `fill_activity.png`

## Metric Definitions

- `final_equity_mtm`: cash plus inventory marked at midprice
- `final_equity_liquidation`: cash plus inventory marked to executable inside price minus liquidation fee
- `realized_pnl`: realized PnL from completed inventory reductions
- `inventory_turnover`: total filled size
- `fill_ratio`: fills divided by quote update count

## Notes

- A small positive MTM result on a short slice is not strong evidence of repeatable profitability
- For this type of strategy, realized PnL, round trips, liquidation equity, and fee efficiency matter more than raw MTM alone
- With crypto microstructure, fee assumptions can dominate the economics of passive market making
