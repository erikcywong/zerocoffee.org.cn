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
CERTS = os.path.join(DATA, "certifications.jsonl")
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
    "label_batch": 40,
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




# ------------------------------------------------------------------ certification model
# Mirrors certify() in assets/api.js. Keep the two in step.
WORKFLOW = [
    ("application", "Application & scope", 2),
    ("docreview", "Document review", 3),
    ("verification", "On-site verification", 2),
    ("techreview", "Technical review", 2),
    ("issued", "Label issued", 1),
]


def fnv(text: str) -> str:
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def build_certification(d: dict) -> dict:
    farm = (d.get("farm") or "unnamed farm").strip()[:80]
    plantlets = max(240, int(d.get("plantlets") or 240000))
    batch = max(60, int(d.get("batchSize") or 480))
    grade = d.get("grade") or "B"
    batches = round(plantlets / batch)
    source = d.get("source") if isinstance(d.get("source"), dict) else None
    rederive = 2000 if source else 0
    fee = 28000 + 6000 + 4000 + batches * 40 + rederive
    days = sum(w[2] for w in WORKFLOW)
    issued = time.time()
    seq = f"{int(issued) % 100000:05d}"
    payload = f"{farm}|{plantlets}|{grade}|CJV-MTH-1.0|{seq}"
    iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(issued))
    expires = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(issued + 365 * 86400))
    return {
        "id": f"ZC-{time.strftime('%Y', time.localtime(issued))}-{seq}",
        "farm": farm, "plantlets": plantlets, "batchSize": batch, "batches": batches,
        "grade": grade, "method": "CJV-MTH-1.0", "hash": fnv(payload),
        "fee": fee, "days": days, "issued": iso, "expires": expires, "status": "issued",
        "workflow": [
            {"id": w[0], "en": w[1], "days": w[2],
             "at": time.strftime("%Y-%m-%d", time.localtime(issued - (len(WORKFLOW) - 1 - i) * 2 * 86400))}
            for i, w in enumerate(WORKFLOW)
        ],
        "source": source,
        "lines": [
            {"k": "PCF verification (year 1)", "v": 28000},
            {"k": "Baseline co-signing", "v": 6000},
            {"k": "Evidence grade assessment", "v": 4000},
            {"k": f"Label review × {batches}", "v": batches * 40},
        ] + ([{"k": "Platform evidence re-derivation", "v": rederive}] if source else []),
    }


def store_cert(rec: dict) -> dict:
    with LOCK:
        with open(CERTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_certs(limit: int = 500) -> list[dict]:
    if not os.path.exists(CERTS):
        return []
    with LOCK:
        with open(CERTS, encoding="utf-8") as fh:
            rows = [json.loads(x) for x in fh if x.strip()]
    return rows[::-1][:limit]


# ------------------------------------------------------------------ revenue model
def simulate(d: dict) -> dict:
    farms = max(1, min(500, int(d.get("farms") or 20)))
    plantlets = max(1000, int(d.get("plantlets") or 240000))
    batch = max(60, int(d.get("batchSize") or 480))
    years = max(1, min(10, int(d.get("years") or 3)))
    grade = d.get("grade") or "B"
    ramp = [0.3, 0.6, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
    labels_year = round(plantlets / batch)
    grade_price = {"A": 80, "B": 60, "C": 40}.get(grade, 60)

    rows, cum = [], 0.0
    for y in range(1, years + 1):
        live = max(1, round(farms * ramp[min(y - 1, len(ramp) - 1)]))
        prev = round(farms * ramp[min(y - 2, len(ramp) - 1)]) if y > 1 else 0
        new = live if y == 1 else max(0, live - prev)
        labels = live * labels_year
        rev = {
            "verification": new * 28000,
            "surveillance": 0 if y == 1 else live * 12000,
            "labels": labels * 40,
            "baseline": new * 6000 if y == 1 else 0,
            "grade": live * 4000,
        }
        revenue = sum(rev.values())
        # verification is per site, not per label: 5% sampling at 0.08 day each
        days = new * 6 + (0 if y == 1 else live * 2) + labels * 0.05 * 0.08 + live * 0.5
        cost = days * 3800 * 1.25
        gross = revenue - cost
        cum += gross
        rows.append({
            "year": y, "farms": live, "labels": labels,
            "revenue": round(revenue), "cost": round(cost), "gross": round(gross),
            "cum": round(cum), "margin": round(gross / revenue * 100, 1) if revenue else 0,
            "breakdown": {k: round(v) for k, v in rev.items()},
            "platformLabelFees": round(labels * grade_price),
        })
    return {
        "model": "zv-revenue-v1",
        "inputs": {"farms": farms, "plantlets": plantlets, "batchSize": batch, "years": years,
                   "grade": grade, "withLabel": True},
        "labelsYear": labels_year, "rows": rows,
        "totals": {
            "revenue": sum(r["revenue"] for r in rows),
            "cost": sum(r["cost"] for r in rows),
            "gross": sum(r["gross"] for r in rows),
            "platformLabelFees": sum(r["platformLabelFees"] for r in rows),
        },
    }


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
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/api/health":
            return self._json(200, {
                "ok": True, "service": "zerocarbon-verify",
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "leads": len(read_leads(10_000)), "certs": len(read_certs(10_000)),
                "models": ["zv-quote-v1", "zv-revenue-v1"],
            })
        if path == "/api/rates":
            return self._json(200, {"rates": RATES, "currency": "CNY"})
        if path == "/api/certifications":
            return self._json(200, {"certs": read_certs()})
        if path == "/api/simulate":
            return self._json(200, simulate({k: v[0] for k, v in qs.items()}))
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
        if path == "/api/simulate":
            return self._json(200, simulate(self._body() or {}))
        if path == "/api/certifications":
            rec = build_certification(self._body() or {})
            store_cert(rec)
            return self._json(201, rec)
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
