// Pull the NYC Open Data capital-projects tables we build on. No auth, no key, no deps.
// usage: node scripts/pull.mjs [reporting_period]   default 202605
import { writeFileSync, mkdirSync } from 'node:fs';

const HOST = 'https://data.cityofnewyork.us/resource';
const PERIOD = process.argv[2] ?? '202605';

const SETS = [
  { id: 'fb86-vt7u', name: 'budget_and_schedule',
    what: 'the bridge — budget, spend, phase, schedule, agency. Carries BOTH fms_id and pid.',
    where: `reporting_period='${PERIOD}'` },
  { id: 'qj5n-h5qp', name: 'spend_history',
    what: 'monthly snapshots. earliest = original budget; budget_variance = delta vs prior month.',
    where: null },
];

async function pull({ id, name, where }) {
  const rows = [];
  const LIMIT = 50000;               // Socrata's $limit DEFAULTS TO 1000. Never rely on the default.
  for (let offset = 0; ; offset += LIMIT) {
    const u = new URL(`${HOST}/${id}.json`);
    u.searchParams.set('$limit', LIMIT);
    u.searchParams.set('$offset', offset);
    if (where) u.searchParams.set('$where', where);
    const page = await (await fetch(u)).json();
    if (!Array.isArray(page)) throw new Error(`${id}: ${JSON.stringify(page).slice(0, 300)}`);
    rows.push(...page);
    process.stdout.write(`  ${name}: ${rows.length} rows\r`);
    if (page.length < LIMIT) break;
  }
  mkdirSync('data', { recursive: true });
  writeFileSync(`data/${name}.json`, JSON.stringify(rows));
  console.log(`  ${name}: ${rows.length} rows -> data/${name}.json`);
  return rows.length;
}

console.log(`pulling NYC capital projects, reporting_period=${PERIOD}`);
for (const s of SETS) await pull(s);
console.log('done.');
