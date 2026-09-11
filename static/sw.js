// Minimal service worker: exists mainly to satisfy PWA installability criteria
// (Chrome/Android require a registered service worker with a fetch handler before
// showing an install prompt), not to cache the dashboard itself. The site's whole
// point is live data, so the HTML/data are always network-fetched, never served
// stale from a cache -- only the static icons/manifest get a cache-first fallback,
// since those never change and speed up the initial app-shell paint.
const CACHE_NAME = "teka-static-v1";
const STATIC_ASSETS = [
  "icon-192.png",
  "icon-512.png",
  "icon-maskable-512.png",
  "manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .catch(() => {})
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isStaticAsset = STATIC_ASSETS.some((name) => url.pathname.endsWith(name));
  if (isStaticAsset) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
    return;
  }
  event.respondWith(fetch(event.request));
});
