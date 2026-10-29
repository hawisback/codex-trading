import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading")

from libs.config.settings import get_platform_settings
from services.broker_gateway.zerodha_kite_adapter import ZerodhaKiteAdapter

IST = timezone(timedelta(hours=5, minutes=30))

async def main():
    settings = get_platform_settings()
    adapter = ZerodhaKiteAdapter(settings)
    await adapter.initialize()
    if settings.kite_access_token:
        auth_ok = await adapter.authenticate_access_token(
            api_key=settings.kite_api_key,
            access_token=settings.kite_access_token
        )
        print("Authenticated with access token:", auth_ok)
    
    tokens = {
        "NIFTY26O1322300CE": 11417090,
        "NIFTY26O1322350CE": 11417602,
        "NIFTY26O1322450CE": 11419650,
        "NIFTY26O1322500CE": 11420674,
        "NIFTY26O1322550CE": 11421186,
    }
    
    start_dt = datetime(2026, 10, 9, 9, 15)
    end_dt = datetime(2026, 10, 9, 15, 30)

    option_candles = {}
    for sym, token in tokens.items():
        try:
            raw_candles = await adapter._run(
                lambda t=token: adapter._kite.historical_data(
                    instrument_token=t,
                    from_date=start_dt,
                    to_date=end_dt,
                    interval="minute"
                )
            )
            print(f"Loaded {len(raw_candles)} 1m candles for {sym}. Sample: open={raw_candles[0]['open']}, close={raw_candles[-1]['close']}")
            option_candles[sym] = [
                {
                    "date": c["date"].isoformat() if hasattr(c["date"], "isoformat") else str(c["date"]),
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"]
                }
                for c in raw_candles
            ]
        except Exception as e:
            print(f"Error fetching candles for {sym}: {e}")
                
    output_path = r"c:\Users\hawis\Documents\antigravity\splendid-bardeen\option_candles_today.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(option_candles, f, indent=2)
    print(f"All TRUE option candles saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
