import collections

class MatchingEngine:
    def __init__(self):
        # Order Book: {Symbol: {'bids': [Orders], 'asks': [Orders]}}
        self.order_book = collections.defaultdict(lambda: {'bids': [], 'asks': []})

    def process_order(self, order):
        """Main entry for Price-Time Priority matching."""
        symbol = order.symbol
        side = order.side
        
        if side == 1:
            self.match(order, self.order_book[symbol]['asks'], reverse=False)
            if order.leaves_qty > 0:
                self.order_book[symbol]['bids'].append(order)
                self.order_book[symbol]['bids'].sort(key=lambda x: (-x.price, x.cl_ord_id))
        else:
            self.match(order, self.order_book[symbol]['bids'], reverse=True)
            if order.leaves_qty > 0:
                self.order_book[symbol]['asks'].append(order)
                self.order_book[symbol]['asks'].sort(key=lambda x: (x.price, x.cl_ord_id))

    def match(self, incoming_order, book_side, reverse):
        """Matches incoming orders against the resting order book."""
        for resting_order in list(book_side):
            if incoming_order.leaves_qty <= 0: break
            
            # Check price priority
            can_match = (incoming_order.price >= resting_order.price) if not reverse else (incoming_order.price <= resting_order.price)
            
            if can_match:
                match_qty = min(incoming_order.leaves_qty, resting_order.leaves_qty)
                self.execute_trade(incoming_order, resting_order, match_qty)
                
                if resting_order.leaves_qty == 0:
                    book_side.remove(resting_order)