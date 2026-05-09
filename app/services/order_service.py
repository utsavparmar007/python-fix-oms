import logging
from datetime import datetime
from app.models.execution import Execution
from app.models.order import Order
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


class OrderService:

    def __init__(self, session_factory):
        self.Session = session_factory

    def handle_new_order_from_fix(self, cl_ord_id, symbol, side, quantity,
                               price, client_id, order_type,
                               broker_id=None, trader_id=None, client_ref=None, time_in_force="0"):
        session = self.Session()
        try:
            order = Order(
                cl_ord_id  = cl_ord_id,
                symbol     = symbol,
                side       = int(side),
                quantity   = int(quantity),
                price      = float(price),
                order_type = order_type,
                status     = "NEW",
                client_id  = client_id,
                cum_qty    = 0,
                leaves_qty = int(quantity),
                avg_px     = 0.0,
                broker_id  = broker_id,    
                trader_id  = trader_id,    
                client_ref = client_ref,
                time_in_force = time_in_force   
            )
            session.add(order)
            session.commit()
            session.refresh(order)
            return order
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def handle_cancel_request(self, orig_cl_ord_id, new_cl_ord_id):
        session = self.Session()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == orig_cl_ord_id).first()

            if not order:
                return None, False, "Unknown Order"
            if order.status in ["FILLED", "CANCELED"]:
                return order, False, "Too late to cancel"
            
            # ── Check if the NEW ClOrdID is already used ──────
            if self.is_duplicate_clordid(order.client_id, new_cl_ord_id):
                return order, False, f"Duplicate ClOrdID: {new_cl_ord_id}"

            order.cl_ord_id  = new_cl_ord_id
            order.status     = "CANCELED"
            order.leaves_qty = 0
            session.commit()
            session.refresh(order)
            return order, True, ""
        except Exception as e:
            session.rollback()
            logger.error(f"handle_cancel_request error: {e}")
            return None, False, str(e)
        finally:
            session.close()

    def handle_replace_request(self, orig_cl_ord_id, new_cl_ord_id, new_price, new_qty):
        session = self.Session()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == orig_cl_ord_id).first()

            if not order:
                return None, False, "Unknown Order"
            if order.status in ["FILLED", "CANCELED"]:
                return order, False, "Too late to replace"
            
            # ── Check if the NEW ClOrdID is already used ──────
            if self.is_duplicate_clordid(order.client_id, new_cl_ord_id):
                return order, False, f"Duplicate ClOrdID: {new_cl_ord_id}"
            
            if int(new_qty) < order.cum_qty:
                return order, False, "New qty < already filled qty"

            order.cl_ord_id  = new_cl_ord_id
            order.price      = float(new_price)
            order.quantity   = int(new_qty)
            order.leaves_qty = order.quantity - order.cum_qty

            if order.cum_qty > 0 and order.leaves_qty > 0:
                order.status = "PARTIALLY_FILLED"
            elif order.leaves_qty <= 0:
                order.status = "FILLED"
            else:
                order.status = "NEW"

            session.commit()
            session.refresh(order)
            return order, True, ""
        except Exception as e:
            session.rollback()
            logger.error(f"handle_replace_request error: {e}")
            return None, False, str(e)
        finally:
            session.close()

    def partial_fill(self, cl_ord_id, client_id, fill_qty, fill_price):
        session = self.Session()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == cl_ord_id).first()
            if not order or order.status in ["FILLED", "CANCELED"]:
                return None

            order.last_qty = fill_qty
            order.last_px  = fill_price

            total_cost     = order.cum_qty * order.avg_px + fill_qty * fill_price
            order.cum_qty += fill_qty
            order.avg_px   = total_cost / order.cum_qty

            order.leaves_qty -= fill_qty
            if order.leaves_qty <= 0:
                order.leaves_qty = 0
                order.status     = "FILLED"
            else:
                order.status = "PARTIALLY_FILLED"

            execution = Execution(
                order_id   = order.order_id,
                cl_ord_id  = cl_ord_id,
                symbol     = order.symbol,
                fill_qty   = fill_qty,
                fill_price = fill_price,
                timestamp  = datetime.utcnow(),
            )
            session.add(execution)
            session.commit()
            session.refresh(order)
            return order
        except Exception as e:
            session.rollback()
            logger.error(f"partial_fill error for {cl_ord_id}: {e}")
            raise
        finally:
            session.close()

    def mass_cancel(self, symbol=None, client_id=None):
        session = self.Session()
        try:
            query = session.query(Order).filter(Order.status.in_(["NEW", "PARTIALLY_FILLED"]))
            if symbol:
                query = query.filter(Order.symbol == symbol)
            if client_id:
                query = query.filter(Order.client_id == client_id)

            active = query.all()
            for order in active:
                order.status     = "CANCELED"
                order.leaves_qty = 0

            session.commit()
            for order in active:
                session.refresh(order)
            return active
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
            
    def cancel_remainder(self, cl_ord_id):
        """Forces an order's status to CANCELED and wipes out its remaining quantity."""
        session = self.Session()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == cl_ord_id).first()
            if order:
                order.status = "CANCELED"  # Or your equivalent OrdStatus enum (e.g., "4")
                order.leaves_qty = 0
                session.commit()
        except Exception as e:
            logger.error(f"Failed to cancel remainder for {cl_ord_id}: {e}")
            session.rollback()
        finally:
            session.close()
            
    def is_duplicate_clordid(self, client_id, cl_ord_id):
        session = self.Session()
        try:
            # Look for any existing order with the exact same Client ID and ClOrdID
            existing_order = session.query(Order).filter(
                Order.client_id == client_id,
                Order.cl_ord_id == cl_ord_id
            ).first()
            
            return existing_order is not None
        except Exception as e:
            logger.error(f"Database error checking duplicate ClOrdID: {e}")
            return True # Fail safe: assume duplicate if DB crashes
        finally:
            session.close()
