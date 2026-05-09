from sqlalchemy import Column, String, Integer, Float, UniqueConstraint
import uuid
from app.db.database import Base


class Order(Base):
    __tablename__ = "orders"

    order_id   = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    cl_ord_id  = Column(String, index=True)
    symbol     = Column(String, index=True)
    side       = Column(Integer)   # 1=Buy, 2=Sell
    quantity   = Column(Integer)
    price      = Column(Float)
    order_type = Column(String, default="LIMIT")
    time_in_force = Column(String, default="0")
    status     = Column(String, default="NEW")
    client_id  = Column(String, default="CLIENT", index=True)
    cum_qty    = Column(Integer, default=0)
    leaves_qty = Column(Integer)
    avg_px     = Column(Float, default=0.0)
    last_qty   = Column(Integer, default=0)
    last_px    = Column(Float, default=0.0)
    broker_id    = Column(String, nullable=True)   # tag 448 where 452=1  (Executing Firm)
    trader_id    = Column(String, nullable=True)   # tag 448 where 452=36 (Entering Trader)
    client_ref   = Column(String, nullable=True)   # tag 448 where 452=3  (Client ID)
    
    __table_args__ = (UniqueConstraint('client_id', 'cl_ord_id', name='_client_clordid_uc'),)

    def __repr__(self):
        return f"<Order {self.cl_ord_id} | {self.symbol} | {self.status} | client={self.client_id}>"
