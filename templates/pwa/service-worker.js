{% load static %}
/* PFC optional PWA worker.
 *
 * Dynamic pages, scores, registrations, tournaments, events, APIs and WebSocket
 * workflows are deliberately network-only. Only the app shell and immutable
 * static assets are cached for reliable installed-app startup.
 */
const CACHE_NAME = 'pfc-app-shell-v1';
const APP_SHELL = [
  '/manifest.webmanifest',
  '{% static "pwa/pfc-icon-192.png" %}',
  '{% static "pwa/pfc-icon-512.png" %}',
  '{% static "pfcLOGO.svg" %}',
  '{% static "PFCtextwhite.svg" %}',
  '{% static "css/styles.css" %}',
  '{% static "pwa/offline.html" %}',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => key.startsWith('pfc-app-shell-') && key !== CACHE_NAME)
        .map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Never cache mutations, cross-origin content, navigations, API responses, or
  // dynamic page data. This keeps scores, registrations, event state, and
  // tournament information authoritative and network-fresh.
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/matches/') ||
    url.pathname.startsWith('/tournaments/') ||
    url.pathname.startsWith('/signin/') ||
    url.pathname.startsWith('/friendly-games/') ||
    url.pathname.startsWith('/billboard/') ||
    url.pathname.startsWith('/invites/') ||
    url.pathname.startsWith('/track/') ||
    url.pathname.startsWith('/my-matches/') ||
    url.pathname.startsWith('/simple/')
  ) {
    return;
  }

  // Always request pages from the network. If offline, show only a neutral
  // connection-required page instead of any cached tournament or score state.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('{% static "pwa/offline.html" %}'))
    );
    return;
  }

  // Cache-first applies only to versioned static assets. WhiteNoise serves these
  // with content hashes in production, so a refreshed deployment obtains a new
  // URL instead of stale app code.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (!response || !response.ok || response.type !== 'basic') return response;
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        });
      })
    );
  }
});

// Optional Web Push. Push payloads are prompts only: they contain no
// authoritative Match state and notification clicks only focus/open PFC root.
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (error) { data = {}; }
  const body = String(data.body || '');
  const title = String(data.title || 'PFC');
  const tag = String(data.tag || 'pfc-notification');
  const requestedUrl = String(data.url || '/');
  const target = new URL(requestedUrl, self.location.origin);
  const safeUrl = target.origin === self.location.origin ? target.pathname + target.search : '/';

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: '{% static "pwa/pfc-icon-192.png" %}',
      badge: '{% static "pwa/pfc-icon-192.png" %}',
      tag,
      renotify: false,
      data: { url: safeUrl },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = new URL(
    (event.notification.data && event.notification.data.url) || '/',
    self.location.origin
  ).href;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) return client.focus();
      }
      for (const client of clientList) {
        if (!client.url.startsWith(self.location.origin)) continue;
        if ('navigate' in client && 'focus' in client) {
          return client.navigate(targetUrl).then(function () { return client.focus(); });
        }
        if ('focus' in client) return client.focus();
      }
      return clients.openWindow ? clients.openWindow(targetUrl) : undefined;
    })
  );
});

// The browser can invalidate a subscription while PFC is closed. The worker
// cannot safely use a CSRF-protected account endpoint on its own, so it asks an
// open PFC page to refresh the existing opt-in without requesting permission.
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      clientList.forEach((client) => client.postMessage({
        type: 'pfc:pushsubscriptionchange',
      }));
    })
  );
});
