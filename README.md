# FIX OMS — Order Management System

A FIX 4.4 Order Management System built in Python. It accepts connections from multiple trading clients simultaneously, runs pre-trade risk checks, matches orders using price-time priority, tracks positions and P&L, and maintains a live market data snapshot — all over the FIX protocol.

---

## What It Does

- Accepts FIX 4.4 connections from multiple clients (CLIENT, CLIENT2, PRIME)
- Handles New Order (35=D), Cancel (35=F), and Cancel/Replace (35=G)
- Runs pre-trade risk checks before accepting any order
- Matches buy and sell orders using price-time priority
- Tracks per-client positions and realized P&L after every fill
- Maintains a live market data snapshot (last price, VWAP, volume, high/low, BBO)
- Persists all orders and executions to a SQLite database
- Sends Execution Reports (35=8) and Cancel Rejects (35=9) back to clients

---

## Project Structure

```
FIX OMS/
├── oms.py                          ← Entry point — starts the FIX acceptor
├── requirements.txt
├── config/
│   ├── server.cfg                  ← FIX session config (port, sessions, heartbeat)
│   ├── client.cfg                  ← Config for connecting a test client
│   ├── client2.cfg
│   └── spec/
│       └── FIX44.xml               ← FIX 4.4 data dictionary
├── app/
│   ├── fix/
│   │   └── application.py          ← Core FIX application (routes all messages)
│   ├── services/
│   │   ├── order_service.py        ← Order CRUD and fill logic
│   │   ├── matching_engine.py      ← Price-time priority matching
│   │   ├── risk_engine.py          ← Pre-trade risk checks
│   │   ├── position_service.py     ← Position and P&L tracking
│   │   ├── market_data_service.py  ← VWAP, volume, BBO updates
│   │   ├── execution_service.py    ← Execution record management
│   │   └── order_state_machine.py  ← Valid order status transitions
│   ├── models/
│   │   ├── order.py                ← Order table
│   │   ├── execution.py            ← Execution/fill table
│   │   ├── position.py             ← Position table
│   │   └── market_data.py          ← Market data snapshot table
│   ├── core/
│   │   ├── liquidity_book.py       ← In-memory order book (bids/asks)
│   │   └── logger.py               ← Shared logger setup
│   ├── db/
│   │   ├── database.py             ← SQLAlchemy engine and session factory
│   │   └── base.py                 ← Declarative base for all models
│   ├── mapping/
│   │   └── fix_mapper.py           ← Converts FIX message fields to Order objects
│   └── repository/
│       └── order_repository.py     ← Low-level order DB queries
├── store/                          ← FIX message store (auto-created)
└── logs/                           ← FIX session logs (auto-created)
```

---

## Setup

**Requirements:** Python 3.9+

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the OMS
python oms.py
```

When it starts you should see:

```
Initializing database...
--- FIX OMS STARTED ---
Listening for client connections...
Multi-client support: YES  |  Risk checks: YES  |  Positions: YES
```

---

## Configuration

The FIX session config lives in `config/server.cfg`. The OMS listens on port **9878** and supports three pre-configured sessions:

| SenderCompID | TargetCompID | Description |
|---|---|---|
| OMS | CLIENT | Primary trading client |
| OMS | CLIENT2 | Second trading client |
| OMS | PRIME | Prime broker / institutional |

To add a new client, add a new `[SESSION]` block to `server.cfg` with the desired `TargetCompID`. No code changes needed.

---

## Supported FIX Messages

### Incoming (from client → OMS)

| MsgType | Name | Description |
|---|---|---|
| 35=D | New Order Single | Place a new buy or sell order |
| 35=F | Order Cancel Request | Cancel an existing active order |
| 35=G | Order Cancel/Replace | Modify the price or quantity of an active order |

### Outgoing (from OMS → client)

| MsgType | Name | When sent |
|---|---|---|
| 35=8 | Execution Report | Order accepted, filled, cancelled, replaced, or rejected |
| 35=9 | Order Cancel Reject | Cancel or replace request was rejected |

---

## Order Lifecycle

```
Client sends 35=D
       ↓
Risk check (qty, price, notional, position limit)
       ↓ fail               ↓ pass
35=8 REJECTED          35=8 NEW sent to client
                              ↓
                     Matching engine checks order book
                     ↓ match found         ↓ no match
               35=8 FILL sent         Order queued in book
               position updated       (waits for counterpart)
               market data updated
```

After a cancel:
```
Client sends 35=F with OrigClOrdID
       ↓ order found and active    ↓ order already done
35=8 CANCELED sent               35=9 CANCEL REJECT sent
                                  with reason text
```

---

## Risk Checks

Every order passes through the risk engine before being accepted. The default limits are:

| Check | Default Limit |
|---|---|
| Maximum order quantity | 100,000 shares |
| Maximum order notional value | £10,000,000 |
| Maximum net position per symbol | ±500,000 shares |
| Minimum price | 0.0001 |
| Maximum price | 999,999.00 |

To apply different limits to a specific client, add an entry to `CLIENT_LIMITS` in `app/services/risk_engine.py`:

```python
CLIENT_LIMITS = {
    "CLIENT2": {
        "max_order_value": 5_000_000,
        "max_position_qty": 100_000,
    }
}
```

---

## Order Matching

The matching engine uses **price-time priority**:

- Bids are sorted highest price first, then oldest first at the same price.
- Asks are sorted lowest price first, then oldest first.
- A match happens when an incoming buy price is >= the best ask, or an incoming sell price is <= the best bid.
- The match price is always the resting order's price.
- Partial fills are supported — the unfilled remainder stays in the book.

---

## Database

The OMS uses **SQLite** (`oms.db`) via SQLAlchemy. Tables are created automatically on startup.

| Table | Contents |
|---|---|
| `orders` | Every order with full state (status, filled qty, avg price) |
| `executions` | Every individual fill event |
| `positions` | Per-client, per-symbol net position and P&L |
| `market_data` | Latest price snapshot per symbol |

The in-memory order book (`liquidity_book.py`) is separate from the database and resets when the OMS restarts. Active orders from a previous run will be in the database but not in the book — something to be aware of in production use.

---

## FIX Tag Reference

Common tags used throughout the system:

| Tag | Name | Values |
|---|---|---|
| 35 | MsgType | D=New, F=Cancel, G=Replace, 8=ExecReport, 9=CancelReject |
| 11 | ClOrdID | Unique order ID assigned by the client |
| 41 | OrigClOrdID | The ClOrdID of the order being cancelled or replaced |
| 49 | SenderCompID | Who sent the message (e.g. CLIENT) |
| 54 | Side | 1=Buy, 2=Sell |
| 55 | Symbol | Instrument ticker (e.g. AAPL) |
| 38 | OrderQty | Number of shares |
| 44 | Price | Limit price |
| 39 | OrdStatus | 0=New, 1=PartFill, 2=Filled, 4=Canceled, 8=Rejected |
| 150 | ExecType | 0=New, F=Trade, 4=Canceled, 5=Replaced, 8=Rejected |
| 14 | CumQty | Total quantity filled so far |
| 151 | LeavesQty | Quantity still open |
| 6 | AvgPx | Average fill price |
| 58 | Text | Reject reason or informational message |

---

## Logs

QuickFIX writes session logs to the `logs/` directory and stores message sequences in `store/`. These are created automatically and are useful for debugging raw FIX traffic. Each log file is named by session (e.g. `FIX.4.4-OMS-CLIENT.messages.log`).

---

## Dependencies

```
sqlalchemy==2.0.47
quickfix==1.15.1
```

QuickFIX must be installed from a `.whl` file matching your Python version and OS if a binary is not available via pip. Check the QuickFIX Python documentation for the correct wheel file.