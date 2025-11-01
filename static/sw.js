const CACHE_NAME = 'addarr-cache-v1';
const urlsToCache = [
  '/',
  '/static/css/styles.css',
  '/static/images/logo.png',
  '/static/images/favicon.ico',
  '/static/js/main.js'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
  );
});

// Add to sw.js
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        
        return fetch(event.request).catch(() => {
          // For HTML pages, return the offline page
          if (event.request.headers.get('accept').includes('text/html')) {
            return caches.match('/offline.html');
          }
        });
      })
  );
});

// In your service worker, add this message handler
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

// Notify clients when new content is available
self.addEventListener('activate', (event) => {
    event.waitUntil(
        self.clients.matchAll().then((clients) => {
            clients.forEach((client) => {
                client.postMessage({
                    type: 'CONTENT_LOADED',
                    message: 'New content is available'
                });
            });
        })
    );
});