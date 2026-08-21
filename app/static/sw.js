/* V Push Service Worker —— network-first：静态外壳离线可用，API 永不缓存 */
const CACHE = "dav-shell-v81";
const SHELL = [
  "/",
  "/app.js",
  "/style.css",
  "/vendor/design-tokens.css",
  "/logo.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-192-dark.png",
  "/icon-512-dark.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  let url;
  try {
    url = new URL(e.request.url);
  } catch {
    return;
  }
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // 动态数据永不缓存
  if (url.pathname.startsWith("/feed/")) return; // 私有 RSS：token 即凭证，永不缓存
  e.respondWith(networkFirst(e.request));
});

self.addEventListener("push", (e) => {
  let data = {};
  try {
    data = e.data ? e.data.json() : {};
  } catch {
    data = { body: e.data ? e.data.text() : "" };
  }
  e.waitUntil(self.registration.showNotification(data.title || "V Push", {
    body: data.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: data.url || "/" },
    tag: data.tag || "vpush",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if ("focus" in client) {
        await client.focus();
        if ("navigate" in client && url) await client.navigate(url);
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});

async function networkFirst(req) {
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) {
      const cache = await caches.open(CACHE);
      // 用裸路径作缓存键，避免 ?v= 版本号 query 撑爆缓存
      cache.put(new Request(new URL(req.url).pathname), fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await caches.match(req, { ignoreSearch: true });
    return cached || Response.error();
  }
}
