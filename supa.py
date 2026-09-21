"""Tiny Supabase REST client (stdlib only) for the scheduled job.

The dashboard's data lives in Supabase behind row-level security, so the public site and repo
hold nothing readable. This job signs in as a dedicated "publisher" account: RLS lets that one
account write the data tables and nothing else -- narrower than the all-powerful service key.
Configured entirely through environment variables; unset means "run locally without a backend".
"""
import json
import os
import urllib.error
import urllib.request
import datetime
import socket
import time

RETRIES = 4                       # attempts per request
BACKOFF_SECONDS = (2, 5, 12)      # waits between attempts
ENV_KEYS = ("KAIRO_SUPABASE_URL", "KAIRO_SUPABASE_ANON_KEY", "KAIRO_PUBLISHER_EMAIL", "KAIRO_PUBLISHER_PASSWORD")


class Backend:
    def __init__(self, url, anon_key, email, password):
        self.url = url.rstrip("/")
        self.anon = anon_key
        self.email = email
        self.password = password
        self.token = None

    @classmethod
    def from_env(cls):
        vals = [os.environ.get(k) for k in ENV_KEYS]
        return cls(*vals) if all(vals) else None

    def _request(self, method, path, body=None, headers=None, auth=True, timeout=30):
        h = {"apikey": self.anon, "Content-Type": "application/json"}
        if auth:
            h["Authorization"] = f"Bearer {self.token}"
        if headers:
            h.update(headers)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        # Temporary trouble (network error, timeout, HTTP 429/5xx) is retried a few times: every call here is safe to repeat
        # (reads, token requests, and upserts that merge on a key). Anything else, e.g. a 4xx from a bad request, fails at once.
        last = None
        for attempt in range(RETRIES):
            if attempt:
                time.sleep(BACKOFF_SECONDS[attempt - 1])
            req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as e:
                # Server-side detail only -- never echo request headers/body, which carry credentials.
                detail = e.read().decode("utf-8", "replace")[:300]
                last = RuntimeError(f"{method} {path.split('?')[0]} -> HTTP {e.code}: {detail}")
                if e.code != 429 and e.code < 500:
                    raise last from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
                last = RuntimeError(f"{method} {path.split('?')[0]} -> {type(e).__name__} (temporary network problem)")
        raise last from None

    def sign_in(self):
        r = self._request("POST", "/auth/v1/token?grant_type=password",
                          {"email": self.email, "password": self.password}, auth=False)
        self.token = r["access_token"]

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def get_state(self, key="state"):
        rows = self._request("GET", f"/rest/v1/app_state?key=eq.{key}&select=value")
        return rows[0]["value"] if rows else None

    def put_state(self, value, key="state"):
        self._request("POST", "/rest/v1/app_state?on_conflict=key",
                      [{"key": key, "value": value, "updated_at": self._now()}],
                      headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def publish_portions(self, portions):
        """portions: {key: {"title", "sort_order", "html", "data"}} -> one upsert."""
        now = self._now()
        rows = [{"key": k, "title": v.get("title", ""), "sort_order": v.get("sort_order", 0),
                 "html": v.get("html", ""), "data": v.get("data", {}), "updated_at": now}
                for k, v in portions.items()]
        self._request("POST", "/rest/v1/portions?on_conflict=key", rows,
                      headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def publish_notifications(self, events):
        """events already carry id/ts/type/title/body/portion_key; existing ids are left untouched."""
        if not events:
            return
        self._request("POST", "/rest/v1/notifications?on_conflict=id", events,
                      headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})

    # ---- generic table access (used by the Market Events job) ----

    def select(self, table, query="select=*"):
        return self._request("GET", f"/rest/v1/{table}?{query}") or []

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return
        # PostgREST rejects a bulk body whose objects have different keys ("All object keys must match"), and the events
        # job legitimately sends rows with different optional fields. Send one request per identical key set, so no
        # column is ever written as NULL just to make the shapes match.
        groups = {}
        for r in rows:
            groups.setdefault(tuple(sorted(r)), []).append(r)
        for batch in groups.values():
            self._request("POST", f"/rest/v1/{table}?on_conflict={on_conflict}", batch,
                          headers={"Prefer": "resolution=merge-duplicates,return=minimal,missing=default"})
