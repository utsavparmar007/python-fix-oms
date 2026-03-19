import quickfix as fix
import threading
import logging
import uuid
from flask import Flask, jsonify, request
from app.fix.application import OMSApplication
from app.repository.order_repository import OrderRepository
from app.db.database import engine, Base
from app.models.order import Order 

# 1. Initialize Database Tables
Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OMS")

# Global instance
oms_application = OMSApplication()

def start_fix():
    try:
        settings = fix.SessionSettings("config/server.cfg")
        acceptor = fix.SocketAcceptor(
            oms_application, 
            fix.FileStoreFactory(settings), 
            settings, 
            fix.FileLogFactory(settings)
        )
        acceptor.start()
        logger.info("FIX Server started for 'CLIENT' on port 9878.")
        while True:
            import time
            time.sleep(1)
    except Exception as e:
        logger.error(f"FIX Configuration Error: {e}")

# --- Flask REST API ---
app = Flask(__name__)
repo = OrderRepository()

@app.route("/orders", methods=["GET"])
def get_orders():
    """Fetches all orders for the dashboard."""
    db_orders = repo.get_all()
    return jsonify([{
        "cl_ord_id": o.cl_ord_id,
        "symbol": o.symbol,
        "side": "BUY" if o.side == 1 else "SELL",
        "qty": o.quantity,
        "status": o.status,
        "cum_qty": o.cum_qty,
        "price": o.price
    } for o in db_orders])

# --- JSON ---

@app.route("/admin/execute", methods=["POST"])
def admin_execute():
    """
    Control everything via JSON.
    Actions: NEW, FILL, PARTIAL, CANCEL, REPLACE
    """
    data = request.get_json()
    action = data.get("action", "").upper()
    cl_ord_id = data.get("id")
    target_client = "CLIENT" 

    try:
        # --- NEW ---
        if action == "NEW":
            qty = int(data.get("qty", 100))
            new_order = Order(
                cl_ord_id=str(uuid.uuid4()),
                symbol=data.get("symbol", "AAPL"),
                quantity=qty,
                price=float(data.get("price", 150.0)),
                side=1 if data.get("side", "BUY").upper() == "BUY" else 2,
                status="NEW",
                cum_qty=0,
                leaves_qty=qty
            )
            order = oms_application.order_service.handle_new_order(new_order)
            msg = "Order Created"

        # --- FILL ---
        elif action == "FILL":
            order = oms_application.order_service.fill_order(cl_ord_id, target_client)
            msg = "Full Fill Executed"

        # --- PARTIAL ---
        elif action == "PARTIAL":
            order = oms_application.order_service.partial_fill(cl_ord_id, target_client)
            msg = "Partial Fill Executed"

        # --- CANCEL ---
        elif action == "CANCEL":
            order = oms_application.order_service.cancel_order(cl_ord_id)
            msg = "Order Canceled"
            
        # --- REPLACE ---
        elif action == "REPLACE":
            order = oms_application.order_service.replace_order(
                cl_ord_id, 
                data.get("price"), 
                data.get("qty")
            )
            msg = "Order Modified"

        else:
            return jsonify({"error": f"Invalid action: {action}"}), 400

        # Safety Check for Order Existence
        if not order:
            return jsonify({"status": "error", "message": f"Order {cl_ord_id} not found or finished"}), 404

        # Notify via FIX (Raw string SessionID to avoid C++ error)
        session_id = fix.SessionID("FIX.4.4", "OMS", target_client)
        oms_application.send_execution_report(order, session_id)

        return jsonify({
            "status": "success",
            "message": msg,
            "id": order.cl_ord_id,
            "order_status": order.status
        })

    except Exception as e:
        logger.error(f"Execution Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Start FIX Engine
    threading.Thread(target=start_fix, daemon=True).start()
    # Start API
    app.run(host="0.0.0.0", port=5000, debug=False)