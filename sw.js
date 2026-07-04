const CACHE_NAME = 'daily-report-cache-v1';
const HTML_FILE = '/portfolio/daily-report.html';

self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // HTML 和 MP3 均网络优先：永远拿最新版本
  if (url.pathname === HTML_FILE || url.pathname.endsWith('.mp3')) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then(fresh => {
          const clone = fresh.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return fresh;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // 其他资源：网络优先
  event.respondWith(
    fetch(event.request).then(fresh => {
      const clone = fresh.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
      return fresh;
    }).catch(() => caches.match(event.request))
  );
});
