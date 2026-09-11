self.addEventListener("install", (event) => {
  event.waitUntil(caches.open("farmos-shell-v1").then((cache) => cache.addAll(["/", "/scan", "/filament"])));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith("/api/")) return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then((hit) => hit || caches.match("/"))),
  );
});
