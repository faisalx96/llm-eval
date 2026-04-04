/**
 * قيِّم Shell — Navigation Shell Module
 *
 * Single source of truth for sidebar, topbar, breadcrumbs, user menu,
 * project switching, and layout. Injected into every page.
 *
 * Usage: include <script src="/static/shell.js"></script> in <head>.
 * The shell auto-initializes on DOMContentLoaded.
 */
(function () {
  'use strict';

  // ── Skip in export mode ──
  if (window.__QYM_EXPORT__) return;

  // ── Prevent double-init ──
  if (window.QymShell) return;

  // ── Cached state ──
  let _user = null;
  let _projects = [];
  let _currentProject = null;
  let _routeCtx = null;

  // ══════════════════════════════════════════════════
  // URL PARSING
  // ══════════════════════════════════════════════════

  function getAppRootPath() {
    const path = window.location.pathname;
    const patterns = [
      /\/projects\/[^/]+\/runs\/[^/]+$/,
      /\/projects\/[^/]+\/reviews$/,
      /\/projects\/[^/]+\/settings$/,
      /\/projects\/[^/]+\/overview$/,
      /\/projects\/[^/]+$/,
      /\/run\/[^/]+$/,
      /\/reviews$/,
      /\/profile$/,
      /\/admin$/,
      /\/trash$/,
      /\/compare$/,
    ];
    for (const pattern of patterns) {
      if (pattern.test(path)) {
        const next = path.replace(pattern, '/');
        return next.endsWith('/') ? next : next + '/';
      }
    }
    if (path.endsWith('/')) return path;
    return (path.substring(0, path.lastIndexOf('/') + 1) || '/');
  }

  const BASE_URL = window.location.origin + getAppRootPath();

  function apiUrl(path) {
    return BASE_URL + path.replace(/^\.?\//, '');
  }

  function parseRoute() {
    const pathname = window.location.pathname;
    const search = new URLSearchParams(window.location.search);

    // Project-scoped routes: /projects/{slug}/...
    const projectMatch = pathname.match(/\/projects\/([^/]+)(?:\/(.*))?$/);
    if (projectMatch) {
      const slug = decodeURIComponent(projectMatch[1]);
      const rest = projectMatch[2] || '';
      let page = 'runs'; // default project page
      let subId = null;

      if (rest === '' || rest === 'runs') {
        // Check ?view= param for Charts/Runs/Models
        const view = search.get('view');
        if (view === 'charts') page = 'charts';
        else if (view === 'models') page = 'models';
        else page = 'runs';
      }
      else if (rest === 'overview') page = 'overview';
      else if (rest === 'reviews') page = 'reviews';
      else if (rest === 'settings') page = 'settings';
      else if (rest.startsWith('runs/')) { page = 'run-detail'; subId = rest.slice(5); }

      return { projectSlug: slug, page: page, subId: subId };
    }

    // Legacy run detail: /run/{id}
    const runMatch = pathname.match(/\/run\/(.+)$/);
    if (runMatch) return { projectSlug: null, page: 'run-detail', subId: runMatch[1] };

    // Global pages
    if (pathname.endsWith('/admin')) return { projectSlug: null, page: 'admin', subId: null };
    if (pathname.endsWith('/profile')) return { projectSlug: null, page: 'profile', subId: null };
    if (pathname.endsWith('/trash')) return { projectSlug: null, page: 'trash', subId: null };
    if (pathname.endsWith('/compare')) return { projectSlug: null, page: 'compare', subId: null };
    if (pathname.endsWith('/reviews')) return { projectSlug: null, page: 'reviews', subId: null };

    // Root = projects landing
    return { projectSlug: null, page: 'projects', subId: null };
  }

  // ══════════════════════════════════════════════════
  // UTILITY
  // ══════════════════════════════════════════════════

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }

  function projectUrl(slug, subPage) {
    const root = getAppRootPath();
    if (!slug) return root;
    let url = root + 'projects/' + encodeURIComponent(slug);
    if (subPage && subPage !== 'runs') url += '/' + subPage;
    return url;
  }

  // ══════════════════════════════════════════════════
  // SVG ICONS (inline, stroke-based, 18px)
  // ══════════════════════════════════════════════════

  const ICONS = {
    dashboard: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    charts: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    runs: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    models: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    reviews: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    traces: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    admin: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    profile: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    signout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    collapse: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/><polyline points="14 8 9 12 14 16"/>',
    project: '<polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5"/><line x1="12" y1="22" x2="12" y2="15.5"/><polyline points="22 8.5 12 15.5 2 8.5"/>',
    chevronDown: '<polyline points="6 9 12 15 18 9"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    dots: '<circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>',
  };

  function icon(name, size) {
    const s = size || 18;
    return '<svg class="nav-item-icon" viewBox="0 0 24 24" width="' + s + '" height="' + s + '" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
  }

  function iconRaw(name, w, h) {
    return '<svg viewBox="0 0 24 24" width="' + (w||14) + '" height="' + (h||14) + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
  }

  // ══════════════════════════════════════════════════
  // HTML BUILDERS
  // ══════════════════════════════════════════════════

  function buildNavItem(label, page, iconName, opts) {
    opts = opts || {};
    const href = opts.href || '#';
    const badge = opts.badge ? '<span class="nav-item-badge ' + (opts.badgeClass || 'count') + '">' + esc(opts.badge) + '</span>' : '';
    return '<a class="nav-item" href="' + href + '" data-tooltip="' + esc(label) + '" data-page="' + page + '">'
      + icon(iconName)
      + '<span class="nav-item-label">' + esc(label) + '</span>'
      + badge
      + '</a>';
  }

  function buildSidebarHTML() {
    const root = getAppRootPath();
    const projectSlug = _routeCtx.projectSlug;

    // Project switcher
    const projectName = _currentProject ? esc(_currentProject.name) : 'Select a project';

    // Project-scoped nav items
    const projectNav = [
      buildNavItem('Dashboard', 'overview', 'dashboard', { href: projectSlug ? projectUrl(projectSlug, 'overview') : '#' }),
      buildNavItem('Charts', 'charts', 'charts', { href: projectSlug ? projectUrl(projectSlug) + '?view=charts' : '#' }),
      buildNavItem('Runs', 'runs', 'runs', { href: projectSlug ? projectUrl(projectSlug) : '#' }),
      buildNavItem('Models', 'models', 'models', { href: projectSlug ? projectUrl(projectSlug) + '?view=models' : '#' }),
      buildNavItem('Reviews', 'reviews', 'reviews', { href: projectSlug ? projectUrl(projectSlug, 'reviews') : '#' }),
      buildNavItem('Traces', 'traces', 'traces', { href: '#' }),
      buildNavItem('Project Settings', 'settings', 'settings', { href: projectSlug ? projectUrl(projectSlug, 'settings') : '#' }),
    ].join('');

    return ''
      // Logo
      + '<div class="sidebar-logo">'
      +   '<a href="' + root + '">'
      +     '<img src="' + root + 'static/qym_icon.png" alt="قيِّم" class="logo-icon-img" />'
      +     '<img src="' + root + 'static/qym_text.png" alt="قيِّم" class="logo-text-img" />'
      +   '</a>'
      + '</div>'

      // Project Switcher
      + '<div class="sidebar-project">'
      +   '<button class="project-trigger" id="shell-project-trigger">'
      +     '<span class="project-trigger-icon">' + iconRaw('project', 10, 10) + '</span>'
      +     '<span class="project-trigger-text">' + projectName + '</span>'
      +     '<span class="project-trigger-chevron">' + iconRaw('chevronDown', 12, 12) + '</span>'
      +   '</button>'
      +   '<div class="project-popover" id="shell-project-popover">'
      +     '<div class="popover-search"><input type="text" placeholder="Search projects…" id="shell-project-search" /></div>'
      +     '<div class="popover-list" id="shell-project-list"></div>'
      +     '<div class="popover-footer"><button class="popover-footer-btn" id="shell-create-project-btn">' + iconRaw('plus') + ' Create Project</button></div>'
      +   '</div>'
      + '</div>'

      // Nav
      + '<nav class="sidebar-nav">'
      +   '<div class="project-nav-items">' + projectNav + '</div>'
      +   '<div class="nav-section-label">Platform</div>'
      +   buildNavItem('Admin', 'admin', 'admin', { href: root + 'admin', badge: 'Admin', badgeClass: 'admin-tag' })
      +   buildNavItem('Deleted Runs', 'trash', 'trash', { href: root + 'trash' })
      + '</nav>'

      // User Footer
      + '<div class="sidebar-footer">'
      +   '<div class="user-popover" id="shell-user-popover">'
      +     '<div class="user-popover-header">'
      +       '<div class="user-avatar" id="shell-popover-avatar">?</div>'
      +       '<div class="user-info">'
      +         '<div class="user-name" id="shell-popover-name">User</div>'
      +         '<span class="user-role" id="shell-popover-role"></span>'
      +       '</div>'
      +     '</div>'
      +     '<div class="user-popover-list">'
      +       '<a class="user-popover-item" href="' + root + 'profile">'
      +         iconRaw('profile', 15, 15)
      +         ' Profile'
      +       '</a>'
      +       '<div class="user-popover-divider"></div>'
      +       '<a class="user-popover-item danger" href="#" id="shell-signout-btn">'
      +         iconRaw('signout', 15, 15)
      +         ' Sign Out'
      +       '</a>'
      +     '</div>'
      +   '</div>'
      +   '<button class="user-trigger" id="shell-user-trigger">'
      +     '<div class="user-avatar" id="shell-user-avatar">?</div>'
      +     '<div class="user-info">'
      +       '<div class="user-name" id="shell-user-name">User</div>'
      +       '<div class="user-email" id="shell-user-email"></div>'
      +     '</div>'
      +     '<span class="user-trigger-dots">' + iconRaw('dots') + '</span>'
      +   '</button>'
      + '</div>';
  }

  function buildTopbarHTML() {
    return ''
      + '<div class="topbar-left">'
      +   '<button class="topbar-toggle" id="shell-collapse-btn" title="Toggle sidebar">'
      +     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">' + ICONS.collapse + '</svg>'
      +   '</button>'
      +   '<nav class="breadcrumbs" id="shell-breadcrumbs"></nav>'
      + '</div>'
      + '<div class="topbar-stats" id="shell-topbar-stats"></div>';
  }

  // ══════════════════════════════════════════════════
  // BREADCRUMBS
  // ══════════════════════════════════════════════════

  const PAGE_LABELS = {
    projects: 'Projects',
    overview: 'Dashboard',
    dashboard: 'Dashboard',
    charts: 'Charts',
    runs: 'Runs',
    'run-detail': 'Run Detail',
    models: 'Models',
    reviews: 'Reviews',
    traces: 'Traces',
    settings: 'Project Settings',
    admin: 'Admin',
    trash: 'Deleted Runs',
    profile: 'Profile',
    compare: 'Compare',
  };

  function computeBreadcrumbs(ctx) {
    const root = getAppRootPath();
    var crumbs = [];

    if (ctx.projectSlug && _currentProject) {
      // Project-scoped page
      crumbs.push({ label: _currentProject.name, href: projectUrl(ctx.projectSlug) });

      if (ctx.page === 'run-detail') {
        crumbs.push({ label: 'Runs', href: projectUrl(ctx.projectSlug) });
        crumbs.push({ label: ctx.subId || 'Run', current: true });
      } else if (ctx.page === 'compare') {
        crumbs.push({ label: 'Runs', href: projectUrl(ctx.projectSlug) });
        crumbs.push({ label: 'Compare', current: true });
      } else {
        crumbs.push({ label: PAGE_LABELS[ctx.page] || ctx.page, current: true });
      }
    } else if (ctx.page === 'run-detail') {
      // Legacy /run/{id} URL
      crumbs.push({ label: ctx.subId || 'Run Detail', current: true });
    } else {
      crumbs.push({ label: PAGE_LABELS[ctx.page] || 'Home', current: true });
    }

    return crumbs;
  }

  function renderBreadcrumbs(crumbs) {
    var el = document.getElementById('shell-breadcrumbs');
    if (!el) return;
    var html = '';
    for (var i = 0; i < crumbs.length; i++) {
      if (i > 0) html += '<span class="breadcrumb-sep">/</span>';
      var c = crumbs[i];
      if (c.current) {
        html += '<span class="breadcrumb-item current">' + esc(c.label) + '</span>';
      } else {
        html += '<a class="breadcrumb-item" href="' + c.href + '">' + esc(c.label) + '</a>';
      }
    }
    el.innerHTML = html;
  }

  // ══════════════════════════════════════════════════
  // ACTIVE NAV STATE
  // ══════════════════════════════════════════════════

  function setActiveNav(page) {
    var items = document.querySelectorAll('.sidebar .nav-item');
    items.forEach(function (item) {
      var itemPage = item.getAttribute('data-page');
      if (itemPage === page || (page === 'overview' && itemPage === 'overview')) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });
  }

  // ══════════════════════════════════════════════════
  // PROJECT POPOVER
  // ══════════════════════════════════════════════════

  function renderProjectList(filter) {
    var list = document.getElementById('shell-project-list');
    if (!list) return;
    var query = (filter || '').toLowerCase();
    var filtered = _projects.filter(function (p) {
      return !query || p.name.toLowerCase().indexOf(query) !== -1 || p.slug.toLowerCase().indexOf(query) !== -1;
    });
    var html = '';
    filtered.forEach(function (p) {
      var isActive = _currentProject && _currentProject.slug === p.slug;
      var initials = p.name.split(/\s+/).map(function(w) { return w[0]; }).join('').slice(0, 2).toUpperCase();
      html += '<div class="popover-item' + (isActive ? ' active' : '') + '" data-slug="' + esc(p.slug) + '">'
        + '<span class="popover-item-icon">' + esc(initials) + '</span>'
        + '<span>' + esc(p.name) + '</span>'
        + (isActive ? '<span class="popover-item-check">' + iconRaw('check', 14, 14) + '</span>' : '')
        + '</div>';
    });
    if (!filtered.length) html = '<div style="padding:8px 10px;font-size:12px;color:var(--text-dim)">No projects found</div>';
    list.innerHTML = html;

    // Bind click handlers
    list.querySelectorAll('.popover-item[data-slug]').forEach(function (item) {
      item.addEventListener('click', function () {
        switchProject(item.getAttribute('data-slug'));
      });
    });
  }

  // ══════════════════════════════════════════════════
  // USER POPULATION
  // ══════════════════════════════════════════════════

  function populateUser(user) {
    if (!user) return;
    var displayName = user.display_name || (user.email ? user.email.split('@')[0] : 'User');
    var initials = getInitials(displayName);

    var setText = function (id, val) {
      var el = document.getElementById(id);
      if (el) el.textContent = val || '';
    };

    setText('shell-user-avatar', initials);
    setText('shell-user-name', displayName);
    setText('shell-user-email', user.email || '');
    setText('shell-popover-avatar', initials);
    setText('shell-popover-name', displayName);
    setText('shell-popover-role', user.role || '');

    // Show/hide admin items based on role
    document.querySelectorAll('.nav-item[data-page="admin"], .nav-item[data-page="trash"]').forEach(function (el) {
      el.style.display = user.role === 'ADMIN' ? '' : 'none';
    });
  }

  // ══════════════════════════════════════════════════
  // EVENT BINDING
  // ══════════════════════════════════════════════════

  function bindEvents() {
    var sidebar = document.getElementById('qym-sidebar');

    // Collapse toggle
    var collapseBtn = document.getElementById('shell-collapse-btn');
    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () { toggleSidebar(); });
    }

    // Project trigger
    var projTrigger = document.getElementById('shell-project-trigger');
    var projPopover = document.getElementById('shell-project-popover');
    if (projTrigger && projPopover) {
      projTrigger.addEventListener('click', function (e) {
        e.stopPropagation();
        var isOpen = projPopover.classList.toggle('open');
        projTrigger.classList.toggle('open', isOpen);
        if (isOpen) {
          renderProjectList();
          var searchInput = document.getElementById('shell-project-search');
          if (searchInput) { searchInput.value = ''; searchInput.focus(); }
        }
      });
    }

    // Project search
    var projSearch = document.getElementById('shell-project-search');
    if (projSearch) {
      projSearch.addEventListener('input', function () {
        renderProjectList(projSearch.value);
      });
    }

    // User trigger
    var userTrigger = document.getElementById('shell-user-trigger');
    var userPopover = document.getElementById('shell-user-popover');
    if (userTrigger && userPopover) {
      userTrigger.addEventListener('click', function (e) {
        e.stopPropagation();
        userPopover.classList.toggle('open');
      });
    }

    // Sign out
    var signoutBtn = document.getElementById('shell-signout-btn');
    if (signoutBtn) {
      signoutBtn.addEventListener('click', function (e) {
        e.preventDefault();
        if (window.QymAuth) window.QymAuth.logout();
      });
    }

    // Close popovers on outside click
    document.addEventListener('click', function (e) {
      if (projPopover && !e.target.closest('.sidebar-project')) {
        projPopover.classList.remove('open');
        if (projTrigger) projTrigger.classList.remove('open');
      }
      if (userPopover && !e.target.closest('.sidebar-footer')) {
        userPopover.classList.remove('open');
      }
    });

    // Close on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (projPopover) { projPopover.classList.remove('open'); if (projTrigger) projTrigger.classList.remove('open'); }
        if (userPopover) userPopover.classList.remove('open');
      }
    });
  }

  // ══════════════════════════════════════════════════
  // SIDEBAR COLLAPSE
  // ══════════════════════════════════════════════════

  function toggleSidebar() {
    var sidebar = document.getElementById('qym-sidebar');
    if (!sidebar) return;
    var isCollapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('qym:sidebar-collapsed', isCollapsed ? '1' : '');
    // Close popovers when collapsing
    if (isCollapsed) {
      var pp = document.getElementById('shell-project-popover');
      var pt = document.getElementById('shell-project-trigger');
      var up = document.getElementById('shell-user-popover');
      if (pp) pp.classList.remove('open');
      if (pt) pt.classList.remove('open');
      if (up) up.classList.remove('open');
    }
  }

  function restoreCollapseState() {
    if (localStorage.getItem('qym:sidebar-collapsed') === '1') {
      var sidebar = document.getElementById('qym-sidebar');
      if (sidebar) sidebar.classList.add('collapsed');
    }
  }

  // ══════════════════════════════════════════════════
  // PROJECT SWITCHING
  // ══════════════════════════════════════════════════

  function switchProject(slug) {
    localStorage.setItem('qym:last-project-slug', slug);
    // Navigate to the project's default page (runs)
    window.location.href = projectUrl(slug);
  }

  // ══════════════════════════════════════════════════
  // TOPBAR STATS
  // ══════════════════════════════════════════════════

  function setTopbarStats(stats) {
    var el = document.getElementById('shell-topbar-stats');
    if (!el) return;
    if (!stats || !stats.length) { el.innerHTML = ''; return; }
    var html = '';
    stats.forEach(function (s) {
      html += '<div class="topbar-stat">'
        + '<span class="topbar-stat-dot" style="background:' + (s.color || 'var(--accent-primary)') + '"></span>'
        + '<span class="topbar-stat-value">' + esc(String(s.value)) + '</span> ' + esc(s.label)
        + '</div>';
    });
    el.innerHTML = html;
  }

  // ══════════════════════════════════════════════════
  // TOAST
  // ══════════════════════════════════════════════════

  function toast(message, type) {
    var container = document.getElementById('shell-toast-container');
    if (!container) return;
    var el = document.createElement('div');
    el.className = 'shell-toast' + (type ? ' ' + type : '');
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.3s ease';
      setTimeout(function () { el.remove(); }, 300);
    }, 4000);
  }

  // ══════════════════════════════════════════════════
  // INITIALIZATION
  // ══════════════════════════════════════════════════

  function init() {
    // Skip if already initialized
    if (document.getElementById('qym-app')) return;

    // Parse current route
    _routeCtx = parseRoute();

    // Build shell DOM
    var wrapper = document.createElement('div');
    wrapper.className = 'qym-app';
    wrapper.id = 'qym-app';

    // Sidebar
    var sidebar = document.createElement('aside');
    sidebar.className = 'sidebar';
    sidebar.id = 'qym-sidebar';
    if (!_routeCtx.projectSlug) sidebar.classList.add('no-project');
    sidebar.innerHTML = buildSidebarHTML();

    // Main area
    var mainArea = document.createElement('div');
    mainArea.className = 'main-area';

    // Topbar
    var topbar = document.createElement('header');
    topbar.className = 'topbar';
    topbar.innerHTML = buildTopbarHTML();

    // Content area — move existing body children here
    var content = document.createElement('main');
    content.className = 'shell-content';
    content.id = 'shell-content';

    // Move all existing body children into the content area
    while (document.body.firstChild) {
      content.appendChild(document.body.firstChild);
    }

    // Assemble
    mainArea.appendChild(topbar);
    mainArea.appendChild(content);
    wrapper.appendChild(sidebar);
    wrapper.appendChild(mainArea);
    document.body.appendChild(wrapper);

    // Toast container
    var toastContainer = document.createElement('div');
    toastContainer.className = 'shell-toast-container';
    toastContainer.id = 'shell-toast-container';
    document.body.appendChild(toastContainer);

    // Restore collapse state
    restoreCollapseState();

    // Set active nav
    setActiveNav(_routeCtx.page);

    // Render initial breadcrumbs
    renderBreadcrumbs(computeBreadcrumbs(_routeCtx));

    // Bind events
    bindEvents();

    // Fetch user and projects
    fetchUserAndProjects();
  }

  async function fetchUserAndProjects() {
    try {
      var res = await fetch(apiUrl('v1/me'), { credentials: 'same-origin' });
      if (res.status === 401) {
        if (window.QymAuth) window.QymAuth.redirectToLogin();
        return;
      }
      if (!res.ok) return;
      _user = await res.json();
      window.__QYM_USER__ = _user;
      populateUser(_user);

      // Resolve current project from user's projects list
      if (_routeCtx.projectSlug && _user.projects) {
        _currentProject = _user.projects.find(function (p) { return p.slug === _routeCtx.projectSlug; }) || null;
        if (_currentProject) {
          // Update project trigger text
          var triggerText = document.querySelector('.project-trigger-text');
          if (triggerText) triggerText.textContent = _currentProject.name;
          // Update breadcrumbs with project name
          renderBreadcrumbs(computeBreadcrumbs(_routeCtx));
        }
      }

      // Fetch all projects for the switcher
      _projects = _user.projects || [];
      renderProjectList();

    } catch (e) {
      console.error('[QymShell] Failed to fetch user:', e);
    }

    // Signal that shell is ready
    document.dispatchEvent(new CustomEvent('qym:shell-ready'));
  }

  // ══════════════════════════════════════════════════
  // PUBLIC API
  // ══════════════════════════════════════════════════

  window.QymShell = {
    init: init,
    getUser: function () { return _user; },
    getProject: function () { return _currentProject; },
    getPageContext: function () { return _routeCtx; },
    switchProject: switchProject,
    setTopbarStats: setTopbarStats,
    setBreadcrumbs: renderBreadcrumbs,
    toggleSidebar: toggleSidebar,
    toast: toast,
    apiUrl: apiUrl,
  };

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
