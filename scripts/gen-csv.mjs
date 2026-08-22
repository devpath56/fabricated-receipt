// Emit the three tables the four checks run on, as CSV.
//
// GROUNDING RULE, and it is the whole point: every key, every phase and every vendor spelling is a
// REAL published value. Only the invoice layer is generated, and each generated row points at a
// real budget line. Nothing here invents a project, a key or a company name.
//
//   contracts.csv  100% real   fb86-vt7u, finance view   (+ one generated column: vendor_id)
//   erp.csv        100% real   fb86-vt7u, project view    (+ one DERIVED column: job_open_for_charges)
//   vendors.csv    derived     canonical + alias sets from n6ej-pebd's real payee spellings
//   invoices.csv   generated   every FK real; ground-truth labels on every row
//
// Seeded, so two runs produce byte-identical files. An eval whose input changes under it is not an
// eval (Math.random would make every measured rate unreproducible).
//
// usage: node scripts/gen-csv.mjs [--invoices N] [--seed N] [--period YYYYMM]

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const PERIOD  = arg('period', '202605');
const N_INV   = Number(arg('invoices', 600));
const SEED    = Number(arg('seed', 42));

// DECLARED rates. Precision and recall are meaningless against a rate nobody wrote down.
const RATES = { duplicate: 0.08, alias: 0.35, missing_field: 0.10, dead_job: 0.12 };

// ── seeded RNG (mulberry32) ───────────────────────────────────────────────────
let _s = SEED >>> 0;
const rnd = () => { _s |= 0; _s = _s + 0x6D2B79F5 | 0;
  let t = Math.imul(_s ^ _s >>> 15, 1 | _s);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
  return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const pick = a => a[Math.floor(rnd() * a.length)];
const chance = p => rnd() < p;

const csv = rows => rows.map(r => r.map(v => {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}).join(',')).join('\n') + '\n';

const norm = s => String(s ?? '').replace(/[()]/g, '').trim().toLowerCase().replace(/\s+/g, ' ');
const normVendor = s => String(s ?? '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
  .replace(/\b(inc|llc|corp|corporation|company|co|the|of|for|and|society|association|assn)\b/g, ' ')
  .replace(/\s+/g, ' ').trim();

// ── real sources ──────────────────────────────────────────────────────────────
const bs = JSON.parse(readFileSync('data/budget_and_schedule.json', 'utf8'))
  .filter(r => r.reporting_period === PERIOD);
const awards = JSON.parse(readFileSync('data/capital_awards.json', 'utf8'));
mkdirSync('data', { recursive: true });

// ── TABLE 4 · ERP DB — the project view. Real, plus one derived column. ───────
const DEAD = /completed|cancelled/i;
const erpRows = bs.map(r => [
  (r.pid ?? '').trim(), r.fms_id ?? '', r.current_phase ?? '', norm(r.current_phase),
  r.agency_project_name ?? r.fms_project_name ?? '', r.forecast_completion ?? '',
  DEAD.test(r.current_phase ?? '') ? 'false' : 'true',
]);
writeFileSync('data/erp.csv', csv([
  ['pid', 'fms_id', 'current_phase', 'current_phase_norm', 'agency_project_name',
   'forecast_completion', 'job_open_for_charges'], ...erpRows]));

// ── TABLE 3 · Contract DB — the finance view. Real, plus a generated vendor_id. ─
// vendor_id is the one edge nothing public supplies: no NYC dataset ties a payee to a budget line.
const contractRows = bs.map(r => [
  r.fms_id ?? '', r.budget_line ?? '', r.total_budget ?? '', r.spend_to_date ?? '',
  r.managing_agency ?? '', r.sponsor_agency ?? '', '',   // vendor_id filled after vendors exist
]);

// ── vendors — canonical + REAL alias spellings from n6ej-pebd ─────────────────
const clusters = new Map();
for (const a of awards) {
  const k = normVendor(a.organization);
  if (!k) continue;
  if (!clusters.has(k)) clusters.set(k, new Set());
  clusters.get(k).add(a.organization);
}
const vendors = [...clusters.entries()].map(([k, set], i) => {
  const names = [...set].sort((x, y) => y.length - x.length);   // longest = most complete form
  return { vendor_id: 'V' + String(i + 1).padStart(4, '0'), key: k,
           canonical: names[0], aliases: names };
});
const multi = vendors.filter(v => v.aliases.length > 1);       // the 48 real alias clusters
writeFileSync('data/vendors.csv', csv([
  ['vendor_id', 'canonical_name', 'alias_count', 'aliases'],
  ...vendors.map(v => [v.vendor_id, v.canonical, v.aliases.length, v.aliases.join(' | ')])]));

// assign 1–3 vendors per budget line — the generated finance edge
// Draw roughly half the budget lines' vendors from the 48 that carry MORE THAN ONE real
// spelling. Without this bias only ~5% of vendors can alias at all, the duplicate branch
// almost never fires, and the declared rates become unreachable — a generator quietly
// missing its own declared rate is the exact failure this project exists to catch.
const vendorOf = new Map();
const drawVendor = () => (multi.length && chance(0.5) ? pick(multi) : pick(vendors));
for (const r of bs) {
  if (!r.fms_id || vendorOf.has(r.fms_id)) continue;
  const k = 1 + Math.floor(rnd() * 3);
  vendorOf.set(r.fms_id, Array.from({ length: k }, drawVendor));
}
contractRows.forEach((row, i) => {
  const v = vendorOf.get(bs[i].fms_id);
  row[6] = v ? v.map(x => x.vendor_id).join(' ') : '';
});
writeFileSync('data/contracts.csv', csv([
  ['fms_id', 'budget_line', 'total_budget', 'spend_to_date', 'managing_agency',
   'sponsor_agency', 'vendor_ids'], ...contractRows]));

// ── TABLE 2 · Invoice DB — generated, every FK real ───────────────────────────
const byFms = new Map();
for (const r of bs) if (r.fms_id && !byFms.has(r.fms_id)) byFms.set(r.fms_id, r);
const live = [...byFms.values()].filter(r => !DEAD.test(r.current_phase ?? ''));
const dead = [...byFms.values()].filter(r =>  DEAD.test(r.current_phase ?? ''));

const invoices = [];
let n = 0;
const mkInvoice = (row, vendor, opts = {}) => {
  const useAlias = opts.alias ?? chance(RATES.alias);
  const spelling = useAlias && vendor.aliases.length > 1
    ? pick(vendor.aliases.filter(a => a !== vendor.canonical)) : vendor.canonical;
  const budget = Number(row.total_budget ?? 0) || 250000;
  const id = 'INV-' + String(++n).padStart(5, '0');
  return {
    invoice_id: id,
    po_id: row.fms_id,
    vendor_id: vendor.vendor_id,
    vendor_name: spelling,
    amount: opts.amount ?? Math.round(budget * (0.01 + rnd() * 0.06) * 100) / 100,
    period: opts.period ?? PERIOD,
    status: opts.status ?? (chance(0.55) ? 'paid' : chance(0.6) ? 'pending' : 'denied'),
    submitted_at: `${PERIOD.slice(0, 4)}-${PERIOD.slice(4)}-${String(1 + Math.floor(rnd() * 28)).padStart(2, '0')}`,
    doc_uri: `docs/invoices/${id}.pdf`,
    missing_field: chance(RATES.missing_field)
      ? pick(['po_id', 'amount', 'period', 'vendor_name']) : 'none',
    label_is_duplicate: 'false',
    label_dead_job: DEAD.test(row.current_phase ?? '') ? 'true' : 'false',
  };
};

while (invoices.length < N_INV) {
  const row = chance(RATES.dead_job) && dead.length ? pick(dead) : pick(live);
  const vendor = pick(vendorOf.get(row.fms_id) ?? vendors);
  const inv = mkInvoice(row, vendor);
  invoices.push(inv);

  // PLANTED DUPLICATE: same PO, amount and period, DIFFERENT spelling of the same vendor.
  // A search on the literal name misses it. Only check 2's resolution surfaces it — that is the demo.
  if (chance(RATES.duplicate) && invoices.length < N_INV) {
    // if this vendor cannot alias, re-draw one that can — the duplicate must still be planted
    const dv = vendor.aliases.length > 1 ? vendor : (multi.length ? pick(multi) : vendor);
    if (dv !== vendor) { inv.vendor_id = dv.vendor_id; inv.vendor_name = dv.canonical; }
    const dup = mkInvoice(row, dv, { alias: true,
      amount: inv.amount, period: inv.period, status: 'pending' });
    inv.status = 'paid';
    dup.label_is_duplicate = 'true';
    dup.missing_field = 'none';
    invoices.push(dup);
  }
}

const HEAD = ['invoice_id', 'po_id', 'vendor_id', 'vendor_name', 'amount', 'period', 'status',
              'submitted_at', 'doc_uri', 'missing_field', 'label_is_duplicate', 'label_dead_job'];
writeFileSync('data/invoices.csv', csv([HEAD, ...invoices.map(i => HEAD.map(h => i[h]))]));

// ── what was planted, stated ─────────────────────────────────────────────────
const count = (f, v) => invoices.filter(i => i[f] === v).length;
console.log(`seed=${SEED}  period=${PERIOD}  (re-runs are byte-identical)\n`);
console.log('  data/erp.csv        ' + String(erpRows.length).padStart(5) + ' rows   100% real (fb86-vt7u) + job_open_for_charges derived');
console.log('  data/contracts.csv  ' + String(contractRows.length).padStart(5) + ' rows   100% real (fb86-vt7u) + vendor_ids generated');
console.log('  data/vendors.csv    ' + String(vendors.length).padStart(5) + ` rows   derived from n6ej-pebd — ${multi.length} carry >1 real spelling`);
console.log('  data/invoices.csv   ' + String(invoices.length).padStart(5) + '  rows   generated; every po_id and vendor_name real\n');
console.log('PLANTED, declared:');
console.log(`  duplicates                 ${count('label_is_duplicate', 'true')}   (rate ${RATES.duplicate})`);
console.log(`  invoices with a gap        ${invoices.length - count('missing_field', 'none')}   (rate ${RATES.missing_field})`);
console.log(`  invoices on a dead job     ${count('label_dead_job', 'true')}   (rate ${RATES.dead_job})`);
console.log(`  non-canonical spellings    ${invoices.filter(i => {
  const v = vendors.find(x => x.vendor_id === i.vendor_id);
  return v && i.vendor_name !== v.canonical; }).length}   (rate ${RATES.alias})`);
const achieved = {
  duplicate: count('label_is_duplicate', 'true') / invoices.length,
  missing_field: (invoices.length - count('missing_field', 'none')) / invoices.length,
  dead_job: count('label_dead_job', 'true') / invoices.length,
  alias: invoices.filter(i => { const v = vendors.find(x => x.vendor_id === i.vendor_id);
    return v && i.vendor_name !== v.canonical; }).length / invoices.length,
};
const off = Object.entries(RATES).filter(([k, want]) =>
  Math.abs(achieved[k] - want) / want > 0.35);
if (off.length) {
  console.log('\nRATE MISS — the generator did not achieve what it declared:');
  for (const [k, want] of off)
    console.log(`  ${k}: declared ${want}, achieved ${achieved[k].toFixed(3)}`);
  console.log('  A declared rate the generator misses gives every eval a wrong denominator.');
  process.exitCode = 1;
} else console.log('\nRATES OK — every declared rate achieved within 35% relative.');

console.log(`\n  erp.csv keys with conflicting phase: ${
  (() => { const m = new Map();
    for (const r of bs) { if (!r.fms_id) continue;
      if (!m.has(r.fms_id)) m.set(r.fms_id, new Set()); m.get(r.fms_id).add(norm(r.current_phase)); }
    return [...m.values()].filter(s => s.size > 1).length; })()}  — real, not planted\n`);
