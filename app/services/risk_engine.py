import logging
from app.db.database import SessionLocal
from app.models.position import Position

logger = logging.getLogger(__name__)

# ── Per-client risk limits (can be loaded from DB/config later) ────────────
DEFAULT_LIMITS = {
    "max_order_qty":    100_000,
    "max_position_qty": 500_000,
    "max_order_value":  10_000_000,
    "min_price":        0.0001,
    "max_price":        999_999.0,
}

# Override limits per client — add any SenderCompID here
CLIENT_LIMITS = {}


class RiskEngine:
    """
    Pre-trade risk checks.  Called BEFORE an order is accepted by the OMS.

    Returns (passed: bool, reject_reason: str)
    """

    def check(self, client_id, symbol, side, qty, price):
        limits = {**DEFAULT_LIMITS, **CLIENT_LIMITS.get(client_id, {})}
        
        # 1. Basic quantity check
        if qty <= 0:
            return False, f"Invalid quantity: {qty}"

        if qty > limits["max_order_qty"]:
            return False, f"Order qty {qty} exceeds max allowed {limits['max_order_qty']}"

        # 2. Price sanity
        if price < limits["min_price"] or price > limits["max_price"]:
            return False, f"Price {price} out of range"

        # 3. Notional value check
        notional = qty * price
        if notional > limits["max_order_value"]:
            return False, f"Order notional {notional:,.0f} exceeds max allowed {limits['max_order_value']:,.0f}"

        # 4. Position limit check (would this breach the net limit?)
        session = SessionLocal()
        try:
            pos = (session.query(Position)
                   .filter(Position.client_id == client_id, Position.symbol == symbol)
                   .first())
            current_qty = pos.net_qty if pos else 0
        finally:
            session.close()

        projected = current_qty + (qty if side == 1 else -qty)
        if abs(projected) > limits["max_position_qty"]:
            return False, f"Projected position {projected} would breach limit of ±{limits['max_position_qty']}"

        return True, ""
