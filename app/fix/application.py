import quickfix as fix
import quickfix44 as fix44
import redis
import threading
import uuid
import json
import logging
from app.services.order_service import OrderService
from app.services.risk_engine import RiskException
from app.core.logger import get_logger
from app.models.order import Order  

# Initialize the centralized logger
logger = get_logger()

# Mapping internal statuses to FIX standard values
STATUS_MAP = {
    "NEW": fix.OrdStatus_NEW,
    "PARTIALLY_FILLED": fix.OrdStatus_PARTIALLY_FILLED,
    "FILLED": fix.OrdStatus_FILLED,
    "CANCELED": fix.OrdStatus_CANCELED,
    "REJECTED": fix.OrdStatus_REJECTED,
}

# Mapping internal execution types to FIX standard values
EXEC_TYPE_MAP = {
    "NEW": fix.ExecType_NEW,
    "PARTIALLY_FILLED": fix.ExecType_TRADE,
    "FILLED": fix.ExecType_TRADE,
    "CANCELED": fix.ExecType_CANCELED,
    "REJECTED": fix.ExecType_REJECTED,
}

class OMSApplication(fix.Application):
    def __init__(self):
        super().__init__()
        self.order_service = OrderService()
        self.validator_pipe = redis.Redis(host='localhost', port=6379, decode_responses=True)
        threading.Thread(target=self.listen_for_kills, daemon=True).start()
        

    def onCreate(self, sessionID): 
        logger.info(f"Session created: {sessionID}")

    def onLogon(self, sessionID): 
        logger.info(f"Logon successful: {sessionID}")

    def onLogout(self, sessionID): 
        logger.info(f"Logout: {sessionID}")

    def toAdmin(self, message, sessionID): 
        # This will show the Heartbeats (35=0) being sent
        raw_msg = message.toString().replace('\x01', '|')
        logger.info(f"ToAdmin: {raw_msg}")

    def fromAdmin(self, message, sessionID): 
        # This will show the Heartbeats (35=0) being received
        raw_msg = message.toString().replace('\x01', '|')
        logger.info(f"FromAdmin: {raw_msg}")
    
    def listen_for_kills(self):
        """Background loop that waits for 'CANCEL' signals from the outside validator."""
        logger.info("Security Thread: Listening for Kill Signals from Validator.")
        while True:
            try:
                # Wait for a kill signal (blocking pop)
                result = self.validator_pipe.blpop("oms_kill_switch", timeout=0)
                if result:
                    kill_data = json.loads(result[1])
                    clordid = kill_data.get('clordid')
                    reason = kill_data.get('reason')
                    
                    logger.warning(f"🛑 KILL SIGNAL RECEIVED for Order {clordid} | Reason: {reason}")
                    
                    # Call the internal cancel logic
                    self.trigger_emergency_cancel(clordid)
            except Exception as e:
                logger.error(f"Error in Kill Switch listener: {e}")

    def trigger_emergency_cancel(self, clordid):
        try:
            # 1. Use the new helper to get order details
            order = self.order_service.get_order_by_id(clordid)
            if not order:
                logger.error(f"Kill Switch failed: Order {clordid} not found.")
                return

            # 2. Construct the FIX 35=F (Cancel Request)
            cancel_request = fix44.OrderCancelRequest()
            cancel_request.setField(fix.OrigClOrdID(str(clordid)))
            cancel_request.setField(fix.ClOrdID(f"KILL-{uuid.uuid4().hex[:6]}"))
            cancel_request.setField(fix.Symbol(str(order.symbol)))
            cancel_request.setField(fix.Side(str(order.side)))
            cancel_request.setField(fix.TransactTime())

            # 3. Target the session DIRECTLY (Avoids the Swig iteration bug)
            session_id = fix.SessionID("FIX.4.4", "OMS", "CLIENT")
            
            if fix.Session.lookupSession(session_id):
                fix.Session.sendToTarget(cancel_request, session_id)
                logger.warning(f"🚀 EMERGENCY FIX 35=F SENT for Order: {clordid}")
                
                # Update internal state to CANCELED
                self.order_service.cancel_order(clordid)
            else:
                logger.error("Active session not found. Is the client logged in?")

        except Exception as e:
            logger.error(f"Emergency FIX Cancel failed: {e}")

    def toApp(self, message, sessionID):
        """Logs outgoing application messages with readable separators."""
        raw_msg = message.toString().replace('\x01', '|')
        logger.info(f">>> SENDING APP MSG: {raw_msg}")

        try:
            # We push the raw message to the Redis queue
            self.validator_pipe.rpush("oms_outbound_queue", raw_msg)
        except Exception as e:
            # We wrap this in a try/except so your OMS never crashes 
            # even if the validator system is turned off.
            logger.error(f"External Validator Bridge Error: {e}")

    def fromApp(self, message, sessionID):
        """Routes incoming messages and logs them."""
        raw_msg = message.toString().replace('\x01', '|')
        logger.info(f"<<< RECEIVED APP MSG: {raw_msg}")
        
        client_id = sessionID.getTargetCompID().getValue()
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        val = msg_type.getValue()

        if val == fix.MsgType_NewOrderSingle:
            logger.info(f"New Order received from {client_id}")
            self.handle_new_order(message, sessionID, client_id)
        elif val == fix.MsgType_OrderCancelRequest:
            self.handle_cancel(message, sessionID)
        elif val == fix.MsgType_OrderCancelReplaceRequest:
            self.handle_replace(message, sessionID)

    def handle_new_order(self, message, sessionID, client_id):
        """Processes a new order through the service layer."""
        try:
            symbol = fix.Symbol(); message.getField(symbol)
            side = fix.Side(); message.getField(side)
            qty = fix.OrderQty(); message.getField(qty)
            price = fix.Price(); message.getField(price)
            clordid = fix.ClOrdID(); message.getField(clordid)

            
            order_obj = Order(
                cl_ord_id=clordid.getValue(),
                symbol=symbol.getValue(),
                quantity=int(qty.getValue()),
                price=float(price.getValue()),
                side=side.getValue(), 
                status="NEW",
                cum_qty=0,
                leaves_qty=int(qty.getValue())
            )

            
            order = self.order_service.handle_new_order(order_obj)
            self.send_execution_report(order, sessionID)

        except fix.FieldNotFound as e:
            logger.error(f"Missing mandatory FIX field: {e}")
            self.send_reject(sessionID)
        except RiskException as e:
            logger.warning(f"Risk Reject: {e}")
            self.send_reject(sessionID)

    def send_execution_report(self, order, sessionID):
        """Sends a protocol-compliant FIX Execution Report (35=8)."""
        report = fix44.ExecutionReport()
        report.setField(fix.ClOrdID(str(order.cl_ord_id)))
        report.setField(fix.OrderID(str(order.cl_ord_id)))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(EXEC_TYPE_MAP.get(order.status, fix.ExecType_NEW)))
        report.setField(fix.OrdStatus(STATUS_MAP.get(order.status, fix.OrdStatus_NEW)))
        report.setField(fix.Symbol(str(order.symbol)))
        report.setField(fix.Side(str(int(order.side)))) 
        report.setField(fix.OrderQty(float(order.quantity)))
        report.setField(fix.CumQty(float(order.cum_qty)))
        report.setField(fix.LeavesQty(float(order.leaves_qty)))
        report.setField(fix.AvgPx(float(order.price)))
        
        fix.Session.sendToTarget(report, sessionID)

    def handle_cancel(self, message, sessionID):
        orig_id = fix.OrigClOrdID()
        message.getField(orig_id)
        try:
            order = self.order_service.cancel_order(orig_id.getValue())
            if order:
                self.send_execution_report(order, sessionID)
        except Exception as e:
            logger.error(f"Cancel failed: {e}")

    def handle_replace(self, message, sessionID):
        orig_id = fix.OrigClOrdID()
        price = fix.Price()
        qty = fix.OrderQty()
        message.getField(orig_id)
        message.getField(price)
        message.getField(qty)
        try:
            order = self.order_service.replace_order(
                orig_id.getValue(), 
                price.getValue(), 
                qty.getValue()
            )
            if order:
                self.send_execution_report(order, sessionID)
        except Exception as e:
            logger.error(f"Replace failed: {e}")

    def send_reject(self, sessionID):
        report = fix44.ExecutionReport()
        report.setField(fix.OrderID("REJECT"))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(fix.ExecType_REJECTED))
        report.setField(fix.OrdStatus(fix.OrdStatus_REJECTED))
        fix.Session.sendToTarget(report, sessionID)