// Minimal service worker — caches the app shell.
//
// JS is intentionally NOT in the shell cache. Caching it caused a stale-app
// bug where a deploy added new routes but old `app.js` was served from the
// SW cache, breaking navigation. JS is fetched fresh every load; the browser
// HTTP cache still helps repeat-load speed.
const SHELL_CACHE = "dz-shell-v15";
const SHELL_FILES = [
  "/static/css/tokens.css",
  "/static/css/layout.css",
  "/static/css/screens.css",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Non-GET requests (POST / PUT / DELETE / etc.) are never cacheable and
  // must pass straight through to the network. Intercepting a multipart
  // POST through caches.match + fetch produces "TypeError: Load failed"
  // in Safari — the SW was eating /submissions/capture this way before
  // submissions was added to apiPrefixes.
  if (event.request.method !== "GET") {
    return;
  }
  const url = new URL(event.request.url);
  const apiPrefixes = [
    "/auth", "/places", "/missions", "/submissions", "/healthz",
  ];
  if (apiPrefixes.some((p) => url.pathname.startsWith(p))) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request))
  );
});
