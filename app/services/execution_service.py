from app.models.execution import Execution
from app.db.database import SessionLocal

class ExecutionService:
    def __init__(self):
        self.db = SessionLocal()

    def create_execution(self, order, fill_qty, fill_price):
        """Creates trade record and updates order state exactly once."""
        execution = Execution(
            cl_ord_id=order.cl_ord_id,
            symbol=order.symbol,
            fill_qty=fill_qty,
            fill_price=fill_price
        )

        # Mathematical updates
        order.cum_qty += fill_qty
        order.leaves_qty -= fill_qty
        order.status = "FILLED" if order.leaves_qty <= 0 else "PARTIALLY_FILLED"
        
        self.db.add(execution)
        self.db.commit()
        return order 

    def get_all_executions(self):
        return self.db.query(Execution).all()