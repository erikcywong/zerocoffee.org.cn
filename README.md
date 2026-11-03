# ZeroCarbon Verify — full-stack corporate site

Western-style assurance brand site (reference: dnv.com) with a working backend.
Static front-end + Python API. Zero build step, zero dependencies.

## Run it

```powershell
cd "D:\DeepSeek Harness\Forecast AI bubble\zerocarbon-site"
python server\app.py
# open http://127.0.0.1:8099
```

The server serves the whole site **and** the API from one port, so the quote calculator and the
contact form work end to end.

Environment:

| Variable | Default | Purpose |
|---|---|---|
| `ZV_PORT` | 8099 | listen port |
| `ZV_HOST` | 127.0.0.1 | bind address |
| `ZV_ADMIN_TOKEN` | `dev-token-change-me` | `GET /api/leads` auth |

## Structure

```
index.html              home — hero, stats, three services, process, insights, CTA
services/index.html     12 services in 3 classes, fees, process, live quote calculator
industries/index.html   coffee & agri (primary), food, manufacturing, finance
platform/index.html     registry, browser verification, API reference
about/index.html        independence, accreditation status, structure, filing links
registry/index.html     issued labels, how to verify, revocations, method versions
insights/index.html     the six arguments behind the method
contact/index.html      lead form wired to POST /api/leads
filing/                 the Chinese establishment file (conditions, fees, governance…)
assets/site.css         design system — navy / white / cards / 1240px grid
assets/site.js          quote model, lead capture, nav highlight
server/app.py           stdlib HTTP server: site + /api/*
data/leads.jsonl        created on first lead
```

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/quote` | deterministic model `zv-quote-v1`, mirrored in `assets/site.js` |
| POST | `/api/leads` | validates name/company/email/consent; returns `ZV-YYYYMMDD-XXXXXX` |
| GET | `/api/leads?token=…` | admin list |
| GET | `/api/rates` | published fee table |
| GET | `/api/health` | liveness + counters |

```powershell
curl http://127.0.0.1:8099/api/quote -H "Content-Type: application/json" `
  -d '{"sites":1,"batches":500,"addons":["baseline","grade"],"travel_days":3}'
# → {"currency":"CNY","lines":[…],"total":63700,"model":"zv-quote-v1"}
```

## Deploy

**Static part** → GitHub Pages (`zerocoffee.org` repo, root). Everything except the API works there;
the contact form detects an unreachable API and falls back to a prefilled email draft.

**API** → any Python host (Fly.io / Render / a VPS), then point the site at it:

```
https://site/?api=https://api.example.com     # stored in localStorage
```

**Pricing model lives in two places** (`assets/site.js` `RATES` and `server/app.py` `RATES`).
They are deliberately identical; change both or neither.

## Design notes

- Reference is dnv.com: navy `#00205b`, teal accent `#00958f`, white body, 1240px grid,
  thin 1px borders, card matrices, no shadows except on hover.
- The Chinese filing pages keep their paper aesthetic on purpose — the corporate site is the
  shop window, the filing is the record.
- Every page carries an "Accreditation in progress — not yet accredited" badge in the utility bar.
  Do not remove it: a buyer who checks the HKAS directory and finds nothing is worse off than
  one who reads the caveat.
- No carbon-credit language anywhere. Labels are disclosures, not tradable assets.

## Full stack — two ways to run the same site

The front end calls one API surface (`assets/api.js`). Where that surface lives is a deployment choice:

| Mode | When | Storage |
|---|---|---|
| **browser store** | default on GitHub Pages, no server | `localStorage` — leads and certificates persist in the visitor's browser |
| **live API** | `?api=https://your-host` or `localStorage zv-api` | `data/*.jsonl` on the server |

```powershell
python server/app.py            # http://127.0.0.1:8099
# then open the site with ?api=http://127.0.0.1:8099 to use the shared database
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/quote` | deterministic fee model `zv-quote-v1` |
| POST | `/api/simulate` | revenue model `zv-revenue-v1` |
| POST | `/api/certifications` | run a certification case, persist it |
| GET | `/api/certifications` | list issued certificates |
| POST | `/api/leads` | validated enquiry capture |
| GET | `/api/leads?token=…` | lead list (admin token) |
| GET | `/api/rates` · `/api/health` | fee table · liveness |

### Deploy the API

Any Python host works — the service is stdlib only, no dependencies.

```bash
# Fly.io
fly launch --copy-config --name zerocoffee-org-cn
fly deploy

# Render — import the repo, it picks up render.yaml
# Docker
docker build -t zv . && docker run -p 8099:8099 -v zvdata:/app/data zv
```

CI (`.github/workflows/api-smoke.yml`) boots the service and exercises every endpoint on each push.
