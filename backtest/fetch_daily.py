"""Download full daily history (Binance public mirror) for a wide candidate universe -> backtest/data_daily/*.json.
Includes coins that later collapsed or were delisted (LUNA, FTT, ...) so the momentum test isn't only looking at today's survivors.
Row: [open_time_ms, open, high, low, close, quote_volume]"""
import json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
COINS = ("BTC ETH BNB SOL XRP DOGE ADA TRX LINK AVAX DOT LTC BCH NEAR UNI ATOM ETC APT ARB OP INJ SUI AAVE FIL HBAR XLM TON SHIB PEPE ICP "
         "LUNA FTT EOS XMR XTZ ALGO VET THETA MATIC SAND MANA AXS FTM EGLD FLOW CHZ GALA CRV MKR SNX COMP RUNE KAVA ZEC DASH NEO IOTA ENJ BAT ZIL "
         "QTUM ONT WAVES KSM STX IMX LDO RNDR GRT 1INCH SUSHI YFI CAKE ANKR LRC").split()
OUT = os.path.join(os.path.dirname(__file__), "data_daily"); os.makedirs(OUT, exist_ok=True)
def get(url):
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(1.2)
    return None
def one(c):
    rows, t = [], 1483228800000  # 2017-01-01
    while True:
        d = get(f"https://data-api.binance.vision/api/v3/klines?symbol={c}USDT&interval=1d&startTime={t}&limit=1000")
        if not d: break
        rows += [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])] for k in d]
        t = d[-1][0] + 86400000
        if len(d) < 1000: break
    if rows: json.dump(rows, open(os.path.join(OUT, c + ".json"), "w"))
    return c, len(rows), (time.strftime("%Y-%m-%d", time.gmtime(rows[0][0]/1000)), time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0]/1000))) if rows else None
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(one, COINS): print(*r, flush=True)
