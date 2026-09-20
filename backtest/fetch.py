"""Download ~2y of 1h spot candles (Binance public mirror) for liquid coins into backtest/data/*.json."""
import json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
COINS = "BTC ETH BNB SOL XRP DOGE ADA TRX LINK AVAX DOT LTC BCH NEAR UNI ATOM ETC APT ARB OP INJ SUI AAVE FIL HBAR XLM TON SHIB PEPE ICP".split()
OUT = os.path.join(os.path.dirname(__file__), "data"); os.makedirs(OUT, exist_ok=True)
END = int(time.time() * 1000); START = END - 730 * 86400 * 1000
def get(url):
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.5)
    return None
def one(c):
    rows, t = [], START
    while t < END:
        d = get(f"https://data-api.binance.vision/api/v3/klines?symbol={c}USDT&interval=1h&startTime={t}&limit=1000")
        if not d: break
        rows += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in d]
        t = d[-1][0] + 3600000
        if len(d) < 1000: break
    json.dump(rows, open(os.path.join(OUT, c + ".json"), "w"))
    return c, len(rows)
with ThreadPoolExecutor(6) as ex:
    for c, n in ex.map(one, COINS): print(c, n, flush=True)
