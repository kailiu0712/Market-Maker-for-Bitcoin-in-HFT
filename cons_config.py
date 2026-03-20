"""
Configuration module for the market-making backtest system.

This module defines all configuration parameters for the market-making strategy,
including file paths, data validation thresholds, and trading parameters.
"""

from pathlib import Path

# ==================== File Paths ====================

BASE_DIR = Path(__file__).resolve().parent
# ==================== Input/Output Directories ====================

INPUT_DIR = BASE_DIR / "input"  # Directory containing input market data files
OUTPUT_DIR = BASE_DIR / "output"  # Directory for all backtest output files

# Version tag for output files (included in filenames for easy identification)
VERSION = '_7bp_72h_0.005_4.0_eth'

# Raw market event data file (Parquet format with OHLC and order book data)
RAW_EVENT_CSV = INPUT_DIR / "0313to0315 eth.parquet"

# ==================== Output File Paths ====================

# JSON schema summary describing the structure and statistics of input data
SCHEMA_SUMMARY_JSON = OUTPUT_DIR / f"schema_summary{VERSION}.json"

# CSV with strategy performance metrics (sharpe ratio, max drawdown, PnL, etc.)
METRICS_CSV = OUTPUT_DIR / f"strategy_metrics{VERSION}.csv"

# CSV with state timeseries (inventory, cash, equity, mid price, etc. over time)
STATE_TIMESERIES_CSV = OUTPUT_DIR / f"state_timeseries{VERSION}.csv"

# CSV with detailed fill log (all fills executed: side, price, size, fees)
FILL_LOG_CSV = OUTPUT_DIR / f"fill_log{VERSION}.csv"

# CSV with quote updates (posted quotes, reprices, cancellations)
QUOTE_LOG_CSV = OUTPUT_DIR / f"quote_log{VERSION}.csv"

# PNG plot of cumulative PnL and equity curve over time
PNL_PNG = OUTPUT_DIR / f"cumulative_pnl{VERSION}.png"

# PNG plot of inventory position over time
INVENTORY_PNG = OUTPUT_DIR / f"inventory{VERSION}.png"

# PNG plot of equity drawdown from running peak
DRAWDOWN_PNG = OUTPUT_DIR / f"drawdown{VERSION}.png"

# PNG scatter plot of all fills (price vs time, colored by side)
FILL_ACTIVITY_PNG = OUTPUT_DIR / f"fill_activity{VERSION}.png"

# ==================== Data Loading & Validation ====================

# Maximum number of events to process from input file (limits test duration)
MAX_EVENTS = 80_000_000

# Frequency of progress logging while loading events
REPORT_EVERY_N_EVENTS = 100_000

# Min valid price threshold (prices below this are filtered out)
MIN_VALID_PRICE = 1_000.0

# Max valid price threshold (prices above this are filtered out)
MAX_VALID_PRICE = 2_000_000.0

# Min valid order amount threshold (amounts below this are filtered out)
MIN_VALID_AMOUNT = 1e-8

# Max valid order amount threshold (amounts above this are filtered out)
MAX_VALID_AMOUNT = 1_000.0

# Price minimum increment (grid size for rounding prices)
PRICE_TICK = 0.01

# ==================== Logging & Refresh Cadence ====================

# Interval (ms) for logging state snapshots (inventory, cash, equity, etc.)
STATE_LOG_INTERVAL_MS = 1_000

# Interval (ms) for refreshing quotes (minimum time between quote updates)
QUOTE_REFRESH_MS = 500

# ==================== Core Strategy Parameters ====================

# Fee rate for maker (our) orders (as a decimal: 0.07%)
MAKER_FEE_RATE = 0.0007

# Fee rate applied to liquidation of inventory at end of backtest
LIQUIDATION_FEE_RATE = 0.0007

# Starting cash balance for the strategy
INITIAL_CASH = 20_000.0

# Default order size for market-making quotes (in base asset)
BASE_ORDER_SIZE = 0.01

# Minimum order size (orders smaller than this will be rounded to zero)
MIN_ORDER_SIZE = 0.005

# Maximum allowed absolute inventory position (in base asset)
MAX_INVENTORY = 0.15

# Target inventory level (strategy tries to revert to this)
INVENTORY_TARGET = 0.0

# Inventory-based price adjustment (ticks moved per unit of inventory)
INVENTORY_SKEW_TICKS = 8.0

# At this inventory fraction, switch to reduce-only (avoid exceeding max_inventory)
INVENTORY_SOFT_LIMIT_FRACTION = 0.75

# Factor controlling how order sizes react to inventory (0-1.5 multiplier range)
SIZE_SKEW_FACTOR = 0.75

# ==================== Alpha/Signal Generation ====================

# Weight for microprice vs mid-price in fair price calculation (0-1)
MICROPRICE_WEIGHT = 0.7

# Order book imbalance alpha contribution (basis points)
IMABALANCE_ALPHA_BPS = 4.0

# Trade flow alpha contribution (basis points)
TRADE_FLOW_ALPHA_BPS = 4.0

# Book flow alpha contribution (basis points)
BOOK_FLOW_ALPHA_BPS = 2.0

# Maximum alpha clipping magnitude (prevents extreme adjustments)
ALPHA_CLIP_BPS = 12.0

# ==================== Spread Calculation Parameters ====================

# Minimum half-spread (distance from reservation price to quotes, in ticks)
MIN_HALF_SPREAD_TICKS = 2.0

# Market spread multiplier (wider spreads when market is wide)
MARKET_SPREAD_MULTIPLIER = 1.25

# Volatility multiplier (wider spreads in volatile markets)
VOLATILITY_SPREAD_MULTIPLIER = 2.0

# Flow (alpha) multiplier (narrower spreads when we have directional signal)
FLOW_SPREAD_MULTIPLIER = 0.35

# Inventory multiplier (wider spreads when inventory is extreme)
INVENTORY_SPREAD_MULTIPLIER = 0.75

# ==================== Quote Opportunity Gating ====================

# Minimum edge required to quote (prevents quoting when edge is negative)
MIN_REQUIRED_EDGE_BUFFER_BPS = 1.0

# Max volatility to quote (disable quotes if vol exceeds this threshold)
MAX_VOLATILITY_TO_QUOTE_BPS = 20.0

# Max flow ratio to quote (disable quotes if flow is too large)
MAX_FLOW_RATIO_TO_QUOTE = 0.08

# Minimum directional alpha needed to quote (prevents one-sided quotes)
MIN_DIRECTIONAL_ALPHA_BPS = 1.0

# Allow two-sided quotes when alpha is small (prevents one-sided-only behavior)
ALLOW_TWO_SIDED_WHEN_ALPHA_SMALL = True

# ==================== Quote Persistence & Inventory Management ====================

# Price move threshold before reprice (if move < this, keep existing quote)
QUOTE_REPRICE_THRESHOLD_TICKS = 2.0

# Max age of quote before forced refresh (milliseconds)
QUOTE_MAX_AGE_MS = 3_000

# Inventory threshold for unwinding (as fraction of max_inventory)
INVENTORY_UNWIND_THRESHOLD_FRACTION = 0.01

# Unwind at touch of market (vs at reservation price)
INVENTORY_UNWIND_JOIN_TOUCH = True

# Size multiplier for inventory unwinding (increase size to reduce inventory faster)
INVENTORY_UNWIND_SIZE_MULTIPLIER = 1.35

# Volatility threshold for calm market (tightens spreads in calm conditions)
CALM_MARKET_VOL_THRESHOLD_BPS = 6.0

# Spread threshold for calm market (as basis points of price)
CALM_MARKET_SPREAD_THRESHOLD_BPS = 1.2

# Spread tightening factor in calm market (multiply spread by this)
CALM_MARKET_TIGHTENING_FACTOR = 0.65

# ==================== Feature Calculation Windows ====================

# Rolling window duration for short-term volatility (milliseconds)
VOLATILITY_WINDOW_MS = 5_000

# Rolling window duration for trade flow signals (milliseconds)
FLOW_WINDOW_MS = 5_000

# Rolling window duration for order book flow (milliseconds)
BOOK_FLOW_WINDOW_MS = 5_000

# Rolling window duration for long-term volatility (milliseconds)
LONG_VOL_WINDOW_MS = 60_000

# ==================== Fill Execution Model ====================

# Probability of fill at touch of market (our posted quotes get hit)
TOUCH_FILL_FRACTION = 0.35

# Probability of fill at improved price (better than our quote)
IMPROVED_PRICE_FILL_FRACTION = 0.85

# Minimum fill size below which fills are ignored
MIN_FILL_SIZE = 1e-6
