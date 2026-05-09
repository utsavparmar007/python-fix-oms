import quickfix as fix
from app.core.liquidity_book import LiquidityManager
from app.services.position_service import PositionService
from app.services.market_data_service import MarketDataService
from app.core.logger import get_logger

logger = get_logger()


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
        
        # Safely extract Time In Force (Defaults to '0' / Day Order)
        tif = getattr(order, 'time_in_force', '0')

        # ── 1. THE FOK PRE-CHECK ─────────────────────────────────────
        if tif == "4":  # 4 = Fill or Kill
            available_liquidity = 0
            for resting in list(opp_side):
                is_market = (order.order_type == "MARKET")
                can_match = is_market or ((order.price >= resting.price) if is_buy else (order.price <= resting.price))
                if can_match:
                    available_liquidity += resting.leaves_qty
                else:
                    break # Prices are no longer crossing

            if available_liquidity < order.leaves_qty:
                logger.warning(f"[FOK KILLED] {order.cl_ord_id} needed {order.leaves_qty} but only {available_liquidity} available.")
                self.application.order_service.cancel_remainder(order.cl_ord_id)
                order.leaves_qty = 0
                session_id = self.application.get_session_for_client(order.client_id)
                if session_id:
                    self.application.send_execution_report(order, session_id, fix.ExecType_CANCELED)
                return # Abort! Do not match, do not queue.
        # ─────────────────────────────────────────────────────────────

        if opp_side:
            self.match(order, opp_side, is_buy, book)

        # ── 2. THE IOC/FOK/MARKET TRASH CAN ─────────────────────────
        if order.leaves_qty > 0:
            is_market = (order.order_type == "MARKET")
            if tif in ["3", "4"] or is_market: # 3 = IOC, 4 = FOK, or any Market Order
                reason = "IOC/FOK" if tif in ["3", "4"] else "Market order no liquidity"
                logger.info(f"[CLEANUP] Canceling remaining {order.leaves_qty} shares of {order.cl_ord_id} ({reason}).")
                
                self.application.order_service.cancel_remainder(order.cl_ord_id)
                order.leaves_qty = 0
                session_id = self.application.get_session_for_client(order.client_id)
                if session_id:
                    self.application.send_execution_report(order, session_id, fix.ExecType_CANCELED)
            else:
                # Standard Day Order -> Rest in the book
                book.add_order(order)
                logger.info(f"[QUEUE] {order.symbol}: {order.leaves_qty} shares added to {'Bid' if is_buy else 'Ask'} book.")
        # ─────────────────────────────────────────────────────────────

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

            is_market = (incoming_order.order_type == "MARKET")
            can_match = is_market or (
                (incoming_order.price >= resting_order.price) if is_buy
                else (incoming_order.price <= resting_order.price)
            )

            if not can_match:
                break  # book is sorted; if best price doesn't match, nothing will

            match_qty   = min(remaining_qty, resting_order.leaves_qty)
            match_price = resting_order.price

            # ── Persist fills to DB ───────────────────────────────
            filled_incoming = self.application.order_service.partial_fill(
                incoming_order.cl_ord_id, incoming_order.client_id, match_qty, match_price
            )
            filled_resting = self.application.order_service.partial_fill(
                resting_order.cl_ord_id, resting_order.client_id, match_qty, match_price
            )

            # ── Update local counters ─────────────────────────────
            remaining_qty            -= match_qty
            resting_order.leaves_qty -= match_qty
            resting_order.cum_qty    += match_qty

            # ── Update positions for both clients ─────────────────
            self.position_service.update_position(
                incoming_order.client_id, incoming_order.symbol, incoming_order.side, match_qty, match_price
            )
            self.position_service.update_position(
                resting_order.client_id, resting_order.symbol, resting_order.side, match_qty, match_price
            )

            # ── Update market data snapshot ───────────────────────
            self.market_data_service.on_trade(
                symbol      = incoming_order.symbol,
                trade_qty   = match_qty,
                trade_price = match_price,
                bid         = book.best_bid(),
                ask         = book.best_ask(),
            )

            # ── Send FIX Execution Reports ────────────────────────
            session_id         = self.application.get_session_for_client(incoming_order.client_id)
            resting_session_id = self.application.get_session_for_client(resting_order.client_id)

            if session_id and filled_incoming:
                self.application.send_execution_report(filled_incoming, session_id, fix.ExecType_TRADE)
            if resting_session_id and filled_resting:
                self.application.send_execution_report(filled_resting, resting_session_id, fix.ExecType_TRADE)

            # ── Remove fully-filled resting order from book ───────
            if resting_order.leaves_qty <= 0:
                book_side.remove(resting_order)
            
            logger.info(f"[MATCH] {incoming_order.symbol}: {match_qty} @ {match_price}")
       
        # Propagate local counter back so process_new_order knows remainder
        incoming_order.leaves_qty = remaining_qty