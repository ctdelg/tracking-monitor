/*
 * Lead form inventory for many pages at once (Claude-browser mode, no tracking hits).
 *
 * Fetches each page's HTML from inside a sage.com tab (no scripts run, so no tags fire),
 * finds every CTA that opens a Gated Content form (#gate-<id>) and every embedded form,
 * and leaves the result in window.__inv. Usage in the JavaScript tool:
 *
 *   1. Paste this file, then:  __invForms([["de-home", "/de-de/"], ...]);   // returns 'started'
 *   2. Poll:                    JSON.stringify({p: __inv.progress, done: __inv.done})
 *   3. Export (compact):        __invExport()
 *   4. Save the export to a file and run:
 *        python -m monitor forms import <file> --market DE
 *
 * Keep concurrency low; sage.com answers 429 to bursts.
 */
(function () {
  const UU = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
  const ta = document.createElement('textarea');
  const text = function (s) {
    ta.innerHTML = s.replace(/<[^>]+>/g, ' ');
    return ta.value.replace(/[­​]/g, '').replace(/\s+/g, ' ').trim().slice(0, 40);
  };

  window.__invForms = function (pages, concurrency) {
    const out = { pages: {}, status: {}, progress: 0, done: false };
    window.__inv = out;
    let i = 0;
    async function one(p) {
      const id = p[0], path = p[1];
      try {
        const r = await fetch(path, { credentials: 'omit' });
        out.status[id] = r.status + (r.redirected ? ' -> ' + new URL(r.url).pathname : '');
        if (!r.ok) return;
        const h = await r.text();
        const g = {};
        for (const m of h.matchAll(new RegExp('<a[^>]*href="#gate-(' + UU + ')"[^>]*>([\\s\\S]*?)</a>', 'g'))) {
          const e = g[m[1]] = g[m[1]] || { id: m[1], ctas: [] };
          const t = text(m[2]);
          if (t && !/^gate-/.test(t) && e.ctas.indexOf(t) < 0 && e.ctas.length < 2) e.ctas.push(t);
        }
        let k = h.indexOf('Forms/GatedContent');
        while (k > -1) {
          const seg = h.slice(Math.max(0, k - 700), k);
          for (const m of seg.matchAll(new RegExp('(?:&quot;|")(' + UU + ')(?:&quot;|")', 'g'))) {
            g[m[1]] = g[m[1]] || { id: m[1], ctas: [], embedded: true };
          }
          k = h.indexOf('Forms/GatedContent', k + 1);
        }
        out.pages[id] = Object.values(g);
      } catch (e) {
        out.status[id] = 'ERR ' + String(e).slice(0, 60);
      } finally {
        out.progress++;
      }
    }
    async function worker() { while (i < pages.length) { await one(pages[i++]); await new Promise(function (r) { setTimeout(r, 400); }); } }
    const workers = [];
    for (let w = 0; w < (concurrency || 3); w++) workers.push(worker());
    Promise.all(workers).then(function () { out.done = true; });
    return 'started';
  };

  // Compact export: G = [[gate id, [cta texts], embedded 0/1]], P = {page id: [indexes into G]}, S = page statuses.
  window.__invExport = function () {
    const G = [], idx = {}, P = {};
    for (const [pid, gs] of Object.entries(window.__inv.pages)) {
      if (!gs.length) continue;
      P[pid] = gs.map(function (g) {
        if (!(g.id in idx)) { idx[g.id] = G.length; G.push([g.id, g.ctas, g.embedded ? 1 : 0]); }
        return idx[g.id];
      });
    }
    return JSON.stringify({ G: G, P: P, S: window.__inv.status });
  };
})();
