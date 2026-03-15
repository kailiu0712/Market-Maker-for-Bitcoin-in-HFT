from typing import Dict, List, Optional, Tuple

from data_loader import MarketEvent
from utils import EPS, safe_div


class LocalOrderBook:
    def __init__(self) -> None:
        self.book: Dict[str, Dict[float, float]] = {"BID": {}, "ASK": {}}

    def apply_event(self, event: MarketEvent) -> None:
        if not event.is_book_event:
            return
        self.update_level(event.side, event.price, float(event.remaining))
        self.prune_crossed_book(event.side)

    def update_level(self, side: str, price: float, remaining: float) -> None:
        side = side.upper()
        if side not in self.book:
            return
        if remaining <= EPS:
            self.book[side].pop(price, None)
        else:
            self.book[side][price] = remaining

    def prune_crossed_book(self, anchor_side: str) -> None:
        anchor_side = anchor_side.upper()
        while self.book["BID"] and self.book["ASK"]:
            best_bid = max(self.book["BID"])
            best_ask = min(self.book["ASK"])
            if best_ask > best_bid:
                return
            if anchor_side == "ASK":
                self.book["BID"].pop(best_bid, None)
            else:
                self.book["ASK"].pop(best_ask, None)

    def best_bid(self) -> Optional[float]:
        return max(self.book["BID"]) if self.book["BID"] else None

    def best_ask(self) -> Optional[float]:
        return min(self.book["ASK"]) if self.book["ASK"] else None

    def mid_price(self) -> Optional[float]:
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None or best_ask <= best_bid:
            return None
        return 0.5 * (best_bid + best_ask)

    def spread(self) -> Optional[float]:
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None or best_ask <= best_bid:
            return None
        return best_ask - best_bid

    def depth_at_price(self, side: str, price: float) -> float:
        return float(self.book[side.upper()].get(price, 0.0))

    def top_levels(self, side: str, levels: int = 5) -> List[Tuple[float, float]]:
        side = side.upper()
        if side == "BID":
            prices = sorted(self.book["BID"], reverse=True)[:levels]
            return [(price, self.book["BID"][price]) for price in prices]
        if side == "ASK":
            prices = sorted(self.book["ASK"])[:levels]
            return [(price, self.book["ASK"][price]) for price in prices]
        return []

    def depth(self, side: str, levels: int = 5) -> float:
        return float(sum(size for _, size in self.top_levels(side, levels=levels)))

    def microprice(self) -> Optional[float]:
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        bid_size = self.depth_at_price("BID", best_bid)
        ask_size = self.depth_at_price("ASK", best_ask)
        if bid_size <= EPS and ask_size <= EPS:
            return self.mid_price()
        return safe_div(best_ask * bid_size + best_bid * ask_size, bid_size + ask_size, default=self.mid_price() or 0.0)

    def imbalance(self, levels: int = 1) -> float:
        bid_depth = self.depth("BID", levels=levels)
        ask_depth = self.depth("ASK", levels=levels)
        return safe_div(bid_depth - ask_depth, bid_depth + ask_depth)

    def is_valid(self) -> bool:
        spread = self.spread()
        return spread is not None and spread > 0.0
