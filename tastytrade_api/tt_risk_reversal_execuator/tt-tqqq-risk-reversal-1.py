#!/usr/bin/env python3
"""
Risk Reversal Position Planner v1
Interactive + CLI | Supports Stock/Option | DCA Steps
"""

import json
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple, Optional
from position_planner import build_occ, get_expiry_and_spot, get_filtered_chain, print_position_plan

# Logger (first!)
log = logging.getLogger(__name__)

# Local imports
from config_loader import load_config
from tastytrade_api import TastytradeAPI
from position_planner import build_occ, get_expiry_and_spot, get_filtered_chain, print_position_plan
def debug_order_status(api: TastytradeAPI, order_id: str, account_number: str, timeout: int = 30) -> None:
    """
    Poll the order status until filled, rejected, or timeout.
    Prints live updates with fills.
    """
    import time
    start_time = time.time()
    last_status = None

    print(f"\nPolling order {order_id} for up to {timeout}s...")

    # Track seen fills to avoid duplicates
    if not hasattr(debug_order_status, "seen_fills"):
        debug_order_status.seen_fills = set()

    while time.time() - start_time < timeout:
        try:
            url = f"{api.base_url}/accounts/{account_number}/orders/{order_id}"
            resp = api.session.get(url, headers={"Authorization": api.token}, timeout=10)
            data = resp.json().get("data", {})

            status = data.get("status")
            fills = data.get("fills", [])

            # Print status change
            if status != last_status:
                print(f"  Status: {status}")
                last_status = status

            # Print new fills
            for fill in fills:
                fill_id = fill.get("fill-id")
                if fill_id and fill_id not in debug_order_status.seen_fills:
                    qty = fill.get("quantity")
                    price = fill.get("price")
                    ts = fill.get("filled-at", "")[:19].replace("T", " ")
                    print(f"  FILL: {qty} @ ${price} | {ts}")
                    debug_order_status.seen_fills.add(fill_id)

            # Exit conditions
            if status in ("Filled", "Rejected", "Cancelled", "Expired"):
                if status == "Filled":
                    print(f"Order {order_id} fully filled.")
                else:
                    print(f"Order {order_id} {status}.")
                return

            time.sleep(2)

        except Exception as e:
            print(f"  Poll error: {e}")
            time.sleep(2)

    print(f"Timeout after {timeout}s. Final status: {last_status or "unknown"}")

##### Get Symbol Quote
def get_symbol_quote(api: TastytradeAPI, symbol: str) -> Tuple[float, float]:
    """Return (bid, ask) for underlying symbol."""
    try:
        data = api.get_quotes([symbol])
        item = data["data"]["items"][0]
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        return bid, ask
    except Exception as e:
        log.warning(f"Failed to fetch quote for {symbol}: {e}")
        return 0.0, 0.0
    
# CLI + Interactive Input
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Risk Reversal Position Planner",
        epilog="Omit arguments to enter interactive mode."
    )
    parser.add_argument(
        "--env", choices=["prod", "p", "sandbox", "s"],
        help="Environment: prod/p or sandbox/s"
    )
    parser.add_argument("--symbol", type=str, help="Underlying symbol")
    parser.add_argument(
        "--side", choices=["buy", "b", "sell", "s"],
        help="Side: buy/b or sell/s"
    )
    parser.add_argument(
        "--instrument", choices=["stock", "s", "option", "o"],
        help="Instrument: stock/s or option/o"
    )
    parser.add_argument(
        "--strategy", choices=["Bullish", "b"],
        help="Option strategy: Bullish/b"
    )
    parser.add_argument("--entry", type=float, help="Entry price")
    parser.add_argument("--exit", type=float, help="Exit price (optional)")
    parser.add_argument("--capital", type=float, help="Total capital")
    parser.add_argument("--steps", type=int, help="Max DCA steps")
    return parser
##### Interactive Prompt
def prompt_missing(args, defaults: Dict, api: TastytradeAPI) -> Dict:
    result = vars(args).copy()

    # Environment
    if result.get("env") is None:
        env = input(f"Environment (prod/p, sandbox/s) [{defaults["env"]}]: ").strip().lower()
        result["env"] = "prod" if env in ("prod", "p") else "sandbox" if env in ("sandbox", "s") else defaults["env"]

    # Symbol – with live bid/ask
    if not result.get("symbol"):
        sym = input(f"Symbol [{defaults["symbol"]}]: ").strip().upper()
        result["symbol"] = sym or defaults["symbol"]
        # Show current quote
        bid, ask = get_symbol_quote(api, result["symbol"])
        if bid > 0 and ask > 0:
            print(f"  Current: Bid ${bid:.2f} | Ask ${ask:.2f}")
        else:
            print("  Quote unavailable")

    # Side
    if not result.get("side"):
        side = input("Side (buy/b, sell/s) [buy]: ").strip().lower()
        result["side"] = "buy" if side in ("buy", "b") else "sell" if side in ("sell", "s") else "buy"

    # Instrument
    if not result.get("instrument"):
        inst = input("Instrument (stock/s, option/o) [stock]: ").strip().lower()
        result["instrument"] = "stock" if inst in ("stock", "s") else "option" if inst in ("option", "o") else "stock"

    # Strategy (only if option)
    if result["instrument"] == "option" and not result.get("strategy"):
        strat = input("Strategy (Bullish/b) [Bullish]: ").strip().title()
        result["strategy"] = "Bullish"

    # Entry price (REQUIRED)
    if not result.get("entry"):
        while True:
            try:
                e = input("Entry price: ").strip()
                if not e:
                    print("Entry price is required.")
                    continue
                result["entry"] = float(e)
                break
            except ValueError:
                print("Please enter a valid number.")

    # Exit price (OPTIONAL)
    if not result.get("exit"):
        x = input("Exit price (optional, blank to skip): ").strip()
        if x:
            try:
                result["exit"] = float(x)
            except ValueError:
                print("Invalid number – exit price omitted.")
                result["exit"] = None
        else:
            result["exit"] = None

    # Expiry choice (only for options)
    if result["instrument"] == "option" and not result.get("expiry_choice"):
        print("\nExpiry selection:")
        print("  0 – 0-DTE (expires today)")
        print("  1 – 45+ DTE but < 100 DTE")
        print("  2 – 100+ DTE (default)")
        while True:
            choice = input("Choose expiry (0/1/2) [2]: ").strip()
            if choice == "" or choice == "2":
                result["expiry_choice"] = 2
                break
            elif choice in ("0", "1"):
                result["expiry_choice"] = int(choice)
                break
            else:
                print("Please enter 0, 1, 2, or press Enter for default.")

    # Capital & Steps – ONLY for stock
    if result["instrument"] == "stock":
        if not result.get("capital"):
            while True:
                try:
                    c = input("Total capital ($) [10000]: ").strip()
                    if not c:
                        result["capital"] = 10000.0
                        break
                    result["capital"] = float(c)
                    break
                except ValueError:
                    print("Please enter a valid number.")
        if not result.get("steps"):
            while True:
                try:
                    s = input("Max DCA steps [10]: ").strip()
                    result["steps"] = int(s) if s else 10
                    if result["steps"] < 1:
                        print("Must be >= 1.")
                        continue
                    break
                except ValueError:
                    print("Please enter an integer.")
    else:
        result["capital"] = None
        result["steps"] = None

    return result

##### Main
def main():
    parser = build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load config
    # ------------------------------------------------------------------
    cfg, username, password, account_number, base_url, default_symbol = load_config()
    use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
    defaults = {"env": "prod" if use_prod else "sandbox", "symbol": default_symbol}

    # ------------------------------------------------------------------
    # Interactive mode
    # ------------------------------------------------------------------
    is_interactive = all(getattr(args, k) is None for k in vars(args))
    if is_interactive:
        print("Entering interactive mode...")
        args = argparse.Namespace(**{k: None for k in vars(build_parser().parse_args([]))})

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    env_from_args = getattr(args, "env", None)
    env = env_from_args or defaults["env"]
    use_prod = env == "prod"
    base_url = cfg.get("URI", "prod" if use_prod else "cert")

    # ------------------------------------------------------------------
    # API login
    # ------------------------------------------------------------------
    api = TastytradeAPI(base_url)
    try:
        api.login(username, password)

        # ------------------------------------------------------------------
        # Prompt missing fields (live quote shown)
        # ------------------------------------------------------------------
        params = prompt_missing(args, defaults, api)

        log.info(f"Environment: {"Production" if use_prod else "Sandbox"}")
        log.info(f"Symbol: {params["symbol"]} | Side: {params["side"]} | Instrument: {params["instrument"]}")

        spot = api.get_spot_quote(params["symbol"])
        log.info(f"{params["symbol"]} spot: ${spot:.2f}")

        # ------------------------------------------------------------------
        # Option handling (expiry, chain, strikes)
        # ------------------------------------------------------------------
        expiry = None
        target_strikes = []
        strikes_dict = {}

        if params["instrument"] == "option":
            today = datetime.now(timezone.utc).date()
            choice = params.get("expiry_choice", 2)

            data = api.get_option_chain(params["symbol"], include_closed=False)
            expirations = sorted(
                {i["expiration-date"] for i in data["data"]["items"]},
                key=lambda d: datetime.strptime(d, "%Y-%m-%d").date()
            )
            if not expirations:
                raise RuntimeError("No option expirations found")

            if choice == 0:
                candidates = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() == today]
                label = "0-DTE (today)"
            elif choice == 1:
                min_date = today + timedelta(days=45)
                max_date = today + timedelta(days=99)
                candidates = [e for e in expirations if min_date <= datetime.strptime(e, "%Y-%m-%d").date() <= max_date]
                label = "45+ to <100 DTE"
            else:
                min_date = today + timedelta(days=100)
                candidates = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() >= min_date]
                label = "100+ DTE"

            if not candidates:
                raise RuntimeError(f"No expirations found for {label}")

            expiry = candidates[0]
            log.info(f"Selected expiry ({label}): {expiry}")
            target_strikes, strikes_dict, expiry = get_filtered_chain(
                api, params["symbol"], expiry, spot
            )

        # ------------------------------------------------------------------
        # PRINT THE PLAN
        # ------------------------------------------------------------------
        print_position_plan(params, target_strikes, strikes_dict, expiry, api, account_number)

        # ------------------------------------------------------------------
        # ASK WHETHER TO EXECUTE
        # ------------------------------------------------------------------
        confirm = input("\nPlace the order now? (y/N): ").strip().lower()
        if confirm != "y":
            print("Order cancelled – exiting.")
            return

        # ------------------------------------------------------------------
        # EXECUTE THE ORDER
        # ------------------------------------------------------------------
        if params["instrument"] == "option":
            if not expiry or not target_strikes:
                print("Cannot place option order – missing data.")
            else:
                execute_plan(
                    api=api,
                    params=params,
                    target_strikes=target_strikes,
                    strikes_dict=strikes_dict,
                    expiry=expiry,
                    account_number=account_number
                )
        elif params["instrument"] == "stock":
            step_size = params["capital"] / params["steps"]
            shares_per_step = step_size // params["entry"]
            total_shares = int(shares_per_step * params["steps"])

            print(f"\nExecuting DCA plan: {"Buy" if params["side"] == "buy" else "Sell"} {total_shares} shares of {params["symbol"]}")
            execute_stock_dca_order(
                api=api,
                symbol=params["symbol"],
                side=params["side"],
                total_shares=total_shares,
                entry_price=params["entry"],
                account_number=account_number
            )
        else:
            print("Execution not supported for this instrument.")

    except Exception as e:
        log.error(f"Error: {e}")
    finally:
        api_obj = locals().get("api")
        if api_obj and api_obj.is_logged_in:
            api_obj.logout()


# ----------------------------------------------------------------------
# ORDER EXECUTION EXTENSION
# ----------------------------------------------------------------------
import json
from typing import Dict, Any

def build_risk_reversal_order(
    symbol: str,
    expiry: str,
    strike: float,
    side: str,                 # "buy" or "sell"
    quantity: int = 1,
    price: float = 0.0,        # 0 = market, otherwise limit price
    account_number: str = None
) -> Dict[str, Any]:
    """
    Build a **Bullish Risk Reversal** order payload.
    - Short Put  (sell put)
    - Long Call  (buy call)
    Both legs are placed as a *single* order with `order-type = market` (or limit).
    """
    put_occ  = build_occ(symbol, expiry, "P", strike)
    call_occ = build_occ(symbol, expiry, "C", strike)

    # Decide leg direction based on overall side
    # Bullish RR = sell put + buy call  → net credit (or debit)
    legs = [
        {
            "instrument-type": "Equity Option",
            "symbol": put_occ,
            "quantity": quantity,
            "action": "Sell to Open" if side == "sell" else "Buy to Open"
        },
        {
            "instrument-type": "Equity Option",
            "symbol": call_occ,
            "quantity": quantity,
            "action": "Buy to Open" if side == "buy" else "Sell to Open"
        }
    ]

    order_type = "Market" if price == 0 else "Limit"
    payload = {
        "order-type": order_type,
        "time-in-force": "Day",
        "source": "python-script",
        "legs": legs
    }
    if price != 0:
        payload["price"] = round(price, 2)

    if account_number:
        payload["account-number"] = account_number

    return payload


def place_order(api: TastytradeAPI, payload: Dict[str, Any]) -> Dict:
    """POST the order and return the JSON response."""
    url = f"{api.base_url}/orders"
    headers = {
        "Authorization": api.token, 
        "Content-Type": "application/json",
        "User-Agent": "python-script/1.0"  # ADD THIS FOR EXTRA SAFETY
    }
    r = api.session.post(url, json=payload, headers=headers, timeout=15)
    
    # ENHANCED: Print full response on error
    if r.status_code != 201:
        print(f"ERROR STATUS: {r.status_code}")
        print(f"ERROR RESPONSE: {r.text}")  # ADD THESE LINES
        r.raise_for_status()
    
    return r.json()

def debug_order_status(api: TastytradeAPI, order_id: str, account_number: str, timeout: int = 30) -> None:
    """
    Poll the order status until filled, rejected, or timeout.
    Prints live updates.
    """
    import time
    start_time = time.time()
    last_status = None

    print(f"\nPolling order {order_id} for up to {timeout}s...")

    while time.time() - start_time < timeout:
        try:
            url = f"{api.base_url}/accounts/{account_number}/orders/{order_id}"
            resp = api.session.get(url, headers={"Authorization": api.token}, timeout=10)
            data = resp.json().get("data", {})

            status = data.get("status")
            fills = data.get("fills", [])

            # Print status change
            if status != last_status:
                print(f"  Status: {status}")
                last_status = status

            # Print fills as they arrive
            for fill in fills:
                fill_id = fill.get("fill-id")
                if not hasattr(debug_order_status, "seen_fills"):
                    debug_order_status.seen_fills = set()
                if fill_id and fill_id not in debug_order_status.seen_fills:
                    qty = fill.get("quantity")
                    price = fill.get("price")
                    ts = fill.get("filled-at", "")[:19].replace("T", " ")
                    print(f"  FILL: {qty} @ ${price} | {ts}")
                    debug_order_status.seen_fills.add(fill_id)

            # Exit conditions
            if status in ("Filled", "Rejected", "Cancelled", "Expired"):
                if status == "Filled":
                    print(f"Order {order_id} fully filled.")
                else:
                    print(f"Order {order_id} {status}.")
                return

            time.sleep(2)

        except Exception as e:
            print(f"  Poll error: {e}")
            time.sleep(2)

    print(f"Timeout after {timeout}s. Final status: {last_status or "unknown"}")

def execute_plan(
    api: TastytradeAPI,
    params: Dict,
    target_strikes: list,
    strikes_dict: Dict,
    expiry: str,
    account_number: str
) -> None:
    """
    Interactive execution of the suggested risk-reversal.
    Includes strike selection, quantity, price type, preview, submission, and live status.
    """
    if not target_strikes:
        print("No strikes to execute.")
        return

    # ------------------------------------------------------------------
    # 1. Pick the suggested strike (first MID-credit)
    # ------------------------------------------------------------------
    suggested = None
    for s in target_strikes:
        put = strikes_dict[s]["put"]
        call = strikes_dict[s]["call"]
        if not put or not call:
            continue
        pb, pa = put.get("bid", 0), put.get("ask", 0)
        cb, ca = call.get("bid", 0), call.get("ask", 0)
        put_mid = (pb + pa) / 2 if pb > 0 and pa > 0 else 0
        call_mid = (cb + ca) / 2 if cb > 0 and ca > 0 else 0
        mid = put_mid - call_mid
        if mid > 0:
            suggested = s
            break
    if suggested is None:
        suggested = target_strikes[0]
        print(f"No MID-credit found – using first strike ${suggested}")

    print(f"\nSuggested execution strike: ${suggested}")

    # ------------------------------------------------------------------
    # 2. Confirm quantity & price type
    # ------------------------------------------------------------------
    while True:
        qty_input = input(f"Quantity (contracts) [1]: ").strip()
        qty = int(qty_input) if qty_input else 1
        if qty > 0:
            break
        print("Quantity must be > 0")

    price_type = input("Order type – (M)arket or (L)imit [M]: ").strip().lower()
    limit_price = 0.0
    if price_type == "l":
        while True:
            lp = input("Limit net credit/debit (e.g. 0.15 for $0.15 credit): ").strip()
            if not lp:
                print("Limit price required for limit order.")
                continue
            try:
                limit_price = float(lp)
                break
            except ValueError:
                print("Enter a valid number")

    # ------------------------------------------------------------------
    # 3. Build & preview payload
    # ------------------------------------------------------------------
    payload = build_risk_reversal_order(
        symbol=params["symbol"],
        expiry=expiry,
        strike=suggested,
        side=params["side"],
        quantity=qty,
        price=limit_price,
        account_number=account_number
    )

    print("\nRISK REVERSAL ORDER PREVIEW".center(70, "-"))
    print(json.dumps(payload, indent=2))
    print("-" * 70)

    confirm = input("Submit option order? (y/N): ").strip().lower()
    if confirm != "y":
        print("Order cancelled.")
        return

    # ------------------------------------------------------------------
    # 4. Submit
    # ------------------------------------------------------------------
    try:
        resp = place_order(api, payload)
        print("\nORDER RESPONSE".center(70, "="))
        print(json.dumps(resp, indent=2))

        order_id = resp.get("data", {}).get("order-id")
        if not order_id:
            print("\nOrder submitted, but no order-id returned.")
            return

        print(f"\nOption order submitted! ID: {order_id}")
        debug_order_status(api, order_id, account_number, timeout=30)

    except Exception as e:
        print(f"\nORDER FAILED: {e}")
        log.error(f"Option order failed: {e}")
# ----------------------------------------------------------------------
# STOCK ORDER EXECUTION
# ----------------------------------------------------------------------
def execute_stock_dca_order(
    api: TastytradeAPI,
    symbol: str,
    side: str,           # "buy" or "sell"
    total_shares: int,
    entry_price: float,
    account_number: str
) -> None:
    """
    Places a single market order for the total shares (DCA plan).
    Includes preview, confirmation, submission, and live status polling.
    """
    action = "Buy to Open" if side == "buy" else "Sell to Open"
    order_type = "Market"
    time_in_force = "Day"

    payload = {
        "order-type": order_type,
        "time-in-force": time_in_force,
        "source": "python-script",
        "instrument-type": "Equity",
        "symbol": symbol,
        "quantity": total_shares,
        "action": action,
        "account-number": account_number
    }

    print("\nSTOCK ORDER PREVIEW".center(70, "-"))
    print(json.dumps(payload, indent=2))
    print("-" * 70)

    confirm = input("Submit stock order? (y/N): ").strip().lower()
    if confirm != "y":
        print("Order cancelled.")
        return

    try:
        resp = place_order(api, payload)
        print("\nORDER RESPONSE".center(70, "="))
        print(json.dumps(resp, indent=2))

        order_id = resp.get("data", {}).get("order-id")
        if not order_id:
            print("\nOrder submitted, but no order-id returned.")
            return

        print(f"\nStock order submitted! ID: {order_id}")
        debug_order_status(api, order_id, account_number, timeout=30)

    except Exception as e:
        print(f"\nORDER FAILED: {e}")
        log.error(f"Stock order failed: {e}")


# ----------------------------------------------------------------------
# Extend main() to call execution when requested
def main():
    parser = build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load config
    # ------------------------------------------------------------------
    cfg, username, password, account_number, base_url, default_symbol = load_config()
    use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
    defaults = {"env": "prod" if use_prod else "sandbox", "symbol": default_symbol}

    # ------------------------------------------------------------------
    # Interactive mode
    # ------------------------------------------------------------------
    is_interactive = all(getattr(args, k) is None for k in vars(args))
    if is_interactive:
        print("Entering interactive mode...")
        args = argparse.Namespace(**{k: None for k in vars(build_parser().parse_args([]))})

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    env_from_args = getattr(args, "env", None)
    env = env_from_args or defaults["env"]
    use_prod = env == "prod"
    base_url = cfg.get("URI", "prod" if use_prod else "cert")

    # ------------------------------------------------------------------
    # API login
    # ------------------------------------------------------------------
    api = TastytradeAPI(base_url)
    try:
        api.login(username, password)

        # ------------------------------------------------------------------
        # Prompt missing fields (live quote shown)
        # ------------------------------------------------------------------
        params = prompt_missing(args, defaults, api)

        log.info(f"Environment: {"Production" if use_prod else "Sandbox"}")
        log.info(f"Symbol: {params["symbol"]} | Side: {params["side"]} | Instrument: {params["instrument"]}")

        spot = api.get_spot_quote(params["symbol"])
        log.info(f"{params["symbol"]} spot: ${spot:.2f}")

        # ------------------------------------------------------------------
        # Option handling (expiry, chain, strikes)
        # ------------------------------------------------------------------
        expiry = None
        target_strikes = []
        strikes_dict = {}

        if params["instrument"] == "option":
            today = datetime.now(timezone.utc).date()
            choice = params.get("expiry_choice", 2)

            data = api.get_option_chain(params["symbol"], include_closed=False)
            expirations = sorted(
                {i["expiration-date"] for i in data["data"]["items"]},
                key=lambda d: datetime.strptime(d, "%Y-%m-%d").date()
            )
            if not expirations:
                raise RuntimeError("No option expirations found")

            if choice == 0:
                candidates = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() == today]
                label = "0-DTE (today)"
            elif choice == 1:
                min_date = today + timedelta(days=45)
                max_date = today + timedelta(days=99)
                candidates = [e for e in expirations if min_date <= datetime.strptime(e, "%Y-%m-%d").date() <= max_date]
                label = "45+ to <100 DTE"
            else:
                min_date = today + timedelta(days=100)
                candidates = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() >= min_date]
                label = "100+ DTE"

            if not candidates:
                raise RuntimeError(f"No expirations found for {label}")

            expiry = candidates[0]
            log.info(f"Selected expiry ({label}): {expiry}")
            target_strikes, strikes_dict, expiry = get_filtered_chain(
                api, params["symbol"], expiry, spot
            )

        # ------------------------------------------------------------------
        # PRINT THE PLAN
        # ------------------------------------------------------------------
        print_position_plan(params, target_strikes, strikes_dict, expiry, api, account_number)

        # ------------------------------------------------------------------
        # ASK WHETHER TO EXECUTE
        # ------------------------------------------------------------------
        confirm = input("\nPlace the order now? (y/N): ").strip().lower()
        if confirm != "y":
            print("Order cancelled – exiting.")
            return

        # ------------------------------------------------------------------
        # EXECUTE THE ORDER
        # ------------------------------------------------------------------
        if params["instrument"] == "option":
            if not expiry or not target_strikes:
                print("Cannot place option order – missing data.")
            else:
                execute_plan(
                    api=api,
                    params=params,
                    target_strikes=target_strikes,
                    strikes_dict=strikes_dict,
                    expiry=expiry,
                    account_number=account_number
                )
        elif params["instrument"] == "stock":
            step_size = params["capital"] / params["steps"]
            shares_per_step = step_size // params["entry"]
            total_shares = int(shares_per_step * params["steps"])

            print(f"\nExecuting DCA plan: {"Buy" if params["side"] == "buy" else "Sell"} {total_shares} shares of {params["symbol"]}")
            execute_stock_dca_order(
                api=api,
                symbol=params["symbol"],
                side=params["side"],
                total_shares=total_shares,
                entry_price=params["entry"],
                account_number=account_number
            )
        else:
            print("Execution not supported for this instrument.")

    except Exception as e:
        log.error(f"Error: {e}")
    finally:
        api_obj = locals().get("api")
        if api_obj and api_obj.is_logged_in:
            api_obj.logout()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    main()