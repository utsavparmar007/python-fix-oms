from app.db.database import SessionLocal
from app.models.order import Order


class OrderRepository:


    def save(self, order):
        db = SessionLocal()
        try:
            db.add(order)
            db.commit()
            db.refresh(order)
            return order
        finally:
            db.close()

    def get(self, cl_ord_id):
        db = SessionLocal()
        try:
            return db.query(Order).filter(
                Order.cl_ord_id == cl_ord_id
            ).first()
        finally:
            db.close()

    def update(self, order):
        db = SessionLocal()
        try:
            merged_order = db.merge(order)  
            db.commit()
            db.refresh(merged_order)         
            return merged_order
        finally:
            db.close()


    def get_all(self):
        db = SessionLocal()
        try:
            return db.query(Order).all()
        finally:
            db.close()