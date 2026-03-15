from collections import deque
from math import log, sqrt
from typing import Deque, Dict, Tuple

from data_loader import MarketEvent
from order_book import LocalOrderBook
from utils import EPS, safe_div


class FeatureEngine:
    def __init__(
        self,
        flow_window_ms: int,
        book_flow_window_ms: int,
        volatility_window_ms: int,
        long_vol_window_ms: int,
    ) -> None:
        self.flow_window_ms = flow_window_ms
        self.book_flow_window_ms = book_flow_window_ms
        self.volatility_window_ms = volatility_window_ms
        self.long_vol_window_ms = long_vol_window_ms

        self.trade_flow: Deque[Tuple[int, float]] = deque()
        self.trade_counts: Deque[Tuple[int, float]] = deque()
        self.book_flow: Deque[Tuple[int, float]] = deque()
        self.abs_returns_short: Deque[Tuple[int, float]] = deque()
        self.abs_returns_long: Deque[Tuple[int, float]] = deque()

        self.last_mid = None
        self.last_mid_ts = None

    def update(self, event: MarketEvent, book: LocalOrderBook) -> None:
        ts = event.timestampms

        if event.action == "TRADE":
            signed_trade = event.amount if event.side == "BUY" else -event.amount
            self.trade_flow.append((ts, signed_trade))
            self.trade_counts.append((ts, 1.0))
        elif event.action in {"PLACE", "CANCEL", "FILL_UPDATE"} and event.side in {"BID", "ASK"}:
            side_sign = 1.0 if event.side == "BID" else -1.0
            action_sign = 1.0 if event.action == "PLACE" else -1.0
            self.book_flow.append((ts, side_sign * action_sign * event.amount))

        if book.is_valid():
            mid = book.mid_price()
            if mid is not None and self.last_mid is not None and mid > EPS and self.last_mid > EPS:
                abs_log_ret = abs(log(mid / self.last_mid))
                if ts != self.last_mid_ts or abs(mid - self.last_mid) > EPS:
                    self.abs_returns_short.append((ts, abs_log_ret))
                    self.abs_returns_long.append((ts, abs_log_ret))
            self.last_mid = mid
            self.last_mid_ts = ts

        self._purge(ts)

    def compute(self, timestampms: int, book: LocalOrderBook) -> Dict[str, float]:
        self._purge(timestampms)

        best_bid = book.best_bid()
        best_ask = book.best_ask()
        mid = book.mid_price() or 0.0
        spread = book.spread() or 0.0
        microprice = book.microprice() or mid
        depth_bid_1 = book.depth("BID", levels=1)
        depth_ask_1 = book.depth("ASK", levels=1)
        depth_bid_5 = book.depth("BID", levels=5)
        depth_ask_5 = book.depth("ASK", levels=5)

        trade_flow_5s = sum(value for _, value in self.trade_flow)
        book_flow_5s = sum(value for _, value in self.book_flow)
        trade_count_5s = sum(value for _, value in self.trade_counts)
        vol_short_bps = 1e4 * sqrt(sum(value * value for _, value in self.abs_returns_short))
        vol_long_bps = 1e4 * sqrt(sum(value * value for _, value in self.abs_returns_long))

        return {
            "best_bid": 0.0 if best_bid is None else best_bid,
            "best_ask": 0.0 if best_ask is None else best_ask,
            "mid": mid,
            "spread": spread,
            "microprice": microprice,
            "microprice_edge_bps": 1e4 * safe_div(microprice - mid, mid),
            "imbalance_1": book.imbalance(levels=1),
            "imbalance_5": book.imbalance(levels=5),
            "depth_bid_1": depth_bid_1,
            "depth_ask_1": depth_ask_1,
            "depth_bid_5": depth_bid_5,
            "depth_ask_5": depth_ask_5,
            "depth_total_5": depth_bid_5 + depth_ask_5,
            "trade_flow_5s": trade_flow_5s,
            "book_flow_5s": book_flow_5s,
            "trade_intensity_5s": trade_count_5s / max(self.flow_window_ms / 1000.0, 1.0),
            "volatility_5s_bps": vol_short_bps,
            "volatility_60s_bps": vol_long_bps,
        }

    def _purge(self, timestampms: int) -> None:
        self._purge_deque(self.trade_flow, timestampms - self.flow_window_ms)
        self._purge_deque(self.trade_counts, timestampms - self.flow_window_ms)
        self._purge_deque(self.book_flow, timestampms - self.book_flow_window_ms)
        self._purge_deque(self.abs_returns_short, timestampms - self.volatility_window_ms)
        self._purge_deque(self.abs_returns_long, timestampms - self.long_vol_window_ms)

    @staticmethod
    def _purge_deque(values: Deque[Tuple[int, float]], cutoff: int) -> None:
        while values and values[0][0] < cutoff:
            values.popleft()
