import quickfix as fix
import quickfix44 as fix44
import uuid
import logging
from app.services.order_service import OrderService
from app.services.matching_engine import MatchingEngine
from app.services.risk_engine import RiskEngine
from app.services.position_service import PositionService
from app.core.logger import get_logger
from app.db.database import SessionLocal

logger = get_logger()


class OMSApplication(fix.Application):

    def __init__(self):
        super().__init__()
        self.order_service    = OrderService(SessionLocal)
        self.matching_engine  = MatchingEngine(self)
        self.risk_engine      = RiskEngine()
        self.position_service = PositionService()
        self._sessions        = {}

    #  FIX Session Callbacks───────────────────────────────────
    def onCreate(self, sessionID):
        logger.info(f"Session created: {sessionID}")

    def onLogon(self, sessionID):
        client_id = sessionID.getTargetCompID().getValue()
        self._sessions[client_id] = sessionID
        logger.info(f"Logon: {sessionID}  |  registered client='{client_id}'  | total sessions={len(self._sessions)}")

    def onLogout(self, sessionID):
        client_id = sessionID.getTargetCompID().getValue()
        if client_id in self._sessions:
            logger.warning(f"[LOGOUT]  DISCONNECT — no Logout message received from '{client_id}' | session={sessionID}")
        else:
            logger.info(f"[LOGOUT]  disconnect from '{client_id}'")
        self._sessions.pop(client_id, None)
        logger.info(f"Logout: {sessionID} | removed client='{client_id}' | remaining sessions={len(self._sessions)}")

    def toAdmin(self, message, sessionID):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        val = msg_type.getValue()
        
        if val == fix.MsgType_Heartbeat:
           pass         # 35=0
           #logger.info(f"[HEARTBEAT] >>> Sending to {sessionID}")"""

        elif val == fix.MsgType_Logon: #35 = A
            logger.info(f"[LOGON] >>> Sending Logon to {sessionID}")
        elif val == fix.MsgType_Logout: # 35 = 5
            logger.info(f"[LOGOUT] >>> Sending Logout to {sessionID}")

        raw = message.toString().replace('\x01', '|')
        logger.info(f"[TO ADMIN RAW] {raw}")

    def fromAdmin(self, message, sessionID):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        val = msg_type.getValue()

        if val == fix.MsgType_Heartbeat:
            pass         # 35=0
            #logger.info(f"[HEARTBEAT] <<< Received from {sessionID}")

        elif val == fix.MsgType_Logon:           # 35=A
            logger.info(f"[LOGON] <<< Client connected: {sessionID}")

        elif val == fix.MsgType_Logout:          # 35=5
            reason = fix.Text()
            text = ""
            if message.isSetField(reason):
                message.getField(reason)
                text = reason.getValue()
            logger.info(f"[LOGOUT] <<< Client disconnected: {sessionID} | Reason: {text or 'none'}")

        elif val == fix.MsgType_TestRequest:     # 35=1
            test_id = fix.TestReqID()
            message.getField(test_id)
            logger.info(f"[TEST REQUEST] <<< {sessionID} | TestReqID: {test_id.getValue()}")

        raw = message.toString().replace('\x01', '|')
        logger.debug(f"[FROM ADMIN RAW] {raw}")

    def toApp(self, message, sessionID):
        raw = message.toString().replace('\x01', '|')
        logger.info(f">>> SENDING APP MSG: {raw}")

    def fromApp(self, message, sessionID):
        msg_type = fix.MsgType()
        message.getHeader().getField(msg_type)
        val = msg_type.getValue()

        # Determine client_id from the incoming message's SenderCompID (Tag 49)
        sender = fix.SenderCompID()
        message.getHeader().getField(sender)
        client_id = sender.getValue()

        if val == fix.MsgType_NewOrderSingle:
            self.handle_new_order(message, sessionID, client_id)
        elif val == fix.MsgType_OrderCancelRequest:
            self.handle_cancel(message, sessionID, client_id)
        elif val == fix.MsgType_OrderCancelReplaceRequest:
            self.handle_replace(message, sessionID, client_id)
        elif val == "AN":
            self.handle_position_request(message, sessionID, client_id)

    #  Session Lookup Helper ──────────────────────────────────────
    
    def get_session_for_client(self, client_id):
        return self._sessions.get(client_id)

    @property
    def active_session(self):
        if self._sessions:
            return next(iter(self._sessions.values()))
        return None

    #  New Order  (35=D) ──────────────────────────
    def handle_new_order(self, message, sessionID, client_id):
        try:
            symbol  = fix.Symbol();   message.getField(symbol)
            side    = fix.Side();     message.getField(side)
            qty     = fix.OrderQty(); message.getField(qty)
            clordid = fix.ClOrdID();  message.getField(clordid)

            ord_type     = fix.OrdType()
            order_type_str = "LIMIT"
            if message.isSetField(ord_type):
                message.getField(ord_type)
                order_type_str = "MARKET" if ord_type.getValue() == "1" else "LIMIT"

            price  = fix.Price()
            px_val = 0.0
            if message.isSetField(price):
                message.getField(price)
                px_val = price.getValue()

            # ── Pre-trade Risk Check ───────────
            passed, reason = self.risk_engine.check(
                client_id, symbol.getValue(), int(side.getValue()), int(qty.getValue()), px_val
            )
            if not passed:
                logger.warning(f"[RISK REJECT] {client_id} {clordid.getValue()}: {reason}")
                self._send_risk_reject(message, sessionID, clordid.getValue(), reason)
                return
            
            # ── Persist Order ─────────────────────
            order = self.order_service.handle_new_order_from_fix(
                cl_ord_id  = clordid.getValue(),
                symbol     = symbol.getValue(),
                side       = side.getValue(),
                quantity   = qty.getValue(),
                price      = px_val,
                client_id  = client_id,
                order_type = order_type_str,
            )

            # ── Acknowledge ─────────────────────────
            self.send_execution_report(order, sessionID, fix.ExecType_NEW)
            # ── Match ────────────────────────────────
            self.matching_engine.process_new_order(order)

        except Exception as e:
            logger.warning(f"Order processing failed: {e}")
            self.send_reject(message, sessionID, str(e))

    #  Cancel  (35=F) ──────────────────────────────────────────────────────────────
    def handle_cancel(self, message, sessionID, client_id):
        orig_id   = fix.OrigClOrdID(); message.getField(orig_id)
        cl_ord_id = fix.ClOrdID();     message.getField(cl_ord_id)
        try:
            order, success, reason = self.order_service.handle_cancel_request(
                orig_id.getValue(), cl_ord_id.getValue()
            )
            if success:
                self.send_execution_report(order, sessionID, fix.ExecType_CANCELED)
            else:
                self.send_cancel_reject(cl_ord_id.getValue(), orig_id.getValue(), sessionID, reason)
        except Exception as e:
            logger.error(f"Cancel failed: {e}")

    #  Replace  (35=G)  ────────────────────────────────────────────────────────────────────
    def handle_replace(self, message, sessionID, client_id):
        orig_id   = fix.OrigClOrdID(); message.getField(orig_id)
        cl_ord_id = fix.ClOrdID();     message.getField(cl_ord_id)
        qty       = fix.OrderQty();    message.getField(qty)

        price  = fix.Price()
        px_val = 0.0
        if message.isSetField(price):
            message.getField(price)
            px_val = price.getValue()

        try:
            order, success, reason = self.order_service.handle_replace_request(
                orig_id.getValue(), cl_ord_id.getValue(), px_val, qty.getValue()
            )
            if success:
                self.send_execution_report(order, sessionID, fix.ExecType_REPLACED)
            else:
                self.send_cancel_reject(cl_ord_id.getValue(), orig_id.getValue(), sessionID, reason)
        except Exception as e:
            logger.error(f"Replace failed: {e}")

    #  Position Report Request 
    def handle_position_request(self, message, sessionID, client_id):
        try:
            pos_req_id = fix.StringField(710)
            message.getField(pos_req_id)
        except Exception:
            pos_req_id = None

        positions = self.position_service.get_all_positions(client_id)

        report = fix.Message()
        header = report.getHeader()
        header.setField(fix.MsgType("AP"))
        header.setField(fix.SenderCompID("OMS"))
        header.setField(fix.TargetCompID(client_id))

        report.setField(fix.StringField(710, pos_req_id.getString() if pos_req_id else "0"))
        report.setField(fix.StringField(715, str(uuid.uuid4())))
        report.setField(fix.StringField(1, client_id))

        for pos in positions:
            long_qty  = max(pos.net_qty, 0)
            short_qty = abs(min(pos.net_qty, 0))
            grp = fix.Group(702, 55)
            grp.setField(fix.Symbol(pos.symbol))
            grp.setField(fix.IntField(704, long_qty))
            grp.setField(fix.IntField(705, short_qty))
            grp.setField(fix.FloatField(730, pos.avg_cost))
            grp.setField(fix.StringField(58, f"PnL:{pos.realized_pnl:.2f}"))
            report.addGroup(grp)

        fix.Session.sendToTarget(report, sessionID)
        logger.info(f"[POSITION REPORT] Sent {len(positions)} positions to {client_id}")


     #  Execution Report  (35=8) ─────────────────────────────────────────────────────────────── 
    def send_execution_report(self, order, session_id, exec_type):
        report = fix.Message()
        report.getHeader().setField(fix.MsgType(fix.MsgType_ExecutionReport))

        report.setField(fix.OrderID(order.cl_ord_id))
        report.setField(fix.ClOrdID(order.cl_ord_id))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.Symbol(order.symbol))
        report.setField(fix.Side(str(order.side)))
        report.setField(fix.OrderQty(order.quantity))

        cum_qty    = getattr(order, 'cum_qty',    0)
        leaves_qty = getattr(order, 'leaves_qty', order.quantity)

        report.setField(fix.CumQty(cum_qty))
        report.setField(fix.LeavesQty(leaves_qty))
        report.setField(fix.ExecType(exec_type))

        if exec_type == fix.ExecType_CANCELED:
            report.setField(fix.OrdStatus(fix.OrdStatus_CANCELED))
        elif exec_type == fix.ExecType_REPLACED:
            if cum_qty > 0 and leaves_qty > 0:
                report.setField(fix.OrdStatus(fix.OrdStatus_PARTIALLY_FILLED))
            elif leaves_qty <= 0:
                report.setField(fix.OrdStatus(fix.OrdStatus_FILLED))
            else:
                report.setField(fix.OrdStatus(fix.OrdStatus_NEW))
        elif leaves_qty == 0 and cum_qty > 0:
            report.setField(fix.OrdStatus(fix.OrdStatus_FILLED))
        elif cum_qty > 0:
            report.setField(fix.OrdStatus(fix.OrdStatus_PARTIALLY_FILLED))
        else:
            report.setField(fix.OrdStatus(fix.OrdStatus_NEW))

        report.setField(fix.LastQty(getattr(order, 'last_qty', 0)))
        report.setField(fix.LastPx(getattr(order,  'last_px',  0.0)))
        report.setField(fix.AvgPx(getattr(order,   'avg_px',   0.0)))
        
        # Echo the client_id in Tag 1 (Account) so multi-client can trace
        if hasattr(order, 'client_id'):
            report.setField(fix.StringField(1, order.client_id))

        fix.Session.sendToTarget(report, session_id)

     #  Rejects ────────────────────────────────────
    def send_cancel_reject(self, clOrdID, origClOrdID, sessionID, reason):
        reject = fix44.OrderCancelReject()
        reject.setField(fix.OrderID("NONE"))
        reject.setField(fix.ClOrdID(clOrdID))
        reject.setField(fix.OrigClOrdID(origClOrdID))
        reject.setField(fix.OrdStatus(fix.OrdStatus_REJECTED))
        reject.setField(fix.CxlRejResponseTo(fix.CxlRejResponseTo_ORDER_CANCEL_REQUEST))
        reject.setField(fix.Text(reason))
        fix.Session.sendToTarget(reject, sessionID)

    def send_reject(self, message, sessionID, reason=""):
        """Dedicated risk-reject execution report with Text explaining why."""
        report = fix.Message()
        report.getHeader().setField(fix.MsgType(fix.MsgType_ExecutionReport))
        report.setField(fix.OrderID("NONE"))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(fix.ExecType_REJECTED))
        report.setField(fix.OrdStatus(fix.OrdStatus_REJECTED))

        try:
            clordid = fix.ClOrdID(); message.getField(clordid)
            report.setField(clordid)
        except Exception:
            report.setField(fix.ClOrdID("UNKNOWN"))

        try:
            side = fix.Side(); message.getField(side)
            report.setField(side)
        except Exception:
            report.setField(fix.Side(fix.Side_UNDISCLOSED))

        try:
            symbol = fix.Symbol(); message.getField(symbol)
            report.setField(symbol)
        except Exception:
            report.setField(fix.Symbol("UNKNOWN"))

        report.setField(fix.LeavesQty(0))
        report.setField(fix.CumQty(0))
        report.setField(fix.AvgPx(0.0))
        report.setField(fix.Text(reason))
        fix.Session.sendToTarget(report, sessionID)

    def _send_risk_reject(self, message, sessionID, cl_ord_id, reason):
        report = fix.Message()
        report.getHeader().setField(fix.MsgType(fix.MsgType_ExecutionReport))
        report.setField(fix.OrderID("NONE"))
        report.setField(fix.ClOrdID(cl_ord_id))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.ExecType(fix.ExecType_REJECTED))
        report.setField(fix.OrdStatus(fix.OrdStatus_REJECTED))

        try:
            side = fix.Side(); message.getField(side)
            report.setField(side)
        except Exception:
            report.setField(fix.Side(fix.Side_UNDISCLOSED))

        try:
            symbol = fix.Symbol(); message.getField(symbol)
            report.setField(symbol)
        except Exception:
            report.setField(fix.Symbol("UNKNOWN"))

        report.setField(fix.LeavesQty(0))
        report.setField(fix.CumQty(0))
        report.setField(fix.AvgPx(0.0))
        report.setField(fix.Text(f"RISK: {reason}"))
        fix.Session.sendToTarget(report, sessionID)
