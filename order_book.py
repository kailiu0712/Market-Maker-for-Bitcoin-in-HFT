"""
Local order book management module.

Maintains:
- Bid and ask side order book depths
- Order book validity checks
- Metrics: best bid/ask, mid price, spread, imbalance, microprice
"""

from typing import Dict, List, Optional, Tuple

from data_loader import MarketEvent
from utils import EPS, safe_div


class LocalOrderBook:
    """
    In-memory order book maintaining bid and ask side levels.
    
    Supports:
    - Updating price levels with remaining depth
    - Automatic pruning of crossed books (when best_bid >= best_ask)
    - Querying best price, mid price, spread
    - Depth and imbalance calculations
    - Microprice-weighted pricing
    """
    def __init__(self) -> None:
        self.book: Dict[str, Dict[float, float]] = {"BID": {}, "ASK": {}}

    def apply_event(self, event: MarketEvent) -> None:
        """
        Apply a market event to the order book (updates levels for book events).
        
        Args:
            event (MarketEvent): Market event to apply
            
        Returns:
            None
        """
        if not event.is_book_event:
            return
        self.update_level(event.side, event.price, float(event.remaining))
        self.prune_crossed_book(event.side)

    def update_level(self, side: str, price: float, remaining: float) -> None:
        """
        Update order book level at given price.
        
        Args:
            side (str): "BID" or "ASK"
            price (float): Price level
            remaining (float): Remaining quantity at this level (0 to remove)
            
        Returns:
            None
        """
        side = side.upper()
        if side not in self.book:
            return
        if remaining <= EPS:
            self.book[side].pop(price, None)
        else:
            self.book[side][price] = remaining

    def prune_crossed_book(self, anchor_side: str) -> None:
        """
        Remove crossed levels (best_bid >= best_ask) from order book.
        
        Removes from the non-anchor side to resolve the cross.
        
        Args:
            anchor_side (str): "BID" or "ASK" - the side that triggered the update
            
        Returns:
            None
        """
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
        """
        Get the best (highest) bid price.
        
        Returns:
            Optional[float]: Best bid price or None if no bids
        """
        return max(self.book["BID"]) if self.book["BID"] else None

    def best_ask(self) -> Optional[float]:
        """
        Get the best (lowest) ask price.
        
        Returns:
            Optional[float]: Best ask price or None if no asks
        """
        return min(self.book["ASK"]) if self.book["ASK"] else None

    def mid_price(self) -> Optional[float]:
        """
        Get the mid price (average of best bid and ask).
        
        Returns:
            Optional[float]: Mid price or None if book is one-sided or crossed
        """
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None or best_ask <= best_bid:
            return None
        return 0.5 * (best_bid + best_ask)

    def spread(self) -> Optional[float]:
        """
        Get the bid-ask spread (ask - bid).
        
        Returns:
            Optional[float]: Bid-ask spread or None if book is invalid
        """
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None or best_ask <= best_bid:
            return None
        return best_ask - best_bid

    def depth_at_price(self, side: str, price: float) -> float:
        """
        Get the depth (quantity) at a specific price level.
        
        Args:
            side (str): "BID" or "ASK"
            price (float): Price level
            
        Returns:
            float: Quantity at price (0 if level doesn't exist)
        """
        return float(self.book[side.upper()].get(price, 0.0))

    def top_levels(self, side: str, levels: int = 5) -> List[Tuple[float, float]]:
        """
        Get the top price/quantity pairs for a side.
        
        Args:
            side (str): "BID" or "ASK"
            levels (int): Number of price levels to return
            
        Returns:
            List[Tuple[float, float]]: List of (price, quantity) pairs
        """
        side = side.upper()
        if side == "BID":
            prices = sorted(self.book["BID"], reverse=True)[:levels]
            return [(price, self.book["BID"][price]) for price in prices]
        if side == "ASK":
            prices = sorted(self.book["ASK"])[:levels]
            return [(price, self.book["ASK"][price]) for price in prices]
        return []

    def depth(self, side: str, levels: int = 5) -> float:
        """
        Get the total depth (sum of quantities) at top levels.
        
        Args:
            side (str): "BID" or "ASK"
            levels (int): Number of levels to sum
            
        Returns:
            float: Total quantity across top levels
        """
        return float(sum(size for _, size in self.top_levels(side, levels=levels)))

    def microprice(self) -> Optional[float]:
        """
        Get the microprice (quantity-weighted price of best bid/ask).
        
        The microprice weights the best bid and ask by their opposite side's size.
        This represents the expected fill price if you were to immediately trade.
        
        Returns:
            Optional[float]: Microprice or None if book is invalid or one-sided
        """
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
        """
        Get the order book imbalance ratio.
        
        Imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
        Ranges from -1 (all ask) to +1 (all bid)
        
        Args:
            levels (int): Number of price levels to consider
            
        Returns:
            float: Imbalance ratio in [-1, 1]
        """
        bid_depth = self.depth("BID", levels=levels)
        ask_depth = self.depth("ASK", levels=levels)
        return safe_div(bid_depth - ask_depth, bid_depth + ask_depth)

    def is_valid(self) -> bool:
        """
        Check if order book is in a valid state.
        
        Valid = has both sides with positive spread.
        
        Returns:
            bool: True if book is valid
        """
        spread = self.spread()
        return spread is not None and spread > 0.0
