/* Only fingerprinted public static files can enter this cache. Account data stays online. */
'use strict';
const CACHE_PREFIX = 'applanner-static-';
const CACHE_NAME = CACHE_PREFIX + '20261030-clinical-v1';
const CLINICAL_CACHE = 'applanner-clinical-shell-v1';
const STATIC_FILE = /^\/static\/.+\.[a-f0-9]{12}\.(?:css|js|png|jpg|jpeg|webp|svg|woff2?)$/i;
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('message', event => {
  if (event.data?.type === 'CLINICAL_PREPARE') {
    event.waitUntil((async () => {
      try {
        const cache = await caches.open(CLINICAL_CACHE);
        // Fixed, server-built allowlist. No account HTML, cookies, JSON or PHI.
        for (const path of CLINICAL_OFFLINE_ASSETS) {
          const response = await fetch(new Request(new URL(path, self.location.origin), {credentials:'omit', cache:'reload'}));
          if (!response.ok || response.redirected) throw Error('Offline shell unavailable');
          await cache.put(path, response);
        }
        event.ports[0]?.postMessage({ok:true});
      } catch { event.ports[0]?.postMessage({ok:false}); }
    })());
  }
  if (event.data?.type === 'APPLANNER_ACTIVATE_UPDATE') event.waitUntil(self.skipWaiting());
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method === 'GET' && url.origin === self.location.origin && !url.search &&
      typeof CLINICAL_OFFLINE_ASSETS !== 'undefined' && CLINICAL_OFFLINE_ASSETS.includes(url.pathname)) {
    event.respondWith((async () => {
      // Only the opt-in shell has an offline navigation fallback. Private pages never do.
      try { return await fetch(request); }
      catch { return (await caches.open(CLINICAL_CACHE)).match(url.pathname); }
    })());
    return;
  }
  if (request.method !== 'GET' || request.mode === 'navigate' || url.origin !== self.location.origin || !STATIC_FILE.test(url.pathname) || url.search) return;
  event.respondWith((async () => {
    let cache;
    try { cache = await caches.open(CACHE_NAME); } catch { /* Storage can be disabled. */ }
    const publicRequest = new Request(request.url, {credentials:'omit', mode:'same-origin'});
    let hit;
    try { hit = await cache?.match(publicRequest); } catch { /* Keep the network path working. */ }
    if (!hit) { try { hit = await (await caches.open(CLINICAL_CACHE)).match(publicRequest); } catch {} }
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

self.addEventListener('push',event=>{let data={};try{data=event.data?.json()||{};}catch{}const target=new URL(data.url||'/',self.location.origin);const url=target.origin===self.location.origin?target.pathname+target.search:'/';event.waitUntil(self.registration.showNotification(String(data.title||'ApPlanner').slice(0,120),{body:String(data.body||'Abra o aplicativo para conferir sua agenda.').slice(0,240),tag:String(data.tag||'applanner'),data:{url}}));});
self.addEventListener('notificationclick',event=>{event.notification.close();const target=new URL(event.notification.data?.url||'/',self.location.origin);if(target.origin!==self.location.origin)return;event.waitUntil((async()=>{const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});for(const client of windows){if('focus'in client){await client.navigate(target.href);return client.focus();}}return self.clients.openWindow(target.href);})());});
