from app.models.execution import Execution
from app.db.database import SessionLocal


class ExecutionService:

    def create_execution(self, order, fill_qty, fill_price):
        db = SessionLocal()
        try:
            execution = Execution(
                cl_ord_id  = order.cl_ord_id,
                symbol     = order.symbol,
                fill_qty   = fill_qty,
                fill_price = fill_price,
            )
            db.add(execution)
            db.commit()
        finally:
            db.close()

        # Update the in-memory order object so the caller sees current state.
        order.cum_qty    += fill_qty
        order.leaves_qty -= fill_qty
        if order.leaves_qty < 0:
            order.leaves_qty = 0

        return order

    def get_all_executions(self):
        db = SessionLocal()
        try:
            return db.query(Execution).all()
        finally:
            db.close()
