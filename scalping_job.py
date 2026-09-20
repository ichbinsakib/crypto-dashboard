"""Scheduled SCALPING job. Runs on its own (see .github/workflows/scalping.yml), separately from the main dashboard job, so a slow
or failing dashboard build can never delay signal tracking and the reverse.

  python scalping_job.py           publish to Supabase (needs the four KAIRO_* secrets; fails closed in CI without them)
  python scalping_job.py --dry     no database: run the engine on live candles in memory and (if site/portions.json exists) add the
                                   scalping section to it so the local preview page shows it. Nothing is written to Supabase.

All logic lives in scalping/ (analysis, lifecycle, service). This file only wires data in and results out."""
import json
import os
import sys
import time
import urllib.request

import supa
from scalping import service

BASE = "https://data-api.binance.vision/api/v3/klines"
IS_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
RUNTIME_KEY = "_scalping_runtime"


def log(msg):
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}", flush=True)


def fetch(symbol, interval, limit):
    """Binance's public spot-data mirror (the same one the dashboard already uses). One retry, then the caller marks the coin DISCONNECTED."""
    url = f"{BASE}?symbol={symbol}USDT&interval={interval}&limit={limit}"
    last = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KairoScalping)"}), timeout=15) as r:
                data = json.loads(r.read())
            if isinstance(data, list) and data:
                return data
            last = ValueError("empty klines")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1)
    raise last


def section(payload):
    return {"title": "⚡ Scalping", "sort_order": 6, "html": '<div class="panel panel-scalping"><div id="scalping-root"></div></div>', "data": payload}


def main():
    dry = "--dry" in sys.argv
    backend = None if dry else supa.Backend.from_env()
    if backend is None and not dry:
        if IS_CI:
            log("FATAL: KAIRO_* secrets are missing; refusing to run")
            return 1
        log("No Supabase credentials: running in --dry mode")
        dry = True
    if backend:
        backend.sign_in()
    store = backend if backend else service.MemoryStore()
    runtime = None
    try:
        runtime = backend.get_state(RUNTIME_KEY) if backend else None
    except Exception as e:  # noqa: BLE001
        log(f"runtime state unavailable ({type(e).__name__}); continuing without it")
    payload, notes, runtime_out = service.run(store, fetch, runtime=runtime)
    m = payload["market"]
    log(f"Scalping: market {m['state']} / regime {m['regime']} / data {m['data']}; "
        f"{len(payload['active'])} open, {len(payload['history'])} finished; alerts {len(notes)}")
    for c in payload["coins"]:
        log(f"  {c['symbol']}: {c['state']} ({c['trend']}, {c['regime']}) - {c['reason']}")
    if backend:
        backend.publish_portions({"scalping": section(payload)})
        backend.publish_notifications(notes)
        backend.put_state(runtime_out, RUNTIME_KEY)
        log("Published the scalping section and alerts")
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "portions.json")
        if os.path.exists(path):
            rows = json.load(open(path, encoding="utf-8"))
            rows = [r for r in rows if r.get("key") != "scalping"] + [dict(section(payload), key="scalping")]
            json.dump(rows, open(path, "w", encoding="utf-8"))
            log("Added the scalping section to site/portions.json for the local preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
