import quickfix as fix
from app.core.liquidity_book import LiquidityManager
from app.services.position_service import PositionService
from app.services.market_data_service import MarketDataService


class MatchingEngine:
    """
    Coordinates matching across all symbols.
    After every fill it also:
      • Updates the Position for both the incoming and resting client.
      • Updates the MarketData snapshot (last price, volume, VWAP, BBO).
    """

    def __init__(self, application):
        self.application         = application
        self.liquidity_manager   = LiquidityManager()
        self.position_service    = PositionService()
        self.market_data_service = MarketDataService()

    def process_new_order(self, order):
        """Try to match an incoming order; queue any remainder."""
        book     = self.liquidity_manager.get_book(order.symbol)
        is_buy   = (order.side == 1)
        opp_side = book.asks if is_buy else book.bids

        if opp_side:
            self.match(order, opp_side, is_buy, book)

        if order.leaves_qty > 0:
            book.add_order(order)
            print(f"[QUEUE] {order.symbol}: {order.leaves_qty} shares added to {'Bid' if is_buy else 'Ask'} book.")

        # Refresh BBO after any change
        self.market_data_service.update_bbo(order.symbol, book.best_bid(), book.best_ask())

    def match(self, incoming_order, book_side, is_buy, book):
        """
        Price-Time Priority match loop.
        Uses a local leaves_qty counter to avoid stale ORM state.
        """
        remaining_qty = incoming_order.leaves_qty

        for resting_order in list(book_side):
            if remaining_qty <= 0:
                break

            can_match = (
                (incoming_order.price >= resting_order.price) if is_buy
                else (incoming_order.price <= resting_order.price)
            )

            if not can_match:
                break  # book is sorted; if best price doesn't match, nothing will

            match_qty   = min(remaining_qty, resting_order.leaves_qty)
            match_price = resting_order.price

            # ── 1. Persist fills to DB ───────────────────────────────
            filled_incoming = self.application.order_service.partial_fill(
                incoming_order.cl_ord_id, incoming_order.client_id, match_qty, match_price
            )
            filled_resting = self.application.order_service.partial_fill(
                resting_order.cl_ord_id, resting_order.client_id, match_qty, match_price
            )

            # ── 2. Update local counters ─────────────────────────────
            remaining_qty            -= match_qty
            resting_order.leaves_qty -= match_qty
            resting_order.cum_qty    += match_qty

            # ── 3. Update positions for both clients ─────────────────
            self.position_service.update_position(
                incoming_order.client_id, incoming_order.symbol, incoming_order.side, match_qty, match_price
            )
            self.position_service.update_position(
                resting_order.client_id, resting_order.symbol, resting_order.side, match_qty, match_price
            )

            # ── 4. Update market data snapshot ───────────────────────
            self.market_data_service.on_trade(
                symbol      = incoming_order.symbol,
                trade_qty   = match_qty,
                trade_price = match_price,
                bid         = book.best_bid(),
                ask         = book.best_ask(),
            )

            # ── 5. Send FIX Execution Reports ────────────────────────
            session_id         = self.application.get_session_for_client(incoming_order.client_id)
            resting_session_id = self.application.get_session_for_client(resting_order.client_id)

            if session_id and filled_incoming:
                self.application.send_execution_report(filled_incoming, session_id, fix.ExecType_TRADE)
            if resting_session_id and filled_resting:
                self.application.send_execution_report(filled_resting, resting_session_id, fix.ExecType_TRADE)

            # ── 6. Remove fully-filled resting order from book ───────
            if resting_order.leaves_qty <= 0:
                book_side.remove(resting_order)

            print(f"[MATCH] {incoming_order.symbol}: {match_qty} @ {match_price}")
       
        # Propagate local counter back so process_new_order knows remainder
        incoming_order.leaves_qty = remaining_qty
