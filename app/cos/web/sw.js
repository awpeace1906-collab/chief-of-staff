// Keeps the app shell available offline; data always comes fresh from the server.
const CACHE = "cos-shell-v1";
const SHELL = ["/", "/static/app.js", "/static/manifest.webmanifest", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/oauth/") || url.pathname === "/login") return;
  // network first, so updates land right away; fall back to the cached shell offline
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok && r.type === "basic" && !r.redirected) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request))
  );
});
