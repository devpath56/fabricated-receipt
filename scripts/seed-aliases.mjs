// Emit the vendor-alias gold-set SEED from real data. No fabrication: every cluster below is two
// or more spellings of one recipient that NYC itself published, in data/capital_awards.json.
// usage: node scripts/seed-aliases.mjs   (run scripts/pull.mjs first)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const rows = JSON.parse(readFileSync('data/capital_awards.json', 'utf8'));

// Deliberately CONSERVATIVE. Only punctuation, case, and legal/filler words are removed. Anything
// requiring a similarity threshold is left for the real resolver — a seed that guesses is a seed
// that teaches the wrong thing.
const STOP = /\b(inc|llc|corp|corporation|company|co|the|of|for|and|society|association|assn)\b/g;
const norm = s => String(s ?? '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ')
  .replace(STOP, ' ').replace(/\s+/g, ' ').trim();

const byKey = new Map();
let totalDollars = 0;
for (const r of rows) {
  const k = norm(r.organization);
  if (!k) continue;
  const d = Number(r.funding ?? 0);
  totalDollars += d;
  if (!byKey.has(k)) byKey.set(k, { key: k, variants: new Map(), dollars: 0, rows: 0 });
  const e = byKey.get(k);
  e.variants.set(r.organization, (e.variants.get(r.organization) ?? 0) + 1);
  e.dollars += d; e.rows++;
}

const clusters = [...byKey.values()]
  .filter(e => e.variants.size > 1)
  .map(e => ({ entity_key: e.key, variants: [...e.variants.keys()],
               spellings: e.variants.size, rows: e.rows, dollars: Math.round(e.dollars) }))
  .sort((a, b) => b.spellings - a.spellings || b.dollars - a.dollars);

const clusterDollars = clusters.reduce((s, c) => s + c.dollars, 0);
const seed = {
  source: 'NYC Open Data · Capital Awards · n6ej-pebd',
  url: 'https://data.cityofnewyork.us/d/n6ej-pebd',
  method: 'punctuation + case + legal-suffix normalisation ONLY. No fuzzy matching, no threshold.',
  status: 'SEED — hand-verify before using as ground truth. Recall is a lower bound: any alias pair '
        + 'that differs by more than punctuation is NOT in here and must be found by the resolver.',
  measured: {
    rows: rows.length,
    distinct_raw_names: new Set(rows.map(r => r.organization)).size,
    distinct_after_normalisation: byKey.size,
    clusters_with_multiple_spellings: clusters.length,
    dollars_in_those_clusters: clusterDollars,
    total_dollars: Math.round(totalDollars),
    pct_dollars_exposed: +(100 * clusterDollars / totalDollars).toFixed(1),
  },
  clusters,
};

mkdirSync('eval', { recursive: true });
writeFileSync('eval/vendor-aliases.seed.json', JSON.stringify(seed, null, 2));
console.log(`${clusters.length} clusters · $${clusterDollars.toLocaleString('en-US')} `
  + `(${seed.measured.pct_dollars_exposed}% of $${seed.measured.total_dollars.toLocaleString('en-US')})`);
for (const c of clusters.slice(0, 3)) console.log('  ', c.variants.join('  |  '));
