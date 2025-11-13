import json
import requests
import os
import configparser
import logging
import argparse
import math
import time
import datetime

# A static list of full‑day US stock market holidays (2025) for checking:
US_MARKET_HOLIDAYS_2025 = {
    datetime.date(2025, 1, 1),
    datetime.date(2025, 1, 20),
    datetime.date(2025, 2, 17),
    datetime.date(2025, 4, 18),
    datetime.date(2025, 5, 26),
    datetime.date(2025, 6, 19),
    datetime.date(2025, 7, 4),
    datetime.date(2025, 9, 1),
    datetime.date(2025, 11, 27),
    datetime.date(2025, 12, 25),
    # … add early‑close days or others if needed
}

US_MARKET_HOLIDAYS_2026 = {
    datetime.date(2026, 1, 1),
    datetime.date(2026, 1, 19),
    datetime.date(2026, 2, 16),
    datetime.date(2026, 4, 3),
    datetime.date(2026, 5, 25),
    datetime.date(2026, 6, 19),
    datetime.date(2026, 7, 3),
    datetime.date(2026, 9, 7),
    datetime.date(2026, 11, 26),
    datetime.date(2026, 12, 25),
}


# You can add more years as needed
US_MARKET_HOLIDAYS = US_MARKET_HOLIDAYS_2025.union(US_MARKET_HOLIDAYS_2026)

def is_market_open_today(date: datetime.date) -> bool:
    """
    Returns True if the market is open on the given date.
    Market is closed on weekends and US market holidays (across years).
    """
    return date.weekday() < 5 and date not in US_MARKET_HOLIDAYS


def is_market_open_today(date: datetime.date) -> bool:
    """
    Returns True if the market is open on the given date.
    Market is closed on weekends and US market holidays (across years).
    """
    return date.weekday() < 5 and date not in US_MARKET_HOLIDAYS

# Configure command-line arguments
parser = argparse.ArgumentParser(description="Tastytrade API Balance Fetcher and Trader")
parser.add_argument("--log-response-headers", action="store_true", help="Enable logging of response headers")
parser.add_argument("--dry-run", action="store_true", help="Simulate trade without placing order")
parser.add_argument("--auto", action="store_true", help="Auto-confirm trades (use with caution)")
args = parser.parse_args()

# Configure logging
logging.basicConfig(level=logging.DEBUG if args.log_response_headers else logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration
config = configparser.ConfigParser()
CONFIG_PATH = os.path.join("config", "tt-ben.config")
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
config.read(CONFIG_PATH)

use_prod = config.getboolean("tastytrade", "use_prod", fallback=True)
section = "tastytrade" if use_prod else "tastytradesandbox"

try:
    username = config.get(section, "username")
    password = config.get(section, "password")
    account_number = config.get("accountnumber", "self_directed")
except configparser.NoSectionError as e:
    raise Exception(f"Config error: {e}")

BASE_URL = config.get("URI", "prod" if use_prod else "cert")
logger.info(f"Using environment: {"Production" if use_prod else "Sandbox"}")
logger.info(f"Using account number: {account_number[-4:]:*>4}")

# API request helper
def make_request(session, method, url, headers, data=None, params=None):
    logger.debug(f"Sending {method} to {url}")
    logger.debug(f"Headers: {headers}")
    if data:
        try:
            payload_dict = json.loads(data) if isinstance(data, str) else data
            safe_payload = {k: "****" if k == "password" else v for k, v in payload_dict.items()}
            logger.debug(f"Payload: {safe_payload}")
        except:
            logger.debug(f"Payload: {data}")
    if params:
        logger.debug(f"Params: {params}")
    resp = session.request(method, url, headers=headers, data=data, params=params, timeout=15)
    if args.log_response_headers:
        logger.debug(f"Response headers: {resp.headers}")
    logger.debug(f"Response: {resp.text[:1000]}")
    return resp

# Login
def login(session, base_url, username, password):
    logger.info("Logging in...")
    url = f"{base_url}/sessions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    payload = json.dumps({"login": username, "password": password})
    resp = make_request(session, "POST", url, headers, payload)
    if resp.status_code != 201:
        raise Exception(f"Login failed: {resp.status_code} - {resp.text}")
    logger.info("Login successful")
    return resp.json()["data"]["session-token"]

# WORKING: Use /market-data (undocumented but reliable)
def fetch_sgov_price(session, base_url, session_token):
    logger.info("Fetching SGOV price via /market-data...")
    url = f"{base_url}/market-data"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    params = {"symbols": "SGOV"}
    resp = make_request(session, "GET", url, headers, params=params)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch market data: {resp.status_code} - {resp.text}")
    
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise Exception(f"Invalid JSON from /market-data: {resp.text[:500]}")
    
    items = data.get("data", {}).get("items", [])
    if not items:
        raise Exception("No market data returned for SGOV")
    
    last_price_str = items[0].get("last")
    if not last_price_str:
        raise Exception(f'No "last" price in SGOV market data')
    
    try:
        price = float(last_price_str)
        if price <= 0:
            raise ValueError("Price is zero or negative")
        logger.info(f"SGOV price: ${price:.4f}")
        return price
    except (ValueError, TypeError) as e:
        raise Exception(f"Failed to parse SGOV price '{last_price_str}': {e}")

# Get current position in SGOV
def get_sgov_position(session, base_url, account_number, session_token):
    logger.info("Checking current SGOV position...")
    url = f"{base_url}/accounts/{account_number}/positions"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    resp = make_request(session, "GET", url, headers)
    if resp.status_code != 200:
        logger.warning("Failed to fetch positions, assuming 0 shares")
        return 0.0
    items = resp.json().get("data", {}).get("items", [])
    for item in items:
        if item.get("symbol") == "SGOV":
            qty = float(item.get("quantity", 0))
            logger.info(f"Current SGOV position: {qty} shares")
            return qty
    logger.info("No SGOV position found")
    return 0.0

# Wait for order to fill
def wait_for_balance_update(session, base_url, account_number, session_token,
                            initial_cash, expected_change, timeout=30,
                            poll_interval=1, tolerance=1.00):
    """
    Poll the cash balance until it changes by approximately the expected amount.
    This version avoids stale cache by adding a "no-cache" header and tighter polling.
    """
    logger.info("Waiting for balance to reflect trade...")
    elapsed = 0
    url = f"{base_url}/accounts/{account_number}/balances"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0"
    }

    while elapsed < timeout:
        try:
            resp = make_request(session, "GET", url, headers)
            if resp.status_code != 200:
                logger.debug(f"Balance poll failed: {resp.status_code}")
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

            data = resp.json().get("data", {})
            new_cash_str = data.get("cash-balance")
            if new_cash_str is None:
                logger.debug("No cash-balance field in response")
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

            new_cash = float(new_cash_str)
            diff = round(new_cash - initial_cash, 2)
            logger.info(f"Polling... Cash: ${new_cash:,.2f} (Δ ${diff:+.2f})")

            if abs(diff - expected_change) <= tolerance:
                logger.info(f"Balance updated! New Cash Balance: ${new_cash:,.2f}")
                return new_cash

        except Exception as e:
            logger.debug(f"Polling error: {e}")

        time.sleep(poll_interval)
        elapsed += poll_interval

    logger.warning("Timeout: Balance did not update as expected.")
    return None

# Place market order
def place_order(session, base_url, account_number, session_token, symbol, action, quantity):
    if args.dry_run:
        logger.info(f"[DRY RUN] Would place {action} order for {quantity} shares of {symbol}")
        return None
    logger.info(f"Placing {action} order for {quantity} shares of {symbol}...")
    url = f"{base_url}/accounts/{account_number}/orders"
    headers = {
        "Content-Type": "application/json",
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    api_action = "Buy to Open" if action.upper() == "BUY" else "Sell to Close"
    price_effect = "Debit" if "Buy" in api_action else "Credit"
    payload = json.dumps({
        "time-in-force": "Day",
        "order-type": "Market",
        "price-effect": price_effect,
        "legs": [{
            "instrument-type": "Equity",
            "symbol": symbol,
            "quantity": str(quantity),
            "action": api_action
        }]
    })
    resp = make_request(session, "POST", url, headers, payload)
    if resp.status_code not in (200, 201):
        raise Exception(f"Failed to place order: {resp.status_code} - {resp.text}")
    order_id = resp.json().get("data", {}).get("order", {}).get("id", "unknown")
    logger.info(f"{action} order placed successfully (ID: {order_id})")
    return order_id

# Fetch balances
def fetch_balances(session, base_url, account_number, session_token):
    logger.debug(f"Fetching balances for account: {account_number[-4:]:*>4}")
    url = f"{base_url}/accounts/{account_number}/balances"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    resp = make_request(session, "GET", url, headers)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch balances: {resp.status_code} - {resp.text}")
    return resp.json().get("data", {})


def wait_for_order_fill(session, base_url, account_number, session_token, order_id, quantity, timeout=60):
    """
    Polls the order status until filled, rejected, canceled, or timeout.
    Stops early if 3 consecutive 401 responses are encountered.
    """
    logger.info(f"Waiting for order {order_id} to fill (up to {timeout}s)...")
    url = f"{base_url}/accounts/{account_number}/orders/{order_id}"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    start_time = time.time()
    filled_price = None
    filled_qty = 0
    consecutive_401 = 0

    while time.time() - start_time < timeout:
        try:
            resp = make_request(session, "GET", url, headers)
        except Exception as e:
            logger.debug(f"Order status request failed: {e}")
            time.sleep(1)
            continue

        if resp.status_code == 401:
            consecutive_401 += 1
            logger.warning(f"Order status check returned 401 ({consecutive_401}/3)")
            if consecutive_401 >= 3:
                logger.warning("Received 3 consecutive 401s. Stopping order polling early.")
                return False, None
            time.sleep(2)
            continue
        else:
            consecutive_401 = 0

        if resp.status_code != 200:
            logger.debug(f"Unexpected status {resp.status_code}, retrying...")
            time.sleep(2)
            continue

        try:
            order = resp.json().get("data", {}).get("order", {})
            status = order.get("status")
            filled_qty = float(order.get("filled-quantity", 0))
            legs = order.get("legs", [{}])[0]
            filled_price = legs.get("filled-price")

            logger.debug(f"Order status: {status}, filled: {filled_qty}/{quantity}, price: {filled_price}")

            if status == "Filled" and abs(filled_qty - quantity) < 0.001:
                if filled_price:
                    filled_price = float(filled_price)
                    logger.info(f"Order {order_id} filled at ${filled_price:.4f}")
                    return True, filled_price
                else:
                    logger.warning("Filled but no filled-price. Using market price.")
                    return True, None
            elif status in ["Rejected", "Canceled"]:
                logger.error(f"Order {order_id} {status.lower()}!")
                return False, None

        except Exception as e:
            logger.debug(f"Error parsing order response: {e}")

        time.sleep(2)

    logger.warning(f"Order {order_id} not confirmed filled after {timeout}s.")
    return False, None

# Poll for balance update
def wait_for_balance_update(session, base_url, account_number, session_token, old_balance, expected_change, timeout=30, poll_interval=2):
    start = time.time()
    headers = {"Authorization": f"Bearer {session_token}", "Accept": "application/json"}

    while time.time() - start < timeout:
        try:
            r = session.get(f"{base_url}/accounts/{account_number}/balances", headers=headers, timeout=10)
            if r.status_code != 200:
                time.sleep(poll_interval)
                continue

            data = r.json().get("data", {})
            new_balance = float(data.get("cash-balance", 0))
            delta = new_balance - old_balance
            if abs(delta - expected_change) < 2.0:
                return new_balance

        except Exception as e:
            logger.warning(f"Balance check error: {e}")

        time.sleep(poll_interval)

    return None

# Logout
def logout(session, base_url, session_token):
    logger.info("Logging out...")
    url = f"{base_url}/sessions"
    headers = {
        "Authorization": session_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    resp = make_request(session, "DELETE", url, headers)
    if resp.status_code == 204:
        logger.info("Session terminated successfully")
    else:
        logger.warning(f"Logout failed: {resp.status_code}")

# Main
def main():
    import datetime, math, time, calendar, requests
    from zoneinfo import ZoneInfo

    ny_tz = ZoneInfo("America/New_York")
    now = datetime.datetime.now(tz=ny_tz)
    today, current_time = now.date(), now.time()
    logger.debug(f"Now NY: {now.isoformat()}")

    # Skip trading if market closed (weekend or US holiday)
    if not is_market_open_today(today):
        logger.info(f"Market closed today ({today}). Exit.")
        return

    # --- Determine first and last trading days of the month ---
    y, m = today.year, today.month
    first_trading = next(
        (datetime.date(y, m, d)
         for d in range(1, 8)
         if datetime.date(y, m, d).weekday() < 5 and is_market_open_today(datetime.date(y, m, d))),
        None,
    )
    last_day = calendar.monthrange(y, m)[1]
    last_trading = next(
        (datetime.date(y, m, d)
         for d in range(last_day, last_day - 7, -1)
         if datetime.date(y, m, d).weekday() < 5 and is_market_open_today(datetime.date(y, m, d))),
        None,
    )
    logger.debug(f"First trading={first_trading}, Last trading={last_trading}, Today={today}")

    # --- Login and get initial state ---
    session = requests.Session()
    token = login(session, BASE_URL, username, password)
    balances = fetch_balances(session, BASE_URL, account_number, token)
    cash_before = float(balances.get("cash-balance", 0))
    sgov_shares_before = get_sgov_position(session, BASE_URL, account_number, token)
    sgov_price = fetch_sgov_price(session, BASE_URL, token)
    logger.info(f"Cash ${cash_before:,.2f}, SGOV {sgov_shares_before} @ ${sgov_price:.4f}")

    action, qty = None, 0

    # --- CASE 1: First trading day of the month ---
    if today == first_trading:
        logger.info("Case 1: First trading day of month.")

        # Buy with excess cash
        if cash_before > sgov_price:
            qty = int(cash_before // sgov_price)
            if qty > 0:
                action = "Buy"
                logger.info(f"Deploying idle cash → Buy {qty} SGOV.")
            else:
                logger.info("Cash not enough for one SGOV share — skipping buy.")
        else:
            logger.info("Cash less than SGOV price — skipping buy.")

        # NEW: Negative cash rescue
        if cash_before < 0:
            buffer = 5.0
            needed = abs(cash_before) + buffer
            qty_to_sell = math.ceil(needed / sgov_price)
            qty_to_sell = min(qty_to_sell, int(sgov_shares_before))

            if qty_to_sell > 0:
                expected_proceeds = qty_to_sell * sgov_price
                logger.info(
                    f"Negative cash (${cash_before:,.2f}) → sell {qty_to_sell} SGOV (~${expected_proceeds:,.2f})"
                )
                action, qty = "Sell", qty_to_sell
            else:
                logger.info("Not enough SGOV to cover negative cash — no action.")

    # --- CASE 2: Last trading day after 3:55 PM ET ---
    elif today == last_trading and current_time >= datetime.time(15, 55):
        logger.info("Case 2: Last trading day after 3:55 PM ET → Sell all SGOV.")
        if sgov_shares_before > 0:
            action, qty = "Sell", sgov_shares_before
        else:
            logger.info("No SGOV holdings; skipping Case 2.")

    # --- DEFAULT CASE: Fix negative cash any day ---
    elif cash_before < 0:
        need = abs(cash_before)
        qty = 1 if need < sgov_price else math.ceil(need / sgov_price)
        qty = min(qty, int(sgov_shares_before))
        if qty > 0:
            action = "Sell"
            logger.info(f"Negative cash (${cash_before:,.2f}) → sell {qty} SGOV to recover.")
        else:
            logger.info("Not enough SGOV to fix negative cash — no action.")
    else:
        logger.info("Default case: Cash >= 0 and not first/last trading day — no action.")

    # --- EXECUTION ---
    if not action or qty <= 0:
        logger.info("No trade needed.")
    else:
        logger.info(f"Preparing to {action} {qty} SGOV.")

        # Confirm unless --auto or --dry-run
        if not args.auto and not args.dry_run:
            confirm = input(
                f"\n>>> Confirm {action} {qty} SGOV @ ~${sgov_price:.4f} (y/n)? "
            ).strip().lower()
            if confirm != "y":
                logger.info("Trade cancelled by user.")
                logout(session, BASE_URL, token)
                session.close()
                return

        # Place order
        order_id = place_order(session, BASE_URL, account_number, token, "SGOV", action, qty)

        # --- FAST POST-ORDER VERIFICATION (logout → sleep → relogin → compare) ---
        if order_id and not args.dry_run:
            logger.info("Verifying order fill via logout/login cycle...")

            # 1. Logout
            logout(session, BASE_URL, token)

            # 2. Wait 2 seconds
            time.sleep(2)

            # 3. Login again
            token = login(session, BASE_URL, username, password)

            # 4. Get new balances
            new_cash = float(fetch_balances(session, BASE_URL, account_number, token).get("cash-balance", 0))
            new_position = get_sgov_position(session, BASE_URL, account_number, token)

            # 5. Compare
            cash_changed = new_cash > cash_before if action == "Sell" else new_cash < cash_before
            position_changed = new_position < sgov_shares_before if action == "Sell" else new_position > sgov_shares_before

            if cash_changed or position_changed:
                logger.info(
                    f"Order {order_id} effectively filled. "
                    f"New cash: ${new_cash:,.2f}, SGOV: {new_position}"
                )
            else:
                logger.warning(
                    f"Order {order_id} may still be pending; balances unchanged after 3s. "
                    f"Cash: ${new_cash:,.2f}, SGOV: {new_position}"
                )
        else:
            logger.info("Dry run or no order ID — skipping post-trade check.")

    # --- Final cleanup ---
    logout(session, BASE_URL, token)
    session.close()

if __name__ == "__main__":
    main()