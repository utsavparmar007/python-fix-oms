from app.repository.order_repository import OrderRepository
from app.mapping.fix_mapper import FixMapper
from app.services.order_state_machine import OrderStateMachine
from app.services.risk_engine import RiskEngine, RiskException
from app.services.position_service import PositionService

class OrderService:

    def __init__(self):
        self.repo = OrderRepository()
        self.mapper = FixMapper()
        self.position_service = PositionService()

    # ---------------- NEW ORDER ----------------
    def handle_new_order(self, order_obj):
        """Validates and persists a new order object."""
        # Risk validation BEFORE saving
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
        if fill_qty <= 0: fill_qty = order.leaves_qty # Fallback for odd numbers

        order.cum_qty += fill_qty
        order.leaves_qty -= fill_qty
        order.status = "PARTIALLY_FILLED"
    
        # Update Position Tracker
        self.position_service.update_position(client_id, order.symbol, order.side, fill_qty)
        self.repo.update(order)
        return order

    # ---------------- FULL FILL ----------------
    def fill_order(self, cl_ord_id, client_id):
        order = self.repo.get(cl_ord_id)
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None
    
        fill_qty = order.leaves_qty
        order.cum_qty += fill_qty
        order.leaves_qty = 0
        order.status = "FILLED"
    
        # Update Position Tracker
        self.position_service.update_position(client_id, order.symbol, order.side, fill_qty)
        self.repo.update(order)
        return order
    
    # ---------------- CANCEL ORDER ----------------
    def cancel_order(self, cl_ord_id):
        order = self.repo.get(cl_ord_id)
        if not order or order.status in ["FILLED", "CANCELED"]:
            return None

        # Transition state to CANCELED
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
                raise Exception(f"New quantity {new_qty_int} cannot be less than filled quantity {order.cum_qty}")
            
            order.quantity = new_qty_int
            order.leaves_qty = order.quantity - order.cum_qty

        # Re-validate risk after modification
        RiskEngine.validate(order)
        self.repo.update(order)
        return order