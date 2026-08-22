// Refuse documentation that still describes a plan we no longer follow.
//
// Written because HANDOFF.md carried TWO plans at once: a current findings section and, further
// down and longer, the superseded one. A reader landing on the stale half would have started on
// an AST/text-to-SQL step for a system that no longer generates SQL. Nothing caught it, because
// nothing was checking prose against the decisions the repo had already made.
//
// The rule: a RETIRED term may appear only inside a line that also marks it retired.
//
// usage: node scripts/check-docs.mjs [--selftest]
import { readFileSync } from 'node:fs';

const DOCS = ['HANDOFF.md', 'README.md', 'docs/PM-CHECKLIST.md', 'docs/PROPOSAL.md', 'docs/GRAIN.md'];

// Each entry: what was retired, and why — so a future reader can tell whether to revive it.
const RETIRED = [
  { term: '2xh6-psuq', why: 'shares no field with the spine; current_phase replaces it' },
  { term: 'project_schedules', why: 'the local name for 2xh6-psuq' },
  { term: 'Spider 2.0', why: 'a text-to-SQL benchmark; we no longer generate SQL' },
  { term: 'BookSQL', why: 'same' },
  { term: 'faithfulness grader', why: 'graded a narration against an AST; there is no AST now' },
  { term: 'PNS', why: 'a status value from the dropped dataset; real phases are Construction, (Pending), ...' },
  { term: /\bE[1-8]\b/, why: 'the eight-eval numbering; the plan is four checks' },
];

// Exemption is SECTION-scoped, not line-scoped. A section whose heading marks the subject
// retired is a record of what we measured and rejected -- annotating every line inside it
// would be noise, and deleting it would lose the evidence.
const MARKS_RETIRED = /DROPPED|dropped|retired|superseded|no longer|~~|rejected|NOT used|not used|unused/;
const IS_HEADING = /^#{1,6}\s/;   // markdown headings only — bold text is not a section

export function checkDocs(read) {
  const bad = [];
  for (const file of DOCS) {
    let text;
    try { text = read(file); } catch { continue; }
    let sectionExempt = false;
    text.split('\n').forEach((line, n) => {
      if (IS_HEADING.test(line)) sectionExempt = MARKS_RETIRED.test(line);
      if (sectionExempt || MARKS_RETIRED.test(line)) return;
      for (const { term, why } of RETIRED) {
        const hit = term instanceof RegExp ? term.test(line) : line.includes(term);
        if (hit) bad.push(`${file}:${n + 1} still instructs with "${term}" — ${why}`);
      }
    });
  }
  return bad;
}

const read = f => readFileSync(f, 'utf8');

if (process.argv.includes('--selftest')) {
  // Each mutation reintroduces a retired term as an instruction, not as a note.
  const CLEAN = 'This project runs four checks over the spine.\n';
  const base = () => CLEAN;
  const inject = (target, line) => f => (f === target ? line : CLEAN);
  const cases = [
    ['a dropped dataset is named as usable',
     inject('HANDOFF.md', 'Pull 2xh6-psuq and join it on fms_id.\n')],
    ['a retired benchmark returns',
     inject('docs/PM-CHECKLIST.md', 'Score the gold set with Spider 2.0.\n')],
    ['the old eval numbering returns',
     inject('README.md', 'Start with E7, the duplicate check.\n')],
  ];
  let ok = true;
  for (const [name, reader] of cases) {
    const found = checkDocs(reader);
    const caught = found.length > 0;
    console.log(`${caught ? 'caught  ' : 'MISSED  '} ${name}${caught ? ` -> ${found[0]}` : ''}`);
    if (!caught) ok = false;
  }
  // the inverse: a clean baseline must be silent, and so must a retirement section
  for (const [name, reader] of [
    ['a clean doc set stays quiet', base],
    ['a retired term inside a retirement note stays quiet',
     inject('HANDOFF.md', '| ~~2xh6-psuq~~ | DROPPED — no shared field |\n')],
    ['a retired term under a retirement HEADING stays quiet',
     inject('docs/GRAIN.md', '## project_schedules — DROPPED\n\nIt carries PNS and no fms_id.\n')],
  ]) {
    const quiet = checkDocs(reader).length === 0;
    console.log(`${quiet ? 'caught  ' : 'MISSED  '} ${name}`);
    if (!quiet) ok = false;
  }
  console.log(ok ? '\nSELFTEST PASS - every mutation was caught, and the exemption holds'
                 : '\nSELFTEST FAIL');
  process.exitCode = ok ? 0 : 1;
} else {
  const bad = checkDocs(read);
  if (bad.length) { console.log('FAIL:\n  ' + bad.join('\n  ')); process.exitCode = 1; }
  else console.log(`PASS - ${DOCS.length} docs carry no retired instruction`);
}
