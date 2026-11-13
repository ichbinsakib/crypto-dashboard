"""File-backed store: the same interface as supa.Backend, but everything lives in plain JSON files, so the dashboard needs no
database and nothing that can be paused or shut down.

  store/state/<key>.json    engine state (open positions, P&L history, ...); the key "state" is the main tracker
  store/tables/<name>.json  tables the engines write (scalp_signals, economic_events, ...), as lists of rows
  store/portions.json       the last published content of every tab
  store/notifications.json  the notification feed
  config/<name>.json        SETTINGS you edit by hand (trend_settings, scalp_settings, price_alerts, event_config);
                            a list of rows, e.g. [{"key": "config", "value": {...}}]. Never written by the jobs.

In the hosted build `store/` is persisted on the `data` branch (see .github/workflows/deploy.yml). The published site gets
site/portions.json and site/notifications.json. Everything is public, because GitHub Pages is.
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
NOTIFICATION_KEEP = 300          # newest N notifications kept in the feed
CONFIG_TABLES = ("trend_settings", "scalp_settings", "price_alerts", "event_config")


def _read(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, separators=(",", ":"))
    os.replace(tmp, path)         # an interrupted run never leaves a half-written file behind


def _parse_query(query):
    """The small PostgREST subset the engines use: col=eq.value filters, order=col.desc, limit=N."""
    flt, order, limit = [], None, None
    for part in (query or "").split("&"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        if k == "order":
            col, _, d = v.partition(".")
            order = (col, d == "desc")
        elif k == "limit":
            limit = int(v)
        elif k != "select" and v.startswith("eq."):
            flt.append((k, v[3:]))
    return flt, order, limit


class FileBackend:
    def __init__(self, root=HERE, site_dir=None):
        self.root = root
        self.site_dir = site_dir or os.path.join(root, "site")

    @classmethod
    def from_env(cls):
        """Used whenever the Supabase settings are absent, i.e. always once the database is gone."""
        return cls()

    def _p(self, *parts):
        return os.path.join(self.root, *parts)

    def sign_in(self):
        pass

    # ---- state ----
    def get_state(self, key="state"):
        return _read(self._p("store", "state", key + ".json"), None)

    def put_state(self, value, key="state"):
        _write(self._p("store", "state", key + ".json"), value)

    # ---- tables ----
    def select(self, table, query="select=*"):
        if table in CONFIG_TABLES and os.path.exists(self._p("config", table + ".json")):
            rows = _read(self._p("config", table + ".json"), [])
        else:
            rows = _read(self._p("store", "tables", table + ".json"), [])
        flt, order, limit = _parse_query(query)
        rows = [r for r in rows if all(str(r.get(k)) == v for k, v in flt)]
        if order:
            rows = sorted(rows, key=lambda r: (r.get(order[0]) is None, r.get(order[0])), reverse=order[1])
        return [dict(r) for r in (rows[:limit] if limit else rows)]

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return
        path = self._p("store", "tables", table + ".json")
        cur = _read(path, [])
        cols = on_conflict.split(",")
        for row in rows:
            for ex in cur:
                if all(ex.get(c) == row.get(c) for c in cols):
                    ex.update(row)
                    break
            else:
                cur.append(dict(row))
        _write(path, cur)

    def seed_price_alerts(self, rows):
        self.upsert("price_alerts", rows, "id")

    # ---- what the site shows ----
    def publish_portions(self, portions):
        """portions: {key: {"title", "sort_order", "html", "data"}}; merged into what earlier jobs published."""
        path = self._p("store", "portions.json")
        cur = {r["key"]: r for r in _read(path, [])}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for k, v in portions.items():
            cur[k] = {"key": k, "title": v.get("title", ""), "sort_order": v.get("sort_order", 0),
                      "html": v.get("html", ""), "data": v.get("data", {}), "updated_at": now}
        rows = sorted(cur.values(), key=lambda r: r["sort_order"])
        _write(path, rows)
        _write(os.path.join(self.site_dir, "portions.json"), rows)

    def publish_notifications(self, events):
        """Events carry id/ts/type/title/body/portion_key; ids already in the feed are left alone."""
        path = self._p("store", "notifications.json")
        cur = _read(path, [])
        have = {e["id"] for e in cur}
        cur.extend(dict(e) for e in events if e["id"] not in have)
        cur = sorted(cur, key=lambda e: e["ts"], reverse=True)[:NOTIFICATION_KEEP]
        _write(path, cur)
        _write(os.path.join(self.site_dir, "notifications.json"), cur)
