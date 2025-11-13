#!/usr/bin/env python3
"""
Tastytrade – PRODUCTION – EQUITY ORDERS (WITH LEGS)
"""

import logging
import requests

# ----------------------------------------------------------------------
# 1. Load config
# ----------------------------------------------------------------------
from config_loader import load_config

cfg, username, password, account_number, base_url, default_symbol = load_config()
use_prod = True
base_url = "https://api.tastyworks.com"

print(f"PRODUCTION MODE ON")
print(f"User: {username} | Account: {account_number}")

# ----------------------------------------------------------------------
# 2. Manual Login
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({
    "User-Agent": "python-script/1.0",
    "Content-Type": "application/json"
})

try:
    r = session.post(f"{base_url}/sessions", json={"login": username, "password": password}, timeout=15)
    r.raise_for_status()
    token = r.json()["data"]["session-token"]
    # ADD THIS LINE TEMPORARILY:
    print(f"\n*** YOUR SESSION TOKEN: {token} ***\n") 
    session.headers["Authorization"] = token
    log.info("Login successful (PROD)")
except Exception as e:
    log.error(f"Login FAILED: {e}")
    raise

# ----------------------------------------------------------------------
# 3. Place EQUITY Order WITH LEGS
# ----------------------------------------------------------------------
def place_equity_order(quantity: int, limit_price: float):
    payload = {
        "order-type": "Limit",
        "time-in-force": "GTC",
        "price": str(limit_price),
        # FIX: ADD THE REQUIRED PRICE-EFFECT FIELD
        "price-effect": "Debit", 
        "legs": [
            {
                "instrument-type": "Equity",
                "symbol": "TQQQ",
                "quantity": str(quantity),
                "action": "Buy to Open"
            }
        ]
    }

    url = f"{base_url}/accounts/{account_number}/orders"
    try:
        r = session.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()["data"]
    except requests.exceptions.HTTPError as e:
        log.error(f"ORDER FAILED ({r.status_code}): {r.json()}")
        raise e

# ----------------------------------------------------------------------
# 4. TEST: 1 Share First
# ----------------------------------------------------------------------
try:
    test_price = 80.00 
    log.info(f"Placing TEST order: Buy 1 TQQQ @ {test_price}")
    result = place_equity_order(1, test_price) # Pass the limit price
    print("\n" + " TEST ORDER RESPONSE ".center(70, "="))
    print(result)
    print("=" * 70)
    print("TEST ORDER PLACED! Check Tastytrade dashboard.")

except Exception as e:
    log.error("TEST FAILED – stopping.")
    raise

# ----------------------------------------------------------------------
# 5. OPTIONAL: 10-Step DCA (450 shares)
# ----------------------------------------------------------------------
try:
    confirm = input("\nRun 10-step DCA (450 shares)? (y/N): ").strip().lower()
    if confirm == "y":
        shares_per_step = 1
        print(f"\nStarting DCA: {shares_per_step} shares × 10 steps")
        for i in range(10):
            try:
                result = place_equity_order(shares_per_step)
                order_id = result.get("order-id", "unknown")
                print(f"  Step {i+1}/10: {shares_per_step} TQQQ → Order ID: {order_id}")
            except Exception as e:
                print(f"  Step {i+1} FAILED: {e}")
                break
        print("DCA COMPLETE")
except Exception as e:
    log.error(f"Error during DCA prompt: {e}")

# ----------------------------------------------------------------------
# 6. Logout
# ----------------------------------------------------------------------
finally:
    try:
        session.delete(f"{base_url}/sessions")
        log.info("Logged out.")
    except:
        pass
    session.close()