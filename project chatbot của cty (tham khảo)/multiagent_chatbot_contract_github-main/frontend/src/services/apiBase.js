const rawBase = (process.env.NEXT_PUBLIC_API_URL || '').trim();
const rawAppUrl = (process.env.NEXT_PUBLIC_APP_URL || '').trim();

// Same-origin by default: frontend calls `/api/v1/...` and nginx forwards internally.
// This prevents exposing backend host/port in browser requests.
export const API_BASE = rawBase === '/' ? '' : rawBase.replace(/\/$/, '');
const APP_BASE = rawAppUrl.replace(/\/$/, '');

export function buildApiUrl(path) {
  if (!path) return API_BASE || '/';
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return API_BASE ? `${API_BASE}${normalizedPath}` : normalizedPath;
}

export function normalizeApiUrl(url) {
  if (!url) return '';
  if (/^(blob:|data:)/i.test(url)) return url;

  const fallbackOrigin = APP_BASE || (typeof window !== 'undefined' ? window.location.origin : 'http://localhost');

  try {
    const resolvedUrl = new URL(url, fallbackOrigin);
    const normalizedPath = `${resolvedUrl.pathname}${resolvedUrl.search}${resolvedUrl.hash}`;

    if (normalizedPath.startsWith('/api/')) {
      return buildApiUrl(normalizedPath);
    }

    return resolvedUrl.toString();
  } catch (_) {
    return url;
  }
}
