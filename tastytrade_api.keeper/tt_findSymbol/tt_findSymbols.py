#!/usr/bin/env python3
"""
tt_findSymbols.py
-----------------
Find symbols in Tastytrade (sandbox or prod) using tt-ben.config
✅ Compatible with tastytrade SDK v10.3.0+

Usage:
    python tt_findSymbols.py
"""

import os
import sys
import configparser
from typing import Tuple


# ----------------------------------------------------------------------
# 1. Load config
# ----------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config", "tt-ben.config")


def load_tasty_config() -> Tuple[str, str, bool]:
    """Read tt-ben.config and return (username, password, is_sandbox)."""
    if not os.path.exists(CONFIG_PATH):
        sys.exit(f"Config not found: {CONFIG_PATH}")

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)

    use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
    section = "tastytrade" if use_prod else "tastytradesandbox"

    username = cfg.get(section, "username")
    password = cfg.get(section, "password")
    is_sandbox = not use_prod

    print(f"[CONFIG] use_prod={use_prod} → section={section} → sandbox={is_sandbox}")
    return username, password, is_sandbox


# ----------------------------------------------------------------------
# 2. Main
# ----------------------------------------------------------------------
def main() -> None:
    username, password, is_sandbox = load_tasty_config()

    # ------------------------------------------------------------------
    # 2a. Import tastytrade SDK
    # ------------------------------------------------------------------
    try:
        from tastytrade.session import Session
        from tastytrade.instruments import Equity, get_all_instruments
    except ImportError:
        sys.exit("tastytrade SDK not installed – please run: pip install tastytrade")

    # ------------------------------------------------------------------
    # 2b. Establish session (v10.3.0+ syntax)
    # ------------------------------------------------------------------
    try:
        if is_sandbox:
            print("[INFO] Connecting to Tastytrade sandbox...")
            session = Session.create_sandbox(username, password)
        else:
            print("[INFO] Connecting to Tastytrade production...")
            session = Session.create_production(username, password)

        print(f"✅ Logged in as {session.user["login"]} (sandbox={is_sandbox})")

    except Exception as e:
        sys.exit(f"[ERROR] Login failed: {e}")

    # ------------------------------------------------------------------
    # 2c. Test lookup of common symbols
    # ------------------------------------------------------------------
    symbols = ["TSLA", "AAPL", "SPY", "MSFT", "AMZN", "QQQ", "IWM", "BTC/USD"]

    print("\n--- Symbol lookup ------------------------------------------------")
    for sym in symbols:
        try:
            inst = Equity.get(session, sym)
            print(f"{sym}: ✅ Found → {inst.symbol} ({inst.description})")
        except Exception as e:
            print(f"{sym}: ❌ Not found – {e}")

    # ------------------------------------------------------------------
    # 2d. Optional: list first 20 instruments in environment
    # ------------------------------------------------------------------
    try:
        instruments = get_all_instruments(session)
        print(f"\n--- Listing instruments (first 20 of {len(instruments)}) ---------")
        for inst in instruments[:20]:
            print(f"{inst.symbol:<10}  {inst.description}")
        if len(instruments) > 20:
            print("... (showing first 20 only)")
    except Exception as e:
        print(f"[WARN] Could not list all instruments: {e}")

    # ------------------------------------------------------------------
    # 2e. Logout
    # ------------------------------------------------------------------
    try:
        session.logout()
        print("\n✅ Logged out.")
    except Exception as e:
        print(f"[WARN] Logout failed: {e}")


if __name__ == "__main__":
    main()
