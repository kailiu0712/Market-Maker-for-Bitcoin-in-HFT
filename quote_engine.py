"""
Quote generation engine for market-making.

Generates bid/ask prices and sizes based on:
- Market impact (spread calculation)
- Inventory position (skew and unwind)
- Volatility and flow conditions
- Opportunity filters (edge and risk gating)
"""

from dataclasses import dataclass
from typing import Dict

from utils import ceil_to_tick, clamp, floor_to_tick


@dataclass
class QuoteTarget:
    """
    Target quote parameters to post to the market.
    
    Attributes:
        timestampms (int): Timestamp when quote was generated
        fair_price (float): Estimated fair value of the instrument
        reservation_price (float): Inventory-adjusted fair price
        alpha_bps (float): Directional bias in basis points
        bid_price (float): Target bid price
        ask_price (float): Target ask price
        bid_size (float): Target bid size (0 if not quoting)
        ask_size (float): Target ask size (0 if not quoting)
        half_spread (float): Half-spread component used in calculation
    """
    timestampms: int
    fair_price: float
    reservation_price: float
    alpha_bps: float
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    half_spread: float


class QuoteEngine:
    """
    Generates optimal bid/ask quotes and sizes.
    
    Process:
    1. Calculate half-spread based on volatility, flow, inventory
    2. Center quotes around reservation price (inventory-adjusted fair price)
    3. Apply inventory unwind when position is extreme
    4. Apply opportunity filters (volatility, flow, edge gates)
    5. Enforce hard limits (min/max price, size constraints)
    
    Returns QuoteTarget objects with proposed bid/ask prices and sizes.
    """
    def __init__(
        self,
        price_tick: float,
        base_order_size: float,
        min_order_size: float,
        min_half_spread_ticks: float,
        market_spread_multiplier: float,
        volatility_spread_multiplier: float,
        flow_spread_multiplier: float,
        inventory_spread_multiplier: float,
        inventory_skew_ticks: float,
        maker_fee_rate: float,
        min_required_edge_buffer_bps: float,
        max_volatility_to_quote_bps: float,
        max_flow_ratio_to_quote: float,
        min_directional_alpha_bps: float,
        allow_two_sided_when_alpha_small: bool,
        inventory_unwind_threshold_fraction: float,
        inventory_unwind_join_touch: bool,
        inventory_unwind_size_multiplier: float,
        calm_market_vol_threshold_bps: float,
        calm_market_spread_threshold_bps: float,
        calm_market_tightening_factor: float,
    ) -> None:
        """
        Initialize quote engine with all configuration parameters.
        
        Parameters control:
        - Spread calculation (market, volatility, flow, inventory multipliers)
        - Inventory management (max inventory, unwind thresholds)
        - Quote quality filters (minimum edge, max volatility, max flow ratio)
        - Market conditions (calm market spread tightening)
        """
        self.price_tick = price_tick
        self.base_order_size = base_order_size
        self.min_order_size = min_order_size
        self.min_half_spread_ticks = min_half_spread_ticks
        self.market_spread_multiplier = market_spread_multiplier
        self.volatility_spread_multiplier = volatility_spread_multiplier
        self.flow_spread_multiplier = flow_spread_multiplier
        self.inventory_spread_multiplier = inventory_spread_multiplier
        self.inventory_skew_ticks = inventory_skew_ticks
        self.maker_fee_rate = maker_fee_rate
        self.min_required_edge_buffer_bps = min_required_edge_buffer_bps
        self.max_volatility_to_quote_bps = max_volatility_to_quote_bps
        self.max_flow_ratio_to_quote = max_flow_ratio_to_quote
        self.min_directional_alpha_bps = min_directional_alpha_bps
        self.allow_two_sided_when_alpha_small = allow_two_sided_when_alpha_small
        self.inventory_unwind_threshold_fraction = inventory_unwind_threshold_fraction
        self.inventory_unwind_join_touch = inventory_unwind_join_touch
        self.inventory_unwind_size_multiplier = inventory_unwind_size_multiplier
        self.calm_market_vol_threshold_bps = calm_market_vol_threshold_bps
        self.calm_market_spread_threshold_bps = calm_market_spread_threshold_bps
        self.calm_market_tightening_factor = calm_market_tightening_factor

    def generate(
        self,
        timestampms: int,
        features: Dict[str, float],
        signal: Dict[str, float],
        risk_state: Dict[str, float],
    ) -> QuoteTarget:
        """
        Generate optimal quote for current market conditions and position.
        
        Applies multiple adjustments in sequence:
        1. Calculate dynamic half-spread based on market conditions
        2. Apply calm market spread tightening if applicable
        3. Apply inventory unwinding when position is extreme
        4. Apply opportunity filters (market conditions, edge requirements)
        5. Enforce minimum order size
        
        Args:
            timestampms (int): Current timestamp
            features (Dict[str, float]): Market features (price, spread, volatility, depth, flow)
            signal (Dict[str, float]): Price signal (fair price, adjusted fair price, alpha)
            risk_state (Dict[str, float]): Risk state (inventory fraction, size multipliers, allowed flags)
            
        Returns:
            QuoteTarget: Target quote with bid/ask prices and sizes
        """
        best_bid = features["best_bid"]
        best_ask = features["best_ask"]
        market_spread = max(features["spread"], self.price_tick)
        fair_price = signal["adjusted_fair_price"]
        inv_frac = risk_state["inventory_fraction"]
        reservation_price = fair_price - inv_frac * self.inventory_skew_ticks * self.price_tick

        half_spread = max(
            self.min_half_spread_ticks * self.price_tick,
            self.market_spread_multiplier * market_spread * 0.5
            + self.volatility_spread_multiplier * (features["volatility_5s_bps"] / 1e4) * fair_price
            + self.flow_spread_multiplier * abs(signal["alpha_bps"]) / 1e4 * fair_price
            + self.inventory_spread_multiplier * abs(inv_frac) * market_spread,
        )
        calm_market = (
            features["volatility_5s_bps"] <= self.calm_market_vol_threshold_bps
            and (market_spread / max(features["mid"], 1e-8) * 1e4) <= self.calm_market_spread_threshold_bps
            and abs(inv_frac) < self.inventory_unwind_threshold_fraction
        )
        if calm_market:
            half_spread = max(self.min_half_spread_ticks * self.price_tick, half_spread * self.calm_market_tightening_factor)

        bid_price = floor_to_tick(reservation_price - half_spread, self.price_tick)
        ask_price = ceil_to_tick(reservation_price + half_spread, self.price_tick)

        if bid_price >= best_ask:
            bid_price = best_ask - self.price_tick
        if ask_price <= best_bid:
            ask_price = best_bid + self.price_tick
        if bid_price >= ask_price:
            bid_price = ask_price - self.price_tick

        bid_size = self.base_order_size * risk_state["bid_size_multiplier"] * risk_state["bid_allowed"]
        ask_size = self.base_order_size * risk_state["ask_size_multiplier"] * risk_state["ask_allowed"]
        bid_price, ask_price, bid_size, ask_size = self._apply_inventory_unwind(
            best_bid=best_bid,
            best_ask=best_ask,
            inv_frac=inv_frac,
            bid_price=bid_price,
            ask_price=ask_price,
            bid_size=bid_size,
            ask_size=ask_size,
        )
        bid_size, ask_size = self._apply_opportunity_filter(
            bid_size=bid_size,
            ask_size=ask_size,
            features=features,
            signal=signal,
            reservation_price=reservation_price,
            bid_price=bid_price,
            ask_price=ask_price,
            risk_state=risk_state,
        )
        bid_size = 0.0 if bid_size < self.min_order_size else bid_size
        ask_size = 0.0 if ask_size < self.min_order_size else ask_size

        return QuoteTarget(
            timestampms=timestampms,
            fair_price=fair_price,
            reservation_price=reservation_price,
            alpha_bps=signal["alpha_bps"],
            bid_price=clamp(bid_price, 0.0, ask_price - self.price_tick),
            ask_price=max(ask_price, bid_price + self.price_tick),
            bid_size=bid_size,
            ask_size=ask_size,
            half_spread=half_spread,
        )

    def _apply_inventory_unwind(
        self,
        best_bid: float,
        best_ask: float,
        inv_frac: float,
        bid_price: float,
        ask_price: float,
        bid_size: float,
        ask_size: float,
    ) -> tuple[float, float, float, float]:
        """
        Apply inventory unwind adjustments when position is extreme.
        
        When inventory is short (negative): disable asking, increase bid size to buy back.
        When inventory is long (positive): disable bidding, increase ask size to sell.
        Optionally join the market touch when unwinding (better fill probability).
        
        Args:
            best_bid (float): Current best bid price
            best_ask (float): Current best ask price
            inv_frac (float): Normalized inventory fraction
            bid_price (float): Proposed bid price
            ask_price (float): Proposed ask price
            bid_size (float): Proposed bid size
            ask_size (float): Proposed ask size
            
        Returns:
            tuple[float, float, float, float]: Adjusted bid_price, ask_price, bid_size, ask_size
        """
        if inv_frac <= -self.inventory_unwind_threshold_fraction:
            ask_size = 0.0
            bid_size *= self.inventory_unwind_size_multiplier
            if self.inventory_unwind_join_touch:
                bid_price = max(bid_price, best_bid)
        elif inv_frac >= self.inventory_unwind_threshold_fraction:
            bid_size = 0.0
            ask_size *= self.inventory_unwind_size_multiplier
            if self.inventory_unwind_join_touch:
                ask_price = min(ask_price, best_ask)
        return bid_price, ask_price, bid_size, ask_size

    def _apply_opportunity_filter(
        self,
        bid_size: float,
        ask_size: float,
        features: Dict[str, float],
        signal: Dict[str, float],
        reservation_price: float,
        bid_price: float,
        ask_price: float,
        risk_state: Dict[str, float],
    ) -> tuple[float, float]:
        """
        Apply opportunity filters to determine if quoting is profitable.
        
        Filters:
        1. Volatility gate: disable if volatility too high
        2. Flow gate: disable if flow ratio exceeds threshold
        3. Edge requirement: only quote if edge sufficient to cover fees + buffer
        4. Directional alpha gate: only post non-preferred side if alpha strong
        
        Args:
            bid_size (float): Proposed bid size
            ask_size (float): Proposed ask size
            features (Dict[str, float]): Market features
            signal (Dict[str, float]): Price signal
            reservation_price (float): Inventory-adjusted fair price
            bid_price (float): Proposed bid price
            ask_price (float): Proposed ask price
            risk_state (Dict[str, float]): Risk state
            
        Returns:
            tuple[float, float]: Filtered bid_size, ask_size (may be set to 0)
        """
        # Use one-side maker fee as the required edge for quoting.
        # In practice, the market-making edge available when posting a single side
        # is often close to half the full spread, so using 2x fee here would
        # prevent quoting in normal narrow-spread conditions.
        required_edge_bps = 1.0 * self.maker_fee_rate * 1e4 + self.min_required_edge_buffer_bps
        short_vol_ok = features["volatility_5s_bps"] <= self.max_volatility_to_quote_bps
        flow_ratio = abs(features["trade_flow_5s"]) / max(features["depth_total_5"], 1e-8)
        flow_ok = flow_ratio <= self.max_flow_ratio_to_quote
        alpha_bps = signal["alpha_bps"]

        bid_edge_bps = max((reservation_price - bid_price) / max(features["mid"], 1e-8) * 1e4, 0.0) + max(alpha_bps, 0.0)
        ask_edge_bps = max((ask_price - reservation_price) / max(features["mid"], 1e-8) * 1e4, 0.0) + max(-alpha_bps, 0.0)

        if not (short_vol_ok and flow_ok):
            if risk_state["inventory_fraction"] > 0.0:
                bid_size = 0.0
            elif risk_state["inventory_fraction"] < 0.0:
                ask_size = 0.0
            else:
                bid_size = 0.0
                ask_size = 0.0

        if bid_edge_bps < required_edge_bps:
            bid_size = 0.0
        if ask_edge_bps < required_edge_bps:
            ask_size = 0.0

        if not self.allow_two_sided_when_alpha_small:
            if alpha_bps >= self.min_directional_alpha_bps:
                ask_size = 0.0 if risk_state["inventory_fraction"] <= 0.0 else ask_size
            elif alpha_bps <= -self.min_directional_alpha_bps:
                bid_size = 0.0 if risk_state["inventory_fraction"] >= 0.0 else bid_size
            else:
                if abs(risk_state["inventory_fraction"]) < 1e-12:
                    bid_size = 0.0
                    ask_size = 0.0
        else:
            if abs(risk_state["inventory_fraction"]) < self.inventory_unwind_threshold_fraction:
                if alpha_bps >= self.min_directional_alpha_bps:
                    ask_size *= 0.7
                elif alpha_bps <= -self.min_directional_alpha_bps:
                    bid_size *= 0.7

        return bid_size, ask_size
