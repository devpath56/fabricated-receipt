// State driver for the check screens.
//
// CONTRACT WITH state-matrix.mjs: every state is a <section data-state="NAME">. Exactly one is
// active at a time via data-active="true". The gate drives each state INDEPENDENTLY and scores it
// on its own — a state reachable only through a code path nobody can address is a state nobody
// designed, and the gate would rightly call it undrawn.
//
// The switcher this file renders is TOOLING. It lives outside the state sections so it cannot
// contribute focusable elements or contrast failures to the artifact the gate measures — the same
// separation design-loop's workbench keeps by putting the prototype in an iframe.
(function () {
  var states = Array.prototype.slice.call(document.querySelectorAll('[data-state]'));
  if (!states.length) return;

  function show(name) {
    var found = false;
    states.forEach(function (s) {
      var on = s.getAttribute('data-state') === name;
      s.setAttribute('data-active', on ? 'true' : 'false');
      if (on) found = true;
    });
    Array.prototype.forEach.call(document.querySelectorAll('.states button'), function (b) {
      b.setAttribute('aria-current', b.dataset.go === name ? 'true' : 'false');
    });
    // The URL carries the state so the gate can address one directly, and so a screenshot of a
    // failing state can be reproduced from its link rather than from a click sequence.
    if (found && window.history && history.replaceState) {
      history.replaceState(null, '', '#' + name);
    }
    return found;
  }

  // Tooling chrome, appended after the artifact so it is last in the tab order.
  var nav = document.createElement('nav');
  nav.className = 'states';
  nav.setAttribute('aria-label', 'State switcher (tooling)');
  states.forEach(function (s) {
    var n = s.getAttribute('data-state');
    var b = document.createElement('button');
    b.type = 'button';
    b.dataset.go = n;
    b.textContent = n;
    b.addEventListener('click', function () { show(n); });
    nav.appendChild(b);
  });
  document.body.appendChild(nav);

  // The gate addresses a state by hash. Default to the first DECLARED state, never to success —
  // opening on the happy path is how a broken error state ships unseen.
  var want = (location.hash || '').replace('#', '');
  if (!want || !show(want)) show(states[0].getAttribute('data-state'));
  window.addEventListener('hashchange', function () {
    show((location.hash || '').replace('#', ''));
  });
})();
