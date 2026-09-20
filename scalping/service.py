"""Server-side context for the SCALPING section: the data the browser cannot fetch itself (Aster funding, OKX open interest).
Prices, candles and the order book are fetched live in the browser from Binance's public API and analysed by static/scalping.js."""
import datetime

from . import config


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def build_payload(aster_mod=None, deriv_mod=None):
    coins = []
    for c in config.COINS:
        sym = c["symbol"]
        funding = oi = mark = None
        try:
            a = aster_mod.SNAPSHOT.get(sym) if aster_mod is not None else None
            if a:
                funding, mark = a.get("funding_pct"), a.get("mark")
        except Exception:  # noqa: BLE001 - optional context
            pass
        try:
            if deriv_mod is not None:
                oi = deriv_mod.okx_oi(sym)["oi_change_pct"]
        except Exception:  # noqa: BLE001
            oi = None
        coins.append({"symbol": sym, "name": c["name"], "funding_pct": funding, "oi_change_pct": oi, "aster_mark": mark})
    return {"coins": coins, "params": config.PARAMS, "generated_at": _now_iso()}
