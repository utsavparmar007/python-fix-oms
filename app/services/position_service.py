import logging
from typing import Optional, List
from app.db.database import SessionLocal
from app.models.position import Position

logger = logging.getLogger(__name__)


class PositionService:
    """
    Updates net position and realized P&L for a client whenever a fill occurs.

    """

    def update_position(self, client_id, symbol, side, fill_qty, fill_price):
        """
        side: 1 = Buy, 2 = Sell
        Returns the updated (or newly created) Position row.
        """
        session = SessionLocal()
        try:
            pos = (session.query(Position)
                   .filter(Position.client_id == client_id, Position.symbol == symbol)
                   .first())

            if pos is None:
                pos = Position(client_id=client_id, symbol=symbol, net_qty=0, avg_cost=0.0, realized_pnl=0.0)
                session.add(pos)

            if side == 1: # ── BUY ─────
                self._apply_buy(pos, fill_qty, fill_price)
            
            else:   # ── SELL ──────
                self._apply_sell(pos, fill_qty, fill_price)

            session.commit()
            session.refresh(pos)
            logger.info(f"[POSITION] {client_id}/{symbol}: qty={pos.net_qty} avg_cost={pos.avg_cost:.4f} realized_pnl={pos.realized_pnl:.4f}")
            return pos
        except Exception as e:
            session.rollback()
            logger.error(f"PositionService error: {e}")
            raise
        finally:
            session.close()

    
    
    # Internal helpers  ───────────────────────────────────────────────────

    def _apply_buy(self, pos, qty, price):
        """Add to long (or reduce short) position."""
        if pos.net_qty >= 0:
            total_cost   = pos.net_qty * pos.avg_cost + qty * price
            pos.net_qty += qty
            pos.avg_cost = total_cost / pos.net_qty
        else:
            close_qty = min(qty, abs(pos.net_qty))
            pos.realized_pnl += close_qty * (pos.avg_cost - price)
            pos.net_qty      += close_qty

            open_qty = qty - close_qty
            if open_qty > 0:
                pos.net_qty  += open_qty
                pos.avg_cost  = price
            elif pos.net_qty == 0:
                pos.avg_cost = 0.0

    def _apply_sell(self, pos, qty, price):
        """Reduce long (or extend short) position."""

        if pos.net_qty > 0:
            close_qty = min(qty, pos.net_qty)
            pos.realized_pnl += close_qty * (price - pos.avg_cost)
            pos.net_qty      -= close_qty

            open_qty = qty - close_qty
            if open_qty > 0:
                pos.net_qty  -= open_qty
                pos.avg_cost  = price
            elif pos.net_qty == 0:
                pos.avg_cost = 0.0
        else:
            total_cost   = abs(pos.net_qty) * pos.avg_cost + qty * price
            pos.net_qty -= qty
            pos.avg_cost = total_cost / abs(pos.net_qty)

    def get_position(self, client_id, symbol) -> Optional[Position]:
        session = SessionLocal()
        try:
            return (session.query(Position)
                    .filter(Position.client_id == client_id, Position.symbol == symbol)
                    .first())
        finally:
            session.close()

    def get_all_positions(self, client_id) -> List[Position]:
        session = SessionLocal()
        try:
            positions = (session.query(Position)
                         .filter(Position.client_id == client_id)
                         .all())
            session.expunge_all()
            return positions
        finally:
            session.close()
