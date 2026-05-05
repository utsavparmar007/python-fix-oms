from sqlalchemy import Column, String, Integer, Float
from app.db.database import Base


class Order(Base):
    __tablename__ = "orders"

    cl_ord_id  = Column(String, primary_key=True, index=True)
    symbol     = Column(String, index=True)
    side       = Column(Integer)   # 1=Buy, 2=Sell
    quantity   = Column(Integer)
    price      = Column(Float)
    order_type = Column(String, default="LIMIT")
    status     = Column(String, default="NEW")
    client_id  = Column(String, default="CLIENT", index=True)
    cum_qty    = Column(Integer, default=0)
    leaves_qty = Column(Integer)
    avg_px     = Column(Float, default=0.0)
    last_qty   = Column(Integer, default=0)
    last_px    = Column(Float, default=0.0)

    def __repr__(self):
        return f"<Order {self.cl_ord_id} | {self.symbol} | {self.status} | client={self.client_id}>"
