/* ZeroCarbon Verify — site behaviour: quote model, lead capture, small helpers */
(function () {
  'use strict';

  /* ---------------- configuration ---------------- */
  // The static site works with no backend; point this at the API when it is running.
  const API_BASE = (function () {
    const q = new URLSearchParams(location.search).get('api');
    if (q) { localStorage.setItem('zv-api', q); return q.replace(/\/+$/, ''); }
    return (localStorage.getItem('zv-api') || 'http://127.0.0.1:8099').replace(/\/+$/, '');
  })();

  /* ---------------- quote model (identical to server/app.py) ---------------- */
  const RATES = {
    pcf_site: 28000,        // first-year verification, per site
    surveillance: 12000,    // annual surveillance, per site
    label_batch: 40,        // per batch label, verifier share
    baseline: 6000,         // baseline co-signing, per exercise
    grade_site: 4000,       // evidence grade assessment, per site per year
    ledger: 8000,           // ledger integrity, per exercise
    mrv_site: 20000,        // MRV audit, per site
    travel_day: 1200,       // per day beyond the first two
    travel_included: 2
  };

  function quote({ sites = 1, batches = 0, addons = [], travelDays = 0 }) {
    sites = Math.max(1, Math.min(50, parseInt(sites, 10) || 1));
    batches = Math.max(0, parseInt(batches, 10) || 0);
    travelDays = Math.max(0, Math.min(60, parseInt(travelDays, 10) || 0));
    const lines = [];
    const push = (label, qty, unit, amount) => lines.push({ label, qty, unit, amount: Math.round(amount) });

    push('Product carbon footprint (year 1)', sites, 'site', RATES.pcf_site * sites);
    push('Annual surveillance', sites, 'site / yr', RATES.surveillance * sites);
    if (batches > 0) push('Label issuance', batches, 'batch', RATES.label_batch * batches);
    if (addons.includes('baseline')) push('Baseline co-signing', 1, 'exercise', RATES.baseline);
    if (addons.includes('grade')) push('Evidence grade assessment', sites, 'site / yr', RATES.grade_site * sites);
    if (addons.includes('ledger')) push('Ledger integrity assurance', 1, 'exercise', RATES.ledger);
    if (addons.includes('mrv')) push('MRV system audit', sites, 'site', RATES.mrv_site * sites);
    const extraTravel = Math.max(0, travelDays - RATES.travel_included);
    if (extraTravel > 0) push('Additional travel days', extraTravel, 'day', RATES.travel_day * extraTravel);

    const total = lines.reduce((a, l) => a + l.amount, 0);
    return { lines, total, currency: 'CNY', recurringNote: 'Surveillance and grades recur annually.' };
  }

  function fmtMoney(n) { return '¥' + Math.round(n).toLocaleString('en-US'); }

  /* ---------------- quote UI ---------------- */
  function bindQuote() {
    const form = document.getElementById('quoteForm');
    if (!form) return;
    const out = document.getElementById('q-out');
    const calc = () => {
      const addons = Array.from(document.getElementById('q-services').selectedOptions).map(o => o.value);
      const q = quote({
        sites: document.getElementById('q-sites').value,
        batches: document.getElementById('q-batches').value,
        addons,
        travelDays: document.getElementById('q-travel').value
      });
      const rows = q.lines.map(l =>
        `  ${l.label.padEnd(34, '.')} ${String(l.qty).padStart(6)} × ${fmtMoney(l.amount / (l.qty || 1))}  =  ${fmtMoney(l.amount)}`
      ).join('\n');
      out.textContent =
        `INDICATIVE QUOTE — ${new Date().toISOString().slice(0, 10)}\n` +
        '─'.repeat(72) + '\n' + rows + '\n' + '─'.repeat(72) +
        `\n${'TOTAL (year 1)'.padEnd(70)} ${fmtMoney(q.total)}\n\n` +
        `Note: ${q.recurringNote} Excludes taxes and client-side data preparation.\n` +
        `Method: see /api/quote on the verification platform.`;
    };
    document.getElementById('q-calc').addEventListener('click', calc);
    ['q-sites', 'q-batches', 'q-travel'].forEach(id =>
      document.getElementById(id).addEventListener('input', calc));
    document.getElementById('q-services').addEventListener('change', calc);
    calc();
  }

  /* ---------------- lead capture ---------------- */
  function bindLead() {
    const btn = document.getElementById('leadSend');
    if (!btn) return;
    const out = document.getElementById('leadOut');

    function read() {
      return {
        name: document.getElementById('f-name').value.trim(),
        company: document.getElementById('f-company').value.trim(),
        email: document.getElementById('f-email').value.trim(),
        role: document.getElementById('f-role').value,
        scope: document.getElementById('f-scope').value,
        message: document.getElementById('f-message').value.trim(),
        consent: document.getElementById('f-consent').checked,
        page: location.pathname,
        ts: new Date().toISOString()
      };
    }

    function validate(d) {
      const errs = [];
      if (!d.name) errs.push('name');
      if (!d.company) errs.push('company');
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(d.email)) errs.push('a valid email');
      if (!d.consent) errs.push('consent');
      return errs;
    }

    function show(text, ok) {
      out.style.display = 'block';
      out.style.borderLeft = '3px solid ' + (ok ? '#00958f' : '#b4761a');
      out.textContent = text;
    }

    btn.addEventListener('click', async () => {
      const d = read();
      const errs = validate(d);
      if (errs.length) { show('Please provide: ' + errs.join(', ') + '.', false); return; }

      btn.disabled = true;
      btn.textContent = 'Sending…';
      try {
        const r = await fetch(API_BASE + '/api/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(d)
        });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
        show(`Enquiry received. Reference ${body.id}.\nWe reply within two working days.\n` +
             `A copy was written to the verification platform's lead log.`, true);
        document.getElementById('leadForm').reset();
      } catch (e) {
        // no backend (static hosting): give the user something they can still send
        const mail = 'mailto:hello@zerocoffee.org' +
          '?subject=' + encodeURIComponent('Verification enquiry — ' + d.company) +
          '&body=' + encodeURIComponent(
            `Name: ${d.name}\nCompany: ${d.company}\nEmail: ${d.email}\nRole: ${d.role}\n` +
            `Service: ${d.scope}\n\n${d.message}\n`);
        show('The verification platform is not reachable from this page (' + e.message + ').\n' +
             'Your enquiry is ready to send as email — click below.', false);
        const a = document.createElement('a');
        a.className = 'btn btn-primary btn-sm';
        a.href = mail;
        a.textContent = 'Open email draft';
        a.style.marginTop = '12px';
        out.appendChild(document.createElement('br'));
        out.appendChild(a);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Send enquiry';
      }
    });
  }

  /* ---------------- small helpers ---------------- */
  function markCurrentNav() {
    const here = location.pathname.split('/').filter(Boolean)[0] || 'index.html';
    document.querySelectorAll('nav.main > .item > a').forEach(a => {
      const href = a.getAttribute('href') || '';
      if (href.startsWith(here) && here !== 'index.html') a.parentElement.classList.add('on');
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindQuote();
    bindLead();
    markCurrentNav();
  });
})();
