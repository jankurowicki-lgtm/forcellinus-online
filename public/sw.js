const CACHE = "forcellinus-shell-v9";
const SHELL = [
  "./", "./index.html", "./styles.css?v=8", "./app.js", "./manifest.webmanifest",
  "./icons/icon.svg", "./art/DP828188-edit.webp", "./art/DP828228-edit.webp",
  "./art/DP828189-edit.webp", "./art/nov-21-prints-00001.webp",
  "./data/meta.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      if (response.ok && new URL(event.request.url).origin === location.origin) {
        caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
      }
      return response;
    }).catch(() => caches.match("./index.html")))
  );
});
