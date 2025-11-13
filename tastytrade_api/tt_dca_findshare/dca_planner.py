#!/usr/bin/env python3
"""
DCA Planner – 10 Steps @ 95% of Live Price (Yahoo Finance)
Capital: $10,000 | User Symbol | No Trade Execution
"""

import yfinance as yf
from datetime import datetime

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
CAPITAL = 10000.0
STEPS = 10
DISCOUNT = 0.95  # 95% of current price

# ----------------------------------------------------------------------
# 1. GET LIVE PRICE FROM YAHOO FINANCE
# ----------------------------------------------------------------------
def get_live_price(symbol: str):
    """
    Fetch current price from Yahoo Finance.
    """
    ticker = yf.Ticker(symbol)
    data = ticker.history(period="1d")
    if data.empty:
        raise ValueError(f"No data for {symbol}")
    current_price = data["Close"].iloc[-1]
    return current_price

# ----------------------------------------------------------------------
# 2. MAIN PLANNER
# ----------------------------------------------------------------------
def main():
    print("=" * 70)
    print("DCA PLANNER – 95% OF LIVE PRICE (Yahoo Finance)")
    print("=" * 70)

    symbol = input("Enter symbol (e.g. SPY): ").strip().upper()
    if not symbol:
        print("No symbol entered.")
        return

    print(f"Fetching live price for {symbol}...")
    try:
        current_price = get_live_price(symbol)
    except Exception as e:
        print(f"Error fetching price: {e}")
        return

    entry_price = current_price * DISCOUNT
    total_shares = int((CAPITAL / entry_price) // STEPS * STEPS)
    shares_per_step = total_shares // STEPS

    print("\n" + "=" * 70)
    print("DCA PLAN")
    print("=" * 70)
    print(f"Symbol:           {symbol}")
    print(f"Current Price:    ${current_price:,.2f}")
    print(f"Entry Price (95%): ${entry_price:,.2f}")
    print(f"Capital:          ${CAPITAL:,.2f}")
    print(f"Steps:            {STEPS}")
    print(f"Total Shares:     {total_shares}")
    print(f"Shares per Step:  {shares_per_step}")
    print(f"Cost per Step:    ${shares_per_step * entry_price:,.2f}")
    print(f"Total Cost:       ${total_shares * entry_price:,.2f}")
    print("=" * 70)

    print("\nDCA Steps:")
    for i in range(STEPS):
        step_cost = shares_per_step * entry_price
        print(f"  Step {i+1:2}: Buy {shares_per_step} {symbol} @ ${entry_price:,.2f} → ${step_cost:,.2f}")

    print("\nNo orders placed. This is a PLAN only.")
    print("=" * 70)

# ----------------------------------------------------------------------
# 3. RUN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    main()