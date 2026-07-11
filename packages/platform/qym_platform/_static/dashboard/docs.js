/* قيِّم Docs — client-side engine for the native documentation page.
 * Renders the section nav, loads content partials on demand (hash-routed),
 * builds a per-page table of contents with scroll-spy, and enhances code
 * blocks with copy buttons. No build step, no external dependencies. */
(function () {
  'use strict';

  // ── Information architecture (verified against code) ──
  var SECTIONS = [
    {
      id: 'get-started',
      title: 'Get started',
      icon: '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2 0-2.8a2 2 0 0 0-3 0z"/><path d="M12 15l-3-3a22 22 0 0 1 8-10c2.6 0 5 2.4 5 5a22 22 0 0 1-10 8z"/><path d="M9 12H4s.6-3.3 2-4.5C7.1 6.5 9 7 9 7"/><path d="M12 15v5s3.3-.6 4.5-2c1-1.1.5-3 .5-3"/>',
      pages: [
        { id: 'what-is-qym', title: 'What is qym' },
        { id: 'install', title: 'Install & requirements' },
        { id: 'api-keys', title: 'Link repo & API keys' },
        { id: 'first-run', title: 'Your first run' },
        { id: 'builtin-metrics', title: 'Built-in metrics tour' },
        { id: 'task-metric-io', title: 'Task & metric I/O' },
        { id: 'datasets', title: 'Datasets & data access' },
        { id: 'errors', title: 'Handling common errors' }
      ]
    },
    {
      id: 'sdk-guide',
      title: 'SDK guide',
      icon: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
      pages: [
        { id: 'structure', title: 'Structure & exports' },
        { id: 'ways-to-evaluate', title: 'Ways to evaluate' },
        { id: 'metrics', title: 'Metrics deep dive' },
        { id: 'custom-metrics', title: 'Custom metrics' },
        { id: 'judges', title: 'LLM-as-judge & pairwise' },
        { id: 'config', title: 'Configs & options' },
        { id: 'multi-model', title: 'Multi-model & group analysis' },
        { id: 'repeats', title: 'Repeat runs & pass@k' },
        { id: 'observers', title: 'Progress & observers' },
        { id: 'results', title: 'Results, artifacts & tracing' }
      ]
    },
    {
      id: 'developer',
      title: 'Developer / API',
      icon: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
      pages: [
        { id: 'api-overview', title: 'API overview & conventions' },
        { id: 'auth', title: 'Authentication' },
        { id: 'ingestion', title: 'Run ingestion' },
        { id: 'endpoints', title: 'Endpoint reference' },
        { id: 'cli', title: 'CLI reference' }
      ]
    }
  ];

  // Flatten for prev/next + lookups.
  var FLAT = [];
  SECTIONS.forEach(function (s) {
    s.pages.forEach(function (p) { FLAT.push({ section: s.id, page: p.id, title: p.title, sectionTitle: s.title }); });
  });

  var ROOT = (window.__QYM_ROOT_PATH__ || '').replace(/\/$/, '');
  function staticUrl(p) { return ROOT + '/static/' + String(p).replace(/^\/+/, ''); }

  var ICON_COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  var ICON_SEARCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';

  var els = {};
  var partialCache = {};
  var tocObserver = null;
  var currentKey = null;
  var loadSequence = 0;

  // data-lang values (or filenames) → highlight.js language ids
  function hljsLang(label) {
    var l = String(label || '').toLowerCase();
    if (l === 'python' || /\.py$/.test(l)) return 'python';
    if (l === 'bash' || l === 'shell' || l === 'sh' || /\.(sh|bash)$/.test(l)) return 'bash';
    if (l === 'json' || /\.json$/.test(l)) return 'json';
    return null; // text / csv / pipeline diagrams stay plain
  }

  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

  function slugify(text) {
    return String(text).toLowerCase().trim()
      .replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-');
  }

  function findPage(sectionId, pageId) {
    var s = SECTIONS.find(function (x) { return x.id === sectionId; });
    if (!s) return null;
    var p = s.pages.find(function (x) { return x.id === pageId; });
    return p ? { section: s, page: p } : null;
  }

  function currentRoute() {
    var h = (location.hash || '').replace(/^#\/?/, '');
    if (!h) return null;
    var parts = h.split('/');
    if (parts.length < 2) return null;
    return { section: parts[0], page: parts[1], heading: parts[2] || null };
  }

  function scrollToHeading(id, smooth) {
    if (!id) return false;
    var target = document.getElementById(id);
    if (!target) return false;
    target.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
    return true;
  }

  // ── Section nav ──
  function buildNav() {
    var html = ''
      + '<div class="docs-search">' + ICON_SEARCH
      + '<input type="text" id="docs-search-input" placeholder="Search docs…" autocomplete="off" spellcheck="false" /></div>';
    SECTIONS.forEach(function (s) {
      html += '<div class="docs-nav-section" data-section="' + s.id + '">'
        + '<div class="docs-nav-section-title"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' + s.icon + '</svg>' + esc(s.title) + '</div>';
      s.pages.forEach(function (p) {
        html += '<a class="docs-nav-link" href="#' + s.id + '/' + p.id + '" data-key="' + s.id + '/' + p.id + '">' + esc(p.title) + '</a>';
      });
      html += '</div>';
    });
    html += '<div class="docs-nav-empty" id="docs-nav-empty" style="display:none">No matching pages</div>';
    els.subnav.innerHTML = html;

    var input = document.getElementById('docs-search-input');
    if (input) {
      input.addEventListener('input', function () { filterNav(input.value); });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          var first = els.subnav.querySelector('.docs-nav-link:not([style*="none"])');
          if (first) { location.hash = first.getAttribute('href'); input.blur(); }
        } else if (e.key === 'Escape') {
          input.value = ''; filterNav(''); input.blur();
        }
      });
      // "/" focuses search from anywhere on the page
      document.addEventListener('keydown', function (e) {
        if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
        var t = document.activeElement;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
        e.preventDefault();
        input.focus();
      });
    }
  }

  function filterNav(query) {
    var q = (query || '').toLowerCase().trim();
    var anyVisible = false;
    SECTIONS.forEach(function (s) {
      var sectionEl = els.subnav.querySelector('.docs-nav-section[data-section="' + s.id + '"]');
      var visibleInSection = 0;
      s.pages.forEach(function (p) {
        var link = sectionEl.querySelector('[data-key="' + s.id + '/' + p.id + '"]');
        var match = !q || p.title.toLowerCase().indexOf(q) !== -1 || s.title.toLowerCase().indexOf(q) !== -1;
        link.style.display = match ? '' : 'none';
        if (match) { visibleInSection++; anyVisible = true; }
      });
      sectionEl.style.display = visibleInSection ? '' : 'none';
    });
    var empty = document.getElementById('docs-nav-empty');
    if (empty) empty.style.display = anyVisible ? 'none' : '';
  }

  function setActiveNav(key) {
    els.subnav.querySelectorAll('.docs-nav-link').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-key') === key);
    });
  }

  function bindRouteLinks() {
    var page = els.content.closest('.docs-page');
    if (!page) return;
    page.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var link = event.target.closest('a[href^="#"]');
      if (!link || !page.contains(link)) return;
      var href = link.getAttribute('href');
      if (!href || href === '#') return;
      var routeTarget = href.replace(/^#\/?/, '').split('/');
      if (routeTarget.length < 2 || !findPage(routeTarget[0], routeTarget[1])) return;

      // Native hash navigation scrolls the outgoing article before hashchange
      // renders the destination. Own the history update so there is only one
      // scroll operation, after the new article is mounted.
      event.preventDefault();
      history.pushState(null, '', href);
      route();
    });
  }

  // ── Code block enhancement (copy buttons + syntax highlighting) ──
  function enhanceCode() {
    els.content.querySelectorAll('pre').forEach(function (pre) {
      if (pre.closest('.docs-codeblock')) return;
      var lang = pre.getAttribute('data-lang') || 'code';
      var text = pre.innerText;

      var hl = hljsLang(lang);
      if (hl && window.hljs) {
        try { pre.innerHTML = window.hljs.highlight(text, { language: hl, ignoreIllegals: true }).value; } catch (e) {}
      } else if (text.indexOf('\n') === -1) {
        // Single-line plain-text output (error messages, URLs) reads better
        // wrapped than behind a horizontal scrollbar. Multi-line text blocks
        // (ASCII diagrams) keep pre + scroll.
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.wordBreak = 'break-word';
      }

      var wrap = document.createElement('div');
      wrap.className = 'docs-codeblock';
      var head = document.createElement('div');
      head.className = 'docs-codeblock-head';
      head.innerHTML = '<span class="docs-codeblock-lang">' + esc(lang) + '</span>'
        + '<button class="docs-copy-btn" type="button" title="Copy" aria-label="Copy code">' + ICON_COPY + '</button>';
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(head);
      wrap.appendChild(pre);
      var btn = head.querySelector('.docs-copy-btn');
      btn.addEventListener('click', function () {
        var done = function () {
          btn.classList.add('copied');
          btn.innerHTML = ICON_CHECK;
          if (window.QymShell && window.QymShell.toast) window.QymShell.toast('Copied to clipboard', 'success');
          setTimeout(function () { btn.classList.remove('copied'); btn.innerHTML = ICON_COPY; }, 1800);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text); done(); });
        } else { fallbackCopy(text); done(); }
      });
    });

    // Wide tables scroll inside their own container instead of breaking the column
    els.content.querySelectorAll('table').forEach(function (table) {
      if (table.closest('.docs-table-wrap')) return;
      var wrap = document.createElement('div');
      wrap.className = 'docs-table-wrap';
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    ta.remove();
  }

  // ── Table of contents + scroll-spy + heading anchors ──
  function buildTOC(key) {
    if (tocObserver) { tocObserver.disconnect(); tocObserver = null; }
    var headings = Array.prototype.slice.call(els.content.querySelectorAll('h2, h3'));
    if (!headings.length) { els.toc.innerHTML = '<div class="docs-toc-empty">—</div>'; return; }
    var html = '<div class="docs-toc-title">On this page</div>';
    headings.forEach(function (h, i) {
      if (!h.id) h.id = slugify(h.textContent) || ('section-' + i);
      var lvl = h.tagName === 'H3' ? ' lvl-3' : '';
      html += '<a class="docs-toc-link' + lvl + '" data-target="' + h.id + '">' + esc(h.textContent) + '</a>';
    });
    els.toc.innerHTML = html;

    // Hover anchors make every heading shareable (#section/page/heading)
    headings.forEach(function (h) {
      var a = document.createElement('a');
      a.className = 'docs-anchor';
      a.href = '#' + key + '/' + h.id;
      a.textContent = '#';
      a.title = 'Link to this section';
      h.appendChild(a);
    });

    els.toc.querySelectorAll('.docs-toc-link').forEach(function (a) {
      a.addEventListener('click', function () {
        var id = a.getAttribute('data-target');
        if (scrollToHeading(id, true)) history.replaceState(null, '', '#' + key + '/' + id);
      });
    });

    var scroller = document.getElementById('shell-content') || null;
    tocObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var id = entry.target.id;
        els.toc.querySelectorAll('.docs-toc-link').forEach(function (a) {
          a.classList.toggle('active', a.getAttribute('data-target') === id);
        });
      });
    }, { root: scroller, rootMargin: '0px 0px -75% 0px', threshold: 0 });
    headings.forEach(function (h) { tocObserver.observe(h); });
  }

  // ── Prev / next ──
  function buildPager(key) {
    var idx = FLAT.findIndex(function (f) { return (f.section + '/' + f.page) === key; });
    if (idx < 0) return;
    var prev = idx > 0 ? FLAT[idx - 1] : null;
    var next = idx < FLAT.length - 1 ? FLAT[idx + 1] : null;
    var html = '';
    if (prev) html += '<a class="prev" href="#' + prev.section + '/' + prev.page + '"><span class="docs-pager-label">Previous</span><span class="docs-pager-title">' + esc(prev.title) + '</span></a>';
    if (next) html += '<a class="next" href="#' + next.section + '/' + next.page + '"><span class="docs-pager-label">Next</span><span class="docs-pager-title">' + esc(next.title) + '</span></a>';
    if (html) {
      var pager = document.createElement('div');
      pager.className = 'docs-pager';
      pager.innerHTML = html;
      els.content.appendChild(pager);
    }
  }

  // ── Page loading ──
  function loadPage(sectionId, pageId, heading) {
    var found = findPage(sectionId, pageId);
    if (!found) { found = findPage(FLAT[0].section, FLAT[0].page); sectionId = FLAT[0].section; pageId = FLAT[0].page; }
    var key = sectionId + '/' + pageId;
    var requestSequence = ++loadSequence;
    currentKey = key;
    setActiveNav(key);
    document.title = 'قيِّم • ' + found.page.title;
    // Keep the current article mounted while the next partial loads. Replacing
    // it with a short loading row collapses the scroll area and makes the
    // three-column layout visibly jump on every page switch.
    els.content.setAttribute('aria-busy', 'true');
    if (!els.content.childElementCount) {
      els.content.innerHTML = '<div class="docs-loading">Loading…</div>';
    }

    var render = function (htmlText) {
      if (requestSequence !== loadSequence) return;
      els.content.innerHTML = htmlText;
      enhanceCode();
      buildTOC(key);
      buildPager(key);
      els.content.removeAttribute('aria-busy');
      if (!(heading && scrollToHeading(heading, false))) {
        var scroller = document.getElementById('shell-content');
        if (scroller) scroller.scrollTop = 0;
        else window.scrollTo(0, 0);
      }
    };

    if (partialCache[key]) { render(partialCache[key]); return; }
    fetch(staticUrl('docs/' + key + '.html'), { credentials: 'same-origin' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(function (text) {
        partialCache[key] = text;
        render(text);
      })
      .catch(function () {
        if (requestSequence !== loadSequence) return;
        render('<p class="docs-eyebrow">' + esc(found.section.title) + '</p>'
          + '<h1>' + esc(found.page.title) + '</h1>'
          + '<div class="docs-callout warn"><svg class="docs-callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
          + '<p>This page hasn’t been written yet.</p></div>');
      });
  }

  function route() {
    var r = currentRoute();
    if (!r || !findPage(r.section, r.page)) {
      var first = FLAT[0];
      history.replaceState(null, '', '#' + first.section + '/' + first.page);
      loadPage(first.section, first.page);
      return;
    }
    // Same page, new heading (in-page anchor click): scroll without re-rendering
    if ((r.section + '/' + r.page) === currentKey) {
      if (r.heading) scrollToHeading(r.heading, true);
      return;
    }
    loadPage(r.section, r.page, r.heading);
  }

  function start() {
    els.subnav = document.getElementById('docs-subnav');
    els.content = document.getElementById('docs-content');
    els.toc = document.getElementById('docs-toc');
    if (!els.subnav || !els.content || !els.toc) return;
    buildNav();
    bindRouteLinks();
    window.addEventListener('hashchange', route);
    document.addEventListener('qym:popstate', function (event) {
      var target = currentRoute();
      if (!target || !findPage(target.section, target.page)) return;
      event.preventDefault();
      route();
    });
    route();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
