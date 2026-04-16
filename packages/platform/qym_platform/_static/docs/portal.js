(function () {
  'use strict';

  function normalizeSlug(pathname) {
    var path = pathname.replace(/\/+$/, '');
    var docsIndex = path.indexOf('/docs');
    if (docsIndex === -1) return '';
    var relative = path.slice(docsIndex + '/docs'.length).replace(/^\/+/, '');
    return relative;
  }

  function docsBase() {
    var path = window.location.pathname;
    var docsIndex = path.indexOf('/docs');
    return docsIndex === -1 ? '/docs/' : path.slice(0, docsIndex + '/docs'.length + 1);
  }

  function setHtml(id, value) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = value || '';
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value || '';
  }

  function renderNav(data, currentSlug) {
    var nav = document.getElementById('portal-nav');
    if (!nav) return;
    var base = docsBase();
    nav.innerHTML = data.sections.map(function (section) {
      var links = section.pages.map(function (page) {
        var slug = page.slug || '';
        var href = base + (slug ? slug + '/' : '');
        var active = slug === currentSlug ? ' active' : '';
        return '<a class="portal-nav-link' + active + '" href="' + href + '">' + page.title + '</a>';
      }).join('');
      return '<div class="portal-nav-section"><div class="portal-nav-heading">' + section.title + '</div><div class="portal-nav-list">' + links + '</div></div>';
    }).join('');
  }

  function renderSearch(data, currentSlug) {
    var input = document.getElementById('portal-search-input');
    var results = document.getElementById('portal-results');
    if (!input || !results) return;
    var base = docsBase();
    input.addEventListener('input', function () {
      var query = input.value.trim().toLowerCase();
      if (!query) {
        results.hidden = true;
        results.innerHTML = '';
        return;
      }
      var matches = data.pages.filter(function (page) {
        var haystack = [page.title, page.summary, page.section].concat(page.keywords || []).join(' ').toLowerCase();
        return haystack.indexOf(query) !== -1;
      });
      results.hidden = false;
      results.innerHTML = matches.length ? matches.map(function (page) {
        var slug = page.slug || '';
        var href = base + (slug ? slug + '/' : '');
        return '<div class="portal-result"><a href="' + href + '">' + page.title + '</a><div class="portal-result-summary">' + page.summary + '</div></div>';
      }).join('') : '<div class="portal-result">No matching pages.</div>';
    });
  }

  function renderPage(data) {
    var slug = normalizeSlug(window.location.pathname);
    var page = data.pages.find(function (item) { return item.slug === slug; }) || data.pages.find(function (item) { return item.slug === ''; }) || data.pages[0];
    renderNav(data, page.slug);
    renderSearch(data, page.slug);
    setText('portal-title', page.title);
    setText('portal-summary', page.summary);
    setText('portal-generated-at', new Date(data.generated_at).toLocaleString());
    setHtml('portal-content', page.body_html);
    var appLink = document.getElementById('portal-app-link');
    if (appLink) {
      var base = docsBase();
      appLink.href = base.replace(/docs\/$/, '');
    }
  }

  fetch(docsBase() + 'portal-data.json', {credentials: 'same-origin'})
    .then(function (response) { return response.json(); })
    .then(renderPage)
    .catch(function (error) {
      console.error('[qym-docs] Failed to load portal data', error);
      setHtml('portal-content', '<p>Failed to load docs content.</p>');
    });
})();

