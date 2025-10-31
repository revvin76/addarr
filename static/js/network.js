const PREFERRED_BASE_KEY = 'addarr_base_url';

async function fetchJsonWithFallback(path, options = {}, timeoutMs = 5000) {
  const base = await resolveBaseUrl();
  try {
    return await fetchWithTimeout(new URL(path, base).toString(), options, timeoutMs);
  } catch (err) {
    // try duckdns as fallback by asking /api/tunnel/status (server returns duckdns_url)
    try {
      const s = await fetch('/api/tunnel/status', {cache: 'no-store'});
      const info = await s.json();
      const duck = info.duckdns_url || window.location.origin;
      localStorage.setItem(PREFERRED_BASE_KEY, duck);
      return await fetchWithTimeout(new URL(path, duck).toString(), options, timeoutMs);
    } catch (err2) {
      throw err2;
    }
  }
}

async function resolveBaseUrl() {
  const saved = localStorage.getItem(PREFERRED_BASE_KEY);
  if (saved) return saved;

  // Ask server for tunnel status (includes duckdns_url)
  try {
    const res = await fetchWithTimeout('/api/tunnel/status', {}, 4000);
    const info = await res.json();
    if (info.tunnel && info.tunnel.public_url) {
      localStorage.setItem(PREFERRED_BASE_KEY, info.tunnel.public_url);
      return info.tunnel.public_url;
    }
    if (info.duckdns_url) {
      localStorage.setItem(PREFERRED_BASE_KEY, info.duckdns_url);
      return info.duckdns_url;
    }
  } catch (e) {
    // network error -> try duckdns directly if server published it previously
  }
  return window.location.origin;
}

function fetchWithTimeout(resource, options = {}, timeout = 5000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  return fetch(resource, {...options, signal: controller.signal})
    .finally(() => clearTimeout(id));
}