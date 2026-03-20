"""
Market-making backtest simulator.

Orchestrates the end-to-end backtesting process:
- Loads market event data
- Simulates order book and trade events
- Quotes prices based on fair value and risk management
- Executes fills and tracks P&L
- Generates performance metrics
"""

from typing import Dict, List

import pandas as pd

from data_loader import inspect_schema, stream_market_events
from execution_simulator import ExecutionSimulator
from feature_engine import FeatureEngine
from metrics import build_metrics
from order_book import LocalOrderBook
from quote_engine import QuoteEngine
from risk_manager import RiskManager
from signal_engine import SignalEngine
from utils import EPS, safe_div


class MarketMakingBacktester:
    """
    End-to-end market-making backtest simulator.
    
    Integrates multiple components:
    - LocalOrderBook: order book state management
    - FeatureEngine: market microstructure feature computation
    - SignalEngine: directional signal generation
    - RiskManager: inventory-based risk limits
    - QuoteEngine: quote price and size generation
    - ExecutionSimulator: fill simulation
    
    Processes market events sequentially and logs state at regular intervals.
    Produces detailed fills, quotes, and state timeseries DataFrames.
    """
    def __init__(self, config_module) -> None:
        """
        Initialize the backtest simulator with configuration.
        
        Creates instances of all strategy components and sets up
        state tracking variables (inventory, cash, P&L).
        
        Args:
            config_module: Configuration module with all strategy parameters
        """
        self.cfg = config_module
        self.book = LocalOrderBook()
        self.feature_engine = FeatureEngine(
            flow_window_ms=self.cfg.FLOW_WINDOW_MS,
            book_flow_window_ms=self.cfg.BOOK_FLOW_WINDOW_MS,
            volatility_window_ms=self.cfg.VOLATILITY_WINDOW_MS,
            long_vol_window_ms=self.cfg.LONG_VOL_WINDOW_MS,
        )
        self.signal_engine = SignalEngine(
            microprice_weight=self.cfg.MICROPRICE_WEIGHT,
            imbalance_alpha_bps=self.cfg.IMBALANCE_ALPHA_BPS,
            trade_flow_alpha_bps=self.cfg.TRADE_FLOW_ALPHA_BPS,
            book_flow_alpha_bps=self.cfg.BOOK_FLOW_ALPHA_BPS,
            alpha_clip_bps=self.cfg.ALPHA_CLIP_BPS,
        )
        self.risk_manager = RiskManager(
            max_inventory=self.cfg.MAX_INVENTORY,
            inventory_target=self.cfg.INVENTORY_TARGET,
            inventory_soft_limit_fraction=self.cfg.INVENTORY_SOFT_LIMIT_FRACTION,
            size_skew_factor=self.cfg.SIZE_SKEW_FACTOR,
        )
        self.quote_engine = QuoteEngine(
            price_tick=self.cfg.PRICE_TICK,
            base_order_size=self.cfg.BASE_ORDER_SIZE,
            min_order_size=self.cfg.MIN_ORDER_SIZE,
            min_half_spread_ticks=self.cfg.MIN_HALF_SPREAD_TICKS,
            market_spread_multiplier=self.cfg.MARKET_SPREAD_MULTIPLIER,
            volatility_spread_multiplier=self.cfg.VOLATILITY_SPREAD_MULTIPLIER,
            flow_spread_multiplier=self.cfg.FLOW_SPREAD_MULTIPLIER,
            inventory_spread_multiplier=self.cfg.INVENTORY_SPREAD_MULTIPLIER,
            inventory_skew_ticks=self.cfg.INVENTORY_SKEW_TICKS,
            maker_fee_rate=self.cfg.MAKER_FEE_RATE,
            min_required_edge_buffer_bps=self.cfg.MIN_REQUIRED_EDGE_BUFFER_BPS,
            max_volatility_to_quote_bps=self.cfg.MAX_VOLATILITY_TO_QUOTE_BPS,
            max_flow_ratio_to_quote=self.cfg.MAX_FLOW_RATIO_TO_QUOTE,
            min_directional_alpha_bps=self.cfg.MIN_DIRECTIONAL_ALPHA_BPS,
            allow_two_sided_when_alpha_small=self.cfg.ALLOW_TWO_SIDED_WHEN_ALPHA_SMALL,
            inventory_unwind_threshold_fraction=self.cfg.INVENTORY_UNWIND_THRESHOLD_FRACTION,
            inventory_unwind_join_touch=self.cfg.INVENTORY_UNWIND_JOIN_TOUCH,
            inventory_unwind_size_multiplier=self.cfg.INVENTORY_UNWIND_SIZE_MULTIPLIER,
            calm_market_vol_threshold_bps=self.cfg.CALM_MARKET_VOL_THRESHOLD_BPS,
            calm_market_spread_threshold_bps=self.cfg.CALM_MARKET_SPREAD_THRESHOLD_BPS,
            calm_market_tightening_factor=self.cfg.CALM_MARKET_TIGHTENING_FACTOR,
        )
        self.execution_simulator = ExecutionSimulator(
            touch_fill_fraction=self.cfg.TOUCH_FILL_FRACTION,
            improved_price_fill_fraction=self.cfg.IMPROVED_PRICE_FILL_FRACTION,
            min_fill_size=self.cfg.MIN_FILL_SIZE,
            price_tick=self.cfg.PRICE_TICK,
            quote_reprice_threshold_ticks=self.cfg.QUOTE_REPRICE_THRESHOLD_TICKS,
            quote_max_age_ms=self.cfg.QUOTE_MAX_AGE_MS,
        )

        self.inventory = 0.0
        self.cash = float(self.cfg.INITIAL_CASH)
        self.realized_pnl = 0.0
        self.avg_cost = 0.0
        self.trade_count = 0
        self.processed_events = 0
        self.next_quote_refresh_ts = None
        self.next_state_log_ts = None
        self.state_rows: List[Dict[str, float]] = []

    def run(self) -> Dict[str, object]:
        """
        Execute the complete backtest.
        
        Workflow:
        1. Inspect and log input data schema
        2. Stream market events from data file
        3. Process each event (update book, compute features, generate quotes)
        4. Track fills and state at regular intervals
        5. Build performance metrics
        6. Return comprehensive results
        
        Returns:
            Dict[str, object]: Dictionary with keys:
                - schema_summary: Input data statistics and structure
                - state_df: Full state timeseries (inventory, equity, etc.)
                - fill_df: All fills executed with details
                - quote_df: All quote refreshes with details
                - metrics_df: Summary performance metrics
        """
        schema_summary = inspect_schema(
            csv_path=self.cfg.RAW_EVENT_CSV,
            min_valid_price=self.cfg.MIN_VALID_PRICE,
            max_valid_price=self.cfg.MAX_VALID_PRICE,
            min_valid_amount=self.cfg.MIN_VALID_AMOUNT,
            max_valid_amount=self.cfg.MAX_VALID_AMOUNT,
        )

        for event in stream_market_events(
            csv_path=self.cfg.RAW_EVENT_CSV,
            min_valid_price=self.cfg.MIN_VALID_PRICE,
            max_valid_price=self.cfg.MAX_VALID_PRICE,
            min_valid_amount=self.cfg.MIN_VALID_AMOUNT,
            max_valid_amount=self.cfg.MAX_VALID_AMOUNT,
            max_events=self.cfg.MAX_EVENTS,
        ):
            self._process_event(event)

        state_df = pd.DataFrame(self.state_rows)
        fill_df = pd.DataFrame(self.execution_simulator.fill_log)
        quote_df = pd.DataFrame(self.execution_simulator.quote_log)

        if not fill_df.empty:
            fill_df["signed_qty"] = fill_df["fill_size"].where(fill_df["quote_side"].eq("BID"), -fill_df["fill_size"])
            fill_df["notional"] = fill_df["fill_size"] * fill_df["fill_price"]
            fill_df["fee"] = fill_df["notional"] * self.cfg.MAKER_FEE_RATE

        metrics_df = build_metrics(
            state_df=state_df,
            fill_df=fill_df,
            quote_df=quote_df,
            maker_fee_rate=self.cfg.MAKER_FEE_RATE,
        )
        metrics_df["processed_events"] = float(self.processed_events)
        metrics_df["configured_max_events"] = float(self.cfg.MAX_EVENTS if self.cfg.MAX_EVENTS is not None else -1)

        return {
            "schema_summary": schema_summary,
            "state_df": state_df,
            "fill_df": fill_df,
            "quote_df": quote_df,
            "metrics_df": metrics_df,
        }

    def _process_event(self, event) -> None:
        """
        Process a single market event.
        
        Steps:
        1. Update order book if book event
        2. Simulate fills if trade event
        3. Compute features if book is valid
        4. Generate and place quotes at refresh intervals
        5. Log state at logging intervals
        6. Report progress
        
        Args:
            event: Market event to process
            
        Returns:
            None
        """
        self.processed_events += 1

        if event.action == "TRADE":
            fills = self.execution_simulator.process_event(event)
            for fill in fills:
                self._apply_fill(fill)

        if event.is_book_event:
            self.book.apply_event(event)

        if event.action in {"CANCEL", "FILL_UPDATE"}:
            self.execution_simulator.process_event(event)

        if not self.book.is_valid():
            return

        self.feature_engine.update(event, self.book)

        if self._should_refresh_quotes(event.timestampms):
            features = self.feature_engine.compute(event.timestampms, self.book)
            signal = self.signal_engine.compute(features)
            risk_state = self.risk_manager.side_adjustments(self.inventory)
            quote_target = self.quote_engine.generate(
                timestampms=event.timestampms,
                features=features,
                signal=signal,
                risk_state=risk_state,
            )
            self.execution_simulator.refresh_quotes(
                timestampms=event.timestampms,
                seq=event.seq,
                book=self.book,
                quote_target=quote_target,
                inventory=self.inventory,
            )
            self.next_quote_refresh_ts = event.timestampms + self.cfg.QUOTE_REFRESH_MS

        if self._should_log_state(event.timestampms):
            self._log_state(event.timestampms, event.seq)
            self.next_state_log_ts = event.timestampms + self.cfg.STATE_LOG_INTERVAL_MS

        if self.processed_events % self.cfg.REPORT_EVERY_N_EVENTS == 0:
            print(f"Processed {self.processed_events:,} events")

    def _apply_fill(self, fill: Dict[str, float]) -> None:
        """
        Apply a fill to inventory and cash positions.
        
        Updates:
        - Inventory (add/subtract fill size)
        - Cash (deduct payment + fees / add proceeds - fees)
        - Average cost (for P&L tracking)
        - Realized P&L (for closing positions)
        
        Args:
            fill (Dict[str, float]): Fill with quote_side, fill_size, fill_price
            
        Returns:
            None
        """
        side = fill["quote_side"]
        qty = fill["fill_size"]
        price = fill["fill_price"]
        fee = qty * price * self.cfg.MAKER_FEE_RATE

        if side == "BID":
            self.cash -= qty * price + fee
            new_inventory = self.inventory + qty
            if self.inventory >= 0.0:
                weighted_cost = self.avg_cost * max(self.inventory, 0.0) + qty * price
                self.avg_cost = safe_div(weighted_cost, max(new_inventory, EPS), default=price)
            else:
                close_qty = min(qty, abs(self.inventory))
                self.realized_pnl += close_qty * (self.avg_cost - price)
                if new_inventory > 0.0:
                    self.avg_cost = price
            self.inventory = new_inventory
        else:
            self.cash += qty * price - fee
            new_inventory = self.inventory - qty
            if self.inventory <= 0.0:
                weighted_cost = self.avg_cost * max(abs(self.inventory), 0.0) + qty * price
                self.avg_cost = safe_div(weighted_cost, max(abs(new_inventory), EPS), default=price)
            else:
                close_qty = min(qty, self.inventory)
                self.realized_pnl += close_qty * (price - self.avg_cost)
                if new_inventory < 0.0:
                    self.avg_cost = price
            self.inventory = new_inventory

        fill["inventory_after"] = self.inventory
        fill["cash_after"] = self.cash
        fill["fee"] = fee
        fill["notional"] = qty * price
        fill["realized_pnl_after"] = self.realized_pnl
        self.trade_count += 1

    def _should_refresh_quotes(self, timestampms: int) -> bool:
        """
        Check if quotes should be refreshed at this timestamp.
        
        Based on QUOTE_REFRESH_MS interval.
        
        Args:
            timestampms (int): Current timestamp
            
        Returns:
            bool: True if refresh due
        """
        if self.next_quote_refresh_ts is None:
            return True
        return timestampms >= self.next_quote_refresh_ts

    def _should_log_state(self, timestampms: int) -> bool:
        """
        Check if state should be logged at this timestamp.
        
        Based on STATE_LOG_INTERVAL_MS interval.
        
        Args:
            timestampms (int): Current timestamp
            
        Returns:
            bool: True if logging due
        """
        if self.next_state_log_ts is None:
            return True
        return timestampms >= self.next_state_log_ts

    def _log_state(self, timestampms: int, seq: int) -> None:
        """
        Log current strategy state snapshot.
        
        Captures:
        - Price levels (best bid/ask, mid)
        - Positions (inventory, cash, realized P&L)
        - Equity (mark-to-market and liquidation)
        - Trading activity (trade count, active quotes)
        
        Args:
            timestampms (int): Timestamp of snapshot
            seq (int): Event sequence number
            
        Returns:
            None
        """
        mid = self.book.mid_price() or 0.0
        best_bid = self.book.best_bid() or 0.0
        best_ask = self.book.best_ask() or 0.0
        equity_mtm = self.cash + self.inventory * mid
        liquidation_price = best_bid if self.inventory > 0 else best_ask if self.inventory < 0 else mid
        equity_liquidation = self.cash + self.inventory * liquidation_price - abs(self.inventory) * liquidation_price * self.cfg.LIQUIDATION_FEE_RATE
        total_pnl_mtm = equity_mtm - float(self.cfg.INITIAL_CASH)
        total_pnl_liquidation = equity_liquidation - float(self.cfg.INITIAL_CASH)
        # Realized PnL only tracks closed-position price differences in this model.
        # The remaining mark-to-market contribution, including open-position fees,
        # belongs in unrealized PnL so realized + unrealized = total PnL.
        unrealized_pnl = total_pnl_mtm - self.realized_pnl

        self.state_rows.append(
            {
                "timestampms": timestampms,
                "seq": seq,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "inventory": self.inventory,
                "cash": self.cash,
                "avg_cost": self.avg_cost,
                "realized_pnl": self.realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "equity_mtm": equity_mtm,
                "equity_liquidation": equity_liquidation,
                "total_pnl_mtm": total_pnl_mtm,
                "total_pnl_liquidation": total_pnl_liquidation,
                "trade_count": self.trade_count,
                "bid_quote_price": None if self.execution_simulator.bid_quote is None else self.execution_simulator.bid_quote.price,
                "ask_quote_price": None if self.execution_simulator.ask_quote is None else self.execution_simulator.ask_quote.price,
                "bid_quote_size": None if self.execution_simulator.bid_quote is None else self.execution_simulator.bid_quote.remaining_size,
                "ask_quote_size": None if self.execution_simulator.ask_quote is None else self.execution_simulator.ask_quote.remaining_size,
            }
        )
