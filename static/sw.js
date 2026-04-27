// ─────────────────────────────────────────────────────────────────────────────
// Addarr service worker
// Bump CACHE_NAME any time you change asset behaviour or want clients to
// drop stale entries on their next visit.
// ─────────────────────────────────────────────────────────────────────────────
const CACHE_NAME = 'addarr-cache-v3';

// Pre-cache only the genuine static shell. HTML pages and API responses are
// never pre-cached — that's what was producing ERR_CONTENT_LENGTH_MISMATCH on
// the manage page (a stale/truncated main.js was being served from cache and
// the browser rejected it because the body was shorter than Content-Length).
const PRECACHE_URLS = [
    '/static/css/styles.css',
    '/static/css/manage-page.css',
    '/static/images/logo.png',
    '/static/images/favicon.ico',
    '/static/images/placeholder.png',
    '/static/images/apple-touch-icon.png',
    '/offline.html',
];

// ── Install: pre-cache shell, but never let one bad asset block install ──────
self.addEventListener('install', event => {
    event.waitUntil((async () => {
        const cache = await caches.open(CACHE_NAME);
        // Use individual put() so a single 404/timeout doesn't reject the whole
        // install (cache.addAll is all-or-nothing).
        await Promise.all(PRECACHE_URLS.map(async (url) => {
            try {
                const resp = await fetch(url, { cache: 'reload' });
                if (resp && resp.ok) await cache.put(url, resp.clone());
            } catch (_) { /* ignore — best effort */ }
        }));
        self.skipWaiting();
    })());
});

// ── Activate: drop any caches with names other than the current one ──────────
self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(names.map(n => n === CACHE_NAME ? null : caches.delete(n)));
        await self.clients.claim();
        const clients = await self.clients.matchAll();
        clients.forEach(c => c.postMessage({ type: 'CONTENT_LOADED', message: 'Service worker updated' }));
    })());
});

// ── Helpers ──────────────────────────────────────────────────────────────────
function isStaticAsset(url) {
    return url.pathname.startsWith('/static/');
}

function isHtmlRequest(request) {
    const accept = request.headers.get('accept') || '';
    return request.mode === 'navigate' || accept.includes('text/html');
}

// ── Fetch: route by request type ─────────────────────────────────────────────
self.addEventListener('fetch', event => {
    const req = event.request;

    // Only handle GETs we actually want to manage. Anything else passes through.
    if (req.method !== 'GET') return;

    let url;
    try { url = new URL(req.url); } catch (_) { return; }

    // Skip cross-origin requests (TMDB images, CDN libs, etc.) entirely —
    // letting the browser handle them avoids the redirect / opaque-response
    // pitfalls that produce content-length mismatches.
    if (url.origin !== self.location.origin) return;

    // Never cache or intercept API endpoints. Image proxy, library status,
    // enrichment, etc. must always hit the network with fresh params.
    if (url.pathname.startsWith('/api/')) return;

    // Static assets: stale-while-revalidate. Serve cache fast, refresh in bg.
    if (isStaticAsset(url)) {
        event.respondWith((async () => {
            const cache = await caches.open(CACHE_NAME);
            const cached = await cache.match(req);
            const networkPromise = fetch(req).then(resp => {
                if (resp && resp.ok) cache.put(req, resp.clone()).catch(() => {});
                return resp;
            }).catch(() => null);
            return cached || (await networkPromise) || new Response('', { status: 504 });
        })());
        return;
    }

    // HTML / page navigations: network-first, fall back to offline page.
    if (isHtmlRequest(req)) {
        event.respondWith((async () => {
            try {
                const fresh = await fetch(req);
                return fresh;
            } catch (_) {
                const cache = await caches.open(CACHE_NAME);
                return (await cache.match('/offline.html'))
                    || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
            }
        })());
        return;
    }

    // Anything else (e.g. manifest.json, sw.js itself): network with cache fallback.
    event.respondWith((async () => {
        try {
            return await fetch(req);
        } catch (_) {
            const cache = await caches.open(CACHE_NAME);
            return (await cache.match(req)) || new Response('', { status: 504 });
        }
    })());
});

// ── Allow clients to trigger SKIP_WAITING from page scripts ──────────────────
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
