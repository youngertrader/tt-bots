#!/usr/bin/env python3
"""
Tastytrade – PRODUCTION – EQUITY ORDERS (WITH LEGS)
SAFE PRICE = 20.0 | REAL ORDER IDs | DOUBLE-QUOTED JSON
Interactive 10-step DCA
"""

import logging
import requests
import sys
import json

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
    print(f"\n*** YOUR SESSION TOKEN: {token} ***\n")
    session.headers["Authorization"] = token
    log.info("Login successful (PROD)")
except Exception as e:
    log.error(f"Login FAILED: {e}")
    raise

# ----------------------------------------------------------------------
# 3. Helper: Submit order (buy/sell)
# ----------------------------------------------------------------------
def _submit_order(payload: dict):
    url = f"{base_url}/accounts/{account_number}/orders"
    try:
        r = session.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]
        order_obj = data.get("order", {})
        # Use "id" field (real order number)
        order_id = order_obj.get("id") or order_obj.get("order-id") or "unknown"
        return {"data": data, "order_id": order_id}
    except requests.exceptions.HTTPError as e:
        error_detail = r.json() if r.content else "No response body"
        log.error(f"ORDER FAILED ({r.status_code}): {json.dumps(error_detail, indent=2)}")
        raise e

# ----------------------------------------------------------------------
# 3a. Place BUY order
# ----------------------------------------------------------------------
def place_buy_order(quantity: int, limit_price: float, time_in_force: str = "Day"):
    payload = {
        "order-type": "Limit",
        "time-in-force": time_in_force,
        "price": str(limit_price),
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
    return _submit_order(payload)

# ----------------------------------------------------------------------
# 3b. Place SELL order (close)
# ----------------------------------------------------------------------
def place_sell_order(quantity: int, limit_price: float, time_in_force: str = "Day"):
    payload = {
        "order-type": "Limit",
        "time-in-force": time_in_force,
        "price": str(limit_price),
        "price-effect": "Credit",
        "legs": [
            {
                "instrument-type": "Equity",
                "symbol": "TQQQ",
                "quantity": str(quantity),
                "action": "Sell to Close"
            }
        ]
    }
    return _submit_order(payload)

# ----------------------------------------------------------------------
# 4. TEST: 1 Share @ $20.0
# ----------------------------------------------------------------------
# try:
#     test_price = 20.0  # SAFE PRICE
#     tif_mode = "Day"
#     log.info(f"Placing TEST order: Buy 1 TQQQ @ {test_price} (TIF: {tif_mode})")
#     result = place_buy_order(1, test_price, tif_mode)
#     order_id = result["order_id"]
#     print("\n" + " TEST ORDER RESPONSE ".center(70, "="))
#     print(json.dumps(result["data"], indent=2))  # DOUBLE QUOTES
#     print("=" * 70)
#     print(f"TEST ORDER PLACED! Order ID: {order_id}")
# except Exception as e:
#     log.error("TEST FAILED – stopping.")
#     raise

# ----------------------------------------------------------------------
# 5. INTERACTIVE 10-Step DCA (450 shares @ $20.0)
# ----------------------------------------------------------------------
try:
    confirm = input("\nRun 10-step DCA (450 shares)? (y/N): ").strip().lower()
    if confirm != "y":
        sys.exit("DCA aborted by user.")

    shares_per_step = 45
    tif_mode = "Day"
    current_price =  20.0
    bought_qty = 0
    step = 0

    print(f"\nStarting INTERACTIVE DCA: {shares_per_step} shares per step (TIF: {tif_mode})")

    while step < 10:
        step += 1
        try:
            result = place_buy_order(shares_per_step, current_price, tif_mode)
            order_id = result["order_id"]

            print("\n" + " ORDER RESPONSE ".center(70, "="))
            print(json.dumps(result["data"], indent=2))  # DOUBLE QUOTES
            print("=" * 70)
            print(f" ORDER PLACED! Order ID: {order_id}")

            bought_qty += shares_per_step
            print(f"  Step {step}/10: {shares_per_step} TQQQ @ {current_price} → Order ID: {order_id}")
        except Exception as e:
            print(f"  Step {step} FAILED: {e}")
            break

        if step == 10:
            print("DCA COMPLETE – all 10 steps executed.")
            break

        # Prompt for next action
        while True:
            nxt = input(
                f"\nNext? (next <price> | close | quit)  [default price {current_price}]: "
            ).strip().lower()

            if nxt.startswith("next"):
                parts = nxt.split()
                if len(parts) >= 2 and parts[1].replace(".", "", 1).replace("-", "", 1).isdigit():
                    current_price = float(parts[1])
                    break
                else:
                    print(f"  → Using previous price {current_price}")
                    break

            elif nxt == "close":
                try:
                    close_result = place_sell_order(bought_qty, current_price, tif_mode)
                    sell_id = close_result["order_id"]
                    print(f"  CLOSE POSITION: {bought_qty} TQQQ @ {current_price} → Order ID: {sell_id}")
                    print(json.dumps(close_result["data"], indent=2))
                except Exception as ex:
                    print(f"  CLOSE FAILED: {ex}")
                sys.exit("Position closed – exiting DCA.")

            elif nxt in ("quit", "q", "exit"):
                print("DCA stopped by user.")
                sys.exit(0)

            else:
                print("  Invalid input – type 'next <price>', 'close' or 'quit'")

except Exception as e:
    log.error(f"Error during DCA: {e}")
    raise

# ----------------------------------------------------------------------
# 6. Logout
# ----------------------------------------------------------------------
finally:
    try:
        session.delete(f"{base_url}/sessions")
        log.info("Logged out.")
    except Exception:
        pass
    session.close()