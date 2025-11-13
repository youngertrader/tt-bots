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
from config_loader import load_config

# ----------------------------------------------------------------------
# Logger (first!)
# ----------------------------------------------------------------------
log = logging.getLogger(__name__)

# Local imports
from config_loader import load_config
from tastytrade_api import TastytradeAPI
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
    
# ----------------------------------------------------------------------
# CLI + Interactive Input
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# CLI Parser
# ----------------------------------------------------------------------
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

##### OCC Builder
def build_occ(underlying: str, expiry: str, opt_type: str, strike: float) -> str:
    """Generate OCC symbol: ROOT(6) + YYMMDD + C/P + 8-digit strike."""
    exp = expiry.replace("-", "")[2:]  # "2025-12-26" → "251226"
    strike_pad = f"{int(strike * 1000):08d}"  # $27.0 → "00027000"
    root = underlying.upper()
    padded = root.ljust(6)[:6]  # "T" → "T     ", "SPY" → "SPY   "
    return f"{padded}{exp}{opt_type.upper()}{strike_pad}"

# Get expiry + spot
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
# Get chain + interactive strike selection
# ----------------------------------------------------------------------
def get_filtered_chain(api: TastytradeAPI, symbol: str, target_expiry: str, spot: float):
    data = api.get_option_chain(symbol, include_closed=False)
    all_options = data["data"]["items"]
    chain = [opt for opt in all_options if opt["expiration-date"] == target_expiry]
    if not chain:
        raise RuntimeError(f"No options for {target_expiry}")

    log.info(f"Filtered chain: {len(chain)} options")

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

    itm_strike = max((s for s in strikes if s < spot), default=None)
    if not itm_strike:
        raise RuntimeError("No ITM strike")

    all_strikes = sorted(strikes.keys())
    idx = all_strikes.index(itm_strike)
    start = max(0, idx - 3)
    end = min(len(all_strikes), idx + 4)
    default_strikes = all_strikes[start:end]

    below = [str(s) for s in default_strikes if s < itm_strike]
    above = [str(s) for s in default_strikes if s > itm_strike]
    below_str = ", ".join(below) if below else "none"
    above_str = ", ".join(above) if above else "none"

    print(f"\n[{symbol}] Available strikes (below: {below_str}, ITM={itm_strike:.0f}, above: {above_str}):")
    user_input = input(f"\nEnter strikes (comma-separated) or press Enter for default {len(default_strikes)}: ").strip()

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
                target_strikes = default_strikes
        except Exception as e:
            log.error(f"Invalid input: {e}. Using default.")
            target_strikes = default_strikes

    log.info(f"Selected strikes: {target_strikes}")

    symbols_to_quote = []
    for s in target_strikes:
        put_occ = build_occ(symbol, target_expiry, "P", s)
        call_occ = build_occ(symbol, target_expiry, "C", s)
        symbols_to_quote.extend([put_occ, call_occ])

    raw = api.get_quotes(symbols_to_quote)
    market_quotes = {}
    for item in raw["data"]["items"]:
        sym = item["symbol"]
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        market_quotes[sym] = {"bid": bid, "ask": ask}

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

##### Print Plan
##### Print Plan
def print_position_plan(params: Dict, target_strikes, strikes_dict, expiry, api: TastytradeAPI, account_number: str):
    symbol = params["symbol"]
    side = params["side"]
    instrument = params["instrument"]
    strategy = params.get("strategy", "N/A")
    entry = params.get("entry")
    if entry is None:
        raise ValueError("Entry price is required.")
    exit_ = params.get("exit")

    side_label = "SELL (Short)" if side == "sell" and instrument == "stock" else side.upper()

    print(f"\n{"="*20} POSITION PLAN {"="*20}")
    print(f"Symbol: {symbol}")
    print(f"Side: {side_label}")
    print(f"Instrument: {instrument.upper()}")
    if instrument == "option":
        print(f"Strategy: {strategy}")
    exit_str = f"${exit_:.2f}" if exit_ is not None else "Not Set"
    print(f"Entry: ${entry:.2f} | Exit: {exit_str}")

    # ==================================================================
    # STOCK: DCA Plan (Long or Short)
    # ==================================================================
    if instrument == "stock":
        capital = params["capital"]
        steps = params["steps"]
        step_size = capital / steps
        print(f"Capital: ${capital:,.2f} | Steps: {steps} | Step Size: ${step_size:,.2f}\n")

        shares_per_step = step_size // entry
        total_shares = shares_per_step * steps

        if side == "buy":
            cost = total_shares * entry
            print("Stock DCA Plan (Long):")
            print(f"  Shares per step: {shares_per_step}")
            print(f"  Total shares: {total_shares}")
            print(f"  Total cost: ${cost:,.2f}")
            if exit_ is not None:
                proceeds = total_shares * exit_
                pnl = proceeds - cost
                print(f"  Exit proceeds: ${proceeds:,.2f}")
                print(f"  P&L: ${pnl:,.2f} ({pnl/cost:+.1%})")
            else:
                print("  Exit price not set – P&L not calculated")

        elif side == "sell":
            proceeds = total_shares * entry
            print("Stock DCA Plan (Short):")
            print(f"  Shares per step: {shares_per_step}")
            print(f"  Total shares: {total_shares}")
            print(f"  Initial proceeds: ${proceeds:,.2f}")
            if exit_ is not None:
                cost = total_shares * exit_
                pnl = proceeds - cost
                print(f"  Cover cost: ${cost:,.2f}")
                print(f"  P&L: ${pnl:,.2f} ({pnl/proceeds:+.1%})")
            else:
                print("  Exit price not set – P&L not calculated")

    # ==================================================================
    # OPTION: Buying Power + Full Risk Reversal Table + Auto-Suggest
    # ==================================================================
    else:
        # --- Buying power ---
        try:
            bal = api.get(f"/accounts/{account_number}/balances")
            buying_power = float(bal["data"]["buying-power"])
            print(f"Account Buying Power: ${buying_power:,.2f}\n")
        except Exception as e:
            log.warning(f"Could not fetch buying power: {e}")
            print("Account Buying Power: <unavailable>\n")

        if not target_strikes:
            print("  No strikes available.")
            return

        headers = ["Call Bid", "Call Ask", "Strike", "Put Bid", "Put Ask", "Bullish", "Bearish", "Call OCC", "Put OCC"]
        rows = []
        nat_mid_opp_data = []

        # First pass: collect data
        for s in target_strikes:
            put = strikes_dict[s]["put"]
            call = strikes_dict[s]["call"]
            if not put or not call:
                continue

            cb = call.get("bid", 0)
            ca = call.get("ask", 0)
            pb = put.get("bid", 0)
            pa = put.get("ask", 0)

            put_mid = (pb + pa) / 2 if pb and pa else 0
            call_mid = (cb + ca) / 2 if cb and ca else 0
            nat = pb - ca
            mid = put_mid - call_mid
            opp = pa - cb

            bullish = pb + ca
            bearish = cb + pa

            nat_str = f"NAT: {abs(nat):.2f} {"db" if nat < 0 else "cr"}"
            mid_str = f"MID: {mid:.2f} {"cr" if mid > 0 else "db"}"
            opp_str = f"OPP: {opp:.2f} {"cr" if opp > 0 else "db"}"

            nat_mid_opp_data.append({
                "strike": s,
                "nat": nat, "mid": mid, "opp": opp,
                "nat_str": nat_str, "mid_str": mid_str, "opp_str": opp_str,
                "cb": cb, "ca": ca, "pb": pb, "pa": pa,
                "bullish": bullish, "bearish": bearish
            })

        if not nat_mid_opp_data:
            print("  No valid option data.")
            return

        # Sort by NAT: most debit → most credit
        nat_mid_opp_data.sort(key=lambda x: x["nat"])

        # Auto-suggest first MID > 0
        credit_strike = None
        for item in nat_mid_opp_data:
            if item["mid"] > 0:
                credit_strike = item["strike"]
                break
        if credit_strike is None:
            credit_strike = nat_mid_opp_data[0]["strike"]
            print(f"  No MID credit found. Using first strike: ${credit_strike}\n")
        else:
            print(f"  Suggested Strike (first MID credit): ${credit_strike}\n")

        # Build rows
        for item in nat_mid_opp_data:
            s = item["strike"]
            cb_str = f"${item["cb"]:.2f}" if item["cb"] else "-"
            ca_str = f"${item["ca"]:.2f}" if item["ca"] else "-"
            pb_str = f"${item["pb"]:.2f}" if item["pb"] else "-"
            pa_str = f"${item["pa"]:.2f}" if item["pa"] else "-"

            call_occ = build_occ(symbol, expiry, "C", s)
            put_occ = build_occ(symbol, expiry, "P", s)

            bullish_content = f"{item["nat_str"]}\n{item["mid_str"]}\n{item["opp_str"]}"

            rows.append([
                cb_str, ca_str, f"${s:.1f}",
                pb_str, pa_str,
                bullish_content,
                f"${item["bearish"]:.2f}",
                call_occ, put_occ
            ])

        # Dynamic column widths
        col_widths = []
        for i in range(len(headers)):
            max_w = len(headers[i])
            for row in rows:
                cell = str(row[i])
                lines = cell.split("\n")
                max_w = max(max_w, max(len(l) for l in lines))
            col_widths.append(max_w)

        sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

        # Print table
        print(f"[{symbol}] Risk Reversal Table (Expiry: {expiry})")
        print(sep)
        print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |")
        print(sep)
        for row in rows:
            lines = [str(cell).split("\n") for cell in row]
            max_lines = max(len(l) for l in lines)
            for line_idx in range(max_lines):
                line = []
                for cell_lines, w in zip(lines, col_widths):
                    if line_idx < len(cell_lines):
                        line.append(cell_lines[line_idx].ljust(w))
                    else:
                        line.append("".ljust(w))
                print("| " + " | ".join(line) + " |")
            print(sep.replace("-", "-"))
        print("\n")

##### Main
def main():
    parser = build_parser()
    args = parser.parse_args()

    # Load config
    cfg, username, password, account_number, base_url, default_symbol = load_config()
    use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
    defaults = {"env": "prod" if use_prod else "sandbox", "symbol": default_symbol}

    # Full interactive mode
    is_interactive = all(getattr(args, k) is None for k in vars(args))
    if is_interactive:
        print("Entering interactive mode...")
        args = argparse.Namespace(**{k: None for k in vars(build_parser().parse_args([]))})

    # Determine env early for API
    env_from_args = getattr(args, "env", None)
    env = env_from_args or defaults["env"]
    use_prod = env == "prod"
    base_url = cfg.get("URI", "prod" if use_prod else "cert")

    # Create API early to fetch live quote
    api = TastytradeAPI(base_url)
    try:
        api.login(username, password)

        # Prompt with live bid/ask
        params = prompt_missing(args, defaults, api)

        # Log setup
        log.info(f"Environment: {"Production" if use_prod else "Sandbox"}")
        log.info(f"Symbol: {params["symbol"]} | Side: {params["side"]} | Instrument: {params["instrument"]}")

        # Get spot price
        spot = api.get_spot_quote(params["symbol"])
        log.info(f"{params["symbol"]} spot: ${spot:.2f}")

        # Initialize
        expiry = None
        target_strikes = []
        strikes_dict = {}

        # ==================================================================
        # OPTION: 3-choice expiry selection
        # ==================================================================
        if params["instrument"] == "option":
            today = datetime.now(timezone.utc).date()
            choice = params.get("expiry_choice", 2)  # default to 2

            # Fetch full option chain
            data = api.get_option_chain(params["symbol"], include_closed=False)
            expirations = sorted(
                {i["expiration-date"] for i in data["data"]["items"]},
                key=lambda d: datetime.strptime(d, "%Y-%m-%d").date()
            )

            if not expirations:
                raise RuntimeError("No option expirations found")

            # Filter by choice
            if choice == 0:
                candidates = [e for e in expirations if datetime.strptime(e, "%Y-%m-%d").date() == today]
                label = "0-DTE (today)"
            elif choice == 1:
                min_date = today + timedelta(days=45)
                max_date = today + timedelta(days=99)
                candidates = [
                    e for e in expirations
                    if min_date <= datetime.strptime(e, "%Y-%m-%d").date() <= max_date
                ]
                label = "45+ to <100 DTE"
            else:  # choice == 2
                min_date = today + timedelta(days=100)
                candidates = [
                    e for e in expirations
                    if datetime.strptime(e, "%Y-%m-%d").date() >= min_date
                ]
                label = "100+ DTE"

            if not candidates:
                raise RuntimeError(f"No expirations found for {label}")

            # Pick earliest in range
            expiry = candidates[0]
            log.info(f"Selected expiry ({label}): {expiry}")

            # Fetch chain and strikes
            target_strikes, strikes_dict, expiry = get_filtered_chain(api, params["symbol"], expiry, spot)

        # ==================================================================
        # Print final plan
        # ==================================================================
        print_position_plan(params, target_strikes, strikes_dict, expiry, api, account_number)

    except Exception as e:
        log.error(f"Error: {e}")
    finally:
        api.logout()






if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    main()