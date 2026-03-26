import collections
from app.services.execution_service import ExecutionService
from app.repository.order_repository import OrderRepository 

class MatchingEngine:
    def __init__(self):
        # Order Book: {Symbol: {'bids': [Orders], 'asks': [Orders]}}
        self.order_book = collections.defaultdict(lambda: {'bids': [], 'asks': []})
        self.execution_service = ExecutionService()
        self.repo = OrderRepository()

    def process_order(self, order):
        symbol = order.symbol
        side = order.side
        
        if side == 1: # Buy Side
            self.match(order, self.order_book[symbol]['asks'], reverse=False)
            if order.leaves_qty > 0:
                self.order_book[symbol]['bids'].append(order)
                self.order_book[symbol]['bids'].sort(key=lambda x: (-x.price, x.cl_ord_id))
        else: # Sell Side
            self.match(order, self.order_book[symbol]['bids'], reverse=True)
            if order.leaves_qty > 0:
                self.order_book[symbol]['asks'].append(order)
                self.order_book[symbol]['asks'].sort(key=lambda x: (x.price, x.cl_ord_id))

    def match(self, incoming_order, book_side, reverse):
        for resting_order in list(book_side):
            if incoming_order.leaves_qty <= 0:
                break
            
            can_match = (incoming_order.price >= resting_order.price) if not reverse else (incoming_order.price <= resting_order.price)
            
            if can_match:
                match_qty = min(incoming_order.leaves_qty, resting_order.leaves_qty)
                self.execute_trade(incoming_order, resting_order, match_qty)
                
                if resting_order.leaves_qty == 0:
                    book_side.remove(resting_order)

    def execute_trade(self, incoming_order, resting_order, match_qty):
        """Single source of truth for trade persistence."""
        trade_price = resting_order.price
        
        for order in [incoming_order, resting_order]:
            # Math and database record creation happen here
            updated_order = self.execution_service.create_execution(order, match_qty, trade_price)
            # Permanent status update in orders table
            self.repo.update(updated_order)