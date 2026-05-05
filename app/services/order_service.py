import logging
from datetime import datetime
from app.models.execution import Execution
from app.models.order import Order
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


class OrderService:

    def __init__(self, session_factory):
        self.Session = session_factory

    def handle_new_order_from_fix(self, cl_ord_id, symbol, side, quantity, price,
                                   client_id="CLIENT", order_type="LIMIT"):
        session = SessionLocal()
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
                last_qty   = 0,
                last_px    = 0.0,
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
        session = SessionLocal()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == orig_cl_ord_id).first()

            if not order:
                return None, False, "Unknown Order"
            if order.status in ["FILLED", "CANCELED"]:
                return order, False, "Too late to cancel"

            order.cl_ord_id  = new_cl_ord_id
            order.status     = "CANCELED"
            order.leaves_qty = 0
            session.commit()
            session.refresh(order)
            return order, True, ""
        finally:
            session.close()

    def handle_replace_request(self, orig_cl_ord_id, new_cl_ord_id, new_price, new_qty):
        session = SessionLocal()
        try:
            order = session.query(Order).filter(Order.cl_ord_id == orig_cl_ord_id).first()

            if not order:
                return None, False, "Unknown Order"
            if order.status in ["FILLED", "CANCELED"]:
                return order, False, "Too late to replace"
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
        finally:
            session.close()

    def partial_fill(self, cl_ord_id, client_id, fill_qty, fill_price):
        session = SessionLocal()
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
            return active
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
