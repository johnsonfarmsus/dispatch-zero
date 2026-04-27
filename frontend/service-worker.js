// Minimal service worker — caches the app shell.
const SHELL_CACHE = "dz-shell-v1";
const SHELL_FILES = [
  "/",
  "/static/css/tokens.css",
  "/static/css/layout.css",
  "/static/css/screens.css",
  "/static/js/app.js",
  "/static/js/router.js",
  "/static/js/api.js",
  "/static/js/state.js",
  "/static/js/dom.js",
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
  const url = new URL(event.request.url);
  const apiPrefixes = ["/auth", "/places", "/missions", "/healthz"];
  if (apiPrefixes.some((p) => url.pathname.startsWith(p))) {
    return;
  }
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request))
  );
});
