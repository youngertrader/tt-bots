#!/usr/bin/env python3
"""
Multi-Symbol Risk Reversal Debugger
Supports: AAPL, SPY, TQQQ, VIX, etc.
Interactive symbol input when --symbol not provided.
"""

import json
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

# ----------------------------------------------------------------------
# Logger (MUST be first)
# ----------------------------------------------------------------------
log = logging.getLogger(__name__)

# Local imports
from config_loader import load_config
from tastytrade_api import TastytradeAPI

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Risk Reversal Debugger",
        epilog="If --symbol is omitted, you will be prompted interactively."
    )
    parser.add_argument(
        "--symbol", type=str, help="Underlying symbol (e.g., AAPL, SPY, TQQQ, VIX)"
    )
    parser.add_argument(
        "--min-days", type=int, default=60, help="Minimum DTE for expiry"
    )
    return parser.parse_args()

# ----------------------------------------------------------------------
# OCC Builder
# ----------------------------------------------------------------------
def build_occ(underlying: str, expiry: str, opt_type: str, strike: float) -> str:
    exp = expiry.replace("-", "")[2:]  # "2026-01-16" → "260116"
    strike_pad = f"{int(strike * 1000):08d}"
    root = underlying.upper()
    padded = root.ljust(6)[:6]  # ← LEFT-JUSTIFY to 6 chars
    return f"{padded}{exp}{opt_type.upper()}{strike_pad}"

# ----------------------------------------------------------------------
# Get expiry + spot
# ----------------------------------------------------------------------
def get_expiry_and_spot(api: TastytradeAPI, symbol: str, min_days: int = 60):
    data = api.get_option_chain(symbol, include_closed=False)
    expirations = sorted(
        {i["expiration-date"] for i in data["data"]["items"]},
        key=lambda d: datetime.strptime(d, "%Y-%m-%d")
    )
    today = datetime.now(timezone.utc).date()
    expiry = next((e for e in expirations
                   if datetime.strptime(e, "%Y-%m-%d").date() >= today + timedelta(days=min_days)), None)
    if not expiry:
        raise RuntimeError(f"No expiry >= {min_days} DTE for {symbol}")
    log.info(f"Selected Expiry: {expiry}")

    spot = api.get_spot_quote(symbol)
    log.info(f"{symbol} spot: ${spot:.2f}")
    return expiry, spot

# ----------------------------------------------------------------------
# Get chain + interactive selection
# ----------------------------------------------------------------------
def get_filtered_chain(api: TastytradeAPI, symbol: str, target_expiry: str, spot: float):
    data = api.get_option_chain(symbol, include_closed=False)
    all_options = data["data"]["items"]

    chain = [opt for opt in all_options if opt["expiration-date"] == target_expiry]
    if not chain:
        raise RuntimeError(f"No options for {target_expiry}")

    log.info(f"Filtered chain: {len(chain)} options for {target_expiry}")

    # Group by strike
    strikes: Dict[float, Dict[str, Any]] = {}
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

    log.info(f"ITM Strike: ${itm_strike:.2f} | Default strikes: {default_strikes}")

    below = [str(s) for s in default_strikes if s < itm_strike]
    above = [str(s) for s in default_strikes if s > itm_strike]
    below_str = ", ".join(below) if below else "none"
    above_str = ", ".join(above) if above else "none"

    print(f"\n[{symbol}] Available strikes (below: {below_str}, ITM={itm_strike:.0f}, above: {above_str}):")

    user_input = input(f"\nEnter strikes (e.g., 112, 115) or press Enter for default {len(default_strikes)}: ").strip()
    if user_input == "":
        target_strikes = default_strikes
    else:
        try:
            target_strikes = [float(x.strip()) for x in user_input.split(",") if x.strip()]
            invalid = [s for s in target_strikes if s not in strikes]
            if invalid:
                log.warning(f"Invalid strikes: {invalid}")
                target_strikes = [s for s in target_strikes if s in strikes]
            if not target_strikes:
                log.warning("No valid strikes. Using default.")
                target_strikes = default_strikes
        except Exception as e:
            log.error(f"Invalid input: {e}. Using default.")
            target_strikes = default_strikes

    log.info(f"Selected strikes: {target_strikes}")

    # BUILD OCC SYMBOLS
    symbols_to_quote = []
    for s in target_strikes:
        put_occ = build_occ(symbol, target_expiry, "P", s)
        call_occ = build_occ(symbol, target_expiry, "C", s)
        symbols_to_quote.extend([put_occ, call_occ])

    log.info(f"Quoting {len(symbols_to_quote)} symbols: {symbols_to_quote}")

    # QUOTE
    raw = api.get_quotes(symbols_to_quote)
    log.info("  Status: 200")
    log.info("  Raw market data:")
    for i, item in enumerate(raw["data"]["items"]):
        print(f"    [{i}] {json.dumps(item, indent=2)}")

    market_quotes = {}
    for item in raw["data"]["items"]:
        sym = item["symbol"]
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        market_quotes[sym] = {"bid": bid, "ask": ask}
        log.info(f"  {sym} | Bid: ${bid:.2f} | Ask: ${ask:.2f}")

    # Merge
    for s in target_strikes:
        put_occ = build_occ(symbol, target_expiry, "P", s)
        call_occ = build_occ(symbol, target_expiry, "C", s)
        put_quote = market_quotes.get(put_occ, {"bid": 0, "ask": 0})
        call_quote = market_quotes.get(call_occ, {"bid": 0, "ask": 0})

        if strikes[s]["put"]:
            strikes[s]["put"] = {**strikes[s]["put"], "bid": put_quote["bid"], "ask": put_quote["ask"]}
        if strikes[s]["call"]:
            strikes[s]["call"] = {**strikes[s]["call"], "bid": call_quote["bid"], "ask": call_quote["ask"]}

    return target_strikes, strikes, target_expiry

# ----------------------------------------------------------------------
# Print Table
# ----------------------------------------------------------------------
def print_debug_table(symbol: str, target_strikes, strikes_dict, expiry):
    headers = ["Call Bid", "Call Ask", "Strike", "Put Bid", "Put Ask", "Bullish", "Bearish", "Call OCC", "Put OCC"]
    rows = []
    nat_mid_opp_data = []

    for s in target_strikes:
        put = strikes_dict[s]["put"]
        call = strikes_dict[s]["call"]

        call_bid = call.get("bid", 0) if call else 0
        call_ask = call.get("ask", 0) if call else 0
        put_bid = put.get("bid", 0) if put else 0
        put_ask = put.get("ask", 0) if put else 0

        put_mid = (put_bid + put_ask) / 2 if put_bid and put_ask else 0
        call_mid = (call_bid + call_ask) / 2 if call_bid and call_ask else 0
        nat = put_bid - call_ask
        mid = put_mid - call_mid
        opp = put_ask - call_bid

        bullish = put_bid + call_ask
        bearish = call_bid + put_ask

        nat_str = f"NAT: {abs(nat):.2f} {"db" if nat < 0 else "cr"}"
        mid_str = f"MID: {mid:.2f} {"cr" if mid > 0 else "db"}"
        opp_str = f"OPP: {opp:.2f} {"cr" if opp > 0 else "db"}"

        nat_mid_opp_data.append({
            "strike": s, "nat": nat, "mid": mid, "opp": opp,
            "nat_str": nat_str, "mid_str": mid_str, "opp_str": opp_str,
            "call_bid": call_bid, "call_ask": call_ask,
            "put_bid": put_bid, "put_ask": put_ask,
            "bullish": bullish, "bearish": bearish
        })

    nat_mid_opp_data.sort(key=lambda x: x["nat"])

    for item in nat_mid_opp_data:
        s = item["strike"]
        call_bid_str = f"${item["call_bid"]:.2f}" if item["call_bid"] else "-"
        call_ask_str = f"${item["call_ask"]:.2f}" if item["call_ask"] else "-"
        put_bid_str = f"${item["put_bid"]:.2f}" if item["put_bid"] else "-"
        put_ask_str = f"${item["put_ask"]:.2f}" if item["put_ask"] else "-"

        call_occ = build_occ(symbol, expiry, "C", s)
        put_occ = build_occ(symbol, expiry, "P", s)

        bullish_content = f"{item["nat_str"]}\n{item["mid_str"]}\n{item["opp_str"]}"

        rows.append([
            call_bid_str, call_ask_str, f"${s:.1f}",
            put_bid_str, put_ask_str,
            bullish_content, f"${item["bearish"]:.2f}",
            call_occ, put_occ
        ])

    # Table rendering
    col_widths = []
    for i in range(len(headers)):
        max_width = len(headers[i])
        for row in rows:
            cell = str(row[i])
            lines = cell.split("\n")
            max_width = max(max_width, max(len(line) for line in lines))
        col_widths.append(max_width)

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

    print(f"\n[{symbol}] Risk Reversal Table (Expiry: {expiry})")
    print(sep)
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |")
    print(sep)
    for row in rows:
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
    args = parse_args()
    cfg, USERNAME, PASSWORD, ACCOUNT_NUMBER, BASE_URL, default_symbol = load_config()

    symbol = None
    if args.symbol:
        symbol = args.symbol.upper()
        log.info(f"Using symbol from CLI: {symbol}")
    else:
        user_input = input(f"Enter symbol (default: {default_symbol}): ").strip()
        if user_input:
            symbol = user_input.upper()
            log.info(f"Using symbol from input: {symbol}")
        else:
            symbol = default_symbol
            log.info(f"Using default symbol from config: {symbol}")

    api = TastytradeAPI(BASE_URL)
    try:
        api.login(USERNAME, PASSWORD)
        expiry, spot = get_expiry_and_spot(api, symbol, min_days=args.min_days)
        target_strikes, strikes_dict, expiry = get_filtered_chain(api, symbol, expiry, spot)
        print_debug_table(symbol, target_strikes, strikes_dict, expiry)
    except Exception as e:
        log.error(f"Failed: {e}")
    finally:
        api.logout()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    main()