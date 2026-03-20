class RiskException(Exception):
    pass


class RiskEngine:

    MAX_QTY = 10000
    MIN_PRICE = 1
    MAX_PRICE = 10000000
    ALLOWED_SYMBOLS = {"AAPL", "GOOG", "MSFT","NVDA"}

    @classmethod
    def validate(cls, order):

        if order.symbol not in cls.ALLOWED_SYMBOLS:
            raise RiskException("Symbol not allowed")

        if order.quantity > cls.MAX_QTY:
            raise RiskException("Quantity exceeds risk limit")

        if order.price < cls.MIN_PRICE or order.price > cls.MAX_PRICE:
            raise RiskException("Price out of allowed range")

        return True