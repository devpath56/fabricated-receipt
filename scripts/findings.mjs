// The findings that decide the build plan. Every number the deck and HANDOFF quote about
// joinability, job status and phase quality is printed here, from the pulled data.
//
// Written because two datasets were carried in the plan for days on the assumption that they
// joined to the key table. They do not share a single field with it.
//
// usage: node scripts/findings.mjs   (run scripts/pull.mjs first)
import { readFileSync } from 'node:fs';

const PERIOD = process.argv[2] ?? '202605';
const load = f => JSON.parse(readFileSync('data/' + f + '.json', 'utf8'));
const usd = n => '$' + Math.round(n).toLocaleString('en-US');
const norm = s => String(s ?? '').replace(/[()]/g, '').trim().toLowerCase();

const bsAll = load('budget_and_schedule');
const bs = bsAll.filter(r => r.reporting_period === PERIOD);
const ps = load('project_schedules');
const aw = load('capital_awards');

console.log(`\n=== FINDING 1 — what can actually join (period ${PERIOD}) ===`);
const keysOf = rows => new Set(Object.keys(rows[0] ?? {}));
const bk = keysOf(bs);
for (const [name, rows] of [['project_schedules · 2xh6-psuq', ps], ['capital_awards · n6ej-pebd', aw]]) {
  const shared = [...keysOf(rows)].filter(k => bk.has(k));
  console.log(`  fb86-vt7u <-> ${name}: ${shared.length ? shared.join(', ') : 'NO SHARED FIELD — cannot join'}`);
}
console.log('  => only qj5n-h5qp joins, on fms_id. The other two are standalone corpora.');

console.log('\n=== FINDING 2 — job status needs no join at all ===');
const phases = new Map();
for (const r of bs) phases.set(r.current_phase, (phases.get(r.current_phase) ?? 0) + 1);
console.log(`  fb86-vt7u carries current_phase on the SAME row as fms_id and pid.`);
console.log(`  ${phases.size} distinct values across ${bs.length} rows. Top:`);
for (const [v, n] of [...phases].sort((a, b) => b[1] - a[1]).slice(0, 6))
  console.log(`    ${String(v).padEnd(26)} ${n}`);

console.log('\n=== FINDING 3 — the status enum is aliased, like the vendor names ===');
const byNorm = new Map();
for (const v of phases.keys()) {
  const k = norm(v);
  if (!byNorm.has(k)) byNorm.set(k, []);
  byNorm.get(k).push(v);
}
const aliased = [...byNorm.values()].filter(a => a.length > 1);
console.log(`  ${phases.size} raw values -> ${byNorm.size} after stripping parentheses and case.`);
console.log(`  ${aliased.length} phases are written more than one way:`);
for (const a of aliased) console.log(`    ${a.join('   |   ')}`);
console.log('  => same failure class as vendor aliasing, in the field check 4 depends on.');

console.log('\n=== FINDING 4 — the dead-job signal is real ===');
const dead = bs.filter(r => /completed|cancelled/i.test(r.current_phase ?? ''));
console.log(`  ${dead.length} rows are Completed or Cancelled, carrying ` +
  usd(dead.reduce((s, r) => s + Number(r.total_budget ?? 0), 0)));
console.log('  => check 4 has a genuine positive class without any synthetic data.');

console.log('\n=== FINDING 5 — one key, conflicting answers. This is check 4s real difficulty ===');
const byFms = new Map();
for (const r of bs) {
  if (!r.fms_id) continue;
  if (!byFms.has(r.fms_id)) byFms.set(r.fms_id, new Set());
  byFms.get(r.fms_id).add(norm(r.current_phase));
}
const conflict = [...byFms].filter(([, s]) => s.size > 1);
const cDollars = bs.filter(r => (byFms.get(r.fms_id)?.size ?? 0) > 1)
  .reduce((s, r) => s + Number(r.total_budget ?? 0), 0);
console.log(`  ${byFms.size} distinct fms_id across ${bs.length} rows.`);
console.log(`  ${conflict.length} of them return MORE THAN ONE phase, carrying ${usd(cDollars)}.`);
for (const [f, s] of conflict.slice(0, 3)) console.log(`    ${f.padEnd(14)} ${[...s].join(' / ')}`);
console.log('  => "what is the status of this PO" has no single answer for these.');
console.log('     Check 4 must detect the conflict and COMMENT, never pick one.\n');

console.log('=== BUILD PLAN CONSEQUENCES ===');
const rows = [
  ['1 Intake', 'no real data anywhere', 'fully synthetic — documents + missing-field labels'],
  ['2 Vendor', 'n6ej-pebd names are real', 'synthetic invoices; vendor master derived from the real corpus'],
  ['3 Paid before', 'fms_id values are real', 'synthetic ledger; po_id drawn from real keys'],
  ['4 Job status', 'current_phase is real', 'NO synthetic data. Normalise the enum, and COMMENT on the 96 conflicts'],
];
for (const [c, have, todo] of rows) console.log(`  ${c.padEnd(15)} ${have.padEnd(30)} ${todo}`);
console.log('');
