(function () {
  function currentPath() {
    return window.location.pathname + window.location.search;
  }

  function loginUrl(next) {
    const target = next || currentPath();
    return '/login?next=' + encodeURIComponent(target);
  }

  function redirectToLogin(next) {
    window.location.href = loginUrl(next);
  }

  async function logout() {
    try {
      await fetch('/v1/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
      });
    } catch (_) {}
    redirectToLogin('/');
  }

  function handle401(response, next) {
    if (response && response.status === 401) {
      redirectToLogin(next);
      return true;
    }
    return false;
  }

  function renderAuthGate(target, opts) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) {
      redirectToLogin();
      return;
    }
    const title = (opts && opts.title) || 'قيِّم Platform';
    const message = (opts && opts.message) || 'Sign in to continue';
    el.innerHTML = `
      <div style="display:flex;flex:1;width:100%;align-items:center;justify-content:center;min-height:calc(100vh - 100px);">
        <div style="text-align:center;max-width:360px;padding:40px;">
          <img src="/static/qym_icon.png" alt="قيِّم" style="height:64px;margin-bottom:24px;" />
          <h1 style="font-size:24px;font-weight:600;color:var(--text-primary);margin-bottom:8px;">${title}</h1>
          <p style="color:var(--text-muted);margin-bottom:32px;">${message}</p>
          <a href="${loginUrl()}" style="display:inline-flex;width:100%;padding:12px 24px;background:var(--accent-primary);color:var(--bg-base);border:none;border-radius:6px;font-size:14px;font-weight:500;cursor:pointer;align-items:center;justify-content:center;gap:8px;text-decoration:none;">
            Sign in
          </a>
        </div>
      </div>
    `;
  }

  function injectLogoutMenuItem() {
    if (document.querySelector('[data-qym-logout]')) return;
    const menuNav = document.querySelector('.menu-nav');
    if (!menuNav) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'menu-item';
    btn.setAttribute('data-qym-logout', '1');
    btn.style.width = '100%';
    btn.style.background = 'transparent';
    btn.style.border = '0';
    btn.style.textAlign = 'left';
    btn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
        <polyline points="16 17 21 12 16 7"></polyline>
        <line x1="21" y1="12" x2="9" y2="12"></line>
      </svg>
      Logout
    `;
    btn.addEventListener('click', function () { logout(); });
    menuNav.appendChild(btn);
  }

  async function maybePromptBootstrapAdmin(currentUser) {
    // No-op on all pages. Bootstrap is handled on the profile page.
    return;
  }

  document.addEventListener('DOMContentLoaded', injectLogoutMenuItem);

  window.QymAuth = {
    loginUrl: loginUrl,
    redirectToLogin: redirectToLogin,
    handle401: handle401,
    logout: logout,
    renderAuthGate: renderAuthGate,
    injectLogoutMenuItem: injectLogoutMenuItem,
    maybePromptBootstrapAdmin: maybePromptBootstrapAdmin,
  };
})();
