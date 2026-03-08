/**
 * SecureAuth Service Worker
 * – Caches app shell for fast load / offline
 * – Handles Web Push events → shows iOS/Android notification
 * – On notification tap → opens or focuses the dashboard
 */

const CACHE = 'secureauth-v2';
const SHELL = ['/', '/index.html', '/styles.css', '/app.js',
               '/icons/icon-192.png', '/icons/icon-512.png'];

// ── Install ───────────────────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate ──────────────────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: live for API, cache-first for shell ────────────────────────
self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) {
    e.respondWith(fetch(e.request));
    return;
  }
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

// ── Push: receive notification from server ────────────────────────────
self.addEventListener('push', e => {
  let payload = {
    title: 'SecureAuth',
    body:  'Authentication request received.',
    url:   '/',
  };

  if (e.data) {
    try { Object.assign(payload, e.data.json()); }
    catch { payload.body = e.data.text(); }
  }

  const options = {
    body:             payload.body,
    icon:             '/icons/icon-192.png',
    badge:            '/icons/icon-192.png',
    tag:              'secureauth-auth-request',   // replaces any previous notification
    renotify:         true,
    requireInteraction: true,                      // keeps notification visible until tapped
    data:             { url: payload.url },
    actions: [
      { action: 'open',    title: 'Review Request' },
      { action: 'dismiss', title: 'Dismiss' },
    ],
  };

  e.waitUntil(self.registration.showNotification(payload.title, options));
});

// ── Notification click: open or focus the app ─────────────────────────
self.addEventListener('notificationclick', e => {
  e.notification.close();

  if (e.action === 'dismiss') return;

  const targetUrl = (e.notification.data && e.notification.data.url) || '/';

  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      // If app is already open — focus it
      for (const client of list) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      // Otherwise open a new window
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
