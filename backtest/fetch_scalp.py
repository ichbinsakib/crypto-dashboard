"""Fetch and cache 5m/15m Binance history for the SCALPING coins, paginated. Run once; re-run to refresh."""
import json
import os
import time
import urllib.request

COINS = ("SOL", "LINK", "XRP", "ONDO")
INTERVALS = ("5m", "15m")
DAYS = 90
URL = "https://data-api.binance.vision/api/v3/klines"
OUT = os.path.join(os.path.dirname(__file__), "scalp_data")


def fetch(symbol, interval, start_ms, end_ms):
    out = []
    cur = start_ms
    while cur < end_ms:
        url = f"{URL}?symbol={symbol}&interval={interval}&limit=1000&startTime={cur}&endTime={end_ms}"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        out.extend(data)
        cur = data[-1][0] + 1
        time.sleep(0.15)
        if len(data) < 1000:
            break
    return out


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - DAYS * 86400_000
    for coin in COINS:
        for interval in INTERVALS:
            path = os.path.join(OUT, f"{coin}_{interval}.json")
            print(f"Fetching {coin} {interval}...")
            rows = fetch(f"{coin}USDT", interval, start_ms, end_ms)
            print(f"  {len(rows)} candles")
            with open(path, "w") as f:
                json.dump(rows, f)
