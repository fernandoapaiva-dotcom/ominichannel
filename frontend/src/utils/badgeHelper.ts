import { Conversation, User } from '../types';

export const isGroupConversation = (conv: Conversation): boolean => {
  const phone = conv.contact?.telefone || '';
  const name = conv.contact?.nome || '';
  return Boolean(
    phone.includes('@g.us') ||
    phone.startsWith('120363') ||
    phone.includes('-') ||
    phone.length >= 18 ||
    Boolean((conv.dados_adicionais as any)?.is_group) ||
    Boolean((conv.contact?.dados_adicionais as any)?.is_group) ||
    name.startsWith('SERV -') ||
    name.includes('GRUPO') ||
    name.includes('Servweld/Servsolda')
  );
};

export const isConversationPendingForAttendant = (conv: Conversation, user?: User | null): boolean => {
  if (isGroupConversation(conv)) return false;
  const statusLower = String(conv.status || '').toLowerCase();
  if (statusLower === 'encerrada' || statusLower === 'expirada_por_inatividade') return false;

  const isAdmin = user?.role ? String(user.role).toLowerCase() === 'admin' : false;
  if (!isAdmin && user) {
    // If assigned to another attendant, skip
    if (conv.assigned_user_id && conv.assigned_user_id !== user.id) {
      return false;
    }
  }

  const msgs = conv.messages || [];
  if (msgs.length === 0) return false;

  let lastAttendantIndex = -1;
  let lastClientIndex = -1;

  for (let i = 0; i < msgs.length; i++) {
    const r = String(msgs[i].remetente || '').toLowerCase();
    if (r === 'atendente' || r === 'sistema' || r === 'ia' || r === 'bot') {
      lastAttendantIndex = i;
    } else if (r === 'cliente') {
      lastClientIndex = i;
    }
  }

  if (lastClientIndex === -1) return false;

  // If attendant or system answered after the last client message, not pending
  if (lastAttendantIndex !== -1 && lastClientIndex <= lastAttendantIndex) {
    return false;
  }

  const extra = conv.dados_adicionais || {};
  if (extra.pending_dismissed) return false;
  if (extra.marked_as_read) return false;

  const lastClientMsg = msgs[lastClientIndex];
  if (lastClientMsg && lastClientMsg.timestamp) {
    const t = new Date(lastClientMsg.timestamp).getTime();
    if (!isNaN(t) && (Date.now() - t) > 7 * 24 * 60 * 60 * 1000 && !conv.protocol_number) {
      return false;
    }
  }

  return true;
};

export const isGroupPending = (conv: Conversation): boolean => {
  if (!isGroupConversation(conv)) return false;
  const statusLower = String(conv.status || '').toLowerCase();
  if (statusLower === 'encerrada' || statusLower === 'expirada_por_inatividade') return false;

  const extra = conv.dados_adicionais || {};
  if (extra.pending_dismissed) return false;
  if (extra.marked_as_read) return false;

  const msgs = conv.messages || [];
  if (msgs.length === 0) return false;

  let lastAttendantIndex = -1;
  let lastClientIndex = -1;

  for (let i = 0; i < msgs.length; i++) {
    const r = String(msgs[i].remetente || '').toLowerCase();
    if (r === 'atendente' || r === 'sistema' || r === 'ia' || r === 'bot') {
      lastAttendantIndex = i;
    } else if (r === 'cliente') {
      lastClientIndex = i;
    }
  }

  if (lastClientIndex === -1) return false;

  if (lastAttendantIndex !== -1 && lastClientIndex <= lastAttendantIndex) {
    return false;
  }

  const lastClientMsg = msgs[lastClientIndex];
  if (lastClientMsg && lastClientMsg.timestamp) {
    const t = new Date(lastClientMsg.timestamp).getTime();
    if (!isNaN(t) && (Date.now() - t) > 7 * 24 * 60 * 60 * 1000) {
      return false;
    }
  }

  return true;
};

/**
 * Pede permissão nativa de notificações no navegador / Android PWA
 */
export const requestNotificationPermission = async (): Promise<boolean> => {
  if (typeof window === 'undefined' || !('Notification' in window)) return false;
  try {
    const permission = await Notification.requestPermission();
    return permission === 'granted';
  } catch (err) {
    console.warn('Erro ao solicitar permissão de notificação:', err);
    return false;
  }
};

/**
 * Dispara uma notificação nativa do sistema Android para que o Launcher
 * (Samsung One UI, Pixel, etc.) acerte imediatamente o alerta no ícone do app
 */
export const triggerSystemNotification = async (
  title: string,
  body: string,
  isGroup: boolean = false,
  tag: string = 'msg-alert'
) => {
  if (typeof window === 'undefined' || !('Notification' in window)) return;
  if (Notification.permission !== 'granted') return;

  try {
    if ('serviceWorker' in navigator) {
      const reg = await navigator.serviceWorker.ready;
      await reg.showNotification(title, {
        body,
        icon: '/favicon.svg',
        badge: '/favicon.svg',
        tag,
        renotify: true,
        vibrate: [200, 100, 200] as any,
        data: { isGroup }
      });
    } else {
      new Notification(title, {
        body,
        icon: '/favicon.svg',
        tag
      });
    }
  } catch (err) {
    console.warn('Falha ao exibir notificação do sistema:', err);
  }
};

/**
 * Limpa notificações ativas do sistema
 */
export const clearSystemNotifications = async () => {
  if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const notifications = await reg.getNotifications();
    notifications.forEach(n => n.close());
  } catch (err) {
    // ignore
  }
};

/**
 * Atualiza o ícone do app mobile (Badging API do Android / PWA),
 * o Favicon dinâmico e o título da página com os alertas vermelho (chat) e amarelo (grupo).
 */
export const updateAppBadgesAndIcon = (chatCount: number, groupCount: number) => {
  // 1. Android Home Screen PWA Badging API
  const totalCount = chatCount + groupCount;
  if (typeof navigator !== 'undefined' && 'setAppBadge' in navigator) {
    if (totalCount > 0) {
      (navigator as any).setAppBadge(totalCount).catch(() => {});
    } else {
      (navigator as any).clearAppBadge().catch(() => {});
      clearSystemNotifications().catch(() => {});
    }
  }

  if (typeof navigator !== 'undefined' && navigator.serviceWorker?.controller) {
    navigator.serviceWorker.controller.postMessage({
      type: 'SET_BADGE',
      count: totalCount
    });
  }

  // 2. Título da página com emoji identificador
  let titlePrefix = '';
  if (chatCount > 0 && groupCount > 0) {
    titlePrefix = `🔴(${chatCount}) 🟡(${groupCount}) `;
  } else if (chatCount > 0) {
    titlePrefix = `🔴(${chatCount}) `;
  } else if (groupCount > 0) {
    titlePrefix = `🟡(${groupCount}) `;
  }
  document.title = `${titlePrefix}OminiChannel WhatsApp`;

  // 3. Atualiza Favicon e Apple Touch Icon com o alerta colorido no robô
  let badgeSvgExtra = '';
  if (chatCount > 0 && groupCount > 0) {
    // Ambos: Alerta vermelho (chat) no canto superior direito e amarelo (grupo) no canto superior esquerdo
    badgeSvgExtra = `
      <g id="badge-chat">
        <circle cx="410" cy="102" r="80" fill="#ef4444" stroke="#ffffff" stroke-width="18" />
        <circle cx="410" cy="102" r="38" fill="#ffffff" />
      </g>
      <g id="badge-group">
        <circle cx="102" cy="102" r="80" fill="#f59e0b" stroke="#ffffff" stroke-width="18" />
        <circle cx="102" cy="102" r="38" fill="#ffffff" />
      </g>
    `;
  } else if (chatCount > 0) {
    // Alerta Vermelho de Chat
    badgeSvgExtra = `
      <g id="badge-chat">
        <circle cx="410" cy="102" r="80" fill="#ef4444" stroke="#ffffff" stroke-width="18" />
        <circle cx="410" cy="102" r="38" fill="#ffffff" />
      </g>
    `;
  } else if (groupCount > 0) {
    // Alerta Amarelo de Grupo
    badgeSvgExtra = `
      <g id="badge-group">
        <circle cx="410" cy="102" r="80" fill="#f59e0b" stroke="#ffffff" stroke-width="18" />
        <circle cx="410" cy="102" r="38" fill="#ffffff" />
      </g>
    `;
  }

  const svgContent = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#00f5a0" />
      <stop offset="100%" stop-color="#00d984" />
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="140" fill="url(#bgGrad)" />
  <rect x="236" y="110" width="40" height="44" rx="10" fill="#061f18" />
  <path d="M216 110 L296 110" stroke="#061f18" stroke-width="28" stroke-linecap="round" />
  <line x1="100" y1="285" x2="150" y2="285" stroke="#061f18" stroke-width="28" stroke-linecap="round" />
  <line x1="362" y1="285" x2="412" y2="285" stroke="#061f18" stroke-width="28" stroke-linecap="round" />
  <rect x="135" y="154" width="242" height="230" rx="52" fill="none" stroke="#061f18" stroke-width="32" stroke-linejoin="round" />
  <rect x="195" y="235" width="28" height="68" rx="14" fill="#061f18" />
  <rect x="289" y="235" width="28" height="68" rx="14" fill="#061f18" />
  ${badgeSvgExtra}
</svg>`;

  const dataUri = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgContent)}`;

  const iconLink = document.querySelector("link[rel*='icon']") as HTMLLinkElement;
  if (iconLink) {
    iconLink.href = dataUri;
  }

  const appleLink = document.querySelector("link[rel='apple-touch-icon']") as HTMLLinkElement;
  if (appleLink) {
    appleLink.href = dataUri;
  }
};
