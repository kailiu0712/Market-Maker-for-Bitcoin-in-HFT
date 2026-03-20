"""
Execution simulation and fill model module.

Simulates order book matching and fills:
- Tracks posted quotes (bid and ask)
- Manages queue position for limit orders
- Simulates trade fills based on fill probability model
- Logs all quote activities and fills
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from data_loader import MarketEvent
from order_book import LocalOrderBook


@dataclass
class WorkingQuote:
    """
    Represents a posted market-making quote.
    
    Attributes:
        side (str): "BID" or "ASK"
        price (float): Posted quote price
        size (float): Original order size
        remaining_size (float): Current remaining quantity
        queue_ahead (float): Estimated quantity ahead in queue
        posted_ts (int): Timestamp when quote was posted
        posted_seq (int): Event sequence when quote was posted
        active (bool): Whether quote is still active (not fully filled)
    """
    side: str
    price: float
    size: float
    remaining_size: float
    queue_ahead: float
    posted_ts: int
    posted_seq: int
    active: bool = True


class ExecutionSimulator:
    """
    Simulates order execution and fill generation.
    
    Maintains working quotes and processes trades:
    - Tracks active bid and ask quotes
    - Processes incoming trades to generate fills
    - Updates queue position based on order book events
    - Logs all quote events and fills
    
    Uses configurable fill probabilities:
    - touch_fill_fraction: probability of fill at our posted price
    - improved_price_fill_fraction: probability of fill at better prices
    """
    def __init__(
        self,
        touch_fill_fraction: float,
        improved_price_fill_fraction: float,
        min_fill_size: float,
        price_tick: float,
        quote_reprice_threshold_ticks: float,
        quote_max_age_ms: int,
    ) -> None:
        """
        Initialize the execution simulator.
        
        Args:
            touch_fill_fraction (float): Probability of fill at touch (our price)
            improved_price_fill_fraction (float): Probability of fill at better prices
            min_fill_size (float): Minimum size to record as fill
            price_tick (float): Price grid granularity
            quote_reprice_threshold_ticks (float): Price move before forced reprice
            quote_max_age_ms (int): Max age before quote must refresh
        """
        self.touch_fill_fraction = touch_fill_fraction
        self.improved_price_fill_fraction = improved_price_fill_fraction
        self.min_fill_size = min_fill_size
        self.price_tick = price_tick
        self.quote_reprice_threshold = quote_reprice_threshold_ticks * price_tick
        self.quote_max_age_ms = int(quote_max_age_ms)
        self.bid_quote: Optional[WorkingQuote] = None
        self.ask_quote: Optional[WorkingQuote] = None
        self.quote_log: List[Dict[str, float]] = []
        self.fill_log: List[Dict[str, float]] = []

    def refresh_quotes(self, timestampms: int, seq: int, book: LocalOrderBook, quote_target, inventory: float) -> None:
        """
        Update working quotes based on new quote targets.
        
        Refreshes bid and ask quotes if:
        - No existing quote
        - Price change exceeds reprice threshold
        - Quote has aged beyond max age
        - Size has changed significantly
        
        Otherwise keeps existing quote to maintain queue position.
        
        Args:
            timestampms (int): Current timestamp
            seq (int): Event sequence number
            book (LocalOrderBook): Current order book state
            quote_target: Target quote with new bid/ask prices and sizes
            inventory (float): Current inventory position
            
        Returns:
            None
        """
        self.bid_quote = self._refresh_one_quote(self.bid_quote, "BID", quote_target.bid_price, quote_target.bid_size, timestampms, seq, book, inventory, quote_target)
        self.ask_quote = self._refresh_one_quote(self.ask_quote, "ASK", quote_target.ask_price, quote_target.ask_size, timestampms, seq, book, inventory, quote_target)

    def process_event(self, event: MarketEvent) -> List[Dict[str, float]]:
        """
        Process a market event and generate fills if applicable.
        
        For TRADE events: Check if our quotes match and simulate fills.
        For CANCEL/FILL_UPDATE: Update queue position.
        
        Args:
            event (MarketEvent): Market event to process
            
        Returns:
            List[Dict[str, float]]: List of fills (may be empty)
        """
        fills: List[Dict[str, float]] = []
        if event.action == "TRADE":
            fill = self._process_trade(event)
            if fill is not None:
                fills.append(fill)
                self.fill_log.append(fill)
        elif event.action in {"CANCEL", "FILL_UPDATE"}:
            self._update_queue_ahead(event)
        return fills

    def _refresh_one_quote(self, existing, side, price, size, timestampms, seq, book, inventory, quote_target):
        if size <= 0.0:
            if existing is not None and existing.active:
                self.quote_log.append(
                    {
                        "timestampms": timestampms,
                        "seq": seq,
                        "event": "cancel",
                        "side": side,
                        "price": existing.price,
                        "size": existing.remaining_size,
                        "queue_ahead": existing.queue_ahead,
                        "inventory": inventory,
                        "fair_price": quote_target.fair_price,
                        "reservation_price": quote_target.reservation_price,
                    }
                )
            return None

        if existing is not None and existing.active:
            same_price = abs(existing.price - price) < 1e-12
            same_size = abs(existing.size - size) < 1e-12
            if same_price and same_size:
                return existing
            price_move_small = abs(existing.price - price) <= self.quote_reprice_threshold
            quote_not_stale = (timestampms - existing.posted_ts) < self.quote_max_age_ms
            if price_move_small and quote_not_stale and existing.remaining_size > self.min_fill_size:
                return existing

        best_bid = book.best_bid()
        best_ask = book.best_ask()
        if side == "BID" and (best_bid is None or price > best_bid):
            queue_ahead = 0.0
        elif side == "ASK" and (best_ask is None or price < best_ask):
            queue_ahead = 0.0
        else:
            queue_ahead = book.depth_at_price(side, price)

        quote = WorkingQuote(
            side=side,
            price=float(price),
            size=float(size),
            remaining_size=float(size),
            queue_ahead=float(queue_ahead),
            posted_ts=timestampms,
            posted_seq=seq,
            active=True,
        )
        self.quote_log.append(
            {
                "timestampms": timestampms,
                "seq": seq,
                "event": "new" if existing is None else "replace",
                "side": side,
                "price": quote.price,
                "size": quote.size,
                "queue_ahead": quote.queue_ahead,
                "inventory": inventory,
                "fair_price": quote_target.fair_price,
                "reservation_price": quote_target.reservation_price,
            }
        )
        return quote

    def _process_trade(self, event: MarketEvent) -> Optional[Dict[str, float]]:
        """
        Process a trade event and simulate fill against our quote.
        
        Generates fill only if:
        1. We have an active quote on the passive side
        2. Trade price matches our quote (at touch) or better (improved)
        3. Trade size allows for partial fill after queue ahead
        
        Uses different fill fractions for:
        - Touch (our price): lower fill probability (lower priority)
        - Improved (better price): higher fill probability (we're favored)
        
        Args:
            event (MarketEvent): Trade event
            
        Returns:
            Optional[Dict[str, float]]: Fill details or None if no fill
        """
        passive_side = event.passive_side
        if passive_side == "BID":
            quote = self.bid_quote
            price_condition = quote is not None and event.price <= quote.price
        elif passive_side == "ASK":
            quote = self.ask_quote
            price_condition = quote is not None and event.price >= quote.price
        else:
            return None

        if quote is None or not quote.active or not price_condition:
            return None

        if abs(event.price - quote.price) < 1e-12:
            available_size = max(event.amount - quote.queue_ahead, 0.0) * self.touch_fill_fraction
            quote.queue_ahead = max(quote.queue_ahead - event.amount, 0.0)
        else:
            available_size = event.amount * self.improved_price_fill_fraction

        fill_size = min(quote.remaining_size, available_size)
        if fill_size < self.min_fill_size:
            return None

        quote.remaining_size -= fill_size
        if quote.remaining_size <= self.min_fill_size:
            quote.active = False
            quote.remaining_size = 0.0

        return {
            "timestampms": event.timestampms,
            "seq": event.seq,
            "quote_side": quote.side,
            "trade_side": event.side,
            "fill_price": quote.price,
            "fill_size": fill_size,
            "trade_price": event.price,
            "trade_size": event.amount,
            "queue_ahead_after": quote.queue_ahead,
            "quote_remaining_after": quote.remaining_size,
        }

    def _update_queue_ahead(self, event: MarketEvent) -> None:
        """
        Update queue position for working quotes.
        
        When market orders are cancelled or partially filled on the same side
        and price as our quote, our queue position improves.
        
        Args:
            event (MarketEvent): CANCEL or FILL_UPDATE event
            
        Returns:
            None
        """
        for quote in (self.bid_quote, self.ask_quote):
            if quote is None or not quote.active:
                continue
            if quote.side != event.side:
                continue
            if abs(quote.price - event.price) >= 1e-12:
                continue
            quote.queue_ahead = max(quote.queue_ahead - event.amount, 0.0)
