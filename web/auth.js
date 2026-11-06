/* Shared ARTHIQ login guard. Keep this file before each page's inline app script. */
(() => {
  const loginPath = '/login.html';
  if (window.location.pathname.endsWith('/login.html')) return;

  const nativeFetch = window.fetch.bind(window);
  let redirecting = false;
  window.ARTHIQ_AUTH_READY = (async () => {
    try {
      const response = await nativeFetch('/auth/me', { credentials: 'same-origin' });
      if (!response.ok) throw new Error('login required');
      return response.json();
    } catch (_) {
      redirecting = true;
      window.location.replace(loginPath);
      throw new Error('Redirecting to login');
    }
  })();

  // All page API calls wait for the login check before reaching protected endpoints.
  window.fetch = async (...args) => {
    await window.ARTHIQ_AUTH_READY;
    if (redirecting) throw new Error('Redirecting to login');
    return nativeFetch(...args);
  };

  window.addEventListener('DOMContentLoaded', () => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Log out';
    button.setAttribute('aria-label', 'Log out of ARTHIQ');
    button.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:99999;border:0;border-radius:999px;padding:10px 16px;background:#0f172a;color:#fff;font:600 13px system-ui;box-shadow:0 5px 18px #0003;cursor:pointer';
    button.addEventListener('click', async () => {
      try { await nativeFetch('/auth/logout', { method: 'POST', credentials: 'same-origin' }); }
      finally { window.location.replace(loginPath); }
    });
    document.body.appendChild(button);
  });
})();
