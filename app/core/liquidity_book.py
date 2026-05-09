class OrderBook:
    """Represents the bid and ask sides for a single ticker."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.bids = []  # Price DESC, Time ASC (buyers)
        self.asks = []  # Price ASC,  Time ASC  (sellers)
        self._sequence_counter = 0

    def add_order(self, order):
        """Adds an order to the correct side and maintains Price-Time Priority."""
        if not hasattr(order, '_sequence'):
            order._sequence = self._sequence_counter
            self._sequence_counter += 1
            
        if order.side == 1: #buy
            self.bids.append(order)
            self.bids.sort(key=lambda x: (-x.price, x._sequence))
        else:  #sell
            self.asks.append(order)
            self.asks.sort(key=lambda x: (x.price, x._sequence))

    def best_bid(self):
        """Return the highest resting bid price, or 0.0 if empty."""
        return self.bids[0].price if self.bids else 0.0

    def best_ask(self):
        """Return the lowest resting ask price, or 0.0 if empty."""
        return self.asks[0].price if self.asks else 0.0

    def depth(self):
        """Return a simple depth snapshot — useful for debugging."""
        return {
            "bids": [(o.cl_ord_id, o.price, o.leaves_qty) for o in self.bids],
            "asks": [(o.cl_ord_id, o.price, o.leaves_qty) for o in self.asks],
        }


class LiquidityManager:
    """Manages one OrderBook per ticker dynamically."""

    def __init__(self):
        self.market = {}

    def get_book(self, symbol):
        if symbol not in self.market:
            self.market[symbol] = OrderBook(symbol)
        return self.market[symbol]
