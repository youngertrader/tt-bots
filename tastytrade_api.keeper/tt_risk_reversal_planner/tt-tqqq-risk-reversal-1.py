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

        # OPTION: 3-choice expiry selection & chain fetch
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

            # Fetch chain and strikes using factored function
            target_strikes, strikes_dict, expiry = get_filtered_chain(api, params["symbol"], expiry, spot)

        # Print final plan
        print_position_plan(params, target_strikes, strikes_dict, expiry, api, account_number)

    except Exception as e:
        log.error(f"Error: {e}")
    finally:
        # Note: TastytradeAPI needs to be defined in your environment
        # to ensure api.logout() works if login was successful.
        # Check if the api object exists and if it is logged in before calling logout
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