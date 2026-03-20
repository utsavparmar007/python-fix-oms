from app.models.execution import Execution
from app.db.database import SessionLocal

class ExecutionService:
    def __init__(self):
        self.db = SessionLocal()

    def create_execution(self, order, fill_qty, fill_price):
        """
        Creates a permanent trade record for a specific order fill.
        """
        execution = Execution(
            cl_ord_id=order.cl_ord_id,
            symbol=order.symbol,
            fill_qty=fill_qty,
            fill_price=fill_price
        )
        self.db.add(execution)
        self.db.commit()
        return execution

    def get_all_executions(self):
        """
        Retrieves the entire trade history from the database.
        """
        return self.db.query(Execution).all()