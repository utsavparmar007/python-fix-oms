from app.repository.order_repository import OrderRepository
from app.mapping.fix_mapper import FixMapper
from app.services.order_state_machine import OrderStateMachine
from app.services.risk_engine import RiskEngine, RiskException
from app.services.position_service import PositionService
from app.services.execution_service import ExecutionService  

class OrderService:

    def __init__(self):
        self.repo = OrderRepository()
        self.mapper = FixMapper()
        self.position_service = PositionService()
        self.execution_service = ExecutionService()  

    # ---------------- NEW ORDER ----------------
    def handle_new_order(self, order_obj):
        """Validates and persists a new order object."""
        # Risk validation now works because order_obj has the .symbol attribute
        RiskEngine.validate(order_obj)
        self.repo.save(order_obj)
        return order_obj

    # ---------------- PARTIAL FILL ----------------
    def partial_fill(self, cl_ord_id, client_id):
        order = self.repo.get(cl_ord_id) 
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None
    
        # Logic: Fill 50% of remaining leaves quantity
        fill_qty = order.leaves_qty // 2
        if fill_qty <= 0: 
            fill_qty = order.leaves_qty 

        # Record the partial fill (Execution record)
        self.execution_service.create_execution(order, fill_qty, order.price)
        
        # Position Tracker updates based on fill
        self.position_service.update_position(client_id, order.symbol, order.side, fill_qty)
        
        # Note: ExecutionService handles order.cum_qty and order.leaves_qty math
        self.repo.update(order)
        return order

    # ---------------- FULL FILL ----------------
    def fill_order(self, cl_ord_id, client_id):
        order = self.repo.get(cl_ord_id)
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None
    
        fill_qty = order.leaves_qty
        
        # Record the final fill
        self.execution_service.create_execution(order, fill_qty, order.price)
        
        # Position Tracker
        self.position_service.update_position(client_id, order.symbol, order.side, fill_qty)
    
        self.repo.update(order)
        return order
    
    # ---------------- CANCEL ORDER ----------------
    def cancel_order(self, cl_ord_id):
        order = self.repo.get(cl_ord_id)
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None

        # Transition state to CANCELED via State Machine
        order = OrderStateMachine.transition(order, "CANCELED")
        self.repo.update(order)
        return order

    # ---------------- REPLACE ORDER ----------------
    def replace_order(self, cl_ord_id, new_price=None, new_qty=None):
        order = self.repo.get(cl_ord_id)
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None

        if new_price is not None:
            order.price = float(new_price)

        if new_qty is not None:
            new_qty_int = int(new_qty)
            if new_qty_int < order.cum_qty:
                raise Exception(f"New qty {new_qty_int} < filled qty {order.cum_qty}")
            
            order.quantity = new_qty_int
            order.leaves_qty = order.quantity - order.cum_qty

        # Re-validate risk after modification
        RiskEngine.validate(order)
        self.repo.update(order)
        return order