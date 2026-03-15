import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, Optional


BOOK_ACTIONS = {"INITIAL_SNAPSHOT", "PLACE", "CANCEL", "FILL_UPDATE"}


@dataclass
class MarketEvent:
    timestampms: int
    seq: int
    action: str
    side: str
    price: float
    amount: float
    remaining: Optional[float]

    @property
    def is_trade(self) -> bool:
        return self.action == "TRADE"

    @property
    def is_book_event(self) -> bool:
        return self.action in BOOK_ACTIONS

    @property
    def passive_side(self) -> Optional[str]:
        if self.action != "TRADE":
            return None
        if self.side == "BUY":
            return "ASK"
        if self.side == "SELL":
            return "BID"
        return None


def inspect_schema(
    csv_path: Path,
    min_valid_price: float,
    max_valid_price: float,
    min_valid_amount: float,
    max_valid_amount: float,
    sample_rows: int = 200_000,
) -> Dict[str, object]:
    action_counter: Counter = Counter()
    side_counter: Counter = Counter()
    combo_counter: Counter = Counter()
    first_valid_ts = None
    last_valid_ts = None
    invalid_price = 0
    invalid_amount = 0
    sampled = 0

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
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

            if sampled >= sample_rows:
                break

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
    first_valid_ts = None
    buffered_snapshot = []
    yielded = 0

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
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
                    if max_events is not None and yielded >= max_events:
                        return
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
    return _parse_int(value)
