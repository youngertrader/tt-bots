Goal
tt_tqqq_risk_reversal/ 
├── config_loader.py 
├── tastytrade_api.py
├── position_planner.py  (See planner below)
├── option_utils.py 
├── risk_reversal.py 
├── cli.py  (interactive and command line arguments)
├── config/ 
│ └── tt-ben.config 
└── tests/ (optional, not included)

Position Planner
which environment, sandbox or prod.  prod is the default
who recommand it, default self direct.
what is the symbol
what is position to open: buy (long) or short (sell)
is position for stock, such as ETF, or MSFT, or option (defalt is stock)
    if option what is the strategy print that, currently only Bullish is supported, which is a long.
    ask the expiration date, default are expiration dates 100-120 days away. 
    inital capital will be skip
the entry stock price, 
the exit stock price
the initial capital
the number of steps

recommand

# Interactive (recommended)
python tt-tqqq-risk-reversal-1.py

# Full CLI
python tt-tqqq-risk-reversal-1.py \
  --env prod \
  --symbol SPY \
  --side buy \
  --instrument stock \
  --entry 650 \
  --exit 700 \
  --capital 100000 \
  --steps 5

# Option + Bullish
python tt-tqqq-risk-reversal-1.py --symbol TQQQ --instrument option --strategy Bullish