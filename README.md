# Python FIX Order Management System (OMS)

OMS is a high-performance, multi-threaded Order Management System built with Python, QuickFIX, and Flask. It manages the full lifecycle of FIX 4.4 messages and features a "Self-Healing" security thread that integrates with an external Redis-based risk gateway.

🚀 Key Features

FIX 4.4 Protocol: Full session management (Logon, Heartbeats) and application-level messaging (35=D, 35=G).

Automated Risk Integration: A dedicated background thread monitors the Redis Kill Switch to neutralize non-compliant trades in sub-10ms.

REST API Control: Manage orders manually using Invoke-RestMethod or cURL for rapid testing and simulation.

State Machine Persistence: Tracks cumulative quantities and order states (New, Partial, Filled, Canceled) using SQLAlchemy.

Unit Tested: Built-in test suite to ensure order integrity and state transition accuracy.

🏗️ Architecture

SentinelOMS follows a decoupled microservices pattern:

Execution Layer: Handles FIX connectivity and order routing.

Messaging Layer: Uses Redis as a high-speed bus for outbound validation.

Security Layer: Listens for "Kill Signals" from the Sentinel Validator to trigger emergency 35=F cancels.

🛠️ Installation & Setup

Clone the Repository: git clone https://github.com/utsavparmar007/python-fix-oms.git 

cd python-fix-oms

Install Dependencies: pip install -r requirements.txt

Run the Engine: python main.py

🧪 Automated Testing 

python -m unittest tests/test_order_service.py

📡 API Endpoints

POST /admin/execute: Trigger NEW, FILL, REPLACE, or CANCEL actions via JSON.

GET /orders: View the live order repository state.
