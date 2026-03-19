# Python FIX Order Management System (OMS)

A lightweight Order Management System built with **Python**, **QuickFIX**, and **Flask**. This system allows for manual trade control via a JSON terminal interface.

## Features
- **FIX 4.4 Protocol**: Full session management.
- **REST API Control**: Manage orders using `Invoke-RestMethod` or `cURL`.
- **Manual Matching**: Manually trigger fills, partial fills, and cancellations.
- **Risk Engine**: Includes a 10,000 order limit safety check.

## Setup
1. Install dependencies:
   ```powershell
   pip install -r requirements.txt
