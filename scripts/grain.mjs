// Measure what one row actually IS in each table, instead of trusting the publisher's description.
// This is the deterministic check behind JTBD 2: "assert expected grain before execution."
// You cannot assert a grain nobody wrote down, and you should not write one down unmeasured.
// usage: node scripts/grain.mjs   (run scripts/pull.mjs first)
import { readFileSync } from 'node:fs';

const load = f => JSON.parse(readFileSync('data/' + f + '.json', 'utf8'));
const uniq = (rows, keys) => new Set(rows.map(r => keys.map(k => String(r[k] ?? '')).join(''))).size;

function report(name, rows, candidates) {
  console.log(name.padEnd(22) + ' rows=' + rows.length);
  for (const k of candidates) {
    const u = uniq(rows, k);
    const verdict = u === rows.length ? 'UNIQUE  ' : 'NOT uniq';
    console.log('   ' + verdict + ' ' + k.join(' + ').padEnd(56) + u);
  }
}

report('budget_and_schedule', load('budget_and_schedule'),
  [['fms_id'], ['pid'], ['fms_id', 'budget_line'], ['pid', 'fms_id', 'budget_line']]);

report('spend_history', load('spend_history'),
  [['fms_id'], ['fms_id', 'year_month_reported'], ['fms_id', 'year_month_reported', 'managing_agency']]);

report('capital_awards', load('capital_awards'),
  [['organization'], ['fiscal_year', 'organization', 'capital_project'],
   ['fiscal_year', 'organization', 'capital_project', 'community_district']]);

report('project_schedules', load('project_schedules'),
  [['project_building_identifier'], ['project_building_identifier', 'project_phase_name'],
   ['project_building_identifier', 'project_phase_name', 'project_type_']]);
