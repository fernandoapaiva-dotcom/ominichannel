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

// Listener para mensagens diretas vindas da aplicação (setAppBadge / notifications)
self.addEventListener('message', (event) => {
  if (!event.data) return;
  if (event.data.type === 'SET_BADGE') {
    const count = Number(event.data.count || 0);
    const chatCount = Number(event.data.chatCount || 0);
    const groupCount = Number(event.data.groupCount || 0);

    // 1. App Badging API (Chromium / WebAPK)
    if (self.navigator && 'setAppBadge' in self.navigator) {
      if (count > 0) {
        self.navigator.setAppBadge(count).catch(() => {});
      } else {
        self.navigator.clearAppBadge().catch(() => {});
      }
    }

    // 2. Android Launcher Notification Badge (Samsung One UI, Pixel, etc.)
    // Os launchers do Android computam o número no ícone a partir das notificações ativas do app
    if (self.registration && 'showNotification' in self.registration) {
      if (count > 0) {
        let summaryText = '';
        if (chatCount > 0 && groupCount > 0) {
          summaryText = `${chatCount} cliente(s) aguardando • ${groupCount} grupo(s) com novidades`;
        } else if (chatCount > 0) {
          summaryText = `${chatCount} cliente(s) aguardando atendimento`;
        } else {
          summaryText = `${groupCount} grupo(s) com atividade recente`;
        }

        self.registration.showNotification(`OminiChannel (${count})`, {
          body: summaryText,
          icon: '/icon-192.png',
          badge: '/icon-192.png',
          tag: 'ominichannel-badge-summary',
          renotify: false,
          silent: true,
          data: { url: '/' }
        }).catch(() => {});
      } else {
        self.registration.getNotifications({ tag: 'ominichannel-badge-summary' })
          .then(notifs => notifs.forEach(n => n.close()))
          .catch(() => {});
      }
    }
  }
});
