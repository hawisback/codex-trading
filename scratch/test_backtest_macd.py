import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget, SPOT

md = create_market_data('kite')
ist = timezone(timedelta(hours=5, minutes=30))

print("Kite Session Source initialized.")
# Check spot token
if md.source._spot_token is None:
    md.source.quotes([SPOT], ReadBudget(10.0))
print(f"Spot token: {md.source._spot_token}")

# Let's inspect options in master
options = md.master.options(ReadBudget(10.0))
print(f"Total options: {len(options)}")
for opt in options[:5]:
    print(opt)
