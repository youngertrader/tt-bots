#!/usr/bin/env python3
"""
TQQQ DEBUG: Interactive Strike Selection
* Enter strikes, "a", or blank
* Only quotes selected
* Bullish/Bearish columns
"""

import json
import requests
import os
import configparser
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
CONFIG_PATH = os.path.join("config", "tt-ben.config")
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")

cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH)

use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
section = "tastytrade" if use_prod else "tastytradesandbox"

USERNAME = cfg.get(section, "username")
PASSWORD = cfg.get(section, "password")
ACCOUNT_NUMBER = cfg.get("accountnumber", "self_directed")
BASE_URL = cfg.get("URI", "prod" if use_prod else "cert")


log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Session
# ----------------------------------------------------------------------
session = requests.Session()

def login() -> str:
    r = session.post(f"{BASE_URL}/sessions", json={"login": USERNAME, "password": PASSWORD}, timeout=15)
    if r.status_code != 201:
        raise RuntimeError(f"Login failed: {r.text}")
    token = r.json()["data"]["session-token"]
    log.info("Login successful")
    return token

def logout(token: str):
    try:
        session.delete(f"{BASE_URL}/sessions", headers={"Authorization": token})
    except:
        pass

# ----------------------------------------------------------------------
# OCC Builder
# ----------------------------------------------------------------------
def build_occ(underlying: str, expiry: str, opt_type: str, strike: float) -> str:
    exp = expiry.replace("-", "")[2:]
    strike_pad = f"{int(strike * 1000):08d}"
    root = underlying.upper()[:6]
    padded = root + "  "[:6 - len(root)]
    return f"{padded}{exp}{opt_type.upper()}{strike_pad}"

# ----------------------------------------------------------------------
# Get expiry + spot
# ----------------------------------------------------------------------
def get_expiry_and_spot(token: str, min_days: int = 60):
    r = session.get(f"{BASE_URL}/option-chains/TQQQ", headers={"Authorization": token},
                    params={"include-closed": "false"}, timeout=15)
    expirations = sorted(
        {i["expiration-date"] for i in r.json()["data"]["items"]},
        key=lambda d: datetime.strptime(d, "%Y-%m-%d")
    )
    today = datetime.now(timezone.utc).date()
    expiry = next((e for e in expirations
                   if datetime.strptime(e, "%Y-%m-%d").date() >= today + timedelta(days=min_days)), None)
    if not expiry:
        raise RuntimeError("No expiry")
    log.info(f"Selected Expiry: {expiry}")

    r = session.get(f"{BASE_URL}/market-data/by-type", headers={"Authorization": token},
                    params={"equity-option": ["TQQQ"]}, timeout=15)
    spot_item = next((i for i in r.json()["data"]["items"] if i["symbol"] == "TQQQ"), None)
    if not spot_item:
        raise RuntimeError("TQQQ not in quote")
    spot = float(spot_item["mid"])
    log.info(f"TQQQ spot: ${spot:.2f}")
    return expiry, spot

# ----------------------------------------------------------------------
# Get chain + interactive selection (compact strike list)
# ----------------------------------------------------------------------
def get_filtered_chain(token: str, target_expiry: str, spot: float):
    r = session.get(f"{BASE_URL}/option-chains/TQQQ", headers={"Authorization": token},
                    params={"include-closed": "false"}, timeout=15)
    all_options = r.json()["data"]["items"]

    chain = [opt for opt in all_options if opt["expiration-date"] == target_expiry]
    if not chain:
        raise RuntimeError(f"No options for {target_expiry}")

    log.info(f"Filtered chain: {len(chain)} options for {target_expiry}")

    # Group by strike
    strikes = {}
    for opt in chain:
        try:
            strike = float(opt["strike-price"])
            opt_type = opt.get("option-type", "").lower()
            if opt_type not in ("p", "c"): continue
            if strike not in strikes:
                strikes[strike] = {"put": None, "call": None}
            if opt_type == "p":
                strikes[strike]["put"] = opt
            else:
                strikes[strike]["call"] = opt
        except Exception as e:
            log.error(f"Parse error: {opt} | {e}")
            continue

    # Find ITM put
    itm_strike = max((s for s in strikes if s < spot), default=None)
    if not itm_strike:
        raise RuntimeError("No ITM strike")

    all_strikes = sorted(strikes.keys())
    try:
        idx = all_strikes.index(itm_strike)
    except ValueError:
        raise RuntimeError("ITM strike not in list")
    start = max(0, idx - 3)
    end = min(len(all_strikes), idx + 4)
    default_strikes = all_strikes[start:end]

    # COMPACT STRIKE LIST FORMAT
    log.info(f"ITM Strike: ${itm_strike:.2f} | Default {len(default_strikes)} strikes: {default_strikes}")
    
    below = [str(s) for s in default_strikes if s < itm_strike]
    above = [str(s) for s in default_strikes if s > itm_strike]
    below_str = ", ".join(below) if below else "none"
    above_str = ", ".join(above) if above else "none"
    
    print(f"\nAvailable strikes (below: {below_str}. ITM={itm_strike:.0f}, above: {above_str}):")

    # INTERACTIVE PROMPT
    user_input = input(f"\nEnter strikes (e.g., 112, 115) or press Enter for all {len(default_strikes)} strikes: ").strip()
    if user_input == "":
        target_strikes = default_strikes
    else:
        try:
            target_strikes = [float(x.strip()) for x in user_input.split(",") if x.strip()]
            invalid = [s for s in target_strikes if s not in strikes]
            if invalid:
                log.warning(f"Invalid strikes (not available): {invalid}")
                target_strikes = [s for s in target_strikes if s in strikes]
            if not target_strikes:
                log.warning("No valid strikes entered. Using all default strikes.")
                target_strikes = default_strikes
        except Exception as e:
            log.error(f"Invalid input: {e}. Using all default strikes.")
            target_strikes = default_strikes

    log.info(f"Selected strikes: {target_strikes}")

    # BUILD OCC SYMBOLS
    symbols_to_quote = []
    for s in target_strikes:
        put_occ = build_occ("TQQQ", target_expiry, "P", s)
        call_occ = build_occ("TQQQ", target_expiry, "C", s)
        symbols_to_quote.extend([put_occ, call_occ])

    log.info(f"DEBUG: Quoting {len(symbols_to_quote)} symbols: {symbols_to_quote}")

    # QUOTE
    r = session.get(f"{BASE_URL}/market-data/by-type", headers={"Authorization": token},
                    params={"equity-option": symbols_to_quote}, timeout=15)
    raw = r.json()
    log.info(f"  Status: {r.status_code}")
    log.info(f"  Raw market data:")
    for i, item in enumerate(raw["data"]["items"]):
        print(f"    [{i}] {json.dumps(item, indent=2)}")

    market_quotes = {}
    for item in raw["data"]["items"]:
        sym = item["symbol"]
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        market_quotes[sym] = {"bid": bid, "ask": ask}
        log.info(f"  Parsed: {sym} | Bid: ${bid:.2f} | Ask: ${ask:.2f}")

    # Merge
    for s in target_strikes:
        put_occ = build_occ("TQQQ", target_expiry, "P", s)
        call_occ = build_occ("TQQQ", target_expiry, "C", s)
        put_quote = market_quotes.get(put_occ, {"bid": 0, "ask": 0})
        call_quote = market_quotes.get(call_occ, {"bid": 0, "ask": 0})

        if strikes[s]["put"]:
            strikes[s]["put"] = {**strikes[s]["put"], "bid": put_quote["bid"], "ask": put_quote["ask"]}
        if strikes[s]["call"]:
            strikes[s]["call"] = {**strikes[s]["call"], "bid": call_quote["bid"], "ask": call_quote["ask"]}

    return target_strikes, strikes, target_expiry

# ----------------------------------------------------------------------
# Print Clean ASCII Table + Bullish = Ordered NAT/MID/OPP
# ----------------------------------------------------------------------
def print_debug_table(target_strikes, strikes_dict, expiry):
    headers = ["Call Bid", "Call Ask", "Strike", "Put Bid", "Put Ask", "Bullish", "Bearish", "Call OCC", "Put OCC"]
    rows = []
    nat_mid_opp_data = []  # To collect for sorting

    # First pass: collect data and calculate NAT/MID/OPP
    for s in target_strikes:
        put = strikes_dict[s]["put"]
        call = strikes_dict[s]["call"]

        call_bid = call.get("bid", 0) if call else 0
        call_ask = call.get("ask", 0) if call else 0
        put_bid = put.get("bid", 0) if put else 0
        put_ask = put.get("ask", 0) if put else 0

        # TASTYTRADE NAT/MID/OPP
        put_mid = (put_bid + put_ask) / 2 if put_bid and put_ask else 0
        call_mid = (call_bid + call_ask) / 2 if call_bid and call_ask else 0
        nat = put_bid - call_ask
        mid = put_mid - call_mid
        opp = put_ask - call_bid

        bullish = put_bid + call_ask
        bearish = call_bid + put_ask

        # Format NAT/MID/OPP as string
        nat_str = f"NAT: {abs(nat):.2f} {"db" if nat < 0 else "cr"}"
        mid_str = f"MID: {mid:.2f} {"cr" if mid > 0 else "db"}"
        opp_str = f"OPP: {opp:.2f} {"cr" if opp > 0 else "db"}"

        # Store for sorting
        nat_mid_opp_data.append({
            "strike": s,
            "nat": nat,
            "mid": mid,
            "opp": opp,
            "nat_str": nat_str,
            "mid_str": mid_str,
            "opp_str": opp_str,
            "call_bid": call_bid,
            "call_ask": call_ask,
            "put_bid": put_bid,
            "put_ask": put_ask,
            "bullish": bullish,
            "bearish": bearish
        })

    # Sort by NAT (ascending: most debit to most credit)
    nat_mid_opp_data.sort(key=lambda x: x["nat"])

    # Second pass: build rows in sorted order
    for item in nat_mid_opp_data:
        s = item["strike"]
        call_bid = item["call_bid"]
        call_ask = item["call_ask"]
        put_bid = item["put_bid"]
        put_ask = item["put_ask"]
        bullish = item["bullish"]
        bearish = item["bearish"]

        call_bid_str = f"${call_bid:.2f}" if call_bid else "-"
        call_ask_str = f"${call_ask:.2f}" if call_ask else "-"
        put_bid_str = f"${put_bid:.2f}" if put_bid else "-"
        put_ask_str = f"${put_ask:.2f}" if put_ask else "-"

        call_occ = build_occ("TQQQ", expiry, "C", s)
        put_occ = build_occ("TQQQ", expiry, "P", s)

        # Bullish column: ordered NAT → MID → OPP
        bullish_content = f"{item["nat_str"]}\n{item["mid_str"]}\n{item["opp_str"]}"

        rows.append([
            call_bid_str,
            call_ask_str,
            f"${s:.1f}",
            put_bid_str,
            put_ask_str,
            bullish_content,
            f"${bearish:.2f}",
            call_occ,
            put_occ
        ])

    # Adjust column width for multi-line Bullish
    col_widths = []
    for i in range(len(headers)):
        max_width = len(headers[i])
        for row in rows:
            cell = str(row[i])
            lines = cell.split("\n")
            max_width = max(max_width, max(len(line) for line in lines))
        col_widths.append(max_width)

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    print("\n" + sep)
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |")
    print(sep)
    for row in rows:
        # Split multi-line cells
        lines = [str(cell).split("\n") for cell in row]
        max_lines = max(len(l) for l in lines)
        for line_idx in range(max_lines):
            line = []
            for cell_lines, width in zip(lines, col_widths):
                if line_idx < len(cell_lines):
                    line.append(cell_lines[line_idx].ljust(width))
                else:
                    line.append("".ljust(width))
            print("| " + " | ".join(line) + " |")
        print(sep.replace("-", "-"))
    print("\n")

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    token = None
    try:
        token = login()
        expiry, spot = get_expiry_and_spot(token, min_days=60)
        target_strikes, strikes_dict, expiry = get_filtered_chain(token, expiry, spot)
        print_debug_table(target_strikes, strikes_dict, expiry)
    except Exception as e:
        log.error(f"Failed: {e}")
    finally:
        if token:
            logout(token)

if __name__ == "__main__":
    main()