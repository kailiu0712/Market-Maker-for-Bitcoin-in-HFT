"""
Discrete random search for the Bitcoin market-making strategy.

Tuning philosophy:
- Spend the 50-trial budget on the economic control surface that most directly
  changes fill rate, quote competitiveness, inventory pressure, and adverse
  selection protection.
- Keep the search discrete rather than continuous. In this setting the model is
  noisy, path-dependent, and easy to overfit; a compact set of plausible values
  is more robust than broad continuous sampling.
- Avoid tuning simulator-only assumptions such as fill fractions. Those change
  the backtest's execution model, not the strategy's behavior, and would risk
  fitting the search to the simulator instead of the market-making logic.

Implementation notes:
- This module is intentionally self-contained and does not rely on any existing
  search utilities.
- It uses the existing `MarketMakingBacktester` as the execution engine, but
  overrides parquet/CSV event loading in-process so the event cap of
  10,000,000 is enforced without materializing the full input file.
- Output files are written to `output/random_search` by default.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
import traceback
from collections import Counter, OrderedDict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

import numpy as np
import pandas as pd

import backtester as backtester_module
import config
from backtester import MarketMakingBacktester
from data_loader import BOOK_ACTIONS, MarketEvent
from utils import ensure_dir

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - environment dependent
    pq = None


DEFAULT_TRIALS = 40
DEFAULT_MAX_EVENTS = 24000000
DEFAULT_RANDOM_SEED = 20260319
DEFAULT_WORKERS = 8
DEFAULT_OUTPUT_DIR = config.OUTPUT_DIR / "random_search"
SCHEMA_SAMPLE_ROWS = 200_000
CSV_BATCH_SIZE = 100_000
PARQUET_BATCH_SIZE = 100_000
VERY_POOR_SCORE = -1e18
EVENT_COLUMNS = ("ts", "seq", "action", "side", "price", "amount", "remaining")


# Search only the highest-leverage quoting and risk parameters. We intentionally
# do not tune MIN_HALF_SPREAD_TICKS here because the BTC dataset uses a $0.01
# tick, making the floor economically tiny relative to the volatility and alpha
# spread terms in the current model. That budget is better spent elsewhere.
SEARCH_SPACE: "OrderedDict[str, tuple[Any, ...]]" = OrderedDict(
    [
        # Dominant adverse-selection / competitiveness lever in the half-spread formula.
        ("VOLATILITY_SPREAD_MULTIPLIER", (0.75, 1.0, 1.35, 1.75, 2.25)),
        # Dynamic widening when alpha/flow is strong; protects against being picked off.
        ("FLOW_SPREAD_MULTIPLIER", (0.10, 0.20, 0.35, 0.50, 0.75)),
        # Extra edge above one-side maker fee; modest values avoid over-filtering.
        ("MIN_REQUIRED_EDGE_BUFFER_BPS", (0.00, 0.15, 0.30, 0.60, 1.00)),
        # Stay active through more crypto volatility or go dark earlier.
        ("MAX_VOLATILITY_TO_QUOTE_BPS", (12.0, 18.0, 25.0, 35.0, 50.0)),
        # Gate extreme one-sided flow; a primary fill-vs-adverse-selection tradeoff.
        ("MAX_FLOW_RATIO_TO_QUOTE", (0.04, 0.06, 0.08, 0.12, 0.16)),
        # Reservation-price skew for inventory aversion, from mild to firm.
        ("INVENTORY_SKEW_TICKS", (1.0, 2.0, 3.5, 5.0, 7.5)),
        # When to flip into one-sided inventory unwind mode.
        ("INVENTORY_UNWIND_THRESHOLD_FRACTION", (0.02, 0.04, 0.06, 0.10, 0.15)),
        # Queue-position retention versus quote staleness.
        ("QUOTE_REPRICE_THRESHOLD_TICKS", (1.0, 2.0, 4.0, 6.0, 8.0)),
        # Hard staleness bound for passive quotes.
        ("QUOTE_MAX_AGE_MS", (1_000, 2_000, 3_000, 5_000, 8_000)),
        # Direct volume/risk lever; small set around the current production size.
        ("BASE_ORDER_SIZE", (0.005, 0.010, 0.015, 0.020, 0.030)),
    ]
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run discrete random search for the market-making strategy.")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS, help="Number of random configurations to evaluate.")
    parser.add_argument(
        "--max-events",
        type=int,
        default=DEFAULT_MAX_EVENTS,
        help="Hard cap on the number of market events processed per trial.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Reproducible random seed.")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Number of worker processes for trial-level parallelism.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for search results.",
    )
    return parser.parse_args()


def _is_missing(value: object) -> bool:
    """Return True when a scalar value should be treated as missing."""
    if value is None:
        return True
    if isinstance(value, str):
        text = value.strip()
        return text == "" or text.upper() == "N/A"
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _parse_float(value: object) -> Optional[float]:
    """Parse a scalar into float, returning None on invalid inputs."""
    if _is_missing(value):
        return None
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).strip())
        except Exception:
            return None


def _parse_int(value: object) -> Optional[int]:
    """Parse a scalar into int, returning None on invalid inputs."""
    parsed = _parse_float(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except Exception:
        return None


def _parse_text(value: object) -> str:
    """Normalize a text field to upper-case stripped text."""
    if _is_missing(value):
        return ""
    return str(value).upper().strip()


def _normalize_market_event(
    *,
    ts_value: object,
    seq_value: object,
    action_value: object,
    side_value: object,
    price_value: object,
    amount_value: object,
    remaining_value: object,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
) -> Optional[MarketEvent]:
    """Convert raw scalar values into a validated MarketEvent."""
    action = _parse_text(action_value)
    side = _parse_text(side_value)
    seq = _parse_int(seq_value)
    price = _parse_float(price_value)
    amount = _parse_float(amount_value)
    remaining = _parse_float(remaining_value)
    timestampms = _parse_int(ts_value)

    if seq is None or not action or not side:
        return None
    if price is None or price < min_valid_price or price > max_valid_price:
        return None
    if amount is None or amount < min_valid_amount or amount > max_valid_amount:
        return None
    if action == "TRADE" and side not in {"BUY", "SELL"}:
        return None
    if action != "TRADE" and side not in {"BID", "ASK"}:
        return None
    if action in BOOK_ACTIONS and remaining is None:
        return None
    if action == "TRADE":
        remaining = None
    if timestampms is None:
        timestampms = -1

    return MarketEvent(
        timestampms=timestampms,
        seq=seq,
        action=action,
        side=side,
        price=price,
        amount=amount,
        remaining=remaining,
    )


def _iter_parquet_batches(path: Path, batch_size: int) -> Iterator[Mapping[str, list[object]]]:
    """Yield parquet batches as column-to-list mappings."""
    if pq is None:
        raise ImportError("pyarrow is required to stream parquet data.")
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=batch_size, columns=list(EVENT_COLUMNS)):
        yield batch.to_pydict()


def _iter_csv_batches(path: Path, batch_size: int) -> Iterator[Mapping[str, list[object]]]:
    """Yield CSV batches as column-to-list mappings."""
    for chunk in pd.read_csv(path, usecols=list(EVENT_COLUMNS), chunksize=batch_size):
        yield {column: chunk[column].tolist() for column in EVENT_COLUMNS}


def _iter_raw_batches(path: Path) -> Iterator[Mapping[str, list[object]]]:
    """Yield raw event batches from parquet or CSV without loading the full file."""
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        yield from _iter_parquet_batches(path, PARQUET_BATCH_SIZE)
        return
    if suffix in {".csv", ".txt"}:
        yield from _iter_csv_batches(path, CSV_BATCH_SIZE)
        return
    raise ValueError(f"Unsupported market event file type: {path}")


def inspect_schema_streaming(
    csv_path: Path,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
    sample_rows: int = SCHEMA_SAMPLE_ROWS,
) -> Dict[str, object]:
    """Inspect schema and validation statistics without materializing the full file."""
    action_counter: Counter[str] = Counter()
    side_counter: Counter[str] = Counter()
    combo_counter: Counter[str] = Counter()
    first_valid_ts: Optional[int] = None
    last_valid_ts: Optional[int] = None
    invalid_price = 0
    invalid_amount = 0
    sampled = 0

    for batch in _iter_raw_batches(csv_path):
        batch_rows = len(batch["seq"])
        for index in range(batch_rows):
            action = _parse_text(batch["action"][index])
            side = _parse_text(batch["side"][index])
            action_counter[action] += 1
            side_counter[side] += 1
            combo_counter[f"{action}|{side}"] += 1

            price = _parse_float(batch["price"][index])
            amount = _parse_float(batch["amount"][index])
            ts = _parse_int(batch["ts"][index])

            if price is None or price < min_valid_price or price > max_valid_price:
                invalid_price += 1
            if amount is None or amount < min_valid_amount or amount > max_valid_amount:
                invalid_amount += 1
            if ts is not None:
                if first_valid_ts is None:
                    first_valid_ts = ts
                last_valid_ts = ts

            sampled += 1
            if sampled >= sample_rows:
                return {
                    "columns": list(EVENT_COLUMNS),
                    "sampled_rows": sampled,
                    "event_types": dict(action_counter),
                    "side_values": dict(side_counter),
                    "action_side_combinations": dict(combo_counter),
                    "first_valid_ts": first_valid_ts,
                    "last_valid_ts": last_valid_ts,
                    "approx_sample_duration_hours": None
                    if first_valid_ts is None or last_valid_ts is None
                    else (last_valid_ts - first_valid_ts) / 1000.0 / 3600.0,
                    "invalid_price_rows_in_sample": invalid_price,
                    "invalid_amount_rows_in_sample": invalid_amount,
                    "assumptions": [
                        "INITIAL_SNAPSHOT rows are buffered until the first real-time event.",
                        "Rows with invalid price/amount are filtered before simulation.",
                        "This summary is produced by streaming only the first sample window.",
                    ],
                }

    return {
        "columns": list(EVENT_COLUMNS),
        "sampled_rows": sampled,
        "event_types": dict(action_counter),
        "side_values": dict(side_counter),
        "action_side_combinations": dict(combo_counter),
        "first_valid_ts": first_valid_ts,
        "last_valid_ts": last_valid_ts,
        "approx_sample_duration_hours": None
        if first_valid_ts is None or last_valid_ts is None
        else (last_valid_ts - first_valid_ts) / 1000.0 / 3600.0,
        "invalid_price_rows_in_sample": invalid_price,
        "invalid_amount_rows_in_sample": invalid_amount,
        "assumptions": [
            "INITIAL_SNAPSHOT rows are buffered until the first real-time event.",
            "Rows with invalid price/amount are filtered before simulation.",
            "This summary is produced by streaming only the first sample window.",
        ],
    }


def stream_market_events_streaming(
    csv_path: Path,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
    max_events: Optional[int] = None,
) -> Iterator[MarketEvent]:
    """Stream events from parquet or CSV with a hard event cap."""
    first_valid_ts: Optional[int] = None
    buffered_snapshot: list[MarketEvent] = []
    yielded = 0

    for batch in _iter_raw_batches(csv_path):
        batch_rows = len(batch["seq"])
        for index in range(batch_rows):
            event = _normalize_market_event(
                ts_value=batch["ts"][index],
                seq_value=batch["seq"][index],
                action_value=batch["action"][index],
                side_value=batch["side"][index],
                price_value=batch["price"][index],
                amount_value=batch["amount"][index],
                remaining_value=batch["remaining"][index],
                min_valid_price=min_valid_price,
                max_valid_price=max_valid_price,
                min_valid_amount=min_valid_amount,
                max_valid_amount=max_valid_amount,
            )
            if event is None:
                continue

            if event.timestampms < 0:
                buffered_snapshot.append(event)
                continue

            if first_valid_ts is None:
                first_valid_ts = event.timestampms
                for snapshot_event in buffered_snapshot:
                    snapshot_event.timestampms = first_valid_ts
                    yield snapshot_event
                    yielded += 1
                    if max_events is not None and yielded >= max_events:
                        return
                buffered_snapshot.clear()

            yield event
            yielded += 1
            if max_events is not None and yielded >= max_events:
                return


def install_backtester_data_hooks(schema_summary: Dict[str, object]) -> None:
    """Route backtester data access through this module's streaming readers."""
    backtester_module.inspect_schema = lambda *args, **kwargs: schema_summary
    backtester_module.stream_market_events = stream_market_events_streaming


def initialize_worker(schema_summary: Dict[str, object]) -> None:
    """Initialize a worker process with the cached data hooks."""
    install_backtester_data_hooks(schema_summary=schema_summary)


def build_base_config_attrs() -> Dict[str, Any]:
    """Extract upper-case config attributes into a mutable dictionary."""
    return {name: getattr(config, name) for name in dir(config) if name.isupper()}


def build_trial_config(
    base_attrs: Mapping[str, Any],
    trial_id: str,
    output_dir: Path,
    max_events: int,
    overrides: Mapping[str, Any],
) -> SimpleNamespace:
    """Create an isolated config namespace for a single trial."""
    trial_dir = output_dir / "artifacts" / trial_id
    attrs = dict(base_attrs)
    attrs.update(overrides)
    attrs["MAX_EVENTS"] = int(max_events)
    attrs["OUTPUT_DIR"] = trial_dir
    attrs["VERSION"] = f"_random_search_{trial_id}"
    attrs["REPORT_EVERY_N_EVENTS"] = int(max_events) + 1
    attrs["SCHEMA_SUMMARY_JSON"] = trial_dir / "schema_summary.json"
    attrs["METRICS_CSV"] = trial_dir / "strategy_metrics.csv"
    attrs["STATE_TIMESERIES_CSV"] = trial_dir / "state_timeseries.csv"
    attrs["FILL_LOG_CSV"] = trial_dir / "fill_log.csv"
    attrs["QUOTE_LOG_CSV"] = trial_dir / "quote_log.csv"
    attrs["PNL_PNG"] = trial_dir / "cumulative_pnl.png"
    attrs["INVENTORY_PNG"] = trial_dir / "inventory.png"
    attrs["DRAWDOWN_PNG"] = trial_dir / "drawdown.png"
    attrs["FILL_ACTIVITY_PNG"] = trial_dir / "fill_activity.png"
    attrs["SUMMARY_PDF"] = trial_dir / "strategy_summary.pdf"
    attrs["MID_TOTAL_PNL_PNG"] = trial_dir / "mid_total_pnl.png"
    attrs["REALIZED_UNREALIZED_PNL_PNG"] = trial_dir / "realized_unrealized_pnl.png"
    return SimpleNamespace(**attrs)


def sample_trial_params(rng: np.random.Generator, seen: set[tuple[Any, ...]]) -> Dict[str, Any]:
    """Sample a unique configuration from the discrete search space."""
    max_attempts = 10_000
    keys = list(SEARCH_SPACE.keys())
    for _ in range(max_attempts):
        params: Dict[str, Any] = {}
        for key, values in SEARCH_SPACE.items():
            sampled = rng.choice(values)
            params[key] = sampled.item() if hasattr(sampled, "item") else sampled
        signature = tuple(params[key] for key in keys)
        if signature not in seen:
            seen.add(signature)
            return params
    raise RuntimeError("Unable to sample a unique configuration from the discrete search space.")


def _safe_float(value: object) -> float:
    """Convert a scalar to float, falling back to NaN."""
    if value is None:
        return float("nan")
    try:
        result = float(value)
    except Exception:
        return float("nan")
    return result if math.isfinite(result) else float("nan")


def _jsonable(value: object) -> object:
    """Convert values to JSON-safe scalars."""
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def extract_trial_metrics(metrics_df: pd.DataFrame, initial_cash: float) -> Dict[str, float]:
    """Extract the metric fields needed for logging and scoring."""
    if metrics_df.empty:
        return {
            "roe": float("nan"),
            "total_traded_volume": float("nan"),
            "total_pnl": float("nan"),
            "fill_count": 0.0,
            "processed_events": float("nan"),
        }

    row = metrics_df.iloc[0]
    roe = _safe_float(row.get("equity_return"))
    total_traded_volume = _safe_float(row.get("gross_traded_notional"))
    fill_count = _safe_float(row.get("fill_count"))
    final_equity_mtm = _safe_float(row.get("final_equity_mtm"))
    total_pnl = final_equity_mtm - float(initial_cash) if math.isfinite(final_equity_mtm) else float("nan")

    if not math.isfinite(roe) and math.isfinite(final_equity_mtm) and initial_cash > 0:
        roe = final_equity_mtm / float(initial_cash) - 1.0

    return {
        "roe": roe,
        "total_traded_volume": total_traded_volume,
        "total_pnl": total_pnl,
        "fill_count": fill_count if math.isfinite(fill_count) else 0.0,
        "processed_events": _safe_float(row.get("processed_events")),
    }


def score_trial(total_traded_volume: float, roe: float) -> float:
    """Objective: maximize traded volume times ROE, with hard penalties for invalid runs."""
    if not math.isfinite(total_traded_volume) or total_traded_volume <= 0.0:
        return VERY_POOR_SCORE
    if not math.isfinite(roe):
        return VERY_POOR_SCORE
    return total_traded_volume * (1 + roe)**2


def run_trial(
    *,
    trial_index: int,
    params: Mapping[str, Any],
    base_attrs: Mapping[str, Any],
    output_dir: Path,
    max_events: int,
) -> Dict[str, Any]:
    """Execute one backtest trial and return a flat result row."""
    trial_id = f"trial_{trial_index:03d}"
    trial_cfg = build_trial_config(
        base_attrs=base_attrs,
        trial_id=trial_id,
        output_dir=output_dir,
        max_events=max_events,
        overrides=params,
    )

    started = time.time()
    status = "ok"
    error_message = ""
    roe = float("nan")
    total_traded_volume = float("nan")
    total_pnl = float("nan")
    fill_count = 0.0
    processed_events = float("nan")

    try:
        result = MarketMakingBacktester(trial_cfg).run()
        extracted = extract_trial_metrics(result["metrics_df"], initial_cash=float(trial_cfg.INITIAL_CASH))
        roe = extracted["roe"]
        total_traded_volume = extracted["total_traded_volume"]
        total_pnl = extracted["total_pnl"]
        fill_count = extracted["fill_count"]
        processed_events = extracted["processed_events"]
        if not math.isfinite(total_traded_volume) or total_traded_volume <= 0.0:
            status = "no_volume"
        elif not math.isfinite(roe):
            status = "invalid_roe"
        del result
    except Exception as exc:
        status = "failed"
        error_message = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    elapsed_seconds = time.time() - started
    score = score_trial(total_traded_volume=total_traded_volume, roe=roe)

    row: Dict[str, Any] = {
        "trial_id": trial_id,
        "trial_index": trial_index,
        "status": status,
        "score": score,
        "total_traded_volume": total_traded_volume,
        "roe": roe,
        "total_pnl": total_pnl,
        "fill_count": fill_count,
        "processed_events": processed_events,
        "elapsed_seconds": elapsed_seconds,
        "error": error_message,
    }
    row.update(params)

    gc.collect()
    return row


def run_trial_worker(
    trial_index: int,
    params: Mapping[str, Any],
    base_attrs: Mapping[str, Any],
    output_dir: Path,
    max_events: int,
) -> Dict[str, Any]:
    """Worker entrypoint for a single trial."""
    return run_trial(
        trial_index=trial_index,
        params=params,
        base_attrs=base_attrs,
        output_dir=output_dir,
        max_events=max_events,
    )


def build_failed_row(trial_index: int, params: Mapping[str, Any], error_message: str) -> Dict[str, Any]:
    """Build a failed result row when a worker future errors before normal handling."""
    row: Dict[str, Any] = {
        "trial_id": f"trial_{trial_index:03d}",
        "trial_index": trial_index,
        "status": "failed",
        "score": VERY_POOR_SCORE,
        "total_traded_volume": float("nan"),
        "roe": float("nan"),
        "total_pnl": float("nan"),
        "fill_count": 0.0,
        "processed_events": float("nan"),
        "elapsed_seconds": float("nan"),
        "error": error_message,
    }
    row.update(params)
    return row


def build_results_frame(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Create a best-first results table with stable ranking."""
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        columns = [
            "rank",
            "trial_id",
            "trial_index",
            "status",
            "score",
            "total_traded_volume",
            "roe",
            "total_pnl",
            "fill_count",
            "processed_events",
            "elapsed_seconds",
            "error",
            *SEARCH_SPACE.keys(),
        ]
        return pd.DataFrame(columns=columns)

    if "rank" in frame.columns:
        frame = frame.drop(columns=["rank"])

    frame = frame.sort_values(
        by=["score", "roe", "total_traded_volume", "trial_index"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    frame.insert(0, "rank", np.arange(1, len(frame) + 1, dtype=int))
    return frame


def save_results(results: list[Dict[str, Any]], output_dir: Path) -> pd.DataFrame:
    """Persist the sorted CSV and best-params JSON after every trial."""
    ensure_dir(output_dir)
    frame = build_results_frame(results)
    csv_path = output_dir / "random_search_results.csv"
    frame.to_csv(csv_path, index=False)

    if not frame.empty:
        best_row = frame.iloc[0].to_dict()
        best_payload = {
            "trial_id": _jsonable(best_row["trial_id"]),
            "score": _jsonable(best_row["score"]),
            "status": _jsonable(best_row["status"]),
            "total_traded_volume": _jsonable(best_row["total_traded_volume"]),
            "roe": _jsonable(best_row["roe"]),
            "total_pnl": _jsonable(best_row["total_pnl"]),
            "fill_count": _jsonable(best_row["fill_count"]),
            "processed_events": _jsonable(best_row["processed_events"]),
            "params": {name: _jsonable(best_row[name]) for name in SEARCH_SPACE.keys()},
        }
        with (output_dir / "best_params.json").open("w", encoding="utf-8") as handle:
            json.dump(best_payload, handle, indent=2, sort_keys=True)

    return frame


def render_progress_bar(completed: int, total: int, width: int = 30) -> str:
    """Render a simple terminal progress bar."""
    if total <= 0:
        total = 1
    completed = max(0, min(completed, total))
    filled = int(width * completed / total)
    bar = "#" * filled + "-" * (width - filled)
    percent = 100.0 * completed / total
    return f"[{bar}] {completed}/{total} ({percent:5.1f}%)"


def print_progress(row: Mapping[str, Any], best_score: float, trial_number: int, total_trials: int) -> None:
    """Print a concise one-line progress update with a search progress bar."""
    score = _safe_float(row.get("score"))
    volume = _safe_float(row.get("total_traded_volume"))
    roe = _safe_float(row.get("roe"))
    fills = _safe_float(row.get("fill_count"))
    elapsed = _safe_float(row.get("elapsed_seconds"))
    progress_bar = render_progress_bar(trial_number, total_trials)
    print(
        f"{progress_bar} "
        f"{row['trial_id']} "
        f"status={row['status']} "
        f"score={score:,.4f} "
        f"volume={volume:,.2f} "
        f"roe={roe:.6f} "
        f"fills={fills:,.0f} "
        f"elapsed={elapsed:.1f}s "
        f"best={best_score:,.4f}"
    )


def print_final_summary(frame: pd.DataFrame, output_dir: Path, total_trials: int, max_events: int, seed: int) -> None:
    """Print a short final leaderboard."""
    print("")
    print("Random search complete")
    print(f"Trials: {total_trials}")
    print(f"Max events per trial: {max_events:,}")
    print(f"Seed: {seed}")
    print(f"Results CSV: {output_dir / 'random_search_results.csv'}")
    print(f"Best params JSON: {output_dir / 'best_params.json'}")

    if frame.empty:
        print("No results were recorded.")
        return

    leaderboard = frame.loc[:, ["rank", "trial_id", "score", "total_traded_volume", "roe", "total_pnl", "fill_count", "status"]].head(5)
    print("")
    print("Top trials:")
    print(leaderboard.to_string(index=False))


def main() -> None:
    """Run the discrete random search end to end."""
    args = parse_args()
    if args.trials <= 0:
        raise ValueError("--trials must be positive.")
    if args.max_events <= 0:
        raise ValueError("--max-events must be positive.")
    if args.workers <= 0:
        raise ValueError("--workers must be positive.")

    total_combinations = math.prod(len(values) for values in SEARCH_SPACE.values())
    if args.trials > total_combinations:
        raise ValueError(f"--trials={args.trials} exceeds the discrete search space size of {total_combinations}.")

    worker_count = min(args.workers, args.trials)
    output_dir = args.output_dir.resolve()
    ensure_dir(output_dir)

    print("Starting random search")
    print(f"Input file: {config.RAW_EVENT_CSV}")
    print(f"Output dir: {output_dir}")
    print(f"Trials: {args.trials}")
    print(f"Max events per trial: {args.max_events:,}")
    print(f"Seed: {args.seed}")
    print(f"Workers: {worker_count}")
    print(f"Progress: {render_progress_bar(0, args.trials)}")

    schema_summary = inspect_schema_streaming(
        csv_path=config.RAW_EVENT_CSV,
        min_valid_price=config.MIN_VALID_PRICE,
        max_valid_price=config.MAX_VALID_PRICE,
        min_valid_amount=config.MIN_VALID_AMOUNT,
        max_valid_amount=config.MAX_VALID_AMOUNT,
        sample_rows=SCHEMA_SAMPLE_ROWS,
    )
    install_backtester_data_hooks(schema_summary=schema_summary)

    base_attrs = build_base_config_attrs()
    rng = np.random.default_rng(args.seed)
    seen_signatures: set[tuple[Any, ...]] = set()
    results: list[Dict[str, Any]] = []
    best_score = VERY_POOR_SCORE
    sampled_trials = [(trial_index, sample_trial_params(rng=rng, seen=seen_signatures)) for trial_index in range(1, args.trials + 1)]
    completed_trials = 0

    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=initialize_worker,
        initargs=(schema_summary,),
    ) as executor:
        future_to_trial = {
            executor.submit(
                run_trial_worker,
                trial_index,
                params,
                base_attrs,
                output_dir,
                args.max_events,
            ): (trial_index, params)
            for trial_index, params in sampled_trials
        }

        for future in as_completed(future_to_trial):
            trial_index, params = future_to_trial[future]
            try:
                row = future.result()
            except Exception as exc:
                traceback.print_exc()
                row = build_failed_row(
                    trial_index=trial_index,
                    params=params,
                    error_message=f"{type(exc).__name__}: {exc}",
                )

            results.append(row)
            completed_trials += 1

            frame = save_results(results=results, output_dir=output_dir)
            if not frame.empty:
                best_score = _safe_float(frame.iloc[0]["score"])
            print_progress(row=row, best_score=best_score, trial_number=completed_trials, total_trials=args.trials)

    final_frame = build_results_frame(results)
    save_results(results=results, output_dir=output_dir)
    print_final_summary(
        frame=final_frame,
        output_dir=output_dir,
        total_trials=args.trials,
        max_events=args.max_events,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
