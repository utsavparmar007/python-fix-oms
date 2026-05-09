import quickfix as fix
import quickfix44 as fix44
import uuid
import logging
import queue
import threading
from app.services.order_service import OrderService
from app.services.matching_engine import MatchingEngine
from app.services.risk_engine import RiskEngine
from app.services.position_service import PositionService
from app.core.logger import get_logger
from app.db.database import SessionLocal
from datetime import datetime

logger = get_logger()


class OMSApplication(fix.Application):

    def __init__(self):
        super().__init__()
        self.order_service    = OrderService(SessionLocal)
        self.matching_engine  = MatchingEngine(self)
        self.risk_engine      = RiskEngine()
        self.position_service = PositionService()
        self._sessions        = {}
        self.message_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

    def _process_queue(self):
        while True:
            message, sessionID = self.message_queue.get()
            try:
                msg_type = fix.MsgType()
                message.getHeader().getField(msg_type)
                val = msg_type.getValue()

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
                elif val == fix.MsgType_OrderMassCancelRequest: 
                    self.handle_mass_cancel(message, sessionID, client_id)
            except Exception as e:
                logger.error(f"Error processing message in background thread: {e}")
            finally:
                self.message_queue.task_done()

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
            
        elif val == fix.MsgType_Reject:          # 35=3
            # --- Capture Session Rejects explicitly so they don't hide in raw logs ---
            ref_tag = fix.StringField(371)
            ref_msg = fix.StringField(372)
            reason_txt = fix.Text()
            
            tag_val = "N/A"
            if message.isSetField(ref_tag):
                message.getField(ref_tag)
                tag_val = ref_tag.getValue()
                
            msg_val = "N/A"
            if message.isSetField(ref_msg):
                message.getField(ref_msg)
                msg_val = ref_msg.getValue()
                
            txt_val = "N/A"
            if message.isSetField(reason_txt):
                message.getField(reason_txt)
                txt_val = reason_txt.getValue()

            logger.error(f"[SESSION REJECT] <<< {sessionID} | RefMsgType: {msg_val} | RefTag: {tag_val} | Reason: {txt_val}")

        raw = message.toString().replace('\x01', '|')
        logger.debug(f"[FROM ADMIN RAW] {raw}")

    def toApp(self, message, sessionID):
        raw = message.toString().replace('\x01', '|')
        logger.info(f">>> SENDING APP MSG: {raw}")

    def fromApp(self, message, sessionID):
        raw_msg = message.toString().replace(chr(1), '|')
        logger.info(f"<<< RECEIVED APP MSG: {raw_msg}")

        # Enqueue a clone of the message so the background worker thread can process it asynchronously
        msg_clone = fix.Message(message)
        self.message_queue.put((msg_clone, sessionID))

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
        
            clordid_val = clordid.getValue()
            if self.order_service.is_duplicate_clordid(client_id, clordid_val):
                logger.warning(f"[REJECT] {client_id} sent duplicate ClOrdID: {clordid_val}")
                self.send_order_reject(message, sessionID, clordid_val, f"Duplicate ClOrdID: {clordid_val}")
                return

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
            
            tif = fix.TimeInForce()
            tif_val = "0" # Default to Day (0)
            if message.isSetField(tif):
                message.getField(tif)
                tif_val = tif.getValue()

            # ── Pre-trade Risk Check ───────────
            passed, reason = self.risk_engine.check(
                client_id, symbol.getValue(), int(side.getValue()), int(qty.getValue()), px_val
            )
            if not passed:
                logger.warning(f"[RISK REJECT] {client_id} {clordid.getValue()}: {reason}")
                self._send_risk_reject(message, sessionID, clordid.getValue(), reason)
                return
            
            parties = self.extract_parties(message)

            # ── Persist Order ─────────────────────
            order = self.order_service.handle_new_order_from_fix(
                cl_ord_id  = clordid.getValue(),
                symbol     = symbol.getValue(),
                side       = side.getValue(),
                quantity   = qty.getValue(),
                price      = px_val,
                client_id  = client_id,
                order_type = order_type_str,
                broker_id  = parties["broker_id"],    
                trader_id  = parties["trader_id"],    
                client_ref = parties["client_ref"],
                time_in_force = tif_val   
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
                # Remove from RAM book
                book = self.matching_engine.liquidity_manager.get_book(order.symbol)
                book_side = book.bids if order.side == 1 else book.asks
                for resting in list(book_side):
                    if resting.cl_ord_id == orig_id.getValue():
                        book_side.remove(resting)
                        break
                self.send_execution_report(order, sessionID, fix.ExecType_CANCELED, cl_ord_id=cl_ord_id.getValue(), orig_cl_ord_id=orig_id.getValue())
            else:
                self.send_cancel_reject(cl_ord_id.getValue(), orig_id.getValue(), sessionID, reason)
        except Exception as e:
            logger.error(f"Cancel failed: {e}")

    def handle_mass_cancel(self, message, sessionID, client_id):
        # 1. Extract Mass Cancel Request Type (530)
        # 1=Cancel for Symbol, 7=Cancel All
        req_type = fix.MassCancelRequestType()
        message.getField(req_type)
        cancel_type = req_type.getValue()
        
        clordid = fix.ClOrdID()
        message.getField(clordid)

        target_symbol = None
        if cancel_type == "1":
            sym = fix.Symbol()
            if message.isSetField(sym):
                message.getField(sym)
                target_symbol = sym.getValue()

        # 2. Cancel them in the database
        canceled_orders = self.order_service.mass_cancel(symbol=target_symbol, client_id=client_id)
        
        # 3. YANK THEM FROM THE IN-MEMORY BOOK 
        for o in canceled_orders:
            book = self.matching_engine.liquidity_manager.get_book(o.symbol)
            book_side = book.bids if o.side == 1 else book.asks
            # Remove from RAM
            for resting in list(book_side):
                if resting.cl_ord_id == o.cl_ord_id:
                    book_side.remove(resting)
                    break
            # Send standard Execution Report for each canceled order
            # For Mass Cancel, Tag 11 = MassCancelRequest ClOrdID, Tag 41 = Original Order ClOrdID
            self.send_execution_report(o, sessionID, fix.ExecType_CANCELED, 
                                       cl_ord_id=clordid.getValue(), 
                                       orig_cl_ord_id=o.cl_ord_id)

        # 4. Send the official Mass Cancel Report (35=r)
        report = fix44.OrderMassCancelReport()
        report.setField(fix.ClOrdID(clordid.getValue()))
        report.setField(fix.OrderID(str(uuid.uuid4())))
        report.setField(fix.MassCancelRequestType(cancel_type))
        # Echo the request type as the response scope (e.g. 1=Symbol, 7=All)
        report.setField(fix.MassCancelResponse(cancel_type)) 
        report.setField(fix.TotalAffectedOrders(len(canceled_orders)))
        
        if target_symbol:
            report.setField(fix.Symbol(target_symbol))
            
        fix.Session.sendToTarget(report, sessionID)
        
        logger.info(f"[MASS CANCEL] {client_id} wiped {len(canceled_orders)} orders.")

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
                # Update RAM book
                book = self.matching_engine.liquidity_manager.get_book(order.symbol)
                book_side = book.bids if order.side == 1 else book.asks
                for resting in list(book_side):
                    if resting.cl_ord_id == orig_id.getValue():
                        # Update fields
                        resting.cl_ord_id = cl_ord_id.getValue()
                        resting.price = px_val
                        resting.quantity = qty.getValue()
                        resting.leaves_qty = order.leaves_qty
                        # Re-sort book because price might have changed
                        if order.side == 1:
                            book.bids.sort(key=lambda x: (-x.price, x._sequence))
                        else:
                            book.asks.sort(key=lambda x: (x.price, x._sequence))
                        break
                self.send_execution_report(order, sessionID, fix.ExecType_REPLACED, cl_ord_id=cl_ord_id.getValue(), orig_cl_ord_id=orig_id.getValue())
            else:
                self.send_cancel_reject(cl_ord_id.getValue(), orig_id.getValue(), sessionID, reason)
        except Exception as e:
            logger.error(f"Replace failed: {e}")

    def extract_parties(self, message):
        parties = {"broker_id": None, "trader_id": None, "client_ref": None}

        try:
            if message.isSetField(453):
                
                # Grab the count using a generic IntField
                count_field = fix.IntField(453)
                message.getField(count_field)
                count = count_field.getValue()

                for i in range(1, count + 1):
                    # 453 is the Group, 448 is the first field in the group
                    grp = fix.Group(453, 448)
                    message.getGroup(i, grp)

                    # Extract the ID (Tag 448)
                    party_id = fix.StringField(448)
                    grp.getField(party_id)
                    pid = party_id.getValue()

                    # Extract the Role (Tag 452)
                    party_role = fix.IntField(452)
                    grp.getField(party_role)
                    role = party_role.getValue()

                    # Map it!
                    if role == 1:
                        parties["broker_id"] = pid
                    elif role in [11, 36]:
                        parties["trader_id"] = pid
                    elif role == 3:
                        parties["client_ref"] = pid

        except Exception as e:
            logger.error(f"Party Extraction Failed: {e}")

        logger.info(f"Extracted Parties Dictionary: {parties}")
        return parties

    def add_parties_to_report(self, report, order):
        """
        Injects the Executing Firm and the original Trader ID 
        into an outgoing Execution Report (35=8).
        """
        # We always attach ourselves (1 party). If the order has a trader, it's 2 parties.
        num_parties = 1 if not order.trader_id else 2
        report.setField(fix.NoPartyIDs(num_parties))
        
        # --- Party 1: The Executing Firm (You!) ---
        g1 = fix.Group(453, 448)
        g1.setField(fix.StringField(448, "MY_CUSTOM_OMS")) # Change this to your actual firm name!
        g1.setField(fix.CharField(447, "D"))               # D = Custom/Proprietary
        g1.setField(fix.IntField(452, 1))                  # 1 = Executing Firm
        report.addGroup(g1)
        
        # --- Party 2: Echo the Trader ID (if it exists) ---
        if order.trader_id:
            g2 = fix.Group(453, 448)
            g2.setField(fix.StringField(448, order.trader_id)) 
            g2.setField(fix.CharField(447, "D"))
            g2.setField(fix.IntField(452, 11))             # 11 = Order Originator
            report.addGroup(g2)

        return report

    #  Position Report Request
    def handle_position_request(self, message, sessionID, client_id):
        # Extract PosReqID (Tag 710) from the request if present
        try:
            pos_req_id_field = fix.StringField(710)
            message.getField(pos_req_id_field)
            pos_req_id = pos_req_id_field.getString()
        except Exception:
            pos_req_id = "0"

        positions = self.position_service.get_all_positions(client_id)

        # Send one AP (PositionReport) per position, or one empty AP if none.
        # This avoids broken repeating-group encoding on a raw fix.Message()
        # which causes QuickFIX on the client side to reject the message before
        # fromApp is ever called. One flat AP per position is fully FIX 4.4 compliant.
        today = datetime.now().strftime("%Y%m%d")
        total = max(len(positions), 1)
        entries = positions if positions else [None]

        for pos in entries:
            report = fix44.PositionReport()
            
            # 1. Use strongly-typed fields to force correct FIX 4.4 Tag Ordering
            report.setField(fix.PosMaintRptID(str(uuid.uuid4())))
            report.setField(fix.PosReqID(pos_req_id))
            report.setField(fix.TotalNumPosReports(total))
            report.setField(fix.PosReqResult(0))
            report.setField(fix.ClearingBusinessDate(today))
            report.setField(fix.Account(client_id))
            report.setField(fix.AccountType(1))
            report.setField(fix.SettlPrice(0.0))
            report.setField(fix.SettlPriceType(1))
            report.setField(fix.PriorSettlPrice(0.0))
            
            # Parties group
            parties_grp = fix.Group(453, 448)
            parties_grp.setField(fix.StringField(448, client_id))
            parties_grp.setField(fix.StringField(447, "D"))
            parties_grp.setField(fix.IntField(452, 3))
            report.addGroup(parties_grp)
            
            if pos is not None:
                report.setField(fix.Symbol(pos.symbol))
                long_qty  = max(pos.net_qty, 0)
                short_qty = abs(min(pos.net_qty, 0))
                
                pos_grp = fix.Group(702, 703)
                # 2. FIX: Tag 703 is a String, not an Integer. "TQ" = Transaction Quantity
                pos_grp.setField(fix.StringField(703, "TQ")) 
                pos_grp.setField(fix.DoubleField(704, float(long_qty)))
                pos_grp.setField(fix.DoubleField(705, float(short_qty)))
                report.addGroup(pos_grp)
                
                report.setField(fix.Text(f"AvgCost:{pos.avg_cost:.2f} PnL:{pos.realized_pnl:.2f}"))
            else:
                report.setField(fix.Symbol("N/A"))
                
                pos_grp = fix.Group(702, 703)
                pos_grp.setField(fix.StringField(703, "TQ"))
                pos_grp.setField(fix.DoubleField(704, 0.0))
                pos_grp.setField(fix.DoubleField(705, 0.0))
                report.addGroup(pos_grp)
                
            # PositionAmountData component
            amt_grp = fix.Group(753, 707)
            amt_grp.setField(fix.StringField(707, "CASH"))
            amt_grp.setField(fix.DoubleField(708, 0.0))
            report.addGroup(amt_grp)
            
            fix.Session.sendToTarget(report, sessionID)

        logger.info(f"[POSITION REPORT] Sent {len(entries)} AP message(s) to {client_id} | PosReqID={pos_req_id}")


    #  Execution Report  (35=8) ─────────────────────────────────────────────────────────────── 
    def send_execution_report(self, order, session_id, exec_type, cl_ord_id=None, orig_cl_ord_id=None):
        report = fix44.ExecutionReport()

        # Tag 37 (OrderID) should be the system's unique identifier for the order
        # We'll use the persistent order_id field from the database
        report.setField(fix.OrderID(order.order_id))
        
        # Tag 11 (ClOrdID) and Tag 41 (OrigClOrdID)
        # If this is a response to a Cancel/Replace/MassCancel, cl_ord_id is the Request's ID
        if cl_ord_id:
            report.setField(fix.ClOrdID(cl_ord_id))
            if orig_cl_ord_id:
                report.setField(fix.OrigClOrdID(orig_cl_ord_id))
        else:
            # For New Order Single acknowledgments
            report.setField(fix.ClOrdID(order.cl_ord_id))
        report.setField(fix.ExecID(str(uuid.uuid4())))
        report.setField(fix.Symbol(order.symbol))
        report.setField(fix.Side(str(order.side)))
        report.setField(fix.OrderQty(float(order.quantity)))

        cum_qty    = getattr(order, 'cum_qty',    0)
        leaves_qty = getattr(order, 'leaves_qty', order.quantity)

        report.setField(fix.CumQty(float(cum_qty)))
        report.setField(fix.LeavesQty(float(leaves_qty)))
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

        report.setField(fix.LastQty(float(getattr(order, 'last_qty', 0))))
        report.setField(fix.LastPx(float(getattr(order,  'last_px',  0.0))))
        report.setField(fix.AvgPx(float(getattr(order,   'avg_px',   0.0))))
        
        # Echo the client_id in Tag 1 (Account) so multi-client can trace
        if hasattr(order, 'client_id'):
            report.setField(fix.StringField(1, order.client_id))
        
        self.add_parties_to_report(report, order)

        try:
            fix.Session.sendToTarget(report, session_id)
        except Exception as e:
            logger.error(f"Failed to send Execution Report: {e}")

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
        report = fix44.ExecutionReport()
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

        report.setField(fix.LeavesQty(0.0))
        report.setField(fix.CumQty(0.0))
        report.setField(fix.AvgPx(0.0))
        report.setField(fix.Text(reason))
        fix.Session.sendToTarget(report, sessionID)

    def send_order_reject(self, message, sessionID, clordid_val, reason_text):
        """Sends an ExecutionReport (35=8) rejecting the order."""
        reject = fix44.ExecutionReport()
        
        # Required Execution Report Fields for a Reject
        reject.setField(fix.OrderID("NONE"))           # No OrderID since we didn't accept it
        reject.setField(fix.ClOrdID(clordid_val))      # Echo back the duplicate ID
        reject.setField(fix.ExecID(str(uuid.uuid4()))) # Unique ID for this specific message
        reject.setField(fix.ExecType(fix.ExecType_REJECTED)) # 150=8
        reject.setField(fix.OrdStatus(fix.OrdStatus_REJECTED)) # 39=8
        
        # Pull Side and Symbol from the original message if they exist
        side = fix.Side()
        if message.isSetField(side):
            message.getField(side)
            reject.setField(side)
        else:
            reject.setField(fix.Side(fix.Side_UNDISCLOSED))
            
        symbol = fix.Symbol()
        if message.isSetField(symbol):
            message.getField(symbol)
            reject.setField(symbol)
        else:
            reject.setField(fix.Symbol("UNKNOWN"))
            
        # Quantities must be 0 for a rejected order
        reject.setField(fix.LeavesQty(0.0))
        reject.setField(fix.CumQty(0.0))
        reject.setField(fix.AvgPx(0.0))
        
        # Reason for Rejection
        reject.setField(fix.OrdRejReason(6)) # 103=6 means "Duplicate Order"
        reject.setField(fix.Text(reason_text))
        
        fix.Session.sendToTarget(reject, sessionID)

    def _send_risk_reject(self, message, sessionID, cl_ord_id, reason):
        report = fix44.ExecutionReport()
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

        report.setField(fix.LeavesQty(0.0))
        report.setField(fix.CumQty(0.0))
        report.setField(fix.AvgPx(0.0))
        report.setField(fix.Text(f"RISK: {reason}"))
        fix.Session.sendToTarget(report, sessionID)
