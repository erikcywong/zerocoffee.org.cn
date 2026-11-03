"""ZeroCarbon Verify — full-stack service.

Serves the static site and two APIs:
    POST /api/quote     deterministic pricing (same model as assets/site.js)
    POST /api/leads     validated lead capture, appended to data/leads.jsonl
    GET  /api/leads     lead list (requires the admin token)
    GET  /api/health    liveness

Stdlib only.  Run:  python server/app.py  (then open http://127.0.0.1:8099)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = ROOT
DATA = os.path.join(ROOT, "data")
LEADS = os.path.join(DATA, "leads.jsonl")
os.makedirs(DATA, exist_ok=True)

ADMIN_TOKEN = os.environ.get("ZV_ADMIN_TOKEN", "dev-token-change-me")
LOCK = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}

# ------------------------------------------------------------------ pricing model
# Kept identical to RATES / quote() in assets/site.js. If you change one, change both.
RATES = {
    "pcf_site": 28000,
    "surveillance": 12000,
    "label_batch": 25,
    "baseline": 6000,
    "grade_site": 4000,
    "ledger": 8000,
    "mrv_site": 20000,
    "travel_day": 1200,
    "travel_included": 2,
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def build_quote(payload: dict) -> dict:
    sites = clamp(int(payload.get("sites") or 1), 1, 50)
    batches = clamp(int(payload.get("batches") or 0), 0, 20000)
    travel = clamp(int(payload.get("travel_days") or 0), 0, 60)
    addons = set(payload.get("addons") or [])

    lines = []

    def add(label, qty, unit, amount):
        lines.append({"label": label, "qty": qty, "unit": unit, "amount": round(amount)})

    add("Product carbon footprint (year 1)", sites, "site", RATES["pcf_site"] * sites)
    add("Annual surveillance", sites, "site / yr", RATES["surveillance"] * sites)
    if batches:
        add("Label issuance", batches, "batch", RATES["label_batch"] * batches)
    if "baseline" in addons:
        add("Baseline co-signing", 1, "exercise", RATES["baseline"])
    if "grade" in addons:
        add("Evidence grade assessment", sites, "site / yr", RATES["grade_site"] * sites)
    if "ledger" in addons:
        add("Ledger integrity assurance", 1, "exercise", RATES["ledger"])
    if "mrv" in addons:
        add("MRV system audit", sites, "site", RATES["mrv_site"] * sites)
    extra = max(0, travel - RATES["travel_included"])
    if extra:
        add("Additional travel days", extra, "day", RATES["travel_day"] * extra)

    return {
        "currency": "CNY",
        "lines": lines,
        "total": sum(l["amount"] for l in lines),
        "inputs": {"sites": sites, "batches": batches, "addons": sorted(addons), "travel_days": travel},
        "note": "Surveillance and grade assessment recur annually. Excludes taxes and client-side data preparation.",
        "model": "zv-quote-v1",
    }


# ------------------------------------------------------------------ lead store
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_lead(d: dict) -> list[str]:
    errs = []
    if not (d.get("name") or "").strip():
        errs.append("name")
    if not (d.get("company") or "").strip():
        errs.append("company")
    if not EMAIL.match((d.get("email") or "").strip()):
        errs.append("email")
    if not d.get("consent"):
        errs.append("consent")
    if len((d.get("message") or "")) > 4000:
        errs.append("message too long")
    return errs


def store_lead(d: dict) -> dict:
    lead_id = "ZV-" + time.strftime("%Y%m%d") + "-" + secrets.token_hex(3).upper()
    record = {
        "id": lead_id,
        "received": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "name": d.get("name", "").strip()[:120],
        "company": d.get("company", "").strip()[:160],
        "email": d.get("email", "").strip()[:160],
        "role": d.get("role", "")[:40],
        "scope": d.get("scope", "")[:40],
        "message": d.get("message", "")[:4000],
        "consent": True,
        "page": d.get("page", "")[:200],
        "ua": d.get("ua", "")[:200],
    }
    with LOCK:
        with open(LEADS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_leads(limit: int = 200) -> list[dict]:
    if not os.path.exists(LEADS):
        return []
    with LOCK:
        with open(LEADS, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
    return rows[::-1][:limit]


# ------------------------------------------------------------------ http handler
class Handler(BaseHTTPRequestHandler):
    server_version = "ZeroCarbonVerify/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("ZV_VERBOSE"):
            super().log_message(fmt, *args)

    # ---- helpers
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            return {}
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self._send(204)

    # ---- routes
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == "/api/health":
            return self._json(200, {
                "ok": True, "service": "zerocarbon-verify", "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "leads": len(read_leads(10_000)), "model": "zv-quote-v1",
            })
        if path == "/api/rates":
            return self._json(200, {"rates": RATES, "currency": "CNY"})
        if path == "/api/leads":
            token = self.headers.get("X-Admin-Token") or (qs.get("token") or [""])[0]
            if token != ADMIN_TOKEN:
                return self._json(401, {"error": "admin token required"})
            return self._json(200, {"leads": read_leads(int((qs.get("limit") or ["200"])[0]))})
        return self._static(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/quote":
            return self._json(200, build_quote(self._body() or {}))

        if path == "/api/leads":
            d = self._body() or {}
            d["ua"] = self.headers.get("User-Agent", "")
            errs = validate_lead(d)
            if errs:
                return self._json(422, {"error": "invalid fields", "fields": errs})
            rec = store_lead(d)
            return self._json(201, {"id": rec["id"], "received": rec["received"],
                                    "next": "We reply within two working days."})

        return self._json(404, {"error": "not found"})

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(SITE, rel.replace("/", os.sep)))
        if not full.startswith(SITE):
            return self._send(403, b"forbidden", "text/plain")
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        with open(full, "rb") as fh:
            body = fh.read()
        self._send(200, body, ctype, {"Cache-Control": "no-cache"})


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    port = int(os.environ.get("ZV_PORT", "8099"))
    host = os.environ.get("ZV_HOST", "127.0.0.1")
    srv = Server((host, port), Handler)
    print(f"""
ZeroCarbon Verify — full stack
  site      http://{host}:{port}/
  health    GET  /api/health
  quote     POST /api/quote        {json.dumps(build_quote({}), ensure_ascii=False)[:90]}…
  leads     POST /api/leads
  admin     GET  /api/leads?token=…  (set ZV_ADMIN_TOKEN)
  data      {LEADS}
""")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopping")
        srv.shutdown()


if __name__ == "__main__":
    main()
