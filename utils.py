import json
import math
from pathlib import Path


EPS = 1e-12


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) <= EPS:
        return default
    return float(numerator / denominator)


def clamp(value: float, lower: float, upper: float) -> float:
    return float(max(lower, min(upper, value)))


def floor_to_tick(value: float, tick: float) -> float:
    return math.floor(value / tick) * tick


def ceil_to_tick(value: float, tick: float) -> float:
    return math.ceil(value / tick) * tick


def json_dump(data: dict, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
