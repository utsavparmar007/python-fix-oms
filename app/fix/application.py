import quickfix as fix
import quickfix44 as fix44
import uuid
import threading
from app.services.order_service import OrderService
from app.services.risk_engine import RiskException
from app.core.logger import get_logger

logger = get_logger()

# Mapping internal statuses to FIX standard values
STATUS_MAP = {
    "NEW": fix.OrdStatus_NEW,
    "PARTIALLY_FILLED": fix.OrdStatus_PARTIALLY_FILLED,
    "FILLED": fix.OrdStatus_FILLED,
    "CANCELED": fix.OrdStatus_CANCELED,
    "REJECTED": fix.OrdStatus_REJECTED,
}

EXEC_TYPE_MAP = {
    "NEW": fix.ExecType_NEW,
    "PARTIALLY_FILLED": fix.ExecType_PARTIAL_FILL,
    "FILLED": fix.ExecType_FILL,
    "CANCELED": fix.ExecType_CANCELED,
    "REJECTED": fix.ExecType_REJECTED,
}

class OMSApplication(fix.Application):
    def __init__(self):
        super().__init__()
        self.order_service = OrderService()

    def onCreate(self, sessionID): logger.info(f"Session created: {sessionID}")
    def onLogon(self, sessionID): logger.info(f"Logon successful: {sessionID}")
    def onLogout(self, sessionID): logger.info(f"Logout: {sessionID}")
    def toAdmin(self, message, sessionID): pass
    def fromAdmin(self, message, sessionID): pass
    def toApp(self, message, sessionID): pass

    def fromApp(self, message, sessionID):
        """Routes incoming messages and identifies the specific client."""
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
        """Processes a new order and schedules simulated fills with the client_id."""
        try:
            # 1. Map, Validate Risk, and Save to DB
            order = self.order_service.handle_new_order(message)
            self.send_execution_report(order, sessionID)

            # 2. Delayed Partial Fill (2 seconds) - Passing client_id in the args list
            #threading.Timer(2.0, self.simulate_partial_fill, [order.cl_ord_id, sessionID, client_id]).start()

            # 3. Delayed Full Fill (5 seconds) - Passing client_id in the args list
            #threading.Timer(5.0, self.simulate_full_fill, [order.cl_ord_id, sessionID, client_id]).start()

        except RiskException as e:
            logger.warning(f"Risk Reject: {e}")
            self.send_reject(sessionID)

    def simulate_partial_fill(self, cl_ord_id, sessionID, client_id):
        """Executes a partial fill and updates the specific client's position."""
        try:
            partial = self.order_service.partial_fill(cl_ord_id, client_id)
            self.send_execution_report(partial, sessionID)
        except Exception as e:
            logger.error(f"Partial fill error for {cl_ord_id}: {e}")

    def simulate_full_fill(self, cl_ord_id, sessionID, client_id):
        """Executes a full fill and updates the specific client's position."""
        try:
            filled = self.order_service.fill_order(cl_ord_id, client_id)
            self.send_execution_report(filled, sessionID)
        except Exception as e:
            logger.error(f"Full fill error for {cl_ord_id}: {e}")

    def handle_cancel(self, message, sessionID):
        orig_id = fix.OrigClOrdID()
        message.getField(orig_id)
        try:
            order = self.order_service.cancel_order(orig_id.getValue())
            self.send_execution_report(order, sessionID)
        except Exception as e:
            logger.error(f"Cancel failed: {e}")

    def handle_replace(self, message, sessionID):
        orig_id = fix.OrigClOrdID(); price = fix.Price(); qty = fix.OrderQty()
        message.getField(orig_id); message.getField(price); message.getField(qty)
        try:
            order = self.order_service.replace_order(orig_id.getValue(), price.getValue(), qty.getValue())
            self.send_execution_report(order, sessionID)
        except Exception as e:
            logger.error(f"Replace failed: {e}")

    def send_execution_report(self, order, sessionID):
        """Sends a FIX Execution Report (35=8) back to the target client."""
        report = fix44.ExecutionReport()
        report.setField(fix.OrderID(order.cl_ord_id))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(EXEC_TYPE_MAP[order.status]))
        report.setField(fix.OrdStatus(STATUS_MAP[order.status]))
        report.setField(fix.Symbol(order.symbol))
        report.setField(fix.Side(int(order.side)))
        report.setField(fix.CumQty(order.cum_qty))
        report.setField(fix.LeavesQty(order.leaves_qty))
        report.setField(fix.AvgPx(order.avg_px))
        fix.Session.sendToTarget(report, sessionID)

    def send_reject(self, sessionID):
        report = fix44.ExecutionReport()
        report.setField(fix.OrderID("REJECT"))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(fix.ExecType_REJECTED))
        report.setField(fix.OrdStatus(fix.OrdStatus_REJECTED))
        fix.Session.sendToTarget(report, sessionID)