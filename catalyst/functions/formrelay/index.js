'use strict';

/**
 * Symm form relay (Zoho Catalyst, Advanced I/O).
 * Native forms on the site POST here; we forward each submission into the
 * matching Zoho form's public /records endpoint, so all downstream Zoho
 * automation (Books estimate, notifications, customer email) keeps firing.
 *
 * Field naming: native inputs use the Zoho field link-names (see forms/FORM-MAPPING.md).
 * Composite fields arrive flat as Name_First / Address_City / ... and are
 * re-nested here into the objects Zoho expects.
 *
 * Catalyst Advanced I/O calls module.exports as (req, res); an Express app is
 * exactly such a handler, so exporting the app works directly.
 */

const express = require('express');
const app = express();

// Read the raw body as text (any content-type). The browser sends submissions
// as a CORS-safe "simple request" (text/plain) so no OPTIONS preflight is
// triggered — Catalyst's gateway answers preflights itself without CORS headers,
// so we avoid them entirely. We JSON.parse the body ourselves below.
app.use(express.text({ type: '*/*' }));
function parseBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  try { return JSON.parse(req.body || '{}'); } catch (_) { return {}; }
}

const ORG = 'cropdefense1';

// Map the public form key -> Zoho form name + formperma id.
const FORMS = {
  contact:  { name: 'SymmContact',  perma: '1hrbP4thHbSxXEX3-FV7AlaGVgvzE0DqhXMBYhuHSJw' },
  trial:    { name: 'SymmTrial',    perma: '8hf5iDh9YFVKAO2yZqR-sJRjmV7zqbozDNPH1-1WXww' },
  checkout: { name: 'SymmCheckout', perma: 'MLs4KdlpWZLP2sGA71KvakzyO3DIy44s8VrgA4_e2FU' },
};

// Fields Zoho stores as numbers.
const NUMERIC = new Set(['Number', 'Number1']);

// Origins allowed to call the relay (the live site + local preview).
const ALLOWED_ORIGINS = [
  'https://symmbiotic.com',
  'https://www.symmbiotic.com',
  'https://nstock-ky.github.io',
  'http://localhost:8000',
];

function applyCors(req, res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.includes(origin)) res.set('Access-Control-Allow-Origin', origin);
  res.set('Vary', 'Origin');
  res.set('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.set('Access-Control-Allow-Headers', 'Content-Type');
}

// Flat native fields -> nested Zoho JSON payload.
function buildPayload(body) {
  const out = {};
  for (const [k, v] of Object.entries(body || {})) {
    if (k === 'form' || k === 'hp' || v === undefined || v === null || v === '') continue;
    if (k === 'Checkbox') { out.Checkbox = Array.isArray(v) ? v : [v]; continue; }
    const m = k.match(/^(Name|Address)_/);
    if (m) { const p = m[1]; (out[p] = out[p] || {})[k] = v; continue; }
    out[k] = NUMERIC.has(k) ? Number(v) : v;
  }
  return out;
}

app.options('/:form', (req, res) => { applyCors(req, res); res.status(204).end(); });

app.post('/:form', async (req, res) => {
  applyCors(req, res);
  const form = FORMS[req.params.form];
  if (!form) return res.status(400).json({ ok: false, error: 'unknown form' });

  const body = parseBody(req);

  // Honeypot: bots fill the hidden "hp" field. Pretend success, store nothing.
  if (body && body.hp) return res.json({ ok: true });

  const formUrl = `https://forms.zohopublic.com/${ORG}/form/${form.name}/formperma/${form.perma}`;
  const payload = buildPayload(body);

  try {
    // Prime a session cookie by loading the form first (mirrors a real browser).
    let cookie = '';
    try {
      const g = await fetch(formUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      const sc = g.headers.get('set-cookie');
      if (sc) cookie = sc.split(/,(?=[^;]+=)/).map((s) => s.split(';')[0].trim()).join('; ');
    } catch (_) { /* non-fatal */ }

    const r = await fetch(`${formUrl}/records`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': formUrl,
        'User-Agent': 'Mozilla/5.0',
        ...(cookie ? { Cookie: cookie } : {}),
      },
      body: JSON.stringify(payload),
    });
    const text = await r.text();
    if (!r.ok) return res.status(502).json({ ok: false, error: `zoho ${r.status}`, detail: text.slice(0, 300) });
    return res.json({ ok: true });
  } catch (e) {
    return res.status(500).json({ ok: false, error: String(e) });
  }
});

module.exports = app;
