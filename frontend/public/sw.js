// OminiChannel PWA Service Worker
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Listener para Push Notifications em segundo plano
self.addEventListener('push', (event) => {
  if (!event.data) return;

  try {
    const payload = event.data.json();
    const isGroup = Boolean(payload.is_group);
    const title = payload.title || (isGroup ? 'Mensagem no Grupo' : 'Nova Mensagem');
    const body = payload.body || '';
    const unreadCount = Number(payload.unread_count || 1);

    // Atualiza o crachá/badge no ícone do app na tela inicial do celular
    if (self.navigator && 'setAppBadge' in self.navigator) {
      self.navigator.setAppBadge(unreadCount).catch(() => {});
    }

    const options = {
      body,
      icon: '/icon-192.png',
      badge: '/favicon.svg',
      tag: isGroup ? 'group-alert' : 'chat-alert',
      renotify: true,
      data: {
        url: '/',
        is_group: isGroup
      }
    };

    event.waitUntil(self.registration.showNotification(title, options));
  } catch (err) {
    console.debug('[SW] Push payload error:', err);
  }
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url && 'focus' in client) {
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow('/');
      }
    })
  );
});
