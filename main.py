import quickfix as fix
import threading
import logging
import uuid
from flask import Flask, jsonify, request
from app.fix.application import OMSApplication
from app.repository.order_repository import OrderRepository
from app.db.database import engine, Base
from app.models.order import Order
from app.models.execution import Execution 
from app.services.execution_service import ExecutionService 

# 1. Initialize Database Tables
Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OMS")

# Global instances
oms_application = OMSApplication()
# --- NEW INSTANCE ---
execution_service = ExecutionService() 

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
        "qty": o.quantity,
        "price": o.price,
        "status": o.status,
        "cum_qty": o.cum_qty,
        "leaves_qty": o.leaves_qty
    } for o in db_orders])

# --- NEW ROUTE: TRADE HISTORY ---
@app.route("/history", methods=["GET"])
def get_history():
    """Fetches all trade executions for auditing."""
    executions = execution_service.get_all_executions()
    return jsonify([{
        "id": ex.id,
        "cl_ord_id": ex.cl_ord_id,
        "symbol": ex.symbol,
        "fill_qty": ex.fill_qty,
        "fill_price": ex.fill_price,
        "timestamp": ex.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    } for ex in executions])

@app.route("/admin/execute", methods=["POST"])
def admin_execute():
    """Manual Terminal Control for Fills, Cancels, and Replaces."""
    data = request.json
    action = data.get("action")
    cl_ord_id = data.get("id")
    target_client = data.get("client", "CLIENT")

    try:
        # --- NEW ORDER ---
        if action == "NEW":
            new_order = Order(
                cl_ord_id=str(uuid.uuid4())[:8],
                symbol=data.get("symbol", "AAPL"),
                quantity=data.get("qty", 100),
                price=data.get("price", 150.0),
                side=1, 
                status="NEW",
                leaves_qty=data.get("qty", 100),
                cum_qty=0
            )
            order = oms_application.order_service.handle_new_order(new_order)
            msg = "Order Created"

        # --- FULL FILL ---
        elif action == "FILL":
            order = oms_application.order_service.fill_order(cl_ord_id, target_client)
            msg = "Order Fully Filled"

        # --- PARTIAL FILL ---
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
                cl_ord_id=cl_ord_id,           
                new_price=data.get("price"),   
                new_qty=data.get("qty")        
            )
            msg = "Order Modified"

        else:
            return jsonify({"error": f"Invalid action: {action}"}), 400

        if not order:
            return jsonify({"status": "error", "message": f"Order {cl_ord_id} not found or finished"}), 404

        # Notify via FIX
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
    # Start FIX in background
    fix_thread = threading.Thread(target=start_fix, daemon=True)
    fix_thread.start()
    
    # Start REST API
    app.run(debug=False, port=5000)