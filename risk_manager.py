"""
Inventory and position risk management module.

Manages:
- Inventory limits and soft limits
- Order size adjustments based on inventory
- Buy/sell allowed flags based on constraints
- Inventory skew adjustments to quoted prices
"""

from typing import Dict

from utils import clamp


class RiskManager:
    """
    Computes inventory-based risk adjustments.
    
    Monitors inventory relative to target and limits:
    - Controls order sizes based on how full inventory is
    - Enforces hard max inventory limits
    - Enforces soft limits that restrict to reduce-only below threshold
    - Provides skew adjustments that widen spreads when inventory is extreme
    """
    def __init__(
        self,
        max_inventory: float,
        inventory_target: float,
        inventory_soft_limit_fraction: float,
        size_skew_factor: float,
    ) -> None:
        """
        Initialize the risk manager with inventory parameters.
        
        Args:
            max_inventory (float): Hard limit on absolute inventory
            inventory_target (float): Target inventory level (for returning bias)
            inventory_soft_limit_fraction (float): At this fraction, switch to reduce-only
            size_skew_factor (float): How aggressively to adjust sizes based on inventory
        """
        self.max_inventory = max_inventory
        self.inventory_target = inventory_target
        self.inventory_soft_limit_fraction = inventory_soft_limit_fraction
        self.size_skew_factor = size_skew_factor

    def inventory_fraction(self, inventory: float) -> float:
        """
        Get normalized inventory as fraction of max.
        
        Returns (inventory - target) / max_inventory, clamped to [-1, 1].
        Positive = long inventory, negative = short inventory.
        
        Args:
            inventory (float): Current inventory position
            
        Returns:
            float: Normalized inventory fraction in [-1, 1]
        """
        return clamp((inventory - self.inventory_target) / max(self.max_inventory, 1e-8), -1.0, 1.0)

    def side_adjustments(self, inventory: float) -> Dict[str, float]:
        """
        Compute order size and permission adjustments based on inventory.
        
        Returns dictionary with:
        - bid_size_multiplier: Multiply base order size for bidding
        - ask_size_multiplier: Multiply base order size for asking
        - bid_allowed: 1.0 if can bid, 0.0 if cannot (hard limit)
        - ask_allowed: 1.0 if can ask, 0.0 if cannot (hard limit)
        - inventory_fraction: Normalized inventory position
        
        When inventory is long (positive):
        - Reduce bid size, increase ask size to unwind
        - If approaching max, stop bidding (bid_allowed=0)
        
        When inventory is short (negative):
        - Increase bid size, reduce ask size to unwind
        - If approaching min, stop asking (ask_allowed=0)
        
        Args:
            inventory (float): Current inventory position
            
        Returns:
            Dict[str, float]: Risk adjustments dictionary
        """
        inv_frac = self.inventory_fraction(inventory)
        bid_size_mult = clamp(1.0 - max(inv_frac, 0.0) * self.size_skew_factor, 0.0, 1.5)
        ask_size_mult = clamp(1.0 + max(inv_frac, 0.0) * self.size_skew_factor, 0.0, 1.5)

        if inv_frac < 0.0:
            bid_size_mult = clamp(1.0 + abs(inv_frac) * self.size_skew_factor, 0.0, 1.5)
            ask_size_mult = clamp(1.0 - abs(inv_frac) * self.size_skew_factor, 0.0, 1.5)

        bid_allowed = inventory < self.max_inventory
        ask_allowed = inventory > -self.max_inventory
        reduce_only = abs(inv_frac) >= self.inventory_soft_limit_fraction
        if reduce_only:
            if inventory > self.inventory_target:
                bid_allowed = False
            elif inventory < self.inventory_target:
                ask_allowed = False

        return {
            "inventory_fraction": inv_frac,
            "bid_size_multiplier": bid_size_mult,
            "ask_size_multiplier": ask_size_mult,
            "bid_allowed": float(bid_allowed),
            "ask_allowed": float(ask_allowed),
        }
