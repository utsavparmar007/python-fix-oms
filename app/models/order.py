from sqlalchemy import Column, String, Float, Integer
from app.db.database import Base

class Order(Base):
    __tablename__ = "orders"

    # Primary identifier from the client
    cl_ord_id = Column(String, primary_key=True, index=True)
    symbol = Column(String, index=True)
    side = Column(Integer)  
    quantity = Column(Integer)
    price = Column(Float)
    
    # Life cycle and execution tracking
    status = Column(String, default="NEW")  
    cum_qty = Column(Integer, default=0)    
    leaves_qty = Column(Integer)            
    avg_px = Column(Float, default=0.0)     
    
    # Last execution details for the current Execution Report
    last_qty = Column(Integer, default=0)
    last_px = Column(Float, default=0.0)