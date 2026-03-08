/**
 * SecureAuth Service Worker
 * – Makes the app installable as a PWA on iOS (Safari → Add to Home Screen)
 * – Caches shell assets for fast load; always fetches API calls live from network
 */

const CACHE    = 'secureauth-v1';
const SHELL    = ['/', '/index.html', '/styles.css', '/app.js',
                  '/icons/icon-192.png', '/icons/icon-512.png'];

// ── Install: pre-cache the app shell ─────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ───────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API, cache-first for shell ───────────────
self.addEventListener('fetch', e => {
  // Always go live for API calls
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request));
    return;
  }
  // Shell: cache first, fall back to network
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
