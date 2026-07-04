const CACHE_NAME = 'daily-report-cache-v1';
const HTML_FILE = '/portfolio/daily-report.html';

// 安装时预缓存核心文件（非 HTML）
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll([
        '/portfolio/daily-report.html',
      ]).catch(() => {});
    }).then(() => self.skipWaiting())
  );
});

// 激活时接管旧页面
self.addEventListener('activate', event => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // 对日报 HTML 页面：强制网络优先，永远拿最新版本
  if (url.pathname === HTML_FILE) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then(response => {
          // 更新缓存
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        })
        .catch(() => {
          // 网络失败时回退缓存
          return caches.match(event.request).then(cached => cached || new Response('Offline', { status: 503 }));
        })
    );
    return;
  }

  // 对音频 MP3：缓存优先，网络兜底，避免重复下载大文件
  if (url.pathname.endsWith('.mp3')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          return response;
        });
      })
    );
    return;
  }

  // 其他资源：标准网络优先
  event.respondWith(
    fetch(event.request).then(response => {
      const clone = response.clone();
      caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
      return response;
    }).catch(() => caches.match(event.request))
  );
});
