"""
Price signal generation and alpha computation module.

Generates fair price and directional alpha signals from market features.
Combines multiple signal components:
- Microprice vs mid-price weighting
- Order book imbalance
- Trade flow intensity
- Book flow intensity
"""

from typing import Dict

from utils import clamp


class SignalEngine:
    """
    Generates trading signals and fair price adjustments.
    
    Computes:
    - Fair price (weighted average of mid and microprice)
    - Alpha bias (imbalance-based, trade-flow-based, book-flow-based)
    - Adjusted fair price (fair price + alpha adjustment)
    
    All alpha components are clipped and summed to create directional bias.
    """
    def __init__(
        self,
        microprice_weight: float,
        imbalance_alpha_bps: float,
        trade_flow_alpha_bps: float,
        book_flow_alpha_bps: float,
        alpha_clip_bps: float,
    ) -> None:
        """
        Initialize the signal engine with alpha parameters.
        
        Args:
            microprice_weight (float): Weight for microprice in fair price (0-1)
            imbalance_alpha_bps (float): Imbalance contribution to alpha (basis points)
            trade_flow_alpha_bps (float): Trade flow contribution to alpha (basis points)
            book_flow_alpha_bps (float): Book flow contribution to alpha (basis points)
            alpha_clip_bps (float): Maximum absolute alpha magnitude (basis points)
        """
        self.microprice_weight = microprice_weight
        self.imbalance_alpha_bps = imbalance_alpha_bps
        self.trade_flow_alpha_bps = trade_flow_alpha_bps
        self.book_flow_alpha_bps = book_flow_alpha_bps
        self.alpha_clip_bps = alpha_clip_bps

    def compute(self, features: Dict[str, float]) -> Dict[str, float]:
        """
        Compute fair price and alpha signal from market features.
        
        Returns:
            Dict[str, float]: Dictionary with:
                - "fair_price": Microprice-weighted average of mid & microprice
                - "adjusted_fair_price": Fair price adjusted by alpha
                - "alpha_bps": Total directional bias (basis points)
        """
        mid = features["mid"]
        microprice = features["microprice"]
        depth_total = max(features["depth_total_5"], 1e-8)

        fair_price = (1.0 - self.microprice_weight) * mid + self.microprice_weight * microprice
        imbalance_component = self.imbalance_alpha_bps * features["imbalance_1"]
        trade_component = self.trade_flow_alpha_bps * clamp(features["trade_flow_5s"] / depth_total, -1.0, 1.0)
        book_component = self.book_flow_alpha_bps * clamp(features["book_flow_5s"] / depth_total, -1.0, 1.0)
        alpha_bps = clamp(
            imbalance_component + trade_component + book_component,
            -self.alpha_clip_bps,
            self.alpha_clip_bps,
        )
        adjusted_fair = fair_price * (1.0 + alpha_bps / 1e4)

        return {
            "fair_price": fair_price,
            "adjusted_fair_price": adjusted_fair,
            "alpha_bps": alpha_bps,
        }
