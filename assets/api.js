/* ZeroCarbon Verify — data layer + business model.
 *
 * One API surface, two backends:
 *   - if an API base is configured (?api=… or localStorage zv-api), calls go to the
 *     Python server in /server (deployed anywhere)
 *   - otherwise an in-browser store (IndexedDB) implements the same calls, so the
 *     static site on GitHub Pages is fully functional on its own
 *
 * The fee model below is mirrored exactly in server/app.py. Change both or neither.
 */
(function () {
  'use strict';

  const RATES = {
    verification_site: 28000,   // first-year PCF verification, per site
    surveillance_site: 12000,   // annual surveillance, per site
    label_review: 40,           // per batch, verifier share of the 40-80 buyer fee
    baseline: 6000,             // baseline co-signing, one-off per site
    grade_site: 4000,           // evidence grade assessment, per site / yr
    mrv_site: 20000,            // MRV system audit, per site
    day_rate: 3800,             // person-day cost basis
    overhead: 0.25              // overhead on person-day cost
  };

  const WORKFLOW = [
    { id: 'application', zh: '受理与范围确认', en: 'Application & scope', days: 2 },
    { id: 'docreview', zh: '文件评审', en: 'Document review', days: 3 },
    { id: 'verification', zh: '现场/远程核查', en: 'On-site verification', days: 2 },
    { id: 'techreview', zh: '技术复核', en: 'Technical review', days: 2 },
    { id: 'issued', zh: '签发标签', en: 'Label issued', days: 1 }
  ];

  function fnv(s) {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return ('0000000' + h.toString(16)).slice(-8);
  }

  /* ---------------- quote ---------------- */
  function quote(inp) {
    const sites = Math.max(1, Math.min(50, +(inp.sites || 1)));
    const batches = Math.max(0, +(inp.batches || 0));
    const travelDays = Math.max(0, +(inp.travelDays || 0));
    const addons = inp.addons || [];
    const lines = [];
    const add = (label, qty, unit, amount) => lines.push({ label, qty, unit, amount: Math.round(amount) });

    add('Product carbon footprint (year 1)', sites, 'site', RATES.verification_site * sites);
    add('Annual surveillance', sites, 'site / yr', RATES.surveillance_site * sites);
    if (batches) add('Label issuance', batches, 'batch', RATES.label_review * batches);
    if (addons.includes('baseline')) add('Baseline co-signing', sites, 'site', RATES.baseline * sites);
    if (addons.includes('grade')) add('Evidence grade assessment', sites, 'site / yr', RATES.grade_site * sites);
    if (addons.includes('ledger')) add('Ledger integrity assurance', 1, 'exercise', 8000);
    if (addons.includes('mrv')) add('MRV system audit', sites, 'site', RATES.mrv_site * sites);
    const extra = Math.max(0, travelDays - 2);
    if (extra) add('Additional travel days', extra, 'day', 1200 * extra);
    return { currency: 'CNY', lines, total: lines.reduce((a, l) => a + l.amount, 0), model: 'zv-quote-v1' };
  }

  /* ---------------- revenue projection ---------------- */
  function simulate(inp) {
    const farms = Math.max(1, Math.min(500, +(inp.farms || 20)));
    const plantlets = Math.max(1000, +(inp.plantlets || 240000));
    const batchSize = Math.max(60, +(inp.batchSize || 480));
    const years = Math.max(1, Math.min(10, +(inp.years || 3)));
    const grade = inp.grade || 'B';
    const ramp = inp.ramp || [0.3, 0.6, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0];
    const withLabel = inp.withLabel !== false;
    const labelsYear = Math.round(plantlets / batchSize);
    // a label review is 0.12 person-days; a first-year verification is 6; surveillance 2
    const gradePrice = { A: 80, B: 60, C: 40 }[grade] || 60;

    const rows = [];
    let cum = 0;
    for (let y = 1; y <= years; y++) {
      const live = Math.max(1, Math.round(farms * ramp[Math.min(y - 1, ramp.length - 1)]));
      const newFarms = y === 1 ? live : Math.max(0, live - Math.round(farms * ramp[Math.min(y - 2, ramp.length - 1)]));
      const labels = withLabel ? live * labelsYear : 0;

      const rev = {
        verification: newFarms * RATES.verification_site,
        surveillance: y === 1 ? 0 : live * RATES.surveillance_site,
        labels: labels * RATES.label_review,
        baseline: y === 1 ? newFarms * RATES.baseline : 0,
        grade: y === 1 ? live * RATES.grade_site : live * RATES.grade_site
      };
      const revenue = Object.values(rev).reduce((a, v) => a + v, 0);

      // verification is per site, not per label: 5% sampling, 0.08 day each
      const days = newFarms * 6 + (y === 1 ? 0 : live * 2) + labels * 0.05 * 0.08 + live * 0.5;
      const cost = days * RATES.day_rate * (1 + RATES.overhead);

      const gross = revenue - cost;
      cum += gross;
      rows.push({
        year: y, farms: live, labels,
        revenue: Math.round(revenue), cost: Math.round(cost),
        gross: Math.round(gross), cum: Math.round(cum),
        margin: revenue ? +(gross / revenue * 100).toFixed(1) : 0,
        breakdown: Object.fromEntries(Object.entries(rev).map(([k, v]) => [k, Math.round(v)])),
        // what the platform side collects from buyers on the same lots
        platformLabelFees: Math.round(labels * gradePrice)
      });
    }
    return {
      model: 'zv-revenue-v1', inputs: { farms, plantlets, batchSize, years, grade, withLabel },
      labelsYear, rows,
      totals: {
        revenue: rows.reduce((a, r) => a + r.revenue, 0),
        cost: rows.reduce((a, r) => a + r.cost, 0),
        gross: rows.reduce((a, r) => a + r.gross, 0),
        platformLabelFees: rows.reduce((a, r) => a + r.platformLabelFees, 0)
      }
    };
  }

  /* ---------------- cross-site: the CoffeeJeV platform register ---------------- */
  // Published by tools/export_labels.py on www.coffeejev.space. GitHub Pages sends
  // `access-control-allow-origin: *`, so this is a plain cross-origin fetch.
  const PLATFORM = {
    origin: 'https://www.coffeejev.space',
    register: 'https://www.coffeejev.space/v/labels.json',
    verifyUrl: 'https://www.coffeejev.space/v/?id=',
    methodHash: '9b12abef',
    name: 'CoffeeJeV'
  };

  async function fetchPlatform() {
    const r = await fetch(PLATFORM.register, { cache: 'no-store' });
    if (!r.ok) throw new Error('platform register HTTP ' + r.status);
    const doc = await r.json();
    if (!doc || !Array.isArray(doc.labels)) throw new Error('platform register malformed');
    return doc;
  }

  function payloadOf(lab) {
    return lab._payload || [lab.batch, lab.kgco2e_total, lab.kgco2e_per_unit, lab.grade].join('|');
  }

  /* Independent re-derivation of a platform label. Nothing here trusts the platform:
   * every number is recomputed from the published record. */
  function verifyLabel(lab, prevLabel) {
    const checks = [];
    const add = (id, name, ok, expected, actual, note) =>
      checks.push({ id, name, ok: !!ok, expected, actual, note: note || '' });

    // C1 — hash recomputation
    const payload = payloadOf(lab);
    const expectHash = fnv(String(lab.prev) + payload);
    add('C1', 'Label hash re-derivation', expectHash === lab.hash, expectHash, lab.hash,
        `fnv("${lab.prev}" + "${payload}")`);

    // C2 — chain link to the previous label
    const prevHash = prevLabel ? prevLabel.hash : 'genesis';
    add('C2', 'Chain link to previous label', String(lab.prev) === String(prevHash),
        prevHash, String(lab.prev), prevLabel ? 'previous label in the register' : 'first label');

    // C3 — line items sum to the declared total
    const lines = Array.isArray(lab.lines) ? lab.lines : [];
    const sum = lines.reduce((a, l) => a + (+l.kgco2e || 0), 0);
    const total = +lab.kgco2e_total || 0;
    const sumOk = lines.length > 0 && Math.abs(sum - total) <= Math.max(0.01, total * 0.005);
    add('C3', 'Line items sum to total', sumOk, total.toFixed(3), sum.toFixed(3),
        `${lines.length} line items, tolerance 0.5%`);

    // C4 — unit consistency
    const per = +lab.kgco2e_per_unit || 0;
    const units = per ? total / per : 0;
    const unitsOk = per > 0 && Math.abs(Math.round(units) - units) < 0.02;
    add('C4', 'Per-unit × units = total', unitsOk, 'integer unit count', units.toFixed(2),
        `total ${total} / per-unit ${per}`);

    // C5 — grade matches the metered share
    const dq = +lab.data_quality || 0;
    const expectGrade = dq >= 70 ? 'A' : dq >= 45 ? 'B' : 'C';
    add('C5', 'Evidence grade vs metered share', expectGrade === lab.grade, expectGrade, lab.grade,
        `metered ${dq}% · rule A≥70 · B≥45 · C<45`);

    // C6 — method hash matches the published method version
    add('C6', 'Method hash pinned to CJV-MTH-1.0', lab.method_hash === PLATFORM.methodHash,
        PLATFORM.methodHash, String(lab.method_hash || '—'), `method ${lab.method_version || '—'}`);

    // C7 — reduction recomputed from the co-signed baseline
    const base = +lab.baseline_kgco2e_per_unit || 0;
    const red = base ? (1 - per / base) * 100 : 0;
    const declared = +lab.reduction_vs_baseline_pct || 0;
    add('C7', 'Reduction vs baseline recomputed', base > 0 && Math.abs(red - declared) <= 0.3,
        declared.toFixed(1) + '%', red.toFixed(1) + '%', `baseline ${base} kgCO₂e / unit`);

    // C8 — the label fee matches the published schedule
    const feeByGrade = { A: 80, B: 60, C: 40 };
    add('C8', 'Label fee matches published schedule', feeByGrade[lab.grade] === lab.fee_cny,
        String(feeByGrade[lab.grade] || '—'), String(lab.fee_cny), '¥ per batch by grade');

    const passed = checks.filter(c => c.ok).length;
    return {
      label_id: lab.label_id, batch: lab.batch, hash: lab.hash, prev: lab.prev,
      payload, grade: lab.grade, method: lab.method_version, method_hash: lab.method_hash,
      kgco2e_per_unit: lab.kgco2e_per_unit, kgco2e_total: lab.kgco2e_total,
      baseline: lab.baseline_kgco2e_per_unit, reduction: lab.reduction_vs_baseline_pct,
      data_quality: lab.data_quality, fee_cny: lab.fee_cny,
      checks, passed, total: checks.length, ok: passed === checks.length,
      url: PLATFORM.verifyUrl + lab.label_id, platform: PLATFORM.name,
      verified_at: new Date().toISOString()
    };
  }

  /* ---------------- certification case ---------------- */
  function certify(inp) {
    const farm = (inp.farm || 'unnamed farm').trim().slice(0, 80);
    const plantlets = Math.max(240, +(inp.plantlets || 240000));
    const batchSize = Math.max(60, +(inp.batchSize || 480));
    const grade = inp.grade || 'B';
    const method = 'CJV-MTH-1.0';
    const batches = Math.round(plantlets / batchSize);
    const source = inp.source || null;
    const rederive = source ? 2000 : 0;   // independent re-derivation of platform evidence
    const fee = RATES.verification_site + RATES.baseline + RATES.grade_site
      + batches * RATES.label_review + rederive;
    const days = WORKFLOW.reduce((a, w) => a + w.days, 0);
    const issued = new Date();
    const expires = new Date(issued.getTime() + 365 * 86400e3);
    const seq = (Date.now() % 100000).toString().padStart(5, '0');
    const payload = `${farm}|${plantlets}|${grade}|${method}|${seq}`;
    const hash = fnv(payload);
    return {
      id: `ZC-${issued.getFullYear()}-${seq}`,
      farm, plantlets, batchSize, batches, grade, method, hash,
      fee, days,
      issued: issued.toISOString(), expires: expires.toISOString(),
      status: 'issued',
      workflow: WORKFLOW.map((w, i) => ({
        ...w, at: new Date(issued.getTime() - (WORKFLOW.length - 1 - i) * 2 * 86400e3).toISOString().slice(0, 10)
      })),
      source,
      lines: [
        { k: 'PCF verification (year 1)', v: RATES.verification_site },
        { k: 'Baseline co-signing', v: RATES.baseline },
        { k: 'Evidence grade assessment', v: RATES.grade_site },
        { k: `Label review × ${batches}`, v: batches * RATES.label_review }
      ].concat(source ? [{ k: 'Platform evidence re-derivation', v: rederive }] : [])
    };
  }

  /* ---------------- in-browser store (localStorage) ---------------- */
  // Deliberately synchronous and dependency-free: leads and certificates are tiny,
  // and IndexedDB callbacks do not fire under headless rendering or strict privacy
  // modes, which made the pages hang waiting for a promise that never settled.
  const KEY = 'zv-store-v1';

  function readAll() {
    try { return JSON.parse(localStorage.getItem(KEY) || '{"leads":[],"certs":[]}'); }
    catch (e) { return { leads: [], certs: [] }; }
  }

  function writeAll(db) {
    localStorage.setItem(KEY, JSON.stringify(db));
    return db;
  }

  function put(store, obj) {
    const db = readAll();
    db[store] = db[store] || [];
    const i = db[store].findIndex(x => x.id === obj.id);
    if (i >= 0) db[store][i] = obj; else db[store].push(obj);
    writeAll(db);
    return obj;
  }

  function all(store) {
    return (readAll()[store] || []).slice();
  }

  /* ---------------- unified API ---------------- */
  const base = (function () {
    const q = new URLSearchParams(location.search).get('api');
    if (q) { localStorage.setItem('zv-api', q); return q.replace(/\/+$/, ''); }
    return (localStorage.getItem('zv-api') || '').replace(/\/+$/, '');
  })();

  async function toServer(path, body) {
    const r = await fetch(base + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
    return j;
  }

  async function lead(d) {
    if (base) return toServer('/api/leads', d);
    const id = 'ZV-' + new Date().toISOString().slice(0, 10).replace(/-/g, '') + '-' + Math.random().toString(16).slice(2, 8).toUpperCase();
    await put('leads', { ...d, id, received: new Date().toISOString(), store: 'browser' });
    return { id, received: new Date().toISOString() };
  }

  async function cert(d) {
    const c = certify(d);
    if (base) return toServer('/api/certifications', { ...d, _precomputed: null }).catch(() => c);
    await put('certs', { ...c, store: 'browser' });
    return c;
  }

  async function listLeads() {
    if (base) return (await toServer('/api/leads?token=' + (localStorage.getItem('zv-token') || 'dev-token-change-me'))).leads;
    return (await all('leads')).sort((a, b) => (b.received || '').localeCompare(a.received || ''));
  }

  async function listCerts() {
    if (base) return (await toServer('/api/certifications')).certs;
    return (await all('certs')).sort((a, b) => (b.issued || '').localeCompare(a.issued || ''));
  }

  window.ZV = {
    RATES, WORKFLOW, PLATFORM, fnv, quote, simulate, certify,
    fetchPlatform, verifyLabel, payloadOf,
    lead, cert, listLeads, listCerts,
    mode: () => (base ? 'server' : 'browser'),
    money: n => '¥' + Math.round(n).toLocaleString('en-US'),
    pct: n => (n >= 0 ? '' : '-') + Math.abs(n).toFixed(1) + '%'
  };
})();
