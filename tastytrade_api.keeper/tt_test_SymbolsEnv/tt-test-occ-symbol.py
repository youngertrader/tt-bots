#!/usr/bin/env python3
"""
FINAL TEST: AAPL  260420C00280000 (OFFICIAL EXAMPLE) + MSFT
"""

import json
import requests
import os
import configparser
import logging

# ----------------------------------------------------------------------
CONFIG_PATH = os.path.join("config", "tt-ben.config")
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH)
use_prod = cfg.getboolean("tastytrade", "use_prod", fallback=True)
section = "tastytrade" if use_prod else "tastytradesandbox"
username = cfg.get(section, "username")
password = cfg.get(section, "password")
BASE_URL = cfg.get("URI", "prod" if use_prod else "cert")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def login(s, base):
    r = s.post(f"{base}/sessions", json={"login": username, "password": password})
    if r.status_code != 201:
        raise RuntimeError(f"Login failed: {r.text}")
    return r.json()["data"]["session-token"]


    exp = expiry.replace("-", "")[2:]
    strike_pad = f"{int(strike * 1000):08d}"
    root = underlying.upper()
    if len(root) > 6:
        root = root[:6]
    padded = root + "  "[:6 - len(root)]  # ← EXACTLY 2 SPACES
    sym = f"{padded}{exp}{opt_type.upper()}{strike_pad}"
    log.info(f"Built: {sym!r} | Bytes: {[ord(c) for c in sym[:10]]}")
    return sym

def build_option_symbol(underlying: str, expiry: str, opt_type: str, strike: float) -> str:
    """
    Build 21-char OCC option symbol for Tastytrade API
    Example: AAPL  260417C00280000
    """
    exp = expiry.replace("-", "")[2:]                    # "2026-04-17" → "260417"
    strike_pad = f"{int(strike * 1000):08d}"              # 280.0 → "00280000"
    root = underlying.upper()
    if len(root) > 6:
        root = root[:6]
    padded = root + "  "[:6 - len(root)]                 # ← EXACTLY 2 SPACES
    sym = f"{padded}{exp}{opt_type.upper()}{strike_pad}"
    assert len(sym) == 21, f"Bad length {len(sym)}: {sym}"
    return sym
# ----------------------------------------------------------------------
session = requests.Session()
token = None

try:
    token = login(session, BASE_URL)

    # OFFICIAL EXAMPLE: AAPL Apr 20 2026 $280 Call
    aapl_option = build_option_symbol("AAPL", "2026-04-17", "C", 280.0)

    # DO NOT MANUALLY ENCODE — let `requests` do it
    params = {
        "equity": "MSFT",
        "equity-option": aapl_option
    }

    log.info(f"Raw params: {params}")
    log.info(f"Request URL will be auto-encoded by requests")

    r = session.get(
        f"{BASE_URL}/market-data/by-type",
        params=params,  # ← requests will encode spaces → %20
        headers={"Authorization": token}
    )

    data = r.json()
    with open("by_type_debug.json", "w") as f:
        json.dump(data, f, indent=2)
    log.info("Debug JSON → by_type_debug.json")

    items = data.get("data", {}).get("items", [])
    log.info(f"\n=== {len(items)} ITEMS RETURNED ===")
    for item in items:
        sym = item["symbol"]
        bid = float(item.get("bid") or 0)
        ask = float(item.get("ask") or 0)
        last = float(item.get("last") or 0)
        typ = item.get("instrument-type")
        log.info(f"• {sym} ({typ}): Bid ${bid:.2f}, Ask ${ask:.2f}, Last ${last:.2f}")

    if len(items) == 1:
        log.error("OPTION MISSING – check if AAPL 2026-04-17 exists in chain")

except Exception as e:
    log.error(f"Error: {e}")
finally:
    if token:
        session.delete(f"{BASE_URL}/sessions", headers={"Authorization": token})
    session.close()