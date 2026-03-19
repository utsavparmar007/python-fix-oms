import quickfix as fix
import quickfix44 as fix44
import uuid
import time
import sys

class ClientApp(fix.Application):

    def __init__(self):
        super().__init__()
        self.sessionID = None

    def onCreate(self, sessionID):
        print("Client Session created:", sessionID)

    def onLogon(self, sessionID):
        print("Client Logon:", sessionID)
        self.sessionID = sessionID
        time.sleep(1)
        #self.send_order()

    def onLogout(self, sessionID):
        print("Client Logout:", sessionID)

    def toAdmin(self, message, sessionID):
        print("ToAdmin:", message)

    def fromAdmin(self, message, sessionID):
        print("FromAdmin:", message)

    def toApp(self, message, sessionID):
        print("ToApp:", message)

    def fromApp(self, message, sessionID):
        print("FromApp:", message)

    def send_order(self):

        order = fix44.NewOrderSingle()

        order.setField(fix.ClOrdID(str(uuid.uuid4())))
        order.setField(fix.Symbol("AAPL"))
        order.setField(fix.Side(fix.Side_BUY))
        order.setField(fix.TransactTime())

        order.setField(fix.OrdType(fix.OrdType_LIMIT))
        order.setField(fix.OrderQty(100))
        order.setField(fix.Price(150))

        order.setField(fix.HandlInst('1'))
        order.setField(fix.TimeInForce(fix.TimeInForce_DAY))

        fix.Session.sendToTarget(order, self.sessionID)

        print("NewOrderSingle sent.")
    
    def send_cancel_request(self, orig_cl_ord_id, symbol, side):
        message = fix44.OrderCancelRequest()
        message.setField(fix.OrigClOrdID(orig_cl_ord_id))
        message.setField(fix.ClOrdID(str(uuid.uuid4())))
        message.setField(fix.Symbol(symbol))
        message.setField(fix.Side(side))
        message.setField(fix.TransactTime())
        fix.Session.sendToTarget(message, self.sessionID)
    
    def send_replace_request(self, orig_cl_ord_id, new_qty, new_price):
        message = fix44.OrderCancelReplaceRequest()
        message.setField(fix.OrigClOrdID(orig_cl_ord_id))
        message.setField(fix.ClOrdID(str(uuid.uuid4())))
        message.setField(fix.OrderQty(new_qty))
        message.setField(fix.Price(new_price))
        message.setField(fix.OrdType(fix.OrdType_LIMIT))
        fix.Session.sendToTarget(message, self.sessionID)

if __name__ == "__main__":
    # Check if a config file was provided in the terminal
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        # Fallback to default if no argument is provided
        config_file = "config/client.cfg"

    try:
        print(f"Starting client with config: {config_file}")
        settings = fix.SessionSettings(config_file)
        storeFactory = fix.FileStoreFactory(settings)
        logFactory = fix.FileLogFactory(settings)

        application = ClientApp()
        initiator = fix.SocketInitiator(application, storeFactory, settings, logFactory)

        initiator.start()
        print("Client engine started. Press Ctrl+C to stop.")

        while True:
            time.sleep(1)
    except fix.ConfigError as e:
        print(f"Configuration Error: {e}")
    except KeyboardInterrupt:
        initiator.stop()