#!/usr/bin/env python3
"""
Assemble screens/index.html from the shipped screen files.

WHY THIS IS A SCRIPT AND NOT A HAND-WRITTEN FILE. index.html is the live link people are sent.
If it were hand-copied it would drift from the screens the moment either changed, and the drift
would be invisible -- both files would still render. Assembling it means the combined page cannot
say something the individual screens do not.

    python3 screens/build-index.py

FOUR BUGS THIS SCRIPT EXISTS TO NOT REPEAT, each found by rendering the output rather than reading
it. They are the reason each step below is written the way it is:

  1. Stripping `<title>` with a tag regex leaves `</title>` AND ITS TEXT behind, so "Hands up" and
     "Check 1 Intake" rendered as stray body copy. Titles are removed as whole elements.
  2. Each screen's own `html,body{}` rules leak globally once inlined. The opening screen sets
     `body{overflow:hidden}`, which killed scrolling for the entire page.
  3. Stripping those also takes agave.css's OWN body rule, which carries margin, font-family and
     line-height -- the page fell back to a serif with an 8px body margin. The shell restates them.
  4. `.mark`, `.bar` and `.hud` are SIBLINGS of `.stage` in the opening screen, not children.
     Standalone they resolve against the viewport, which is right for a full-screen presentation and
     wrong inside a panel. The panel is made their containing block.
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).parent
OUT = HERE / 'index.html'

SCREENS = [
    ('opening', '00-opening.html',          'Opening',  'Hands up'),
    ('c1',      'check-1-intake.html',      'Check 1',  'Intake'),
    ('c2',      'check-2-vendor.html',      'Check 2',  'Vendor resolution'),
    ('c3',      'check-3-paid-before.html', 'Check 3',  'Paid before?'),
    ('c4',      'check-4-job-status.html',  'Check 4',  'Job status'),
]


def parse(fn):
    """Return (own <style> css, body markup, ordered state names, beat count)."""
    raw = (HERE / fn).read_text()

    styles = '\n'.join(re.findall(r'<style>(.*?)</style>', raw, re.S))
    # BUG 2: drop html/body rule-sets from the screen's own CSS. They are correct for a standalone
    # page and destructive once five of them share one document.
    styles = re.sub(r'(^|\})\s*(?:html\s*,\s*body|html|body)\s*\{[^}]*\}',
                    lambda m: m.group(1) or '', styles)

    body = re.sub(r'<!--.*?-->', '', raw, flags=re.S)          # contract comments
    body = re.sub(r'<style>.*?</style>', '', body, flags=re.S)
    body = re.sub(r'<script>.*?</script>', '', body, flags=re.S)
    body = re.sub(r'<title>.*?</title>', '', body, flags=re.S)  # BUG 1: whole element, not the tag
    body = re.sub(r'<(?:html|meta|link)\b[^>]*>', '', body)

    seen, states = set(), []
    for s in re.findall(r'data-state="([^"]+)"', raw):
        if s not in seen:
            seen.add(s)
            states.append(s)
    beats = len(re.findall(r'data-beat="\d+"', raw))
    return styles, body.strip(), states, beats


panels, nav, steps = [], [], {}
for key, fn, label, name in SCREENS:
    css, body, states, beats = parse(fn)
    # A screen is stepped by its STATES, or -- for the presentation -- by its BEATS. The shell
    # never needs to know which; it only needs how many steps there are.
    steps[key] = {'n': beats if key == 'opening' else len(states),
                  'kind': 'beat' if key == 'opening' else 'state',
                  'names': states}
    panels.append(f'<style>{css}</style>\n'
                  f'<section class="panel" id="s-{key}" data-screen="{key}" hidden>\n{body}\n</section>')
    nav.append(f'<button class="nav__i" data-go="{key}">'
               f'<span class="nav__n">{label}</span><span class="nav__t">{name}</span></button>')

SHELL_CSS = """
/* ── REVIEW SHELL ───────────────────────────────────────────────────────────
   STEPPING LIVES HERE AND NEVER IN THE PRODUCT SCREENS. This page is a review surface, where
   walking every state a check can reach IS the job. Someone using the actual product sees one
   state, driven by one invoice; a state picker there would be the interface describing its own
   internals to the person using it.

   AND THE STATE NAMES ARE NOT SHOWN. `partial`, `unresolved`, `near` are internal vocabulary, and
   putting them on screen asks the reader to learn the implementation to read the design. There is
   Back and Next, nothing else -- each screen already says what it is in its own verdict. */

/* BUG 3: agave.css's own html/body rules were stripped along with the screens' leaked copies.
   They carried margin, font-family, line-height and the fluid root size. Restated here. */
html{font-size:13.2034px}
@media (min-width:1100px){html{font-size:15px}}
@media (min-width:1500px){html{font-size:16px}}
body{margin:0;background:var(--ag-navy);color:var(--ag-ink-dark);min-height:100vh;
  font-family:var(--ag-font);font-weight:400;font-size:var(--ag-t-body);
  line-height:var(--ag-lh);-webkit-font-smoothing:antialiased}

.shell{display:grid;grid-template-columns:15rem 1fr;min-height:100vh}
@media (max-width:820px){.shell{grid-template-columns:1fr}}

.rail{border-right:1px solid var(--ag-line-dark);padding:1.5rem 0;background:var(--ag-nav);
  position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto}
@media (max-width:820px){.rail{position:static;max-height:none;border-right:0;
  border-bottom:1px solid var(--ag-line-dark)}}
.rail__m{display:flex;align-items:center;gap:.55rem;padding:0 1.25rem 1.25rem;
  font-family:var(--ag-mono);font-size:var(--ag-t-micro);letter-spacing:.14em;
  text-transform:uppercase;color:var(--ag-ink-dark-mute)}
.rail__d{width:.45rem;height:.45rem;background:var(--ag-green);flex:0 0 auto}
.nav{display:flex;flex-direction:column}
@media (max-width:820px){.nav{flex-direction:row;overflow-x:auto}}
.nav__i{display:flex;flex-direction:column;gap:.15rem;text-align:left;background:none;border:0;
  border-left:2px solid transparent;padding:.7rem 1.25rem;cursor:pointer;
  font-family:var(--ag-font);color:var(--ag-ink-dark-mid);white-space:nowrap;
  transition:background-color var(--ag-dur),color var(--ag-dur)}
.nav__i:hover{background:rgba(255,255,255,.04);color:var(--ag-ink-dark)}
.nav__i[aria-current="true"]{border-left-color:var(--ag-green);color:var(--ag-ink-dark);
  background:rgba(23,207,96,.08)}
@media (max-width:820px){.nav__i{border-left:0;border-bottom:2px solid transparent}
  .nav__i[aria-current="true"]{border-bottom-color:var(--ag-green)}}
.nav__n{font-family:var(--ag-mono);font-size:var(--ag-t-micro);letter-spacing:.1em;
  text-transform:uppercase;color:var(--ag-ink-dark-mute)}
.nav__t{font-size:var(--ag-t-sm);font-weight:600}
.nav__i[aria-current="true"] .nav__n{color:var(--ag-green)}

.main{min-width:0;display:flex;flex-direction:column}
.note-bar{padding:.6rem 1.5rem;border-bottom:1px solid var(--ag-line-dark);
  font-size:var(--ag-t-micro);font-family:var(--ag-mono);color:var(--ag-ink-dark-mute);
  letter-spacing:.04em}
.note-bar b{color:var(--ag-ink-dark-mid);font-weight:400}

/* ── THE STEPPER. Two controls and a position, no vocabulary. ─────────────── */
.step{display:flex;align-items:center;gap:.5rem;padding:.75rem 1.5rem;
  border-bottom:1px solid var(--ag-line-dark);background:var(--ag-nav);
  position:sticky;top:0;z-index:5}
.step__b{display:flex;align-items:center;gap:.5rem;font-family:var(--ag-mono);
  font-size:var(--ag-t-micro);letter-spacing:.08em;text-transform:uppercase;
  background:none;border:1px solid var(--ag-line-dark-2);color:var(--ag-ink-dark-mid);
  padding:.4rem .85rem;cursor:pointer;
  transition:background-color var(--ag-dur),color var(--ag-dur),border-color var(--ag-dur)}
.step__b:hover:not(:disabled){border-color:var(--ag-ink-dark-mute);color:var(--ag-ink-dark)}
.step__b:disabled{opacity:.35;cursor:default}
.step__b:focus-visible{outline:2px solid var(--ag-green);outline-offset:2px}

/* THE KEY PRESS PRESSES THE BUTTON. A keystroke that silently changed the screen would leave the
   viewer unable to see what they did; this makes N and B visibly actuate the same control a mouse
   would, so the keyboard is a shortcut to the interface rather than a second, hidden one. */
.step__b[data-fired]{background:var(--ag-green);border-color:var(--ag-green);color:#000}

.step__k{font-family:var(--ag-mono);font-size:.9em;border:1px solid currentColor;
  padding:0 .3rem;opacity:.7;border-radius:0}
.step__pos{display:flex;gap:.3rem;margin-left:.4rem}
.step__dot{width:1.1rem;height:2px;background:var(--ag-line-dark-2)}
.step__dot[data-on]{background:var(--ag-green)}
.step__c{margin-left:auto;font-family:var(--ag-mono);font-size:var(--ag-t-micro);
  color:var(--ag-ink-dark-mute);font-variant-numeric:tabular-nums}

.panel[hidden]{display:none}
.panel{flex:1;position:relative}

/* The opening screen is a presentation; inside the shell it is a panel, not a viewport.
   BUG 4: .mark/.bar/.hud are siblings of .stage, so the panel must be their containing block. */
#s-opening{overflow:hidden;position:relative}
#s-opening .stage{position:relative;inset:auto;min-height:32rem;padding:3rem 2rem}
#s-opening .hud,#s-opening .mark,#s-opening .bar{position:absolute}
#s-opening .beat{display:none}
#s-opening .beat[data-on]{display:block}
/* The standalone screen carries its own key legend and auto-advance bar; the shell owns both now. */
#s-opening .hud,#s-opening .bar{display:none}
"""

JS = """
(function () {
  var STEPS = %(steps)s;
  var cur = 'opening', idx = 0;
  var LABEL = { c1: 'reading the document', c2: 'matching 986 vendor clusters',
                c3: 'searching prior payments', c4: 'looking up the ERP' };
  var back = document.getElementById('back');
  var next = document.getElementById('next');
  var pos  = document.getElementById('pos');
  var count = document.getElementById('count');

  function panel() { return document.querySelector('.panel[data-screen="' + cur + '"]'); }

  /* CSS animations do not restart on a class toggle, and the entrance IS what is under review.
     Replacing the node is the only reliable way to replay it. */
  function replay(el) {
    if (!el) return;
    el.parentNode.replaceChild(el.cloneNode(true), el);
  }

  /* THE HOLD. The panel goes quiet, one line names what is running, and the evidence arrives
     afterwards. Without it the verdict is simply already on screen when the screen appears, and a
     room reads that as information rather than as an answer.
     The loading state is exempt: holding before a skeleton is a wait before a wait. */
  var holdT = null;
  function hold(p, label) {
    clearTimeout(holdT);
    var old = p.querySelector('.ag-hold'); if (old) old.remove();
    p.classList.remove('ag-held');
    if (STEPS[cur].names[idx] === 'loading') return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var el = document.createElement('div');
    el.className = 'ag-hold';
    el.innerHTML = '<span class="ag-hold__t">' + label + '</span>' +
                   '<span class="ag-hold__r"><span class="ag-hold__f"></span></span>';
    p.appendChild(el);
    p.classList.add('ag-held');
    var ms = parseInt(getComputedStyle(document.documentElement)
               .getPropertyValue('--ag-hold'), 10) || 900;
    holdT = setTimeout(function () {
      el.remove();
      p.classList.remove('ag-held');
      /* Replay AFTER the hold, so the cascade plays into a held room rather than behind the cover. */
      replay(p.querySelector('[data-state]:not([hidden])'));
    }, ms);
  }

  function render() {
    var s = STEPS[cur], p = panel();
    if (s.kind === 'beat') {
      p.querySelectorAll('.beat').forEach(function (el, n) {
        if (n === idx) el.setAttribute('data-on', ''); else el.removeAttribute('data-on');
      });
      replay(p.querySelector('.beat[data-on]'));
    } else {
      var want = s.names[idx];
      p.querySelectorAll('[data-state]').forEach(function (el) {
        el.hidden = el.getAttribute('data-state') !== want;
      });
      replay(p.querySelector('[data-state]:not([hidden])'));
      hold(p, LABEL[cur] || 'running check');
    }
    pos.innerHTML = Array.from({ length: s.n }, function (_, i) {
      return '<span class="step__dot"' + (i === idx ? ' data-on' : '') + '></span>';
    }).join('');
    count.textContent = (idx + 1) + ' / ' + s.n;
    back.disabled = idx === 0;
    next.disabled = idx === s.n - 1;
  }

  function go(d) {
    var n = STEPS[cur].n;
    idx = Math.min(Math.max(idx + d, 0), n - 1);
    render();
  }

  function screen(k) {
    cur = k; idx = 0;
    document.querySelectorAll('.panel').forEach(function (p) {
      p.hidden = p.getAttribute('data-screen') !== k;
    });
    document.querySelectorAll('.nav__i').forEach(function (b) {
      b.setAttribute('aria-current', b.getAttribute('data-go') === k ? 'true' : 'false');
    });
    render();
  }

  /* A key press ACTUATES the button rather than bypassing it, so the viewer sees which control
     they used. 160ms is long enough to register and short enough not to lag the transition. */
  function fire(btn) {
    if (btn.disabled) return;
    btn.setAttribute('data-fired', '');
    setTimeout(function () { btn.removeAttribute('data-fired'); }, 160);
    btn.click();
  }

  back.addEventListener('click', function () { go(-1); });
  next.addEventListener('click', function () { go(1); });
  document.querySelectorAll('.nav__i').forEach(function (b) {
    b.addEventListener('click', function () { screen(b.getAttribute('data-go')); });
  });
  document.addEventListener('keydown', function (e) {
    var k = e.key.toLowerCase();
    if (k === 'n' || k === 'arrowright') { e.preventDefault(); fire(next); }
    else if (k === 'b' || k === 'arrowleft') { e.preventDefault(); fire(back); }
  });

  screen('opening');
})();
""" % {'steps': json.dumps(steps)}

doc = f"""<title>Fabricated Receipt</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono:wght@400&display=swap">

<style>
{(HERE / 'agave.css').read_text()}
{SHELL_CSS}
</style>

<div class="shell">
  <aside class="rail">
    <div class="rail__m"><span class="rail__d"></span><span>Fabricated receipt</span></div>
    <nav class="nav" aria-label="screens">
{chr(10).join('      ' + n for n in nav)}
    </nav>
  </aside>
  <div class="main">
    <div class="note-bar">Secondary surface &mdash; static design reference. The <b>primary</b>
      product surface is the Streamlit app in the repo.</div>
    <div class="step">
      <button class="step__b" id="back"><span class="step__k">B</span>Back</button>
      <button class="step__b" id="next"><span class="step__k">N</span>Next</button>
      <span class="step__pos" id="pos" aria-hidden="true"></span>
      <span class="step__c" id="count"></span>
    </div>
{chr(10).join(panels)}
  </div>
</div>

<script>{JS}</script>
"""

OUT.write_text(doc)
print(f'built {OUT} — {len(doc)} bytes')
for k, v in steps.items():
    print(f"  {k:8} {v['n']} {v['kind']}(s)" + (f"  {v['names']}" if v['names'] else ''))
