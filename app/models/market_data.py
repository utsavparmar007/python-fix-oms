from sqlalchemy import Column, String, Integer, Float, DateTime
from datetime import datetime
from app.db.base import Base


class MarketData(Base):
    """
    Stores the latest market data snapshot per symbol.
    Updated whenever a trade executes in the matching engine.
    """
    __tablename__ = "market_data"

    symbol      = Column(String, primary_key=True)
    bid         = Column(Float, default=0.0)    # best bid price in the book
    ask         = Column(Float, default=0.0)    # best ask price in the book
    last_price  = Column(Float, default=0.0)    # last traded price
    last_qty    = Column(Integer, default=0)    # last traded quantity
    volume      = Column(Integer, default=0)    # total volume today
    vwap        = Column(Float, default=0.0)    # volume-weighted average price
    open_price  = Column(Float, default=0.0)    # first trade of the session
    high        = Column(Float, default=0.0)
    low         = Column(Float, default=0.0)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MarketData {self.symbol} bid={self.bid} ask={self.ask} last={self.last_price} vol={self.volume}>"
