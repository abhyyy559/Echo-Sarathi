/* Site theme: dark-first brand, light as a first-class option.
 * Saved choice wins; otherwise dark (deterministic for demos — we do NOT
 * follow the OS on first visit). Applied to <html data-theme> so every
 * stylesheet (global tokens + generated page scopes) can override.
 */
const KEY = 'es-theme';

export function getTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch { /* private mode etc. */
  }
  return 'dark';
}

export function applyTheme(theme) {
  const t = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = t;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t === 'light' ? '#faf7f1' : '#0a0a0b');
  try {
    localStorage.setItem(KEY, t);
  } catch { /* ignore */
  }
  return t;
}

export function initTheme() {
  return applyTheme(getTheme());
}
