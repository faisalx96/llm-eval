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
      /\/projects\/[^/]+\/datasets(?:\/[^/]+(?:\/compare)?)?$/,
      /\/projects\/[^/]+\/settings$/,
      /\/projects\/[^/]+\/overview$/,
      /\/projects\/[^/]+\/charts$/,
      /\/projects\/[^/]+\/models$/,
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

      if (rest === '' || rest === 'runs') page = 'runs';
      else if (rest === 'charts') page = 'charts';
      else if (rest === 'models') page = 'models';
      else if (rest === 'datasets') page = 'datasets';
      else if (rest.startsWith('datasets/')) {
        page = 'datasets';
        var remainder = rest.slice(9);
        if (remainder.endsWith('/compare')) {
          subId = remainder.slice(0, -'/compare'.length);
        } else {
          subId = remainder;
        }
      }
      else if (rest === 'overview') page = 'overview';
      else if (rest === 'reviews') page = 'reviews';
      else if (rest === 'settings') page = 'settings';
      else if (rest.startsWith('runs/')) { page = 'run-detail'; subId = rest.slice(5); }

      return { projectSlug: slug, page: page, subId: subId };
    }

    // Legacy run detail: /run/{id} — keep project context from last known project
    const lastSlug = localStorage.getItem('qym:last-project-slug') || null;
    const runMatch = pathname.match(/\/run\/(.+)$/);
    if (runMatch) return { projectSlug: lastSlug, page: 'run-detail', subId: runMatch[1] };

    // Global pages — truly no project
    if (pathname.endsWith('/admin')) return { projectSlug: null, page: 'admin', subId: null };
    if (pathname.endsWith('/profile')) return { projectSlug: null, page: 'profile', subId: null };
    if (pathname.endsWith('/trash')) return { projectSlug: null, page: 'trash', subId: null };
    if (pathname.endsWith('/docs-guide')) return { projectSlug: null, page: 'docs', subId: null };

    // Compare and reviews without project prefix — keep project context
    if (pathname.endsWith('/compare')) return { projectSlug: lastSlug, page: 'compare', subId: null };
    if (pathname.endsWith('/reviews')) return { projectSlug: lastSlug, page: 'reviews', subId: null };

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

  function isModifiedEvent(e) {
    return !!(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0);
  }

  function getRelativeAppPath(pathname) {
    var root = getAppRootPath();
    if (!pathname.startsWith(root)) return null;
    return pathname.slice(root.length).replace(/^\/+/, '');
  }

  function isNavigableAppPath(pathname) {
    var relative = getRelativeAppPath(pathname);
    if (relative === null) return false;
    if (relative === '') return true;
    return [
      /^projects\/[^/]+(?:\/(?:runs|overview|charts|models|datasets(?:\/[^/]+(?:\/compare)?)?|reviews|settings))?$/,
      /^projects\/[^/]+\/runs\/[^/]+$/,
      /^run\/[^/]+$/,
      /^reviews$/,
      /^profile$/,
      /^admin$/,
      /^trash$/,
      /^compare$/,
    ].some(function (pattern) {
      return pattern.test(relative);
    });
  }

  function canInterceptLink(link, e) {
    if (!link) return false;
    if (isModifiedEvent(e)) return false;
    if (link.hasAttribute('download')) return false;
    if ((link.getAttribute('target') || '').toLowerCase() === '_blank') return false;

    var href = link.getAttribute('href');
    if (!href || href === '#' || href.startsWith('#')) return false;

    var targetUrl;
    try {
      targetUrl = new URL(href, window.location.href);
    } catch (err) {
      return false;
    }

    if (targetUrl.origin !== window.location.origin) return false;
    if (!isNavigableAppPath(targetUrl.pathname)) return false;

    return targetUrl.pathname + targetUrl.search !== window.location.pathname + window.location.search;
  }

  function closeShellPopovers() {
    var projPopover = document.getElementById('shell-project-popover');
    var projTrigger = document.getElementById('shell-project-trigger');
    var userPopover = document.getElementById('shell-user-popover');
    if (projPopover) projPopover.classList.remove('open');
    if (projTrigger) projTrigger.classList.remove('open');
    if (userPopover) userPopover.classList.remove('open');
  }

  function projectExists(projectSlug) {
    if (!projectSlug) return false;
    var projects = _user && Array.isArray(_user.projects) ? _user.projects : _projects;
    return projects.some(function (project) {
      return project && project.slug === projectSlug;
    });
  }

  function updateCurrentProjectForRoute() {
    var sidebar = document.getElementById('qym-sidebar');
    if (_routeCtx && _routeCtx.projectSlug && _user && Array.isArray(_user.projects)) {
      _currentProject = _user.projects.find(function (project) {
        return project && project.slug === _routeCtx.projectSlug;
      }) || null;
    } else {
      _currentProject = null;
    }

    if (sidebar) {
      if (_currentProject) {
        sidebar.classList.remove('no-project');
        rebuildNavHrefs();
      } else {
        sidebar.classList.add('no-project');
      }
    }

    var triggerText = document.querySelector('.project-trigger-text');
    if (triggerText && _currentProject) triggerText.textContent = _currentProject.name;
  }

  function renderProjectNotFound(projectSlug) {
    var content = document.getElementById('shell-content') || document.querySelector('main');
    if (!content) return;
    closeShellPopovers();
    updateCurrentProjectForRoute();
    setTopbarStats([]);
    renderBreadcrumbs([{ label: 'Project Not Found', current: true }]);
    content.innerHTML = ''
      + '<div style="max-width:640px;margin:56px auto;padding:0 20px;">'
      +   '<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;padding:28px 24px;">'
      +     '<div style="font-size:var(--font-sm);font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:var(--error);margin-bottom:12px;">Missing Project</div>'
      +     '<h1 style="margin:0 0 10px 0;font-size:var(--font-title);line-height:1.2;color:var(--text-primary);">Project not found</h1>'
      +     '<p style="margin:0;color:var(--text-secondary);font-size:var(--font-md);line-height:1.6;">The requested project does not exist, is archived, or you no longer have access to it.</p>'
      +     (projectSlug
              ? '<div style="margin-top:16px;padding:10px 12px;border-radius:8px;background:var(--bg-elevated);border:1px solid var(--border-subtle);font-family:var(--font-mono);font-size:var(--font-base);color:var(--text-muted);">Slug: ' + esc(projectSlug) + '</div>'
              : '')
      +     '<div style="margin-top:20px;"><a href="' + getAppRootPath() + '" class="shell-btn shell-btn-primary" style="display:inline-flex;text-decoration:none;">Back to Projects</a></div>'
      +   '</div>'
      + '</div>';
  }

  function syncProjects(projects) {
    var nextProjects = Array.isArray(projects) ? projects.slice() : [];
    if (_user) _user.projects = nextProjects;
    _projects = nextProjects;
    window.__QYM_USER__ = _user;
    updateCurrentProjectForRoute();
    renderProjectList();
  }

  function upsertProject(project) {
    if (!project) return;
    var nextProjects = (_user && Array.isArray(_user.projects) ? _user.projects : _projects).slice();
    var idx = nextProjects.findIndex(function (item) {
      if (!item) return false;
      if (project.id && item.id === project.id) return true;
      return !!(project.slug && item.slug === project.slug);
    });
    if (idx >= 0) nextProjects[idx] = project;
    else nextProjects.push(project);
    syncProjects(nextProjects);
  }

  function removeProject(projectRef) {
    if (!projectRef) return;
    var nextProjects = (_user && Array.isArray(_user.projects) ? _user.projects : _projects).filter(function (item) {
      if (!item) return false;
      if (projectRef.id && item.id === projectRef.id) return false;
      if (projectRef.slug && item.slug === projectRef.slug) return false;
      return true;
    });
    syncProjects(nextProjects);
  }

  function setNavigationPending(isPending) {
    var content = document.getElementById('shell-content');
    if (content) content.classList.toggle('is-navigating', !!isPending);
  }

  // ══════════════════════════════════════════════════
  // SVG ICONS (inline, stroke-based, 18px)
  // ══════════════════════════════════════════════════

  const ICONS = {
    dashboard: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    charts: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    runs: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
    models: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
    datasets: '<path d="M21 5c0 1.7-4 3-9 3S3 6.7 3 5s4-3 9-3 9 1.3 9 3Z"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>',
    reviews: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    traces: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    docs: '<path d="M6 2h9l5 5v15a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v6h6"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/>',
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
    const extraClass = opts.className ? ' ' + opts.className : '';
    return '<a class="nav-item' + extraClass + '" href="' + href + '" data-tooltip="' + esc(label) + '" data-page="' + page + '">'
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
      buildNavItem('Charts', 'charts', 'charts', { href: projectSlug ? projectUrl(projectSlug, 'charts') : '#' }),
      buildNavItem('Runs', 'runs', 'runs', { href: projectSlug ? projectUrl(projectSlug) : '#' }),
      buildNavItem('Models', 'models', 'models', { href: projectSlug ? projectUrl(projectSlug, 'models') : '#' }),
      buildNavItem('Reviews', 'reviews', 'reviews', { href: projectSlug ? projectUrl(projectSlug, 'reviews') : '#' }),
      buildNavItem('Datasets', 'datasets', 'datasets', { href: projectSlug ? projectUrl(projectSlug, 'datasets') : '#' }),
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


      // Nav
      + '<nav class="sidebar-nav">'
      +   '<div class="global-nav-items">'
      +     buildNavItem('Projects', 'projects', 'project', { href: root })
      +     buildNavItem('Docs', 'docs', 'docs', { href: root + 'docs-guide' })
      +   '</div>'
      +   '<div class="project-nav-items">' + projectNav + '</div>'
      +   '<div class="nav-section-label nav-section-role-admin">Platform</div>'
      +   buildNavItem('Admin', 'admin', 'admin', { href: root + 'admin', badge: 'Admin', badgeClass: 'admin-tag', className: 'nav-item-role-admin' })
      +   buildNavItem('Deleted Runs', 'trash', 'trash', { href: root + 'trash', className: 'nav-item-role-admin' })
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
    datasets: 'Datasets',
    reviews: 'Reviews',
    traces: 'Traces',
    settings: 'Project Settings',
    admin: 'Admin',
    trash: 'Deleted Runs',
    profile: 'Profile',
    compare: 'Compare',
    docs: 'Docs',
  };

  function computeBreadcrumbs(ctx) {
    var crumbs = [];

    if (ctx.projectSlug && _currentProject) {
      // First crumb = project switcher
      crumbs.push({ label: _currentProject.name, projectSwitcher: true });

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
      crumbs.push({ label: ctx.subId || 'Run Detail', current: true });
    } else {
      crumbs.push({ label: PAGE_LABELS[ctx.page] || 'Home', current: true });
    }

    return crumbs;
  }

  function renderBreadcrumbs(crumbs) {
    var bcEl = document.getElementById('shell-breadcrumbs');
    if (!bcEl) return;
    var html = '';
    for (var i = 0; i < crumbs.length; i++) {
      if (i > 0) html += '<span class="breadcrumb-sep">/</span>';
      var c = crumbs[i];
      if (c.projectSwitcher) {
        // Embedded project switcher as breadcrumb segment
        html += '<div class="breadcrumb-project" id="breadcrumb-project">'
          + '<button class="breadcrumb-project-btn" id="shell-project-trigger">'
          +   '<span class="project-trigger-icon">'
          +     (_currentProject && _currentProject.slug
                  ? identiconHTML(_currentProject.slug, { cell: 2, gap: 1, showEmpty: false })
                  : iconRaw('project', 10, 10))
          +   '</span>'
          +   '<span class="project-trigger-text">' + esc(c.label) + '</span>'
          +   '<span class="project-trigger-chevron">' + iconRaw('chevronDown', 10, 10) + '</span>'
          + '</button>'
          + '<div class="project-popover" id="shell-project-popover">'
          +   '<div class="popover-search"><input type="text" placeholder="Search projects…" id="shell-project-search" /></div>'
          +   '<div class="popover-list" id="shell-project-list"></div>'
          +   '<div class="popover-footer"><button class="popover-footer-btn" id="shell-create-project-btn">' + iconRaw('plus') + ' Create Project</button></div>'
          + '</div>'
          + '</div>';
      } else if (c.current) {
        html += '<span class="breadcrumb-item current">' + esc(c.label) + '</span>';
      } else {
        html += '<a class="breadcrumb-item" href="' + c.href + '">' + esc(c.label) + '</a>';
      }
    }
    bcEl.innerHTML = html;

    // Rebind project switcher events if it was rendered
    bindProjectSwitcherEvents();
  }

  // ══════════════════════════════════════════════════
  // ACTIVE NAV STATE
  // ══════════════════════════════════════════════════

  // Map sub-pages to their parent nav section
  var NAV_PARENT = {
    'run-detail': 'runs',
    'compare': 'runs',
  };

  function setActiveNav(page) {
    var activePage = NAV_PARENT[page] || page;
    var items = document.querySelectorAll('.sidebar .nav-item');
    items.forEach(function (item) {
      var itemPage = item.getAttribute('data-page');
      if (itemPage === activePage) {
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
      html += '<a class="popover-item' + (isActive ? ' active' : '') + '" data-slug="' + esc(p.slug) + '" href="' + projectUrl(p.slug) + '">'
        + '<span class="popover-item-icon">' + identiconHTML(p.slug, { cell: 2, gap: 1, showEmpty: false }) + '</span>'
        + '<span>' + esc(p.name) + '</span>'
        + (isActive ? '<span class="popover-item-check">' + iconRaw('check', 14, 14) + '</span>' : '')
        + '</a>';
    });
    if (!filtered.length) html = '<div style="padding:8px 10px;font-size:var(--font-base);color:var(--text-muted)">No projects found</div>';
    list.innerHTML = html;

    // Bind click handlers
    list.querySelectorAll('.popover-item[data-slug]').forEach(function (item) {
      item.addEventListener('click', function (e) {
        if (isModifiedEvent(e)) return;
        switchProject(item.getAttribute('data-slug'));
        e.preventDefault();
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
    var sidebar = document.getElementById('qym-sidebar');
    if (sidebar) sidebar.dataset.userRole = user.role || '';

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

  function bindProjectSwitcherEvents() {
    var projTrigger = document.getElementById('shell-project-trigger');
    var projPopover = document.getElementById('shell-project-popover');
    if (!projTrigger || !projPopover || projTrigger.dataset.bound) return;
    projTrigger.dataset.bound = '1';

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

    var projSearch = document.getElementById('shell-project-search');
    if (projSearch) {
      projSearch.addEventListener('input', function () {
        renderProjectList(projSearch.value);
      });
    }

    var createBtn = document.getElementById('shell-create-project-btn');
    if (createBtn) {
      createBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        projPopover.classList.remove('open');
        projTrigger.classList.remove('open');
        openCreateProjectDialog();
      });
    }
  }

  function openCreateProjectDialog() {
    // Remove any existing dialog
    var existing = document.getElementById('shell-create-project-dialog');
    if (existing) existing.remove();

    var dialog = document.createElement('div');
    dialog.id = 'shell-create-project-dialog';
    dialog.className = 'shell-modal-backdrop';
    dialog.innerHTML = ''
      + '<div class="shell-modal">'
      +   '<div class="shell-modal-header">'
      +     '<div class="shell-modal-title">Create Project</div>'
      +     '<button class="shell-modal-close qym-icon-action" type="button" aria-label="Close">&times;</button>'
      +   '</div>'
      +   '<div class="shell-modal-body">'
      +     '<div class="shell-form-group">'
      +       '<label class="shell-form-label">Project Name</label>'
      +       '<input class="shell-form-input" id="shell-new-project-name" type="text" placeholder="My Project" autofocus />'
      +     '</div>'
      +     '<div class="shell-form-group">'
      +       '<label class="shell-form-label">Slug</label>'
      +       '<input class="shell-form-input" id="shell-new-project-slug" type="text" placeholder="my-project" style="font-family:var(--font-mono);font-size:var(--font-base)" />'
      +     '</div>'
      +     '<div class="shell-form-group">'
      +       '<label class="shell-form-label">Description (optional)</label>'
      +       '<input class="shell-form-input" id="shell-new-project-desc" type="text" placeholder="What is this project for?" />'
      +     '</div>'
      +     '<div class="shell-form-error" id="shell-new-project-error"></div>'
      +   '</div>'
      +   '<div class="shell-modal-footer">'
      +     '<button class="shell-btn shell-btn-secondary" id="shell-create-cancel" type="button">Cancel</button>'
      +     '<button class="shell-btn shell-btn-primary" id="shell-create-submit" type="button">Create</button>'
      +   '</div>'
      + '</div>';
    document.body.appendChild(dialog);

    var nameInput = document.getElementById('shell-new-project-name');
    var slugInput = document.getElementById('shell-new-project-slug');
    var descInput = document.getElementById('shell-new-project-desc');
    var errorEl = document.getElementById('shell-new-project-error');
    var cancelBtn = document.getElementById('shell-create-cancel');
    var submitBtn = document.getElementById('shell-create-submit');

    // Auto-generate slug from name
    var slugEdited = false;
    slugInput.addEventListener('input', function () { slugEdited = true; });
    nameInput.addEventListener('input', function () {
      if (!slugEdited) {
        slugInput.value = nameInput.value.toLowerCase()
          .replace(/[^a-z0-9\s-]/g, '')
          .trim()
          .replace(/\s+/g, '-');
      }
    });

    setTimeout(function () { nameInput.focus(); }, 50);

    function closeDialog() { dialog.remove(); }

    cancelBtn.addEventListener('click', closeDialog);
    var closeBtn = dialog.querySelector('.shell-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeDialog);
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) closeDialog();
    });
    document.addEventListener('keydown', function escHandler(e) {
      if (e.key === 'Escape') {
        closeDialog();
        document.removeEventListener('keydown', escHandler);
      }
    });

    async function submit() {
      errorEl.textContent = '';
      var name = nameInput.value.trim();
      var slug = slugInput.value.trim();
      if (!name) { errorEl.textContent = 'Name is required'; return; }
      if (!slug) { errorEl.textContent = 'Slug is required'; return; }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Creating...';
      try {
        var res = await fetch(apiUrl('v1/projects'), {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, slug: slug, description: descInput.value.trim() }),
        });
        var data = await res.json().catch(function () { return {}; });
        if (!res.ok) throw new Error(data.detail || 'Failed to create project');
        closeDialog();
        // Refresh projects list and navigate to the new project
        upsertProject(data);
        navigateTo(projectUrl(data.slug));
      } catch (err) {
        errorEl.textContent = err.message || 'Failed to create project';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Create';
      }
    }

    submitBtn.addEventListener('click', submit);
    nameInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
    slugInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
    descInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
  }

  function openConfirmDialog(options) {
    options = options || {};

    var existing = document.getElementById('shell-confirm-dialog');
    if (existing) existing.remove();

    return new Promise(function (resolve) {
      var descriptions = Array.isArray(options.description) ? options.description : [options.description];
      descriptions = descriptions.filter(function (line) { return !!line; });
      var requiredText = options.requireText || '';
      var needsInput = !!requiredText;

      var dialog = document.createElement('div');
      dialog.id = 'shell-confirm-dialog';
      dialog.className = 'shell-modal-backdrop';
      dialog.innerHTML = ''
        + '<div class="shell-modal" role="dialog" aria-modal="true" aria-labelledby="shell-confirm-title">'
        +   '<div class="shell-modal-header">'
        +     '<div class="shell-modal-title" id="shell-confirm-title">' + esc(options.title || 'Confirm Action') + '</div>'
        +     '<button class="shell-modal-close qym-icon-action" type="button" aria-label="Close">&times;</button>'
        +   '</div>'
        +   '<div class="shell-modal-body">'
        +     descriptions.map(function (line) {
                return '<p class="shell-modal-description">' + esc(line) + '</p>';
              }).join('')
        +     (options.note ? '<div class="shell-modal-note">' + esc(options.note) + '</div>' : '')
        +     (needsInput
                ? '<div class="shell-form-group" style="margin-top:var(--space-md)">'
                  + '<label class="shell-form-label">' + esc(options.inputLabel || 'Type to Confirm') + '</label>'
                  + '<input class="shell-form-input" id="shell-confirm-input" type="text" placeholder="' + esc(options.inputPlaceholder || '') + '" autocomplete="off" />'
                  + '</div>'
                : '')
        +     '<div class="shell-form-error" id="shell-confirm-error"></div>'
        +   '</div>'
        +   '<div class="shell-modal-footer">'
        +     '<button class="shell-btn shell-btn-secondary" id="shell-confirm-cancel" type="button">' + esc(options.cancelLabel || 'Cancel') + '</button>'
        +     '<button class="shell-btn ' + (options.confirmClass || 'shell-btn-primary') + '" id="shell-confirm-submit" type="button">' + esc(options.confirmLabel || 'Confirm') + '</button>'
        +   '</div>'
        + '</div>';
      document.body.appendChild(dialog);

      var closeBtn = dialog.querySelector('.shell-modal-close');
      var cancelBtn = document.getElementById('shell-confirm-cancel');
      var confirmBtn = document.getElementById('shell-confirm-submit');
      var input = document.getElementById('shell-confirm-input');
      var errorEl = document.getElementById('shell-confirm-error');

      function currentValue() {
        return input ? input.value.trim() : '';
      }

      function isValid() {
        return !needsInput || currentValue() === requiredText;
      }

      function refreshState() {
        if (confirmBtn) confirmBtn.disabled = needsInput && !isValid();
        if (errorEl && isValid()) errorEl.textContent = '';
      }

      function cleanup() {
        document.removeEventListener('keydown', onKeyDown);
      }

      function close(result) {
        cleanup();
        dialog.remove();
        resolve(result);
      }

      function onKeyDown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          close({ confirmed: false, value: null });
          return;
        }
        if (e.key === 'Enter' && (!input || document.activeElement === input)) {
          e.preventDefault();
          submit();
        }
      }

      function submit() {
        if (!isValid()) {
          if (errorEl) errorEl.textContent = options.mismatchMessage || 'Confirmation text does not match.';
          if (input) input.focus();
          refreshState();
          return;
        }
        close({ confirmed: true, value: currentValue() });
      }

      if (closeBtn) closeBtn.addEventListener('click', function () { close({ confirmed: false, value: null }); });
      if (cancelBtn) cancelBtn.addEventListener('click', function () { close({ confirmed: false, value: null }); });
      if (confirmBtn) confirmBtn.addEventListener('click', submit);
      if (input) {
        input.addEventListener('input', refreshState);
        setTimeout(function () { input.focus(); }, 50);
      } else {
        setTimeout(function () { confirmBtn && confirmBtn.focus(); }, 50);
      }
      dialog.addEventListener('click', function (e) {
        if (e.target === dialog) close({ confirmed: false, value: null });
      });
      document.addEventListener('keydown', onKeyDown);
      refreshState();
    });
  }

  // ══════════════════════════════════════════════════
  // FORM DIALOG (generalized openConfirmDialog with fields)
  // ══════════════════════════════════════════════════

  function openFormDialog(options) {
    options = options || {};
    var fields = Array.isArray(options.fields) ? options.fields : [];

    var existing = document.getElementById('shell-form-dialog');
    if (existing) existing.remove();

    return new Promise(function (resolve) {
      var dialog = document.createElement('div');
      dialog.id = 'shell-form-dialog';
      dialog.className = 'shell-modal-backdrop';

      var fieldsHtml = fields.map(function (f, idx) {
        var id = 'shell-form-field-' + idx;
        var labelHtml = f.label ? '<label class="shell-form-label" for="' + id + '">' + esc(f.label) + '</label>' : '';
        var helpHtml = f.help ? '<div class="shell-modal-note" style="margin-top:4px;">' + esc(f.help) + '</div>' : '';
        var inputHtml = '';
        if (f.type === 'textarea') {
          inputHtml = '<textarea class="shell-form-input" id="' + id + '" data-field="' + esc(f.name) + '" rows="' + (f.rows || 3) + '" placeholder="' + esc(f.placeholder || '') + '">' + esc(f.value || '') + '</textarea>';
        } else if (f.type === 'select') {
          var opts = (f.options || []).map(function (o) {
            var ov = typeof o === 'object' ? o.value : o;
            var ol = typeof o === 'object' ? o.label : o;
            return '<option value="' + esc(ov) + '"' + (String(ov) === String(f.value) ? ' selected' : '') + '>' + esc(ol) + '</option>';
          }).join('');
          inputHtml = '<select class="shell-form-input" id="' + id + '" data-field="' + esc(f.name) + '">' + opts + '</select>';
        } else if (f.type === 'checkbox') {
          inputHtml = '<label class="shell-form-checkbox">'
            + '<input type="checkbox" id="' + id + '" data-field="' + esc(f.name) + '"' + (f.value ? ' checked' : '') + '/>'
            + '<span class="shell-form-checkbox-copy">'
            +   '<span class="shell-form-checkbox-label">' + esc(f.checkboxLabel || f.label || '') + '</span>'
            +   (f.help ? ' <span class="shell-form-checkbox-help">' + esc(f.help) + '</span>' : '')
            + '</span>'
            + '</label>';
          labelHtml = '';
          helpHtml = '';
        } else {
          inputHtml = '<input class="shell-form-input" type="' + (f.type || 'text') + '" id="' + id + '" data-field="' + esc(f.name) + '" placeholder="' + esc(f.placeholder || '') + '" value="' + esc(f.value || '') + '" autocomplete="off" />';
        }
        return '<div class="shell-form-group">' + labelHtml + inputHtml + helpHtml + '</div>';
      }).join('');

      var descHtml = '';
      if (options.description) {
        var lines = Array.isArray(options.description) ? options.description : [options.description];
        descHtml = lines.filter(Boolean).map(function (l) { return '<p class="shell-modal-description">' + esc(l) + '</p>'; }).join('');
      }
      var detailsHtml = '';
      if (Array.isArray(options.details) && options.details.length) {
        detailsHtml = '<div class="shell-modal-detail-list">'
          + options.details.map(function (item) {
            return '<div class="shell-modal-detail-item">'
              + '<span class="shell-modal-detail-icon" aria-hidden="true">' + esc(item.icon || '✓') + '</span>'
              + '<span class="shell-modal-detail-copy">'
              +   '<span class="shell-modal-detail-title">' + esc(item.title || '') + '</span>'
              +   (item.body ? ' <span class="shell-modal-detail-body">' + esc(item.body) + '</span>' : '')
              + '</span>'
              + '</div>';
          }).join('')
          + '</div>';
      }

      dialog.innerHTML = ''
        + '<div class="shell-modal" role="dialog" aria-modal="true" style="width:' + (options.width || 480) + 'px;">'
        +   '<div class="shell-modal-header">'
        +     '<div class="shell-modal-title">' + esc(options.title || 'Form') + '</div>'
        +     '<button class="shell-modal-close qym-icon-action" type="button" aria-label="Close">&times;</button>'
        +   '</div>'
        +   '<div class="shell-modal-body">'
        +     descHtml
        +     detailsHtml
        +     fieldsHtml
        +     '<div class="shell-form-error" id="shell-form-error"></div>'
        +   '</div>'
        +   '<div class="shell-modal-footer">'
        +     '<button class="shell-btn shell-btn-secondary" id="shell-form-cancel" type="button">' + esc(options.cancelLabel || 'Cancel') + '</button>'
        +     '<button class="shell-btn ' + (options.confirmClass || 'shell-btn-primary') + '" id="shell-form-submit" type="button">' + esc(options.confirmLabel || 'Save') + '</button>'
        +   '</div>'
        + '</div>';
      document.body.appendChild(dialog);

      var closeBtn = dialog.querySelector('.shell-modal-close');
      var cancelBtn = document.getElementById('shell-form-cancel');
      var submitBtn = document.getElementById('shell-form-submit');
      var errorEl = document.getElementById('shell-form-error');

      function readValues() {
        var values = {};
        fields.forEach(function (f, idx) {
          var el = document.getElementById('shell-form-field-' + idx);
          if (!el) return;
          if (f.type === 'checkbox') values[f.name] = !!el.checked;
          else values[f.name] = el.value;
        });
        return values;
      }

      function cleanup() { document.removeEventListener('keydown', onKey); }
      function close(result) { cleanup(); dialog.remove(); resolve(result); }
      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); close({ confirmed: false, values: null }); return; }
        if (e.key === 'Enter' && !(e.target && e.target.tagName === 'TEXTAREA')) { e.preventDefault(); submit(); }
      }
      function submit() {
        var values = readValues();
        for (var i = 0; i < fields.length; i++) {
          var f = fields[i];
          var v = values[f.name];
          if (f.required && (v == null || String(v).trim() === '')) {
            errorEl.textContent = (f.label || f.name) + ' is required.';
            var el = document.getElementById('shell-form-field-' + i);
            if (el) el.focus();
            return;
          }
          if (typeof f.validate === 'function') {
            var msg = f.validate(v, values);
            if (msg) { errorEl.textContent = msg; var ef = document.getElementById('shell-form-field-' + i); if (ef) ef.focus(); return; }
          }
        }
        errorEl.textContent = '';

        // When an async onSubmit handler is provided, keep the dialog open while it runs
        // and surface any error inline (instead of closing and losing the user's input).
        if (typeof options.onSubmit === 'function') {
          var prevLabel = submitBtn ? submitBtn.textContent : '';
          if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = options.submittingLabel || 'Saving…'; }
          if (cancelBtn) cancelBtn.disabled = true;
          Promise.resolve()
            .then(function () { return options.onSubmit(values); })
            .then(function () { close({ confirmed: true, values: values }); })
            .catch(function (err) {
              errorEl.textContent = (err && err.message) ? err.message : String(err || 'Something went wrong.');
              if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = prevLabel; }
              if (cancelBtn) cancelBtn.disabled = false;
            });
          return;
        }

        close({ confirmed: true, values: values });
      }

      if (closeBtn) closeBtn.addEventListener('click', function () { close({ confirmed: false, values: null }); });
      if (cancelBtn) cancelBtn.addEventListener('click', function () { close({ confirmed: false, values: null }); });
      if (submitBtn) submitBtn.addEventListener('click', submit);
      dialog.addEventListener('click', function (e) { if (e.target === dialog) close({ confirmed: false, values: null }); });
      document.addEventListener('keydown', onKey);

      setTimeout(function () {
        var firstInput = dialog.querySelector('input,textarea,select');
        if (firstInput) firstInput.focus();
      }, 50);
    });
  }

  // ══════════════════════════════════════════════════
  // DRAWER (right-side panel)
  // ══════════════════════════════════════════════════

  function openDrawer(options) {
    options = options || {};
    var width = options.width || 480;
    var existing = document.getElementById('shell-drawer');
    if (existing) existing.remove();

    var drawer = document.createElement('div');
    drawer.id = 'shell-drawer';
    drawer.className = 'shell-drawer-backdrop';
    drawer.innerHTML = ''
      + '<div class="shell-drawer" role="dialog" aria-modal="true" style="width:' + width + 'px;">'
      +   '<div class="shell-drawer-header">'
      +     '<div class="shell-drawer-title-wrap">'
      +       '<div class="shell-drawer-title" id="shell-drawer-title">' + esc(options.title || '') + '</div>'
      +       (options.subtitle ? '<div class="shell-drawer-subtitle" id="shell-drawer-subtitle">' + esc(options.subtitle) + '</div>' : '<div class="shell-drawer-subtitle" id="shell-drawer-subtitle"></div>')
      +     '</div>'
      +     '<div class="shell-drawer-actions" id="shell-drawer-actions"></div>'
      +     '<button class="shell-modal-close shell-drawer-close qym-icon-action" type="button" aria-label="Close">&times;</button>'
      +   '</div>'
      +   '<div class="shell-drawer-body" id="shell-drawer-body"></div>'
      +   '<div class="shell-drawer-footer" id="shell-drawer-footer" style="display:none;"></div>'
      + '</div>';
    document.body.appendChild(drawer);

    var body = document.getElementById('shell-drawer-body');
    var footer = document.getElementById('shell-drawer-footer');
    var actions = document.getElementById('shell-drawer-actions');
    var closeBtn = drawer.querySelector('.shell-drawer-close');

    function setTitle(t) { var el = document.getElementById('shell-drawer-title'); if (el) el.textContent = t || ''; }
    function setSubtitle(t) { var el = document.getElementById('shell-drawer-subtitle'); if (el) el.textContent = t || ''; }
    function setBody(content) {
      if (!body) return;
      if (typeof content === 'string') body.innerHTML = content;
      else if (content instanceof Node) { body.innerHTML = ''; body.appendChild(content); }
    }
    function setFooter(content) {
      if (!footer) return;
      if (content == null) { footer.style.display = 'none'; footer.innerHTML = ''; return; }
      footer.style.display = '';
      if (typeof content === 'string') footer.innerHTML = content;
      else if (content instanceof Node) { footer.innerHTML = ''; footer.appendChild(content); }
    }
    function setActions(content) {
      if (!actions) return;
      if (Array.isArray(content)) { renderHeaderActions(content); return; }
      if (typeof content === 'string') actions.innerHTML = content;
      else if (content instanceof Node) { actions.innerHTML = ''; actions.appendChild(content); }
    }
    function renderHeaderActions(list) {
      if (!actions) return;
      actions.innerHTML = '';
      (list || []).forEach(function (a) {
        if (!a) return;
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'shell-drawer-header-action qym-icon-action';
        btn.innerHTML = esc(a.icon || a.label || '');
        var tip = a.tooltip || a.title;
        if (tip) { btn.title = tip; btn.setAttribute('aria-label', tip); }
        if (typeof a.onClick === 'function') {
          btn.addEventListener('click', function (e) { e.preventDefault(); a.onClick(api, e); });
        }
        actions.appendChild(btn);
      });
    }

    // Render any header actions supplied up-front.
    if (options.headerActions) renderHeaderActions(options.headerActions);

    var api = {
      el: drawer,
      body: body,
      footer: footer,
      actions: actions,
      setTitle: setTitle,
      setSubtitle: setSubtitle,
      setBody: setBody,
      setFooter: setFooter,
      setActions: setActions,
      close: function () { cleanup(); drawer.remove(); document.dispatchEvent(new CustomEvent('qym:drawer-close')); if (typeof options.onClose === 'function') options.onClose(); },
    };

    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); api.close(); return; }
      if (typeof options.onKey === 'function') options.onKey(e, api);
    }
    function cleanup() { document.removeEventListener('keydown', onKey); }

    if (closeBtn) closeBtn.addEventListener('click', api.close);
    drawer.addEventListener('click', function (e) {
      if (e.target === drawer && options.dismissOnBackdrop !== false) api.close();
    });
    document.addEventListener('keydown', onKey);

    if (typeof options.render === 'function') options.render(api);
    document.dispatchEvent(new CustomEvent('qym:drawer-open'));

    return api;
  }

  function bindEvents() {
    // Collapse toggle
    var collapseBtn = document.getElementById('shell-collapse-btn');
    if (collapseBtn) {
      collapseBtn.addEventListener('click', function () { toggleSidebar(); });
    }

    // Project switcher (in breadcrumbs)
    bindProjectSwitcherEvents();

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
      var projPopover = document.getElementById('shell-project-popover');
      var projTrigger = document.getElementById('shell-project-trigger');
      if (projPopover && !e.target.closest('.breadcrumb-project')) {
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
        var projPopover = document.getElementById('shell-project-popover');
        var projTrigger = document.getElementById('shell-project-trigger');
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
    navigateTo(projectUrl(slug));
  }

  // ══════════════════════════════════════════════════
  // AJAX NAVIGATION (SPA-like content swap)
  // ══════════════════════════════════════════════════

  var _navigating = false;

  function navigateTo(url, opts) {
    opts = opts || {};
    if (_navigating) return;
    _navigating = true;

    var content = document.getElementById('shell-content');
    document.dispatchEvent(new CustomEvent('qym:before-navigate', { detail: { url: url, opts: opts } }));
    if (!content) { window.location.href = url; return; }

    closeShellPopovers();
    setNavigationPending(true);

    fetchAndSwap(url, opts).then(function () {
      _navigating = false;
      setNavigationPending(false);
    }).catch(function (err) {
      _navigating = false;
      setNavigationPending(false);
      console.error('[QymShell] Navigation failed, falling back:', err);
      window.location.href = url;
    });
  }

  async function fetchAndSwap(url, opts) {
    opts = opts || {};
    var res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var html = await res.text();

    // Parse the fetched HTML
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, 'text/html');

    // Update page title
    var newTitle = doc.querySelector('title');
    if (newTitle) document.title = newTitle.textContent;

    // Collect page-specific <style> tags from <head>
    var newStyles = doc.querySelectorAll('head > style');

    // Collect all body content (this is what shell would wrap)
    var newBody = doc.body;

    // Remove shell/auth scripts from the new content — they're singletons
    // that must not re-execute (they'd re-init the shell itself).
    newBody.querySelectorAll('script[src*="shell.js"], script[src*="auth.js"]').forEach(function (s) { s.remove(); });

    // Remove previously-injected page scripts so re-execution works cleanly.
    // Stateless libs (metrics.js) stay cached by the browser but will be
    // re-executed; that's a no-op because they only define globals.
    document.querySelectorAll('script[data-shell-exec]').forEach(function (s) { s.remove(); });

    // Extract scripts from BOTH head and body. The new page may declare
    // scripts in <head> (e.g. run.html loads metrics.js, trace_viewer.js,
    // playground.js there).
    var scriptInfos = [];
    var allScripts = [].concat(
      Array.prototype.slice.call(doc.head.querySelectorAll('script')),
      Array.prototype.slice.call(newBody.querySelectorAll('script'))
    );
    allScripts.forEach(function (script) {
      if (script.src && (script.src.indexOf('shell.js') !== -1 || script.src.indexOf('auth.js') !== -1)) return;
      scriptInfos.push({
        src: script.src || null,
        text: script.textContent || '',
        type: script.type || '',
      });
      script.remove();
    });

    // Get the content area
    var content = document.getElementById('shell-content');
    if (!content) throw new Error('No shell-content');

    // Remove old page-specific styles
    document.querySelectorAll('style[data-shell-page]').forEach(function (s) { s.remove(); });

    // Keep route-local rules before the canonical component layer. Appending
    // them to <head> made legacy page CSS win only after client-side
    // navigation, even though a full load had the correct source order.
    var sharedComponentsLink = document.querySelector('link[href*="ui_components.css"]');
    newStyles.forEach(function (style) {
      var s = document.createElement('style');
      s.setAttribute('data-shell-page', '1');
      s.textContent = style.textContent;
      document.head.insertBefore(s, sharedComponentsLink || null);
    });

    var fragment = document.createDocumentFragment();
    while (newBody.firstChild) {
      fragment.appendChild(newBody.firstChild);
    }
    content.replaceChildren(fragment);

    if (opts.historyMode !== 'none') {
      history.pushState({ qym: true }, '', url);
    }

    _routeCtx = parseRoute();
    setActiveNav(_routeCtx.page);
    updateCurrentProjectForRoute();

    if (_routeCtx.projectSlug && _user && !projectExists(_routeCtx.projectSlug)) {
      renderProjectNotFound(_routeCtx.projectSlug);
      return;
    }

    renderBreadcrumbs(computeBreadcrumbs(_routeCtx));
    setTopbarStats([]);
    content.scrollTop = 0;

    // Expose the shell user before page scripts run so route scripts can
    // render immediately without waiting for a second shell-ready cycle.
    window.__QYM_USER__ = _user;

    for (var i = 0; i < scriptInfos.length; i++) {
      await executeScript(scriptInfos[i]);
    }

    document.dispatchEvent(new CustomEvent('qym:shell-ready'));
  }

  function executeScript(info) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      if (info.type) s.type = info.type;
      s.setAttribute('data-shell-exec', '1');

      if (info.src) {
        s.src = info.src;
        s.onload = function () { resolve(); };
        s.onerror = function () { reject(new Error('Failed to load script: ' + info.src)); };
        document.body.appendChild(s);
        return;
      }

      if (info.text) {
        s.textContent = info.text;
      }
      document.body.appendChild(s);
      resolve();
    });
  }

  function rebuildNavHrefs() {
    var slug = _routeCtx.projectSlug;
    if (!slug) return;
    var mapping = {
      'overview': projectUrl(slug, 'overview'),
      'charts': projectUrl(slug, 'charts'),
      'runs': projectUrl(slug),
      'models': projectUrl(slug, 'models'),
      'datasets': projectUrl(slug, 'datasets'),
      'reviews': projectUrl(slug, 'reviews'),
      'traces': '#',
      'settings': projectUrl(slug, 'settings'),
    };
    document.querySelectorAll('.sidebar .nav-item[data-page]').forEach(function (item) {
      var page = item.getAttribute('data-page');
      if (mapping[page]) item.setAttribute('href', mapping[page]);
    });
  }

  function interceptNavClicks() {
    document.addEventListener('click', function (e) {
      var link = e.target.closest('#qym-app a[href]');
      if (!canInterceptLink(link, e)) return;
      e.preventDefault();
      navigateTo(link.getAttribute('href'));
    });

    window.addEventListener('popstate', function () {
      var event = new CustomEvent('qym:popstate', {
        cancelable: true,
        detail: { url: window.location.pathname + window.location.search },
      });
      if (!document.dispatchEvent(event)) return;
      navigateTo(window.location.pathname + window.location.search, { historyMode: 'none' });
    });
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

    // The inline styles present on the initial full-page load belong to that
    // route. Mark them so the first client-side navigation removes them just
    // like styles injected by later navigations.
    document.querySelectorAll('head > style:not([data-shell-page])').forEach(function (style) {
      style.setAttribute('data-shell-page', '1');
    });

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
    sidebar.dataset.userRole = '';
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

    history.replaceState({ qym: true }, '', window.location.href);

    // Bind events
    bindEvents();

    // Intercept nav clicks for SPA-like navigation
    interceptNavClicks();

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

      // Fetch all projects for the switcher
      _projects = _user.projects || [];
      updateCurrentProjectForRoute();
      if (_routeCtx.projectSlug && !projectExists(_routeCtx.projectSlug)) {
        renderProjectNotFound(_routeCtx.projectSlug);
        return;
      }
      renderBreadcrumbs(computeBreadcrumbs(_routeCtx));
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

  // Deterministic entity identicon (datasets, projects, ...): an FNV-1a hash
  // of the seed picks a hue (continuous, 0-360 — quantized palettes made
  // unrelated entities share colors) and a horizontally symmetric 5x5 fill
  // pattern, so the same seed renders the same mark on every page and two
  // different seeds practically never render the same one.
  function identiconHTML(seed, opts) {
    opts = opts || {};
    var cell = opts.cell || 10;
    var gap = opts.gap != null ? opts.gap : 3;
    var s = String(seed || '');
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    h >>>= 0;
    var hue = h % 360;
    var palette = ['hsl(' + hue + ', 66%, 58%)', 'hsl(' + hue + ', 70%, 40%)'];
    var halves = [];
    var bits = h, filled = 0;
    for (var row = 0; row < 5; row++) {
      halves.push([null, null, null]);
      for (var col = 0; col < 3; col++) {
        bits = Math.imul(bits ^ (row * 3 + col + 0x9e3779b9), 16777619) >>> 0;
        bits = (bits ^ (bits >>> 13)) >>> 0;
        var v = bits % 4;
        halves[row][col] = v >= 2 ? palette[v - 2] : null;
        if (halves[row][col]) filled++;
      }
    }
    // Very sparse patterns read as near-identical specks — densify from the
    // same full-entropy stream (position AND shade) until the mark has body.
    for (var k = 0; filled < 4 && k < 30; k++) {
      bits = Math.imul(bits ^ (k + 0x85ebca6b), 16777619) >>> 0;
      bits = (bits ^ (bits >>> 13)) >>> 0;
      var at = bits % 15;
      var fr = (at / 3) | 0, fc = at % 3;
      if (!halves[fr][fc]) { halves[fr][fc] = palette[bits % 2]; filled++; }
    }
    var rows = halves.map(function (half) { return [half[0], half[1], half[2], half[1], half[0]]; });
    var radius = Math.max(1, Math.round(cell / 5));
    var cells = '';
    rows.forEach(function (cols) {
      cols.forEach(function (color) {
        var bg = color ? ';background:' + color : (opts.showEmpty === false ? ';background:transparent' : '');
        cells += '<i style="border-radius:' + radius + 'px' + bg + '"></i>';
      });
    });
    var style = 'grid-template-columns:repeat(5,' + cell + 'px);grid-auto-rows:' + cell + 'px;gap:' + gap + 'px';
    var cls = 'qym-identicon' + (opts.className ? ' ' + esc(opts.className) : '');
    var mark = '<span class="' + cls + '" aria-hidden="true" style="' + style + '">' + cells + '</span>';
    if (!opts.chip) return mark;
    // Small rounded container for inline/text contexts where a bare mark
    // reads as noise (run meta lines, pickers, ...).
    var size = 5 * cell + 4 * gap + 6;
    return '<span class="qym-identicon-chip" aria-hidden="true" style="width:' + size + 'px;height:' + size + 'px">' + mark + '</span>';
  }
  function identicon(seed, opts) {
    var host = document.createElement('span');
    host.innerHTML = identiconHTML(seed, opts);
    return host.firstChild;
  }

  // The resolved version label, meant to sit INSIDE the dataset-name block — a divider +
  // muted mono style makes it visually distinct from the name. Empty for ad-hoc/CSV runs.
  function datasetVersionInline(version) {
    return version ? '<span class="ds-version" title="Dataset version">' + esc(version) + '</span>' : '';
  }
  // Trailing alias tags for a dataset reference (production shown as "prod"), placed AFTER
  // the name block. Empty when there are no aliases.
  function datasetAliasTags(aliases) {
    var list = Array.isArray(aliases) ? aliases : [];
    var html = '';
    list.forEach(function (a) {
      var label = a === 'production' ? 'prod' : a;
      var cls = 'ds-alias' + (a === 'production' ? ' production' : '');
      html += '<span class="' + cls + '" title="' + esc(a) + '">' + esc(label) + '</span>';
    });
    return html;
  }

  window.QymShell = {
    init: init,
    identicon: identicon,
    identiconHTML: identiconHTML,
    datasetVersionInline: datasetVersionInline,
    datasetAliasTags: datasetAliasTags,
    getUser: function () { return _user; },
    getProject: function () { return _currentProject; },
    getPageContext: function () { return _routeCtx; },
    switchProject: switchProject,
    setTopbarStats: setTopbarStats,
    setBreadcrumbs: renderBreadcrumbs,
    toggleSidebar: toggleSidebar,
    toast: toast,
    apiUrl: apiUrl,
    navigateTo: navigateTo,
    openCreateProjectDialog: openCreateProjectDialog,
    openConfirmDialog: openConfirmDialog,
    upsertProject: upsertProject,
    removeProject: removeProject,
    projectExists: projectExists,
    renderProjectNotFound: renderProjectNotFound,
    openFormDialog: openFormDialog,
    openDrawer: openDrawer,
  };

  // Auto-init on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
