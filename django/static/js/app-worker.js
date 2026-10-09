/* Only fingerprinted public static files can enter this cache. Account data stays online. */
'use strict';
const CACHE_PREFIX = 'applanner-static-';
const CACHE_NAME = CACHE_PREFIX + '20261008-v1';
const STATIC_FILE = /^\/static\/.+\.[a-f0-9]{12}\.(?:css|js|png|jpg|jpeg|webp|svg|woff2?)$/i;
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('message', event => {
  if (event.data?.type === 'APPLANNER_ACTIVATE_UPDATE') event.waitUntil(self.skipWaiting());
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || request.mode === 'navigate' || url.origin !== self.location.origin || !STATIC_FILE.test(url.pathname) || url.search) return;
  event.respondWith((async () => {
    let cache;
    try { cache = await caches.open(CACHE_NAME); } catch { /* Storage can be disabled. */ }
    const publicRequest = new Request(request.url, {credentials:'omit', mode:'same-origin'});
    let hit;
    try { hit = await cache?.match(publicRequest); } catch { /* Keep the network path working. */ }
    if (hit) return hit;
    const response = await fetch(publicRequest);
    const policy = response.headers.get('Cache-Control') || '';
    const type = response.headers.get('Content-Type') || '';
    if (response.ok && !response.redirected && response.type === 'basic' && !/private|no-store/i.test(policy) && !/text\/html|application\/json/i.test(type)) {
      try { await cache?.put(publicRequest, response.clone()); } catch { /* Quota errors cannot break the application. */ }
    }
    return response;
  })());
});
