"""
Data loading and validation module for market event data.

Provides utilities to:
- Load market event data from parquet files
- Validate price and amount ranges
- Inspect data schema and statistics
- Stream events as a generator for memory efficiency
"""

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, Optional

import pandas as pd


# Valid order book action types
BOOK_ACTIONS = {"INITIAL_SNAPSHOT", "PLACE", "CANCEL", "FILL_UPDATE"}


@dataclass
class MarketEvent:
    """
    Represents a single market event (trade, order book update, or snapshot).
    
    Attributes:
        timestampms (int): Event timestamp in milliseconds (may be -1 for INITIAL_SNAPSHOT)
        seq (int): Event sequence number for ordering
        action (str): Type of event (TRADE, PLACE, CANCEL, FILL_UPDATE, INITIAL_SNAPSHOT)
        side (str): Buy/Sell for trades, Bid/Ask for book events
        price (float): Price level of the event
        amount (float): Amount/size of the event
        remaining (Optional[float]): Remaining quantity on the order (for book events)
    """
    timestampms: int
    seq: int
    action: str
    side: str
    price: float
    amount: float
    remaining: Optional[float]

    @property
    def is_trade(self) -> bool:
        """Check if event is a trade execution."""
        return self.action == "TRADE"

    @property
    def is_book_event(self) -> bool:
        """Check if event is an order book update."""
        return self.action in BOOK_ACTIONS

    @property
    def passive_side(self) -> Optional[str]:
        """
        Get the passive side of a trade (the side that was resting).
        
        For a BUY aggressive order, the passive (resting) side was ASK.
        For a SELL aggressive order, the passive (resting) side was BID.
        
        Returns:
            Optional[str]: "BID" or "ASK" for trades, None for non-trades
        """
        if self.action != "TRADE":
            return None
        if self.side == "BUY":
            return "ASK"
        if self.side == "SELL":
            return "BID"
        return None


def _read_market_data(df_path: Path) -> pd.DataFrame:
    """Read market data from CSV or Parquet into a pandas DataFrame.

    Supports both Parquet and CSV file formats. The caller should handle
    large files carefully (e.g., use chunks in streaming contexts).
    """

    ext = df_path.suffix.lower()
    if ext in {".parquet", ".pq"}:
        return pd.read_parquet(df_path)
    if ext in {".csv", ".txt"}:
        return pd.read_csv(df_path)
    raise ValueError(f"Unsupported data format: {df_path}")


def inspect_schema(
    csv_path: Path,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
    sample_rows: int = 200_000,
) -> Dict[str, object]:
    """Analyze input data schema and generate validation statistics.

    Scans a sample of rows and reports:
    - Column names and data structure
    - Distribution of event types (actions) and sides
    - Valid price/amount ranges found
    - Time coverage of the sample
    - Count of invalid rows (out of range)

    Args:
        csv_path (Path): Path to input data file (Parquet or CSV)
        min_valid_price (float): Minimum valid price threshold
        max_valid_price (float): Maximum valid price threshold
        min_valid_amount (float): Minimum valid order amount
        max_valid_amount (float): Maximum valid order amount
        sample_rows (int): Number of rows to sample (default 200k)

    Returns:
        Dict[str, object]: Schema summary with statistics and assumptions
    """
    action_counter: Counter = Counter()
    side_counter: Counter = Counter()
    combo_counter: Counter = Counter()
    first_valid_ts = None
    last_valid_ts = None
    invalid_price = 0
    invalid_amount = 0
    sampled = 0

    df = _read_market_data(csv_path)
    df_sample = df.head(sample_rows) if len(df) > sample_rows else df
    fieldnames = list(df.columns)
    sampled = 0

    for idx, row in df_sample.iterrows():
        sampled += 1
        action = str(row.get("action", "")).upper().strip()
        side = str(row.get("side", "")).upper().strip()
        action_counter[action] += 1
        side_counter[side] += 1
        combo_counter[(action, side)] += 1

        price = _parse_float(row.get("price"))
        amount = _parse_float(row.get("amount"))
        ts = _parse_timestamp(row.get("ts"))

        if price is None or price < min_valid_price or price > max_valid_price:
            invalid_price += 1
        if amount is None or amount < min_valid_amount or amount > max_valid_amount:
            invalid_amount += 1

        if ts is not None:
            if first_valid_ts is None:
                first_valid_ts = ts
            last_valid_ts = ts

    return {
        "columns": fieldnames,
        "sampled_rows": sampled,
        "event_types": dict(action_counter),
        "side_values": dict(side_counter),
        "action_side_combinations": {f"{k[0]}|{k[1]}": v for k, v in combo_counter.items()},
        "first_valid_ts": first_valid_ts,
        "last_valid_ts": last_valid_ts,
        "approx_sample_duration_hours": (
            None
            if first_valid_ts is None or last_valid_ts is None
            else (last_valid_ts - first_valid_ts) / 1000.0 / 3600.0
        ),
        "invalid_price_rows_in_sample": invalid_price,
        "invalid_amount_rows_in_sample": invalid_amount,
        "assumptions": [
            "INITIAL_SNAPSHOT seeds the book and has blank timestamps.",
            "PLACE/CANCEL/FILL_UPDATE update resting depth using the remaining field.",
            "TRADE carries aggressor side BUY/SELL and should be processed before the following FILL_UPDATE.",
            "Rows with impossible price or amount are filtered before simulation.",
        ],
    }


def stream_market_events(
    csv_path: Path,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
    max_events: Optional[int] = None,
) -> Generator[MarketEvent, None, None]:
    """Stream market events from a data file as a generator.

    Supports both Parquet and CSV input formats.

    Processes events in order:
    1. Buffers INITIAL_SNAPSHOT events (which have negative timestamps)
    2. When first real-time event arrives, assigns snapshot timestamp and yields buffered events
    3. Yields remaining events in chronological order
    4. Filters out events with invalid prices/amounts

    Args:
        csv_path (Path): Path to input data file (Parquet or CSV)
        min_valid_price (float): Minimum valid price threshold
        max_valid_price (float): Maximum valid price threshold
        min_valid_amount (float): Minimum valid order amount
        max_valid_amount (float): Maximum valid order amount
        max_events (Optional[int]): Maximum events to yield (default None = all)

    Yields:
        MarketEvent: Market events in chronological order
    """
    first_valid_ts = None
    buffered_snapshot = []
    yielded = 0

    ext = csv_path.suffix.lower()
    if ext in {".parquet", ".pq"}:
        df_iter = [pd.read_parquet(csv_path)]
    elif ext in {".csv", ".txt"}:
        df_iter = pd.read_csv(csv_path, chunksize=100_000)
    else:
        raise ValueError(f"Unsupported market event file type: {csv_path}")

    for df in df_iter:
        if max_events is not None:
            remaining = max_events - yielded
            if remaining <= 0:
                break
            if len(df) > remaining:
                df = df.head(remaining)

        for idx, row in df.iterrows():
            event = _normalize_row(
                row=row,
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
                buffered_snapshot.clear()

            yield event
            yielded += 1

            if max_events is not None and yielded >= max_events:
                return


def _normalize_row(
    row: Dict[str, str],
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
) -> Optional[MarketEvent]:
    """
    Parse and validate a single row of market event data.
    
    Handles:
    - String-to-float/int conversion with error handling
    - Validation of price/amount ranges
    - Side verification (BUY/SELL for trades, BID/ASK for orders)
    - Remaining amount handling for book events
    - Timestamp defaulting to -1 for INITIAL_SNAPSHOT
    
    Args:
        row (Dict[str, str]): Row of data with string values
        min_valid_price (float): Minimum valid price
        max_valid_price (float): Maximum valid price
        min_valid_amount (float): Minimum valid amount
        max_valid_amount (float): Maximum valid amount
        
    Returns:
        Optional[MarketEvent]: Normalized MarketEvent or None if invalid
    """
    action = str(row.get("action", "")).upper().strip()
    side = str(row.get("side", "")).upper().strip()
    seq = _parse_int(row.get("seq"))
    price = _parse_float(row.get("price"))
    amount = _parse_float(row.get("amount"))
    remaining = _parse_float(row.get("remaining"))
    timestampms = _parse_timestamp(row.get("ts"))

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


def _parse_float(value: object) -> Optional[float]:
    """
    Safely parse a value to float, handling None and "N/A" strings.
    
    Args:
        value (object): Value to parse
        
    Returns:
        Optional[float]: Parsed float or None if parsing fails
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _parse_int(value: object) -> Optional[int]:
    """
    Safely parse a value to int, handling None values and float strings.
    
    Args:
        value (object): Value to parse
        
    Returns:
        Optional[int]: Parsed int (float values are converted via int(float(text))) or None
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _parse_timestamp(value: object) -> Optional[int]:
    """
    Parse a timestamp value (milliseconds since epoch).
    
    Args:
        value (object): Timestamp value to parse
        
    Returns:
        Optional[int]: Parsed timestamp in milliseconds or None
    """
    return _parse_int(value)
