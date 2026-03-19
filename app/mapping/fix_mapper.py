import quickfix as fix
from app.models.order import Order

class FixMapper:
    def map_new_order(self, message):
        """Extracts fields from a NewOrderSingle (35=D) message."""
        cl_ord_id = fix.ClOrdID()
        symbol = fix.Symbol()
        side = fix.Side()
        qty = fix.OrderQty()
        price = fix.Price()

        message.getField(cl_ord_id)
        message.getField(symbol)
        message.getField(side)
        message.getField(qty)
        message.getField(price)

        return Order(
            cl_ord_id=cl_ord_id.getValue(),
            symbol=symbol.getValue(),
            side=int(side.getValue()),
            quantity=int(qty.getValue()),
            price=float(price.getValue()),
            leaves_qty=int(qty.getValue())
        )