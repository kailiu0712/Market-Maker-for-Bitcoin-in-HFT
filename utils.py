"""
Utility functions for mathematical operations and file I/O.

Provides:
- Safe division with default fallback
- Value clamping to min/max bounds
- Price rounding to tick size
- JSON serialization helpers
- Directory creation and management
"""

import json
import math
from pathlib import Path


# Machine epsilon - threshold for treating values as zero
EPS = 1e-12


def ensure_dir(path: Path) -> None:
    """
    Create directory and all parent directories if they don't exist.
    
    Args:
        path (Path): Directory path to create
        
    Returns:
        None
    """
    path.mkdir(parents=True, exist_ok=True)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Divide two floats with protection against division by zero.
    
    Args:
        numerator (float): Numerator
        denominator (float): Denominator
        default (float): Value to return if denominator is near zero (default 0.0)
        
    Returns:
        float: numerator/denominator or default if denominator <= EPS
    """
    if abs(denominator) <= EPS:
        return default
    return float(numerator / denominator)


def clamp(value: float, lower: float, upper: float) -> float:
    """
    Constrain a value within [lower, upper] bounds.
    
    Args:
        value (float): Value to constrain
        lower (float): Minimum bound
        upper (float): Maximum bound
        
    Returns:
        float: Value clamped to [lower, upper]
    """
    return float(max(lower, min(upper, value)))


def floor_to_tick(value: float, tick: float) -> float:
    """
    Round value down to nearest tick size.
    
    Args:
        value (float): Value to round
        tick (float): Tick size (grid granularity)
        
    Returns:
        float: Largest multiple of tick that is <= value
    """
    return math.floor(value / tick) * tick


def ceil_to_tick(value: float, tick: float) -> float:
    """
    Round value up to nearest tick size.
    
    Args:
        value (float): Value to round
        tick (float): Tick size (grid granularity)
        
    Returns:
        float: Smallest multiple of tick that is >= value
    """
    return math.ceil(value / tick) * tick


def json_dump(data: dict, path: Path) -> None:
    """
    Write dictionary to JSON file with pretty printing.
    
    Args:
        data (dict): Dictionary to serialize
        path (Path): File path to write to
        
    Returns:
        None (writes to file)
    """
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
