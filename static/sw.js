// Service Worker para YuIA PWA
// Versão do cache - atualize quando houver mudanças
const CACHE_VERSION = 'v1.0.0';
const CACHE_NAME = `yuia-cache-${CACHE_VERSION}`;
const RUNTIME_CACHE = `yuia-runtime-${CACHE_VERSION}`;

// Arquivos essenciais para cache inicial
const PRECACHE_URLS = [
  '/',
  '/manifest.json',
  '/static/favicon.png',
  '/static/web-app-manifest-192x192.png',
  '/static/web-app-manifest-512x512.png',
  '/static/user.png',
  '/offline.html'
];

// Padrões de URL que devem ser sempre buscados da rede
const NETWORK_ONLY_PATTERNS = [
  /\/api\//,
  /\/socket\.io\//,
  /\/ws\//,
  /\.hot-update\./
];

// Padrões de URL que devem ser cacheados
const CACHEABLE_PATTERNS = [
  /\/static\//,
  /\/assets\//,
  /\/_app\//,
  /\.(?:js|css|png|jpg|jpeg|svg|gif|webp|woff|woff2|ttf|eot)$/
];

// Install event - cacheia arquivos essenciais
self.addEventListener('install', (event) => {
  console.log('[Service Worker] Instalando...', CACHE_VERSION);
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[Service Worker] Pré-cache de arquivos essenciais');
        return cache.addAll(PRECACHE_URLS.map(url => new Request(url, { cache: 'reload' })));
      })
      .then(() => self.skipWaiting())
      .catch((error) => {
        console.error('[Service Worker] Erro no pré-cache:', error);
      })
  );
});

// Activate event - limpa caches antigos
self.addEventListener('activate', (event) => {
  console.log('[Service Worker] Ativando...', CACHE_VERSION);
  
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName.startsWith('yuia-') && cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE) {
            console.log('[Service Worker] Removendo cache antigo:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - estratégia de cache
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignora requisições de outras origens (exceto assets)
  if (url.origin !== location.origin && !request.url.includes('/static/')) {
    return;
  }

  // Network-only para APIs e WebSockets
  if (NETWORK_ONLY_PATTERNS.some(pattern => pattern.test(request.url))) {
    event.respondWith(fetch(request));
    return;
  }

  // Cache-first para recursos estáticos
  if (CACHEABLE_PATTERNS.some(pattern => pattern.test(request.url))) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // Network-first para navegação e HTML
  if (request.mode === 'navigate' || request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Padrão: Network-first
  event.respondWith(networkFirst(request));
});

// Estratégia Cache-First
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  
  if (cached) {
    // Retorna do cache e atualiza em background
    fetchAndCache(request, cache);
    return cached;
  }
  
  try {
    const response = await fetch(request);
    if (response.ok && request.method === 'GET') {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    console.error('[Service Worker] Erro no fetch:', error);
    throw error;
  }
}

// Estratégia Network-First
async function networkFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  
  try {
    const response = await fetch(request);
    if (response.ok && request.method === 'GET') {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    
    // Se for navegação e não há cache, retorna página offline
    if (request.mode === 'navigate') {
      const offlineCache = await caches.open(CACHE_NAME);
      const fallback = await offlineCache.match('/offline.html');
      if (fallback) {
        return fallback;
      }
    }
    
    throw error;
  }
}

// Atualiza cache em background
async function fetchAndCache(request, cache) {
  try {
    const response = await fetch(request);
    if (response.ok && request.method === 'GET') {
      cache.put(request, response.clone());
    }
  } catch (error) {
    // Ignora erros silenciosamente em background
  }
}

// Handler para mensagens do cliente
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    event.waitUntil(
      caches.keys().then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName.startsWith('yuia-')) {
              return caches.delete(cacheName);
            }
          })
        );
      })
    );
  }
});

// Background Sync - para operações offline
self.addEventListener('sync', (event) => {
  console.log('[Service Worker] Background sync:', event.tag);
  
  if (event.tag === 'sync-messages') {
    event.waitUntil(syncMessages());
  }
});

async function syncMessages() {
  // Implementar lógica de sincronização de mensagens quando online
  console.log('[Service Worker] Sincronizando mensagens...');
}

// Push notifications
self.addEventListener('push', (event) => {
  const options = {
    body: event.data ? event.data.text() : 'Nova notificação do YuIA',
    icon: '/static/web-app-manifest-192x192.png',
    badge: '/static/favicon.png',
    vibrate: [100, 50, 100],
    data: {
      dateOfArrival: Date.now(),
      primaryKey: 1
    }
  };

  event.waitUntil(
    self.registration.showNotification('YuIA', options)
  );
});

// Notification click
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        // Se já há uma janela aberta, foca nela
        for (const client of clientList) {
          if (client.url === self.registration.scope && 'focus' in client) {
            return client.focus();
          }
        }
        // Senão, abre uma nova janela
        if (clients.openWindow) {
          return clients.openWindow('/');
        }
      })
  );
});

console.log('[Service Worker] Carregado:', CACHE_VERSION);
