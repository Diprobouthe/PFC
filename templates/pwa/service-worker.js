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
