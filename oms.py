import quickfix as fix
import time
import sys
from app.fix.application import OMSApplication
from app.db.database import engine
from app.db.base import Base
import app.models.order
import app.models.execution
import app.models.position
import app.models.market_data


def main():
    try:
        # 1. Initialize / migrate all DB tables
        print("Initializing database...")
        Base.metadata.create_all(bind=engine)

        # 2. Load FIX Configuration
        settings      = fix.SessionSettings("config/server.cfg")
        application   = OMSApplication()
        store_factory = fix.FileStoreFactory(settings)
        log_factory   = fix.FileLogFactory(settings)

        # 3. Start the FIX Acceptor
        acceptor = fix.SocketAcceptor(application, store_factory, settings, log_factory)
        acceptor.start()

        print("--- FIX OMS STARTED ---")
        print("Listening for client connections...")
        print("Multi-client support: YES  |  Risk checks: YES  |  Positions: YES")

        # 4. Keep the main thread alive
        while True:
            time.sleep(1)

    except (fix.ConfigError, fix.RuntimeError) as e:
        print(f"FIX Configuration Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down OMS...")
        acceptor.stop()


if __name__ == "__main__":
    main()
