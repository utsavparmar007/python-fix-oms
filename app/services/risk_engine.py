class RiskException(Exception):
    pass

class RiskEngine:
    MAX_QTY = 10000
    MIN_PRICE = 1
    MAX_PRICE = 10000
    ALLOWED_SYMBOLS = {"AAPL", "GOOG", "MSFT", "NVDA"}

    @classmethod
    def validate(cls, order):
        """
        Validates an internal Order object (NOT a raw FIX message).
        """
        # Ensure symbol is allowed
        if order.symbol not in cls.ALLOWED_SYMBOLS:
            raise RiskException(f"Symbol {order.symbol} not allowed")

        # Ensure quantity is within limits
        if order.quantity > cls.MAX_QTY:
            raise RiskException(f"Quantity {order.quantity} exceeds risk limit")

        # Ensure price is within range
        if order.price < cls.MIN_PRICE or order.price > cls.MAX_PRICE:
            raise RiskException(f"Price {order.price} out of allowed range")

        return True