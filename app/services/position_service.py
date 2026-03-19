import collections

class PositionService:
    def __init__(self):
        # Nested dict: {client_id: {symbol: quantity}}
        self.positions = collections.defaultdict(lambda: collections.defaultdict(int))

    def update_position(self, client_id, symbol, side, qty):
        """
        Updates net position. 
        Side 1 = Buy (Increase), Side 2 = Sell (Decrease)
        """
        if side == 1:
            self.positions[client_id][symbol] += qty
        else:
            self.positions[client_id][symbol] -= qty
        return self.positions[client_id][symbol]

    def get_client_positions(self, client_id):
        return dict(self.positions[client_id])