from app.db.database import SessionLocal
from app.models.position import Position

db = SessionLocal()
positions = db.query(Position).all()
db.close()

if not positions:
    print("No positions yet.")
else:
    print(f"\n{'Client':<12} {'Symbol':<8} {'Net Qty':>8} {'Avg Cost':>10} {'Realized PnL':>14}")
    print("-" * 56)
    for p in positions:
        print(f"{p.client_id:<12} {p.symbol:<8} {p.net_qty:>8} {p.avg_cost:>10.2f} {p.realized_pnl:>14.2f}")