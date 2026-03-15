from dataclasses import dataclass
from typing import Dict

from utils import ceil_to_tick, clamp, floor_to_tick


@dataclass
class QuoteTarget:
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
        required_roundtrip_bps = 2.0 * self.maker_fee_rate * 1e4 + self.min_required_edge_buffer_bps
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

        if bid_edge_bps < required_roundtrip_bps:
            bid_size = 0.0
        if ask_edge_bps < required_roundtrip_bps:
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
