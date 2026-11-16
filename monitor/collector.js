/*
 * In-page evidence collector.
 *
 * Used in two ways:
 *  1. Playwright mode: injected by monitor/browser.py (requests come from Playwright's own log).
 *  2. Claude-browser mode: Claude pastes this file into the built-in browser's JavaScript tool
 *     and calls the functions below (see skills/tracking-monitor/SKILL.md, "interim browser run").
 *
 * Defines window.__tm with:
 *   __tm.reset()               -> clears first-party cookies + storage for a "first visit"
 *   __tm.mark()                -> remembers the current position in the resource timeline
 *   __tm.snapshot()            -> evidence object (requests since mark, cookies, banner, utag)
 *   await __tm.acceptAndSnapshot(waitMs) -> clicks OneTrust "Accept all", waits, returns snapshot
 */
(function () {
  if (window.__tm && window.__tm.version === 1) return;

  function cookies() {
    const out = {};
    (document.cookie || '').split('; ').forEach(function (c) {
      if (!c) return;
      const i = c.indexOf('=');
      out[c.slice(0, i)] = c.slice(i + 1);
    });
    return out;
  }

  function utagInfo() {
    const scripts = Array.prototype.slice.call(document.scripts)
      .map(function (s) { return s.src; })
      .filter(function (s) { return /tags\.tiqcdn\.com\/utag\//.test(s); });
    if (!window.utag || !window.utag.cfg) {
      return { present: false, scripts: scripts };
    }
    const d = window.utag.data || {};
    return {
      present: true,
      scripts: scripts,
      utid: window.utag.cfg.utid,
      version: window.utag.cfg.v,
      path: window.utag.cfg.path,
      data_keys: Object.keys(d).length,
      page_type: d.page_type || null,
      language: d.language || null,
      country: d.country || null,
      page_name: d.page_name || null
    };
  }

  // Lead forms ("gates") on the page: every CTA that opens #gate-<id>, plus gates rendered on the page.
  function gates() {
    const byId = {};
    const add = function (id) { return byId[id] = byId[id] || { id: id, ctas: [], rendered: false }; };
    Array.prototype.slice.call(document.querySelectorAll('a[href^="#gate-"]')).forEach(function (a) {
      const g = add(a.getAttribute('href').slice(6));
      const t = (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60);
      if (t && g.ctas.indexOf(t) < 0) g.ctas.push(t);
    });
    Array.prototype.slice.call(document.querySelectorAll('[data-gcdc-gate-id]')).forEach(function (e) {
      add(e.getAttribute('data-gcdc-gate-id')).rendered = true;
    });
    return Object.keys(byId).map(function (k) { return byId[k]; });
  }

  function bannerVisible() {
    const b = document.querySelector('#onetrust-banner-sdk');
    if (!b) return false;
    // OneTrust animates the banner in, so size/opacity are unreliable; display:none means hidden.
    return window.getComputedStyle(b).display !== 'none';
  }

  const tm = {
    version: 1,
    _mark: 0,
    reset: function () {
      // Call this on a script-free page of the site (e.g. /robots.txt): on a normal page the
      // running tags re-create their cookies right after they are deleted.
      const names = Object.keys(cookies());
      const host = location.hostname;
      const parts = host.split('.');
      const domains = [host, '.' + host];
      for (let i = 1; i < parts.length - 1; i++) domains.push('.' + parts.slice(i).join('.'));
      names.forEach(function (n) {
        domains.forEach(function (d) {
          document.cookie = n + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain=' + d;
        });
        document.cookie = n + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
      });
      try { localStorage.clear(); } catch (e) {}
      try { sessionStorage.clear(); } catch (e) {}
      return { cleared: names.length, remaining: Object.keys(cookies()) };
    },
    mark: function () {
      tm._mark = performance.getEntriesByType('resource').length;
      return tm._mark;
    },
    snapshot: function () {
      const entries = performance.getEntriesByType('resource').slice(tm._mark);
      const c = cookies();
      const consent = c.OptanonConsent ? decodeURIComponent(c.OptanonConsent) : '';
      const groups = (consent.match(/groups=([^&]*)/) || [])[1] || null;
      return {
        url: location.href,
        title: document.title,
        requests: entries.map(function (e) { return { url: e.name, type: e.initiatorType }; }),
        cookies: c,
        banner: bannerVisible(),
        consent_groups: groups,
        utag: utagInfo(),
        has_form: !!document.querySelector('form input[type=email], form input[name*=mail i]'),
        gates: gates(),
        collected_at: new Date().toISOString()
      };
    },
    // Smaller snapshot for transcription (Claude-browser mode): drops first-party / consent-tool
    // requests and library downloads, reduces each hit URL to the parameters the checks use
    // (account IDs, click IDs, consent state), de-duplicates, and keeps cookie values only
    // where checks need them.
    minifyUrl: function (u) {
      const KP = /^(tid|src|type|cat|gclaw|gclid|gcs|pid|ti|id|ev|en|a|evt|msclkid|event)$/;
      try {
        const x = new URL(u);
        const parts = x.pathname.split(';');
        const mat = parts.slice(1).filter(function (kv) { return KP.test(kv.split('=')[0]); })
          .map(function (s) { return ';' + s; }).join('');
        const q = Array.from(x.searchParams).filter(function (p) { return KP.test(p[0]); })
          .map(function (p) { return p[0] + '=' + p[1].slice(0, 40); }).join('&');
        return x.origin + parts[0] + mat + (q ? '?' + q : '');
      } catch (e) { return u.slice(0, 150); }
    },
    compact: function (s) {
      const keep = /^(_gcl_aw|_gcl_au|_uetmsclkid|_fbc|OptanonConsent)$/;
      const skip = /(^|\.)(sage\.com|cookielaw\.org|onetrust\.com|gstatic\.com|vimeo\.com|youtube\.com|ytimg\.com|nr-data\.net|gatedcontent\.com|medallia\.eu)$|^tags\.tiqcdn\.com$|^cdnjs\.cloudflare\.com$/;
      const c = {};
      Object.keys(s.cookies).forEach(function (k) { c[k] = keep.test(k) ? s.cookies[k] : ''; });
      const out = Object.assign({}, s, { cookies: c });
      const seen = {};
      out.requests = s.requests.filter(function (r) {
        try {
          if (skip.test(new URL(r.url).hostname)) return false;
        } catch (e) { return false; }
        // Library downloads (script/css) are never hits, except Meta's pixel config.
        return !/^(script|link|css)$/.test(r.type) || /connect\.facebook\.net\/signals\/config/.test(r.url);
      }).map(function (r) { return { url: tm.minifyUrl(r.url), type: r.type }; })
        .filter(function (r) { if (seen[r.url]) return false; seen[r.url] = 1; return true; });
      return out;
    },
    // One call for a whole visit after a fresh (reset) load: pre snapshot, accept, post snapshot.
    visit: async function (settleMs, waitMs) {
      await new Promise(function (r) { setTimeout(r, settleMs || 5000); });
      tm._mark = 0;
      const pre = tm.compact(tm.snapshot());
      const post = tm.compact(await tm.acceptAndSnapshot(waitMs || 8000));
      return { status: 200, final_url: location.href, pre: pre, post: post };
    },
    // For each gate on the page, load its configuration and check that the content behind it
    // (product tour redirect, download file) answers. Same-origin HEAD requests only; nothing is submitted.
    gateTargets: async function (account) {
      const list = gates();
      for (const g of list) {
        try {
          const r = await fetch('https://app.gatedcontent.com/gates/' + (account || '50338383') + '/' + g.id);
          const b = ((await r.json()) || {}).Body || {};
          const url = decodeURIComponent(b.gateType === 'redirect' ? (b.redirectUrl || '') : (b.gateType === 'download' ? (b.downloadUrl || '') : ''));
          if (url) {
            g.target_url = url;
            if (new URL(url, location.href).origin === location.origin) {
              const h = await fetch(url, { method: 'HEAD', redirect: 'follow' });
              g.target_status = h.status;
            }
          }
        } catch (e) { g.error = String(e).slice(0, 120); }
      }
      return list;
    },
    acceptAndSnapshot: async function (waitMs) {
      tm.mark();
      const btn = document.querySelector('#onetrust-accept-btn-handler');
      const accepted = !!btn;
      if (btn) btn.click();
      await new Promise(function (r) { setTimeout(r, waitMs || 8000); });
      const s = tm.snapshot();
      s.accepted = accepted;
      return s;
    }
  };
  window.__tm = tm;
})();
