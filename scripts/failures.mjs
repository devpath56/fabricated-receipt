// Reproduce the two failures this project exists to catch, on real public money.
// Both are properties of NYC's own published data. Neither is fabricated.
// usage: node scripts/failures.mjs        (run scripts/pull.mjs first)
import { readFileSync } from 'node:fs';

// Baselines measured 2026-08-21 against reporting_period 202605.
// If these drift, the DATA changed — say so out loud rather than quietly re-baselining.
const BASELINE = {
  projects: 3063, fanout_projects: 207, surplus_rows: 382,
  fanout_dollars: 9933414291, nopid_rows: 2356, nopid_fms: 2343, nopid_dollars: 64836845710,
};

const rows = JSON.parse(readFileSync('data/budget_and_schedule.json', 'utf8'));
const usd = n => '$' + Math.round(n).toLocaleString('en-US');

// ── failure 1: the key fans out ────────────────────────────────────────────
// NYC's own description: "FMS IDs and agency projects don't always have a
// one-to-one relationship." A naive join on fms_id invents rows.
const byPid = new Map();
const nopidFms = new Set();
let nopidRows = 0, nopidDollars = 0;
for (const r of rows) {
  const b = Number(r.total_budget ?? 0);
  const pid = (r.pid ?? '').toString().trim();
  if (!pid) { nopidRows++; nopidDollars += b; nopidFms.add(r.fms_id); continue; }
  if (!byPid.has(pid)) byPid.set(pid, { fms: new Set(), dollars: 0 });
  const e = byPid.get(pid);
  e.fms.add(r.fms_id); e.dollars += b;
}

let fanoutProjects = 0, surplusRows = 0, fanoutDollars = 0, worst = ['', 0];
for (const [pid, e] of byPid) {
  if (e.fms.size > 1) {
    fanoutProjects++; surplusRows += e.fms.size - 1; fanoutDollars += e.dollars;
    if (e.fms.size > worst[1]) worst = [pid, e.fms.size];
  }
}

const withPid = [...byPid.values()].reduce((s, e) => s + e.dollars, 0);
const total = withPid + nopidDollars;

const out = [
  ['FAILURE 1 — the key fans out', ''],
  ['  projects', byPid.size],
  ['  projects with >1 fms_id', `${fanoutProjects} (${(100 * fanoutProjects / byPid.size).toFixed(1)}%)`],
  ['  surplus rows a naive join invents', surplusRows],
  ['  dollars on those projects', usd(fanoutDollars)],
  ['  worst project', `pid ${worst[0]} — ${worst[1]} fms_ids`],
  ['', ''],
  ['FAILURE 2 — the join drops a third of the money, silently', ''],
  ['  rows with no pid at all', nopidRows],
  ['  distinct fms_ids among them', nopidFms.size],
  ['  dollars on those rows', usd(nopidDollars)],
  ['  share of the period unjoinable', `${(100 * nopidDollars / total).toFixed(1)}%`],
  ['  what an inner join reports', usd(withPid)],
  ['  what is actually in the period', usd(total)],
  ['  errors raised', '0  <-- this is the bug'],
];
for (const [k, v] of out) console.log(k.padEnd(46), v);

// ── drift check ────────────────────────────────────────────────────────────
const seen = { projects: byPid.size, fanout_projects: fanoutProjects, surplus_rows: surplusRows,
  fanout_dollars: Math.round(fanoutDollars), nopid_rows: nopidRows, nopid_fms: nopidFms.size, nopid_dollars: Math.round(nopidDollars) };
const drift = Object.entries(BASELINE).filter(([k, v]) => seen[k] !== v);
console.log('');
if (!drift.length) console.log('BASELINE OK — matches the figures in the deck.');
else {
  console.log('BASELINE DRIFT — the deck quotes different numbers. Update BOTH, or say why:');
  for (const [k, v] of drift) console.log(`  ${k}: baseline ${v} -> now ${seen[k]}`);
  process.exitCode = 1;
}
