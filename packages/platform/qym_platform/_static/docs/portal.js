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

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderInline(value) {
    return escapeHtml(value)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  }

  function renderMarkdown(markdown) {
    var lines = String(markdown || '').split(/\r?\n/);
    var html = [];
    var paragraph = [];
    var list = [];
    var inCode = false;
    var code = [];
    var admonition = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      html.push('<p>' + renderInline(paragraph.join(' ')) + '</p>');
      paragraph = [];
    }

    function flushList() {
      if (!list.length) return;
      html.push('<ul>' + list.map(function (item) {
        return '<li>' + renderInline(item) + '</li>';
      }).join('') + '</ul>');
      list = [];
    }

    function flushAdmonition() {
      if (!admonition) return;
      html.push(
        '<div class="portal-admonition portal-admonition-' + admonition.kind + '">' +
        '<div class="portal-admonition-title">' + renderInline(admonition.title) + '</div>' +
        '<div class="portal-admonition-body">' + renderMarkdown(admonition.body.join('\n')) + '</div>' +
        '</div>'
      );
      admonition = null;
    }

    function renderTable(start) {
      var rows = [];
      var index = start;
      while (index < lines.length && /^\s*\|.*\|\s*$/.test(lines[index])) {
        rows.push(lines[index]);
        index += 1;
      }
      if (rows.length < 2 || !/^\s*\|?\s*:?-{3,}:?\s*\|/.test(rows[1])) return start;
      var headers = rows[0].trim().replace(/^\||\|$/g, '').split('|').map(function (cell) { return cell.trim(); });
      var bodyRows = rows.slice(2).map(function (row) {
        return row.trim().replace(/^\||\|$/g, '').split('|').map(function (cell) { return cell.trim(); });
      });
      html.push(
        '<table><thead><tr>' + headers.map(function (cell) { return '<th>' + renderInline(cell) + '</th>'; }).join('') +
        '</tr></thead><tbody>' + bodyRows.map(function (row) {
          return '<tr>' + row.map(function (cell) { return '<td>' + renderInline(cell) + '</td>'; }).join('') + '</tr>';
        }).join('') + '</tbody></table>'
      );
      return index;
    }

    for (var i = 0; i < lines.length; i += 1) {
      var line = lines[i];
      if (inCode) {
        if (/^```/.test(line)) {
          html.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
          code = [];
          inCode = false;
        } else {
          code.push(line);
        }
        continue;
      }

      if (admonition) {
        if (/^:::\s*$/.test(line)) {
          flushAdmonition();
        } else {
          admonition.body.push(line);
        }
        continue;
      }

      if (/^```/.test(line)) {
        flushParagraph();
        flushList();
        inCode = true;
        code = [];
        continue;
      }

      var admonitionMatch = line.match(/^:::(\w+)\s*(.*)$/);
      if (admonitionMatch) {
        flushParagraph();
        flushList();
        admonition = {
          kind: admonitionMatch[1].toLowerCase(),
          title: admonitionMatch[2] || admonitionMatch[1],
          body: []
        };
        continue;
      }

      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }

      if (/^\s*\|.*\|\s*$/.test(line)) {
        flushParagraph();
        flushList();
        var tableEnd = renderTable(i);
        if (tableEnd !== i) {
          i = tableEnd - 1;
          continue;
        }
      }

      var heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        flushList();
        html.push('<h' + heading[1].length + '>' + renderInline(heading[2]) + '</h' + heading[1].length + '>');
        continue;
      }

      var listItem = line.match(/^\s*[-*]\s+(.+)$/);
      if (listItem) {
        flushParagraph();
        list.push(listItem[1]);
        continue;
      }

      paragraph.push(line.trim());
    }

    if (inCode) html.push('<pre><code>' + escapeHtml(code.join('\n')) + '</code></pre>');
    flushAdmonition();
    flushParagraph();
    flushList();
    return html.join('');
  }

  function renderNav(data, currentSlug) {
    var nav = document.getElementById('portal-nav');
    if (!nav) return;
    var sidebar = document.querySelector ? document.querySelector('.portal-sidebar') : null;
    var sidebarScrollTop = sidebar ? sidebar.scrollTop : 0;
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
    if (sidebar) sidebar.scrollTop = sidebarScrollTop;
  }

  function renderSearch(data) {
    var input = document.getElementById('portal-search-input');
    var results = document.getElementById('portal-results');
    if (!input || !results) return;
    if (input.__qymDocsSearchBound) return;
    input.__qymDocsSearchBound = true;
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

  function findPage(data) {
    var slug = normalizeSlug(window.location.pathname);
    return data.pages.find(function (item) { return item.slug === slug; }) || data.pages.find(function (item) { return item.slug === ''; }) || data.pages[0];
  }

  function renderPage(data, options) {
    var page = findPage(data);
    renderNav(data, page.slug);
    renderSearch(data);
    setText('portal-title', page.title);
    setText('portal-summary', page.summary);
    setText('portal-generated-at', new Date(data.generated_at).toLocaleString());
    setHtml('portal-content', page.body_html || renderMarkdown(page.body_mdx));
    document.title = page.title ? page.title + ' | qym Docs' : 'qym Docs';
    if (options && options.scrollMain && window.scrollTo) window.scrollTo({top: 0, behavior: 'auto'});
    var appLink = document.getElementById('portal-app-link');
    if (appLink) {
      var base = docsBase();
      appLink.href = base.replace(/docs\/$/, '');
    }
  }

  function setupClientNavigation(data) {
    if (!document.addEventListener) return;
    document.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var target = event.target;
      var link = target && target.closest ? target.closest('a[href]') : null;
      if (!link) return;

      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#' || href.indexOf('mailto:') === 0 || href.indexOf('tel:') === 0) return;

      var currentUrl = new URL(window.location.href);
      var nextUrl = new URL(href, currentUrl.href);
      var baseUrl = new URL(docsBase(), currentUrl.origin);
      if (nextUrl.origin !== currentUrl.origin) return;
      if (nextUrl.pathname.indexOf(baseUrl.pathname) !== 0) return;
      if (/\/[^/]+\.[^/]+$/.test(nextUrl.pathname)) return;
      if (nextUrl.pathname === window.location.pathname && nextUrl.search === window.location.search && nextUrl.hash === window.location.hash) return;

      event.preventDefault();
      window.history.pushState({}, '', nextUrl.pathname + nextUrl.search + nextUrl.hash);
      renderPage(data, {scrollMain: true});
    });

    window.addEventListener('popstate', function () {
      renderPage(data, {scrollMain: true});
    });
  }

  fetch(docsBase() + 'portal-data.json', {credentials: 'same-origin'})
    .then(function (response) { return response.json(); })
    .then(function (data) {
      renderPage(data);
      setupClientNavigation(data);
    })
    .catch(function (error) {
      console.error('[qym-docs] Failed to load portal data', error);
      setHtml('portal-content', '<p>Failed to load docs content.</p>');
    });
})();
