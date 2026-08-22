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
  const svg = /<svg id="wf" data-step="0" viewBox="0 0 (\d+) (\d+)"[\s\S]*?<\/svg>/.exec(s);
  if (!svg) return ['workflow svg not found'];
  const [W, H] = [Number(svg[1]), Number(svg[2])];
  const b = svg[0];

  // 1. everything inside the viewBox
  for (const m of b.matchAll(/<rect[^>]*?x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"/g)) {
    const [x, y, w, h] = m.slice(1).map(Number);
    if (x < 0 || y < 0 || x + w > W || y + h > H) bad.push(`rect outside viewBox: ${x},${y},${w},${h}`);
  }
  for (const m of b.matchAll(/<text[^>]*?x="([\d.]+)" y="([\d.]+)"/g)) {
    const [x, y] = m.slice(1).map(Number);
    if (x < 0 || x > W || y < 0 || y > H) bad.push(`text outside viewBox: ${x},${y}`);
  }

  // 2. every class the step machine names must exist in the markup
  const classes = new Set();
  for (const m of b.matchAll(/class="([^"]+)"/g)) m[1].split(/\s+/).forEach(c => classes.add(c));
  const wf = /var WF = \[([\s\S]*?)\n  \];/.exec(s);
  if (!wf) bad.push('step table WF not found');
  else {
    for (const m of wf[1].matchAll(/'(ph\d|halo[A-Z]|path[A-Za-z]+|term[A-Za-z]+)'/g))
      if (!classes.has(m[1])) bad.push(`step machine references .${m[1]}, absent from svg`);
  }

  // 3. the token stops on the spine must land on real phase centres
  const centres = new Set();
  for (const m of b.matchAll(/<rect x="210" y="([\d.]+)" width="420" height="60"/g))
    centres.add(Number(m[1]) + 30);
  const START_CY = 76;
  for (const m of (wf ? wf[1].matchAll(/tok:(\d+)/g) : []))
    if (!centres.has(Number(m[1]) + START_CY))
      bad.push(`tok:${m[1]} -> y=${Number(m[1]) + START_CY} is not a phase centre (${[...centres].sort((a, c) => a - c)})`);

  // 4. markers referenced are defined
  const refs = new Set([...b.matchAll(/url\(#([\w-]+)\)/g)].map(m => m[1]));
  const defs = new Set([...b.matchAll(/<marker id="([\w-]+)"/g)].map(m => m[1]));
  for (const r of refs) if (!defs.has(r)) bad.push(`marker #${r} referenced, never defined`);

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

const src = readFileSync('docs/deck.html', 'utf8');

if (process.argv.includes('--selftest')) {
  // NEGATIVE CONTROLS: each mutation must be caught by a different clause above.
  const cases = [
    ['class the step machine names is renamed', s => s.replace('class="ph ph6"', 'class="ph phZZ"')],
    ['a token stop no longer lands on a phase', s => s.replace('tok:470', 'tok:999')],
    ['a theme token is removed', s => s.replace('  --ask:#ffcf25;', '')],
    ['a marker definition is dropped', s => s.replace(/<marker id="ah-deny"[\s\S]*?<\/marker>/, '')],
    ['the N key binding is removed', s => s.replace("e.key === 'n'", "e.key === 'Q'")],
    ['the script is broken', s => s.replace('function wfGo(d){', 'function wfGo(d){ {{')],
  ];
  let ok = true;
  for (const [name, mutate] of cases) {
    const found = checkDeck(mutate(src));
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
  else console.log('PASS - geometry, step references, token stops, markers, both themes, key bindings, script');
}
