// Verify the deck's workflow figure without a browser: geometry, the step machine's
// references, and both themes. Written because the pane needs JS to render, so a file
// preview shows nothing and "it looked fine" is not available as evidence.
//
// Run with --selftest to prove the check can FAIL. A check that has never failed is a
// check nobody has tested (CF-067).
//
// usage: node scripts/check-deck.mjs [--selftest]
import { readFileSync } from 'node:fs';

const TOKEN_ONLY_IN_DARK = new Set(
  ['--rail', '--measure', '--r', '--f-display', '--f-body', '--f-mono', '--shadow']);

export function checkDeck(s) {
  const bad = [];

  // 1. EVERY figure is checked, not only the one this file was written for.
  //    A check that inspects a named subject silently skips the next one added.
  const svgs = [...s.matchAll(/<svg id="(\w+)"[^>]*?viewBox="0 0 (\d+) (\d+)"[\s\S]*?<\/svg>/g)];
  if (!svgs.length) return ['no svg with an id and a viewBox found'];
  for (const sv of svgs) {
    const id = sv[1], W = Number(sv[2]), H = Number(sv[3]), body = sv[0];
    for (const m of body.matchAll(/<rect[^>]*?x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/g)) {
      const [x, y, w, h] = m.slice(1).map(Number);
      if (x < 0 || y < 0 || x + w > W || y + h > H) bad.push(`#${id}: rect outside viewBox: ${x},${y},${w},${h}`);
    }
    for (const m of body.matchAll(/<text[^>]*?x="([\d.]+)" y="([\d.]+)"/g)) {
      const [x, y] = m.slice(1).map(Number);
      if (x < 0 || x > W || y < 0 || y > H) bad.push(`#${id}: text outside viewBox: ${x},${y}`);
    }
    for (const m of body.matchAll(/url\(#([\w-]+)\)/g))
      if (!new RegExp(`<marker id="${m[1]}"`).test(body)) bad.push(`#${id}: marker #${m[1]} referenced, never defined`);
  }
  const wfSvg = svgs.find(v => v[1] === 'wf');
  if (!wfSvg) return [...bad, 'workflow svg #wf not found'];
  const b = wfSvg[0];

  // 1b. every class an animation or state rule names must exist in the markup
  const allClasses = new Set();
  for (const m of s.matchAll(/class="([^"]+)"/g)) m[1].split(/\s+/).forEach(c => allClasses.add(c));
  const svgIds = svgs.map(v => v[1]);
  const cssRule = new RegExp(`#(${svgIds.join('|')})(?:\\.run)?\\s+\\.([\\w]+)`, 'g');
  for (const m of s.matchAll(cssRule))
    if (!allClasses.has(m[2])) bad.push(`css targets #${m[1]} .${m[2]}, absent from the markup`);

  // 2. every class the step machine names must exist in the markup
  const classes = new Set();
  for (const m of b.matchAll(/class="([^"]+)"/g)) m[1].split(/\s+/).forEach(c => classes.add(c));
  const wf = /var WF = \[([\s\S]*?)\n  \];/.exec(s);
  if (!wf) bad.push('step table WF not found');
  else {
    for (const m of wf[1].matchAll(/'(ph\d|halo[A-Z]|path[A-Za-z]+|term[A-Za-z]+)'/g))
      if (!classes.has(m[1])) bad.push(`step machine references .${m[1]}, absent from svg`);
  }

  // The spine is read once, here, and reused by the two clauses below.
  const spine = /<g class="spine">([\s\S]*?)<\/g>\s*\n\s*<g stroke/.exec(b);

  // 2b. EVERY phase in the spine must be reached by some step. The class check only
  //     proved that referenced classes exist -- it could not see a phase drawn on the
  //     figure and never lit, which reads to a viewer as the walkthrough being stuck.
  if (wf) {
    const drawn = new Set();
    if (spine) for (const m of spine[1].matchAll(/class="ph (ph\d)"/g)) drawn.add(m[1]);
    const reached = new Set([...wf[1].matchAll(/'(ph\d)'/g)].map(m => m[1]));
    for (const d of drawn) if (!reached.has(d))
      bad.push(`phase .${d} is drawn in #wf but no step ever activates it`);
  }

  // 2c. All three verdicts must be REACHABLE. A terminal drawn but never routed to
  //     is a promise the walkthrough silently fails to keep.
  if (wf) {
    for (const term of ['termAsk', 'termOk', 'termDeny']) {
      if (!b.includes(`class="term ${term}"`)) { bad.push(`terminal .${term} is not drawn in #wf`); continue; }
      if (!wf[1].includes(`'${term}'`)) bad.push(`terminal .${term} is drawn but no step routes to it`);
    }
    for (const path of ['pathAsk', 'pathOk', 'pathDeny'])
      if (!wf[1].includes(`'${path}'`)) bad.push(`path .${path} is drawn but no step activates it`);
  }

  // 3. the token stops on the spine must land on real phase centres
  // Derive the spine's geometry from the markup, never from constants that go stale
  // when the figure is redrawn. An empty centre set is itself a failure.
  const centres = new Set();
  if (!spine) bad.push('spine group not found in #wf');
  else for (const m of spine[1].matchAll(/<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"/g))
    centres.add(Number(m[1]) + Number(m[2]) / 2);
  if (!centres.size) bad.push('no phase rects found in the #wf spine');
  const START_CY = Number((/<g class="tok"><circle cx="[\d.]+" cy="([\d.]+)"/.exec(b) || [])[1] ?? NaN);
  if (!Number.isFinite(START_CY)) bad.push('token start cy not found in #wf');
  for (const m of (wf ? wf[1].matchAll(/tok:(\d+)/g) : []))
    if (!centres.has(Number(m[1]) + START_CY))
      bad.push(`tok:${m[1]} -> y=${Number(m[1]) + START_CY} is not a phase centre (${[...centres].sort((a, c) => a - c)})`);

  // 5. every custom property used anywhere resolves in BOTH themes
  const dark = /:root\{([\s\S]*?)\n\}/.exec(s)?.[1] ?? '';
  const light = /:root\[data-theme="light"\]\{([\s\S]*?)\n\}/.exec(s)?.[1] ?? '';
  for (const v of new Set([...s.matchAll(/var\((--[\w-]+)\)/g)].map(m => m[1]))) {
    if (!dark.includes(v + ':')) bad.push(`${v} undefined in dark theme`);
    if (!TOKEN_ONLY_IN_DARK.has(v) && !light.includes(v + ':')) bad.push(`${v} undefined in light theme`);
  }

  // 6. the keys the figure advertises are actually bound
  for (const k of ['n', 'b']) if (!s.includes(`e.key === '${k}'`)) bad.push(`key '${k}' advertised but not bound`);

  // 7. the script must parse
  const js = s.slice(s.lastIndexOf('<script>') + 8, s.lastIndexOf('</script>'));
  try { new Function(js); } catch (e) { bad.push(`inline script does not parse: ${e.message}`); }

  return bad;
}

const svgCount = t => (t.match(/<svg id="/g) || []).length;
const src = readFileSync('docs/deck.html', 'utf8');

if (process.argv.includes('--selftest')) {
  // NEGATIVE CONTROLS: each mutation must be caught by a different clause above.
  const cases = [
    // Both derive their target from the source. A control that hardcodes a literal
    // goes stale the moment the figure is redrawn, and then proves nothing.
    ['class the step machine names is renamed',
     s => s.replace(/class="ph (ph\d)"/, 'class="ph phZZ"')],
    ['a token stop no longer lands on a phase',
     s => s.replace(/tok:\d+/, 'tok:9999')],
    ['a theme token is removed', s => s.replace('  --ask:#ffcf25;', '')],
    ['a marker definition is dropped', s => s.replace(/<marker id="ah-deny"[\s\S]*?<\/marker>/, '')],
    ['the N key binding is removed', s => s.replace("e.key === 'n'", "e.key === 'Q'")],
    ['the script is broken', s => s.replace('function wfGo(d){', 'function wfGo(d){ {{')],
    ['a shape leaves the persona diagram viewBox', s => s.replace('<rect x="344" y="196" width="104"', '<rect x="344" y="1196" width="104"')],
    // Derived: rewrite every reference to the LAST drawn phase so it stays drawn
    // and unreached, whatever the step table's current shape happens to be.
    ['a drawn phase is never reached by any step',
     s => { const ids = [...s.matchAll(/class="ph (ph\d)"/g)].map(m => m[1]);
            const last = ids[ids.length - 1];
            return s.replace(new RegExp(`'${last}'`, 'g'), "'ph1'"); }],
    ['a verdict is drawn but never routed to',
     s => s.replace("term:'termOk'", "term:'termDeny'")],
    ['a class the persona animation drives is renamed', s => s.replace('class="wave"', 'class="waveXX"')],
  ];
  // A control whose replace() matches nothing is a NO-OP, and a no-op is
  // indistinguishable from a miss unless it is checked separately. Both times a
  // figure was redrawn, controls went stale this way and reported MISSED.
  let ok = true;
  for (const [name, mutate] of cases) {
    const mutated = mutate(src);
    if (mutated === src) {
      console.log(`STALE    ${name} -> its target string no longer exists; the control mutated nothing`);
      ok = false;
      continue;
    }
    const found = checkDeck(mutated);
    const caught = found.length > 0;
    console.log(`${caught ? 'caught  ' : 'MISSED  '} ${name}${caught ? ` -> ${found[0]}` : ''}`);
    if (!caught) ok = false;
  }
  console.log(ok ? '\nSELFTEST PASS - every mutation was caught'
                 : '\nSELFTEST FAIL - a mutation slipped through');
  process.exitCode = ok ? 0 : 1;
} else {
  const bad = checkDeck(src);
  if (bad.length) { console.log('FAIL:\n  ' + bad.join('\n  ')); process.exitCode = 1; }
  else console.log(`PASS - ${svgCount(src)} figure(s): geometry, animated classes, step references, token stops, markers, both themes, key bindings, script`);
}
