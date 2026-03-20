from sqlalchemy import Column, String, Float, Integer, DateTime
from datetime import datetime
from app.db.base import Base

class Execution(Base):
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True)
    cl_ord_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    fill_qty = Column(Integer, nullable=False)
    fill_price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)