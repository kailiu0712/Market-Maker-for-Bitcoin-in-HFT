"""
Aggressive market-making configuration variant.

This is a more aggressive than baseline market-making configuration designed to
significantly increase fill frequency and traded notional while maintaining
profitability after fees and realistic adverse selection.

DESIGN RATIONALE:
-----------------
The baseline config (config.py) is too conservative, resulting in only ~1 fill per day.
The primary culprits are:

1. MIN_HALF_SPREAD_TICKS = 2.0 creates a baseline spread of ~80-100 bps per side,
   far wider than typical market spreads (10-30 bps in normal conditions).
   With a 7 bps fee per side, we need only 14 bps gross spread to break even,
   leaving up to 70+ bps of unnecessary buffer.

2. INVENTORY_SKEW_TICKS = 8.0 is extremely aggressive: even 0.01 inventory nudges
   quotes 0.08 ticks away from reservation price, pushing passive quotes further
   from where they fill.

3. MIN_REQUIRED_EDGE_BUFFER_BPS = 1.0 requires 15 bps total edge above fees,
   which when combined with 50+ bps wide baseline quotes, prevents fills.

4. QUOTE_REPRICE_THRESHOLD_TICKS = 2.0 causes frequent requotes that reset queue
   position, reducing fill probability from passive queue depth.

5. INVENTORY_UNWIND_THRESHOLD_FRACTION = 0.01 (ultra-tight at 1% of max) triggers
   aggressive one-sided behavior too early.

CHANGES IN THIS VARIANT:
------------------------
Aggressiveness lever: Tighten passive spreads, relax edge filters, reduce inventory
penalties, stabilize quotes for better queue priority.

Key parameter changes:
- Reduce MIN_HALF_SPREAD_TICKS: 2.0 -> 1.0
  Rationale: Baseline offset from market is fixed 2 ticks. Aggressive variant
  should be at market when conditions are normal. At $2500 ETH, 1 tick = $0.01 = 40 bps.
  Still provides 26 bps of edge above fee (40 bps - 7 bps - 7 bps), sufficient for
  cost coverage with modest profit margin. This is the LARGEST lever for fill rate.

- Reduce INVENTORY_SKEW_TICKS: 8.0 -> 3.5
  Rationale: Still provide inventory aversion (skew away from accumulating risk),
  but less severe. 3.5 ticks means 0.1 inventory offset moves reservation ~0.35 ticks,
  keeping quotes closer to fair market levels while signaling inventory preference.

- Reduce MIN_REQUIRED_EDGE_BUFFER_BPS: 1.0 -> 0.3
  Rationale: We need 14 bps to cover 2x 7 bps fee. Requiring only 0.3 bps extra buffer
  (14.3 bps total) means we quote when spread capture is barely profitable but realistic,
  not when we have 50+ bps of guaranteed edge. This prevents over-filtering.

- Increase MAX_VOLATILITY_TO_QUOTE_BPS: 20.0 -> 35.0
  Rationale: Current 20 bps is below typical crypto volatility even in calm periods.
  35 bps allows quoting through moderate volatility spikes without going black entirely.
  We still widen spreads when vol is high (via VOLATILITY_SPREAD_MULTIPLIER).

- Increase INVENTORY_UNWIND_THRESHOLD_FRACTION: 0.01 -> 0.06
  Rationale: Only aggressively unwind when inventory is 6% of max rather than 1%.
  This allows the strategy to build positions more naturally and participate two-sided
  in normal conditions. Still enforces unwind when positions become truly stressed.

- Increase QUOTE_REPRICE_THRESHOLD_TICKS: 2.0 -> 4.0
  Rationale: Only reprice if market moves 4 ticks instead of 2. This reduces quote
  churn and allows better queue position maintenance. Modern market conditions rarely
  see 4-tick moves without massive events, so this meaningfully stabilizes quotes.

- Increase MAX_FLOW_RATIO_TO_QUOTE: 0.08 -> 0.12
  Rationale: Relax one-sided flow gating. 0.12 still prevents quoting into extreme
  flow but allows participation during normal to moderately adverse flow conditions.

- Reduce MIN_DIRECTIONAL_ALPHA_BPS: 1.0 -> 0.5
  Rationale: Lower threshold for "strong directional signal" to unlock two-sided quotes
  when alpha is small. Allows more natural two-sided participation.

- Increase CALM_MARKET_VOL_THRESHOLD_BPS: 6.0 -> 10.0
  Rationale: Relax the definition of "calm market" to include more conditions.
  Makes spread tightening kick in (via CALM_MARKET_TIGHTENING_FACTOR = 0.65) more often,
  helping narrow spreads in typical conditions.

Parameters UNCHANGED from baseline (still sound):
- MAX_INVENTORY = 0.15: Risk limit is healthy
- INVENTORY_UNWIND_SIZE_MULTIPLIER = 1.35: Unwind aggressively when needed
- INVENTORY_UNWIND_JOIN_TOUCH = True: Join market when unwinding (good for execution)
- ALLOW_TWO_SIDED_WHEN_ALPHA_SMALL = True: Encourages two-sided participation
- Alpha components (IMBALANCE_ALPHA_BPS, TRADE_FLOW_ALPHA_BPS, etc.): Still provide
  good directional signals without over-skewing spreads
- Calm market tightening factor (0.65): Apply spread reduction in calm conditions
- All alpha clipping and volatility windows: No changes needed
- Fee rates: Fixed by exchange
"""

from pathlib import Path

# ==================== File Paths ====================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# Version tag for output files (identifies this as aggressive variant)
VERSION = '_0bp_12h_bitcoin'

# v2: 1.0 required_edge_bp + agg params + 7bp

# Raw market event data file
RAW_EVENT_CSV = INPUT_DIR / "0313to0317 bitcoin.parquet"

# ==================== Output File Paths ====================

SCHEMA_SUMMARY_JSON = OUTPUT_DIR / f"schema_summary{VERSION}.json"
METRICS_CSV = OUTPUT_DIR / f"strategy_metrics{VERSION}.csv"
STATE_TIMESERIES_CSV = OUTPUT_DIR / f"state_timeseries{VERSION}.csv"
FILL_LOG_CSV = OUTPUT_DIR / f"fill_log{VERSION}.csv"
QUOTE_LOG_CSV = OUTPUT_DIR / f"quote_log{VERSION}.csv"
PNL_PNG = OUTPUT_DIR / f"cumulative_pnl{VERSION}.png"
INVENTORY_PNG = OUTPUT_DIR / f"inventory{VERSION}.png"
DRAWDOWN_PNG = OUTPUT_DIR / f"drawdown{VERSION}.png"
FILL_ACTIVITY_PNG = OUTPUT_DIR / f"fill_activity{VERSION}.png"
SUMMARY_PDF = OUTPUT_DIR / f"strategy_summary{VERSION}.pdf"

# Additional plots
MID_TOTAL_PNL_PNG = OUTPUT_DIR / f"mid_total_pnl{VERSION}.png"
REALIZED_UNREALIZED_PNL_PNG = OUTPUT_DIR / f"realized_unrealized_pnl{VERSION}.png"

# ==================== Data Loading & Validation ====

MAX_EVENTS = 1_000_000     # 1000000 ~ 1h of data, adjust as needed for testing or full run
REPORT_EVERY_N_EVENTS = 100_000
MIN_VALID_PRICE = 1_000.0
MAX_VALID_PRICE = 2_000_000.0
MIN_VALID_AMOUNT = 1e-8
MAX_VALID_AMOUNT = 1_000.0
PRICE_TICK = 0.01

# ==================== Logging & Refresh Cadence ====================

STATE_LOG_INTERVAL_MS = 1_000
QUOTE_REFRESH_MS = 500

# ==================== Core Strategy Parameters ====================

MAKER_FEE_RATE = 0.0007
LIQUIDATION_FEE_RATE = 0.0007
INITIAL_CASH = 3_000.0
BASE_ORDER_SIZE = 0.03
MIN_ORDER_SIZE = 0.005
MAX_INVENTORY = 0.15
INVENTORY_TARGET = 0.0

# --- AGGRESSIVE CHANGE 1: Reduce inventory skew ---
# Baseline: 8.0 ticks - too aggressive, pushes quotes away from market
# Aggressive: 3.5 ticks - still provides inventory aversion but quotes stay closer to fair
INVENTORY_SKEW_TICKS = 1.0

INVENTORY_SOFT_LIMIT_FRACTION = 0.75

# Size adjustment factor
SIZE_SKEW_FACTOR = 0.75

# ==================== Alpha/Signal Generation ====================

MICROPRICE_WEIGHT = 0.7
IMBALANCE_ALPHA_BPS = 4.0
TRADE_FLOW_ALPHA_BPS = 4.0
BOOK_FLOW_ALPHA_BPS = 2.0
ALPHA_CLIP_BPS = 12.0

# ==================== Spread Calculation Parameters ====================

# --- AGGRESSIVE CHANGE 2: Reduce baseline half-spread ---
# Baseline: 2.0 ticks = ~80-100 bps at typical asset price.
# Too wide compared to 7 bps fee and typical market spreads of 10-30 bps.
# Aggressive: 1.0 ticks = ~40 bps at typical price = 26 bps edge after fees.
# Still profitable but competitive with market. LARGEST single lever for fill rate.
MIN_HALF_SPREAD_TICKS = 1.0

MARKET_SPREAD_MULTIPLIER = 1.25
VOLATILITY_SPREAD_MULTIPLIER = 1.0
FLOW_SPREAD_MULTIPLIER = 0.35
INVENTORY_SPREAD_MULTIPLIER = 0.75

# ==================== Quote Opportunity Gating ====================

# --- AGGRESSIVE CHANGE 3: Relax edge buffer requirement ---
# Baseline: 1.0 bps - adds to the 14 bps (2x fee) to total 15 bps required
# This is too strict when spreads are naturally narrow.
# Aggressive: 0.3 bps - barely above fee coverage, allows participation in tighter spreads
MIN_REQUIRED_EDGE_BUFFER_BPS = 0.0

# --- AGGRESSIVE CHANGE 4: Relax volatility gate ---
# Baseline: 20.0 bps - too conservative for crypto volatility.
# Blocks quoting during moderate vol spikes that are typical and profitable.
# Aggressive: 35.0 bps - allows quoting through normal to elevated volatility.
# Spreads widen automatically via VOLATILITY_SPREAD_MULTIPLIER when vol is high.
MAX_VOLATILITY_TO_QUOTE_BPS = 18.0

# --- AGGRESSIVE CHANGE 5: Relax flow ratio gate ---
# Baseline: 0.08 - blocks when abs(flow) / depth > 8%
# Aggressive: 0.12 - allows quoting in moderately adverse flow conditions
MAX_FLOW_RATIO_TO_QUOTE = 0.04

# --- AGGRESSIVE CHANGE 6: Lower directional alpha threshold ---
# Baseline: 1.0 bps - higher bar to unlock two-sided quoting when alpha is weak
# Aggressive: 0.5 bps - more willing to participate two-sided in smaller alpha regimes
MIN_DIRECTIONAL_ALPHA_BPS = 0.5

# When alpha is weak, allow two-sided quotes (controlled by other logic)
ALLOW_TWO_SIDED_WHEN_ALPHA_SMALL = True

# ==================== Quote Persistence & Inventory Management ====================

# --- AGGRESSIVE CHANGE 7: Increase quote reprice hysteresis ---
# Baseline: 2.0 ticks - reprice if market moves 2 ticks, resets queue position often
# Aggressive: 4.0 ticks - only reprice on 4 tick moves. Keeps quotes in queue longer,
# improving passive fill probability. Markets rarely move 4 ticks without major events.
QUOTE_REPRICE_THRESHOLD_TICKS = 6.0

QUOTE_MAX_AGE_MS = 1_000

# --- AGGRESSIVE CHANGE 8: Relax inventory unwind threshold ---
# Baseline: 0.01 (1% of max) - triggers aggressive unwind too early
# Aggressive: 0.06 (6% of max) - allows building positions more naturally.
# Still forces unwind when positions become stressed.
INVENTORY_UNWIND_THRESHOLD_FRACTION = 0.15

INVENTORY_UNWIND_JOIN_TOUCH = True
INVENTORY_UNWIND_SIZE_MULTIPLIER = 1.35

# --- AGGRESSIVE CHANGE 9: Relax calm market threshold ---
# Baseline: 6.0 bps - tight definition restricts when spread tightening applies
# Aggressive: 10.0 bps - looser definition applies spread tightening more often
CALM_MARKET_VOL_THRESHOLD_BPS = 10.0

CALM_MARKET_SPREAD_THRESHOLD_BPS = 1.2
CALM_MARKET_TIGHTENING_FACTOR = 0.65

# ==================== Feature Calculation Windows ====================

VOLATILITY_WINDOW_MS = 5_000
FLOW_WINDOW_MS = 5_000
BOOK_FLOW_WINDOW_MS = 5_000
LONG_VOL_WINDOW_MS = 60_000

# ==================== Fill Execution Model ====================

TOUCH_FILL_FRACTION = 0.35
IMPROVED_PRICE_FILL_FRACTION = 0.85
MIN_FILL_SIZE = 1e-6
