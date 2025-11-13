#!/usr/bin/env python3
"""
TQQQ DCA @ $50.00 – Smart TIF + GTC Limit Orders
"""

import logging
import requests
from decimal import Decimal
from datetime import datetime, time, UTC
import pytz
import holidays
import time

# ----------------------------------------------------------------------
# 1. CONFIG & SESSION
# ----------------------------------------------------------------------
from config_loader import load_config

cfg, username, password, account_number, base_url, default_symbol = load_config()
use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
base_url = cfg.get("URI", "prod" if use_prod else "cert")

print(f"PRODUCTION MODE: {"ON" if use_prod else "OFF"}")
print(f"User: {username} | Account: {account_number} | Symbol: TQQQ")

# ----------------------------------------------------------------------
# 2. LOGGING & SESSION
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

session = requests.Session()
session.headers.update({
    "User-Agent": "tt-tqqq-dca/1.0",
    "Content-Type": "application/json"
})

# ----------------------------------------------------------------------
# 3. LOGIN
# ----------------------------------------------------------------------
try:
    r = session.post(f"{base_url}/sessions", json={"login": username, "password": password}, timeout=15)
    r.raise_for_status()
    token = r.json()["data"]["session-token"]
    session.headers["Authorization"] = token
    log.info("Login successful")
except Exception as e:
    log.error(f"Login FAILED: {e}")
    raise

# ----------------------------------------------------------------------
# 4. SMART TIF HELPER (FIXED: UTC → datetime.UTC)
# ----------------------------------------------------------------------
US_HOLIDAYS = holidays.US(years=datetime.now(UTC).year)

def get_tif_and_type(symbol: str, limit_price: float | None = None):
    now_et = datetime.now(pytz.timezone("US/Eastern"))
    today = now_et.date()
    if today in US_HOLIDAYS:
        if limit_price is None:
            raise ValueError("Limit price required on holidays")
        return "GTC", "Limit", {"price": f"{limit_price:.2f}", "price-effect": "Debit"}

    _24H = {"BTCUSD", "ETHUSD", "ES", "NQ"}
    if symbol.upper() in _24H:
        return "24 Hour", "Market", {}

    t = now_et.time()
    reg_open, reg_close = time(9, 30), time(16, 0)
    ext_open, ext_close = time(4, 0), time(20, 0)

    if reg_open <= t <= reg_close:
        return "Day", "Market", {}
    elif ext_open <= t < reg_open or reg_close < t <= ext_close:
        return "Extended", "Market", {}
    else:
        if limit_price is None:
            raise ValueError("Limit price required outside trading hours")
        return "GTC", "Limit", {"price": f"{limit_price:.2f}", "price-effect": "Debit"}

# ----------------------------------------------------------------------
# 5. DEBUG ORDER STATUS
# ----------------------------------------------------------------------
def debug_order_status(order_id: str, timeout: int = 10):
    url = f"{base_url}/accounts/{account_number}/orders/{order_id}"
    for _ in range(timeout):
        try:
            r = session.get(url, timeout=10)
            r.raise_for_status()
            status = r.json()["data"].get("status", "Unknown")
            print(f"  Order {order_id} → Status: {status}")
            if status in {"Filled", "Cancelled", "Rejected"}:
                break
        except Exception as e:
            print(f"  Status check failed: {e}")
        time.sleep(1)

# ----------------------------------------------------------------------
# 6. MAIN EXECUTION – DCA @ $50.00
# ----------------------------------------------------------------------
def main():
    params = {
        "instrument": "stock",
        "symbol": "TQQQ",
        "side": "buy",
        "capital": 45000.0,
        "entry": 50.00,           # UPDATED: $50.00
        "steps": 10
    }

    total_shares = int((params["capital"] / params["entry"]) // params["steps"] * params["steps"])
    shares_per_step = total_shares // params["steps"]

    print("\n" + "="*70)
    print("TQQQ DCA PLAN @ $50.00")
    print("="*70)
    print(f"Capital: ${params["capital"]:,.2f}")
    print(f"Entry: ${params["entry"]:.2f}")
    print(f"Steps: {params["steps"]}")
    print(f"Total Shares: {total_shares}")
    print(f"Shares per Step: {shares_per_step}")
    print(f"Current Time (ET): {datetime.now(pytz.timezone("US/Eastern")).strftime("%Y-%m-%d %H:%M:%S %Z")}")
    print("="*70)

    confirm = input("\nPlace 10-step DCA @ $50.00? (y/N): ").strip().lower()
    if confirm != "y":
        print("Order cancelled by user.")
        return

    tif, otype, price_payload = get_tif_and_type(params["symbol"], params["entry"])

    print(f"\nExecuting DCA: {shares_per_step} shares × {params["steps"]} steps")
    print(f"Time-in-Force: {tif} | Order Type: {otype}")
    if otype == "Limit":
        print(f"Limit Price: ${params["entry"]:.2f}")

    for i in range(params["steps"]):
        payload = {
            "order-type": otype,
            "time-in-force": tif,
            **price_payload,
            "legs": [
                {
                    "instrument-type": "Equity",
                    "symbol": params["symbol"],
                    "quantity": str(shares_per_step),
                    "action": "Buy to Open" if params["side"] == "buy" else "Sell to Open"
                }
            ]
        }

        url = f"{base_url}/accounts/{account_number}/orders"
        try:
            r = session.post(url, json=payload, timeout=15)
            r.raise_for_status()
            order_id = r.json()["data"]["order-id"]
            print(f"DCA Step {i+1}/{params["steps"]}: {shares_per_step} TQQQ (TIF={tif}) → ID: {order_id}")
            debug_order_status(order_id, timeout=10)
        except Exception as e:
            log.error(f"Step {i+1} FAILED: {e}")
            if hasattr(e, "response"):
                print(e.response.json())
            break

    print("\nDCA EXECUTION COMPLETE")

# ----------------------------------------------------------------------
# 7. RUN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            session.delete(f"{base_url}/sessions")
            log.info("Logged out.")
        except:
            pass
        session.close()