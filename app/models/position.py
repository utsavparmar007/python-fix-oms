from sqlalchemy import Column, String, Integer, Float, DateTime
from datetime import datetime
from app.db.base import Base


class Position(Base):
    """
    Tracks net position and realized P&L per client per symbol.
    Updated on every fill.
    """
    __tablename__ = "positions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    client_id    = Column(String, nullable=False, index=True)   # SenderCompID of the client
    symbol       = Column(String, nullable=False, index=True)
    net_qty      = Column(Integer, default=0)    # positive=long, negative=short
    avg_cost     = Column(Float, default=0.0)   # weighted avg cost of current open position
    realized_pnl = Column(Float, default=0.0)    # locked-in profit/loss from closed trades
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return (f"<Position client={self.client_id} symbol={self.symbol} "
                f"qty={self.net_qty} avg_cost={self.avg_cost:.4f} "
                f"realized_pnl={self.realized_pnl:.4f}>")
