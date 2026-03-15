from typing import Dict

from utils import clamp


class RiskManager:
    def __init__(
        self,
        max_inventory: float,
        inventory_target: float,
        inventory_soft_limit_fraction: float,
        size_skew_factor: float,
    ) -> None:
        self.max_inventory = max_inventory
        self.inventory_target = inventory_target
        self.inventory_soft_limit_fraction = inventory_soft_limit_fraction
        self.size_skew_factor = size_skew_factor

    def inventory_fraction(self, inventory: float) -> float:
        return clamp((inventory - self.inventory_target) / max(self.max_inventory, 1e-8), -1.0, 1.0)

    def side_adjustments(self, inventory: float) -> Dict[str, float]:
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
