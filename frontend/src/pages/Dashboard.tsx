import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { User, Conversation, WhatsAppNumber, ConversationStatus } from '../types';
import { apiFetch } from '../services/api';
import { Sidebar } from '../components/Sidebar';
import { ChatList } from '../components/ChatList';
import { ChatArea } from '../components/ChatArea';
import { TransferModal } from '../components/TransferModal';
import { AdminPanel } from '../components/AdminPanel';
import { ContactsPanel } from '../components/ContactsPanel';
import { SegmentationPanel } from '../components/SegmentationPanel';
import { NewConversationModal } from '../components/NewConversationModal';
import { MediaGalleryModal } from '../components/MediaGalleryModal';
import { SyncTaskbar } from '../components/SyncTaskbar';
import { CalendarModal } from '../components/CalendarModal';

import { DepartmentBar } from '../components/DepartmentBar';
import { MobileBottomNav } from '../components/MobileBottomNav';
import {
  isConversationPendingForAttendant,
  isGroupPending,
  updateAppBadgesAndIcon,
  triggerSystemNotification,
  requestNotificationPermission
} from '../utils/badgeHelper';

interface DashboardProps {
  user: User;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ user, onLogout }) => {
  const [activeTab, setActiveTab] = useState<'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin'>('chats');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<number | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<ConversationStatus | 'all' | 'nao_lidas'>('all');
  const [isCalendarOpen, setIsCalendarOpen] = useState<boolean>(false);
  const [calendarPrefill, setCalendarPrefill] = useState<any>(null);
  const [calendarSummary, setCalendarSummary] = useState<{ today_pending: number; overdue: number; total_pending: number } | null>(null);

  // WhatsApp-style individual conversation drafts (Rascunhos por cliente)
  const [conversationDrafts, setConversationDrafts] = useState<{ [convId: number]: string }>(() => {
    try {
      const saved = localStorage.getItem('omini_conversation_drafts');
      return saved ? JSON.parse(saved) : {};
    } catch {
      return {};
    }
  });

  const handleSaveDraft = useCallback((convId: number, text: string) => {
    setConversationDrafts(prev => {
      const next = { ...prev };
      if (text && text.trim()) {
        next[convId] = text;
      } else {
        delete next[convId];
      }
      try {
        localStorage.setItem('omini_conversation_drafts', JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);

  const displayedConversations = React.useMemo(() => {
    const INTERNAL_SUFFIXES = ['32346622', '992136622', '32421100', '30421044', '98334833', '99883344'];
    return conversations.filter(c => {
      const phone = c.contact?.telefone || '';
      const name = c.contact?.nome || '';
      const cleanPhone = phone.replace(/\D/g, '');

      // Do not list internal company numbers or Fernando Aragão admin test numbers as client cards
      if (INTERNAL_SUFFIXES.some(s => cleanPhone.endsWith(s))) {
        return false;
      }

      const isGroup = Boolean(
        phone.includes('@g.us') ||
        phone.startsWith('120363') ||
        phone.includes('-') ||
        phone.length >= 18 ||
        (c.dados_adicionais as any)?.is_group === true ||
        (c.contact?.dados_adicionais as any)?.is_group === true ||
        name.startsWith('SERV -') ||
        name.includes('GRUPO') ||
        name.includes('Servweld/Servsolda')
      );

      // In WhatsApp, the main chats view shows BOTH individual chats and groups!
      // Only when explicitly navigating to the "groups" tab, filter strictly to groups.
      if (activeTab === 'groups') {
        return isGroup;
      }
      return true;
    });
  }, [conversations, activeTab]);
  
  // Computes active conversation prioritizing active selected ID then department
  const activeConversation = useMemo(() => {
    if (activeConversationId) {
      // Direct lookup in all conversations to prevent chat disappearance during search/filters
      const found = conversations.find(c => c.id === activeConversationId);
      if (found) {
        if (selectedDeptId !== 'all' && String(found.whatsapp_number_id) !== String(selectedDeptId)) {
          const cid = found.contact_id || found.contact?.id;
          const cleanPhone = (found.contact?.telefone || '').replace(/\D/g, '');
          const sameContactInDept = conversations.find(c =>
            String(c.whatsapp_number_id) === String(selectedDeptId) &&
            ((cid && (c.contact_id === cid || c.contact?.id === cid)) ||
             (cleanPhone.length >= 8 && (c.contact?.telefone || '').replace(/\D/g, '').includes(cleanPhone.slice(-8))))
          );
          if (sameContactInDept) return sameContactInDept;
        }
        return found;
      }
    }

    if (selectedDeptId !== 'all') {
      const deptConvs = displayedConversations.filter(c => String(c.whatsapp_number_id) === String(selectedDeptId));
      if (deptConvs.length > 0) return deptConvs[0];
    }

    return displayedConversations.length > 0 ? displayedConversations[0] : null;
  }, [conversations, displayedConversations, activeConversationId, selectedDeptId]);

  const pendingBadgeCount = useMemo(() => {
    if (!conversations || !Array.isArray(conversations)) return 0;
    return conversations.filter(c => isConversationPendingForAttendant(c, user)).length;
  }, [conversations, user]);

  const groupPendingBadgeCount = useMemo(() => {
    if (!conversations || !Array.isArray(conversations)) return 0;
    return conversations.filter(isGroupPending).length;
  }, [conversations]);

  // Atualiza crachá/badge do app no celular (Badging API do Android/PWA), Favicon dinâmico e título
  useEffect(() => {
    updateAppBadgesAndIcon(pendingBadgeCount, groupPendingBadgeCount);
  }, [pendingBadgeCount, groupPendingBadgeCount]);

  // Modals state
  const [isTransferModalOpen, setIsTransferModalOpen] = useState(false);
  const [isNewConvModalOpen, setIsNewConvModalOpen] = useState(false);
  const [isMediaGalleryOpen, setIsMediaGalleryOpen] = useState(false);
  const [showNotificationPrompt, setShowNotificationPrompt] = useState<boolean>(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      return Notification.permission === 'default';
    }
    return false;
  });

  const currentSearchTermRef = useRef<string>('');

  const fetchConversations = useCallback(async (searchQuery?: string) => {
    try {
      const term = searchQuery !== undefined ? searchQuery : currentSearchTermRef.current;
      currentSearchTermRef.current = term;

      const url = term && term.trim()
        ? `/conversations/?search=${encodeURIComponent(term.trim())}`
        : '/conversations/';
      const data = await apiFetch(url);
      if (Array.isArray(data)) {
        setConversations(prev => {
          const prevMap = new Map<number, Conversation>();
          prev.forEach(c => prevMap.set(c.id, c));

          // Collect all optimistic/sending messages across all conversations
          const pendingMessages: { [key: string]: Message[] } = {};
          prev.forEach(c => {
            const sending = (c.messages || []).filter(m => m.id < 0 || m.status === 'sending');
            if (sending.length > 0) {
              const cid = c.contact_id || c.contact?.id;
              const phone = (c.contact?.telefone || '').replace(/\D/g, '');
              if (cid) {
                pendingMessages[`cid_${cid}`] = [...(pendingMessages[`cid_${cid}`] || []), ...sending];
              }
              if (phone.length >= 8) {
                pendingMessages[`phone_${phone.slice(-8)}`] = [...(pendingMessages[`phone_${phone.slice(-8)}`] || []), ...sending];
              }
              pendingMessages[`conv_${c.id}`] = [...(pendingMessages[`conv_${c.id}`] || []), ...sending];
            }
          });

          return data.map((c: Conversation) => {
            const prevConv = prevMap.get(c.id);

            // Determine messages: if prevConv already has full history loaded, PRESERVE IT!
            let currentMsgs = c.messages || [];
            if (prevConv && prevConv.messages && prevConv.messages.length > 0) {
              if (prevConv.messages.length >= currentMsgs.length) {
                const existingIds = new Set(prevConv.messages.map(m => m.id));
                const newIncoming = currentMsgs.filter(m => !existingIds.has(m.id));
                currentMsgs = newIncoming.length > 0
                  ? [...prevConv.messages, ...newIncoming]
                  : prevConv.messages;
              }
            }

            const cid = c.contact_id || c.contact?.id;
            const phone = (c.contact?.telefone || '').replace(/\D/g, '');
            const keyCid = cid ? `cid_${cid}` : '';
            const keyPhone = phone.length >= 8 ? `phone_${phone.slice(-8)}` : '';
            const keyConv = `conv_${c.id}`;

            const sending = [
              ...(keyConv ? (pendingMessages[keyConv] || []) : []),
              ...(keyCid ? (pendingMessages[keyCid] || []) : []),
              ...(keyPhone ? (pendingMessages[keyPhone] || []) : [])
            ];

            if (sending.length > 0) {
              const existingTexts = new Set(currentMsgs.map(m => (m.conteudo || '').split('|')[0].trim()));
              const existingIds = new Set(currentMsgs.map(m => m.id));

              const now = Date.now();
              const uniqueToKeep: Message[] = [];
              const seenTempIds = new Set<number>();

              sending.forEach(m => {
                const isStale = m.timestamp && (now - new Date(m.timestamp).getTime() > 15000);
                const rawContent = (m.conteudo || '').split('|')[0].trim();
                if (!isStale && !seenTempIds.has(m.id) && !existingIds.has(m.id) && !existingTexts.has(rawContent)) {
                  seenTempIds.add(m.id);
                  uniqueToKeep.push(m);
                }
              });

              if (uniqueToKeep.length > 0) {
                currentMsgs = [...currentMsgs, ...uniqueToKeep];
              }
            }

            // Preserve any local state from prevConv
            const mergedDados = {
              ...(prevConv?.dados_adicionais || {}),
              ...(c.dados_adicionais || {})
            };

            return {
              ...c,
              dados_adicionais: mergedDados,
              messages: currentMsgs
            };
          });
        });
      }
    } catch (err) {
      console.error('Error fetching conversations:', err);
    }
  }, []);

  const fetchNumbers = async () => {
    try {
      const data = await apiFetch('/whatsapp-numbers/');
      setWhatsappNumbers(data);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchCalendarSummary = useCallback(async () => {
    try {
      const data = await apiFetch('/calendar/summary');
      setCalendarSummary(data);
    } catch (err) {
      console.debug('Error fetching calendar summary:', err);
    }
  }, []);

  const handleCloseCalendar = useCallback(() => {
    setIsCalendarOpen(false);
    setCalendarPrefill(null);
    fetchCalendarSummary();
  }, [fetchCalendarSummary]);

  const loadActiveConversationDetail = useCallback(async (convId: number) => {
    try {
      const detail = await apiFetch(`/conversations/${convId}`);
      if (detail && detail.id) {
        setConversations(prev => {
          const index = prev.findIndex(c => c.id === convId);
          if (index >= 0) {
            const existing = prev[index];
            const existingMsgs = existing.messages || [];
            const detailMsgs = detail.messages || [];

            // Combine messages avoiding duplicates
            const msgMap = new Map<number, Message>();
            detailMsgs.forEach((m: Message) => msgMap.set(m.id, m));
            existingMsgs.forEach((m: Message) => {
              if (!msgMap.has(m.id) || m.id < 0 || m.status === 'sending') {
                msgMap.set(m.id, m);
              }
            });

            const sortedMsgs = Array.from(msgMap.values()).sort(
              (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
            );

            const next = [...prev];
            next[index] = {
              ...existing,
              ...detail,
              messages: sortedMsgs
            };
            return next;
          } else {
            return [detail, ...prev];
          }
        });
      }
    } catch (err) {
      console.error('Error loading active conversation detail:', err);
    }
  }, []);

  // Automatically ensure full message history is loaded for active conversation
  const activeConvIdToLoad = activeConversationId || activeConversation?.id;
  useEffect(() => {
    if (!activeConvIdToLoad) return;
    const conv = conversations.find(c => c.id === activeConvIdToLoad);
    if (!conv || !conv.messages || conv.messages.length <= 5) {
      loadActiveConversationDetail(activeConvIdToLoad);
    }
  }, [activeConvIdToLoad, conversations, loadActiveConversationDetail]);

  // Android System Back Button Interceptor for Mobile PWA
  useEffect(() => {
    const handlePopState = (e: PopStateEvent) => {
      const state = e.state || window.history.state;
      if (state?.page === 'chat' || state?.page === 'sublayer' || state?.sublayerOpen) {
        return;
      }
      if (activeConversationId !== null) {
        setActiveConversationId(null);
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [activeConversationId]);

  const handleSelectConversation = useCallback((convId: number) => {
    setActiveConversationId(convId);
    loadActiveConversationDetail(convId);
    try {
      window.history.pushState({ page: 'chat', chatOpen: true, convId }, '');
    } catch {}
    // Optimistically mark as read for all conversations and messages of this contact
    setConversations(prev => {
      const selected = prev.find(c => c.id === convId);
      const contactId = selected?.contact_id || selected?.contact?.id;
      const cleanPhone = (selected?.contact?.telefone || '').replace(/\D/g, '');

      return prev.map(c => {
        const matchesContact = (
          c.id === convId ||
          (contactId && (c.contact_id === contactId || c.contact?.id === contactId)) ||
          (cleanPhone.length >= 8 && (c.contact?.telefone || '').replace(/\D/g, '').includes(cleanPhone.slice(-8)))
        );

        if (matchesContact) {
          const currentMsgs = c.messages || [];
          return {
            ...c,
            messages: currentMsgs.map(m => m.remetente === 'cliente' ? { ...m, status: 'read' } : m),
            dados_adicionais: {
              ...(c.dados_adicionais || {}),
              marked_as_read: true,
              pending_dismissed: true
            }
          };
        }
        return c;
      });
    });
    // Persist to backend silently
    apiFetch(`/conversations/${convId}/mark_read`, { method: 'POST' })
      .catch(err => console.debug('Error auto-marking conversation read:', err));
  }, [loadActiveConversationDetail]);

  useEffect(() => {
    fetchConversations();
    fetchNumbers();
    fetchCalendarSummary();
  }, [fetchConversations, fetchCalendarSummary]);

  const [notificationAlert, setNotificationAlert] = useState<string | null>(null);

  const playNotificationSound = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, ctx.currentTime);
      osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.4);
    } catch (e) {
      console.error(e);
    }
  };

  // User Presence State (digitando / gravando áudio)
  const [userPresences, setUserPresences] = useState<Record<number, { status: string; agentName?: string; expiresAt: number }>>({});

  // 1. Polling Fallback Safety Net (Every 5s)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchConversations();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchConversations]);

  // 2. WebSocket Live Realtime Connection with Auto-Reconnect & Dynamic Host
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    let socket: WebSocket | null = null;
    let isSubscribed = true;
    let reconnectTimeout: any = null;

    const connectWebSocket = () => {
      if (!isSubscribed) return;

      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/ws?token=${token}`;

      socket = new WebSocket(wsUrl);

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'USER_PRESENCE') {
            const convId = payload.conversation_id;
            const presenceStatus = payload.presence;
            const agentName = payload.agent_name;
            if (presenceStatus === 'paused' || presenceStatus === 'unavailable') {
              setUserPresences(prev => {
                const next = { ...prev };
                delete next[convId];
                return next;
              });
            } else {
              setUserPresences(prev => ({
                ...prev,
                [convId]: {
                  status: presenceStatus,
                  agentName,
                  expiresAt: Date.now() + 8000
                }
              }));
            }
          } else if (payload.type === 'CONTACT_UPDATED') {
            if (payload.contact_id && payload.foto_perfil_url) {
              setConversations(prev => prev.map(c => {
                if (c.contact_id === payload.contact_id || c.contact?.id === payload.contact_id) {
                  return {
                    ...c,
                    contact: {
                      ...c.contact,
                      foto_perfil_url: payload.foto_perfil_url
                    }
                  };
                }
                return c;
              }));
            }
          } else if (payload.type === 'CONVERSATION_ESCALATED') {
            fetchConversations();
            playNotificationSound();
            setNotificationAlert(payload.message || "🚨 ATENÇÃO: Nova conversa transferida para atendimento humano!");
            setTimeout(() => setNotificationAlert(null), 10000);
          } else if (payload.type === 'NEW_MESSAGE') {
            const newMsg: Message = {
              id: payload.id || Date.now(),
              conversation_id: payload.conversation_id,
              remetente: payload.remetente,
              conteudo: payload.conteudo,
              tipo: payload.tipo || 'texto',
              status: payload.status || 'sent',
              whatsapp_msg_id: payload.whatsapp_msg_id,
              dados_adicionais: payload.dados_adicionais || {},
              timestamp: payload.timestamp || new Date().toISOString()
            };

            setConversations(prev => {
              let found = false;
              const targetPhone = String(payload.contact_phone || payload.phone || '').replace(/\D/g, '');
              const updated = prev.map(c => {
                const cid = c.contact_id || c.contact?.id;
                const phone = (c.contact?.telefone || '').replace(/\D/g, '');

                const matches = (
                  c.id === payload.conversation_id ||
                  (payload.contact_id && cid && cid === payload.contact_id) ||
                  (targetPhone.length >= 8 && phone.length >= 8 && phone.includes(targetPhone.slice(-8)))
                );

                if (matches) {
                  found = true;
                  const currentMsgs = c.messages || [];
                  const hasSameId = currentMsgs.some(m => m.id === newMsg.id);
                  const isFromClient = newMsg.remetente === 'cliente';
                  const nextDados = {
                    ...(c.dados_adicionais || {}),
                    ...(isFromClient ? { marked_as_read: false, pending_dismissed: false } : {})
                  };

                  if (hasSameId) {
                    return {
                      ...c,
                      dados_adicionais: nextDados,
                      ultima_interacao_em: newMsg.timestamp,
                      messages: currentMsgs.map(m => m.id === newMsg.id ? { ...m, ...newMsg } : m)
                    };
                  }
                  let replaced = false;
                  const replacedSending = currentMsgs.map(m => {
                    if (!replaced && (m.id < 0 || m.status === 'sending') && m.remetente === newMsg.remetente) {
                      const c1 = (m.conteudo || '').split('|')[0].trim();
                      const c2 = (newMsg.conteudo || '').split('|')[0].trim();
                      if (m.id < 0 || c1 === c2 || m.tipo === 'audio' || newMsg.tipo === 'audio') {
                        replaced = true;
                        return newMsg;
                      }
                    }
                    return m;
                  });
                  const alreadyPresent = replacedSending.some(m => m.id === newMsg.id);
                  return {
                    ...c,
                    dados_adicionais: nextDados,
                    ultima_interacao_em: newMsg.timestamp,
                    messages: alreadyPresent ? replacedSending : [...replacedSending, newMsg]
                  };
                }
                return c;
              });

              if (!found) {
                fetchConversations();
                return prev;
              }
              return updated;
            });

            if (payload.remetente === 'cliente') {
              playNotificationSound();

              const phone = String(payload.contact_phone || payload.phone || '');
              const isGroupMsg = Boolean(
                phone.includes('@g.us') ||
                phone.startsWith('120363') ||
                payload.dados_adicionais?.is_group ||
                payload.is_group
              );
              const senderName = payload.contact_name || (isGroupMsg ? 'Grupo' : 'Cliente');
              const preview = payload.conteudo
                ? (payload.conteudo.length > 60 ? payload.conteudo.slice(0, 60) + '...' : payload.conteudo)
                : 'Nova mensagem recebida';

              triggerSystemNotification(
                isGroupMsg ? `🟡 ${senderName}` : `🔴 ${senderName}`,
                preview,
                isGroupMsg,
                `conv-${payload.conversation_id}`
              );
            }
          } else if (payload.type === 'conversation_pinned_toggled') {
            setConversations(prev => prev.map(c => {
              if (c.id === payload.conversation_id || (payload.contact_id && c.contact_id === payload.contact_id)) {
                const extra = { ...(c.dados_adicionais || {}) };
                let pinnedUsers = Array.isArray(extra.pinned_by_users) ? [...extra.pinned_by_users] : [];
                if (payload.is_pinned) {
                  if (!pinnedUsers.includes(payload.user_id)) pinnedUsers.push(payload.user_id);
                } else {
                  pinnedUsers = pinnedUsers.filter((id: number) => id !== payload.user_id);
                }
                extra.pinned_by_users = pinnedUsers;
                extra[`pinned_user_${payload.user_id}`] = payload.is_pinned;
                delete extra.is_pinned;
                return { ...c, dados_adicionais: extra };
              }
              return c;
            }));
          } else if (payload.type === 'MESSAGE_STATUS_UPDATE') {
            setConversations(prev => prev.map(c => {
              if (c.id === payload.conversation_id) {
                const isFailed = payload.status === 'failed';
                return {
                  ...c,
                  messages: isFailed
                    ? (c.messages || []).filter(m => m.id !== payload.id && (!payload.whatsapp_msg_id || m.whatsapp_msg_id !== payload.whatsapp_msg_id))
                    : (c.messages || []).map(m => {
                        if (
                          (payload.id && m.id === payload.id) ||
                          (payload.whatsapp_msg_id && m.whatsapp_msg_id === payload.whatsapp_msg_id) ||
                          (payload.status === 'read' && m.remetente === 'cliente')
                        ) {
                          return {
                            ...m,
                            status: payload.status,
                            whatsapp_msg_id: payload.whatsapp_msg_id || m.whatsapp_msg_id
                          };
                        }
                        return m;
                      })
                };
              }
              return c;
            }));

          } else if (payload.type === 'MESSAGE_REACTION_UPDATE') {
            setConversations(prev => prev.map(c => {
              if (c.id === payload.conversation_id) {
                return {
                  ...c,
                  messages: (c.messages || []).map(m => {
                    if (m.id === payload.message_id) {
                      return {
                        ...m,
                        dados_adicionais: {
                          ...(m.dados_adicionais || {}),
                          reaction: payload.reaction
                        }
                      };
                    }
                    return m;
                  })
                };
              }
              return c;
            }));
          } else if (payload.type === 'CONVERSATIONS_MARKED_READ') {
            setConversations(prev => prev.map(c => {
              if (!payload.whatsapp_number_id || c.whatsapp_number_id === payload.whatsapp_number_id) {
                return {
                  ...c,
                  dados_adicionais: { ...(c.dados_adicionais || {}), marked_as_read: true, pending_dismissed: true },
                  messages: (c.messages || []).map(m => m.remetente === 'cliente' ? { ...m, status: 'read' } : m)
                };
              }
              return c;
            }));
          }
        } catch (err) {
          console.error('WebSocket parse error:', err);
        }
      };

      socket.onclose = () => {
        if (isSubscribed) {
          reconnectTimeout = setTimeout(connectWebSocket, 2000);
        }
      };
    };

    connectWebSocket();

    return () => {
      isSubscribed = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (socket) socket.close();
    };
  }, [fetchConversations]);

  const handleSendMessage = async (text: string, tipo: string = 'texto', quotedMsg?: Message | null) => {
    if (!activeConversation) return;

    let targetConv = activeConversation;
    let actualTipo = tipo || 'texto';
    if (tipo === 'texto') {
      const lower = text.toLowerCase();
      if (lower.endsWith('.gif')) actualTipo = 'video';
      else if (lower.endsWith('.ogg') || lower.endsWith('.webm') || lower.endsWith('.mp3') || lower.endsWith('.wav') || lower.endsWith('.m4a') || lower.includes('voice_note')) actualTipo = 'audio';
      else if (lower.endsWith('.webp') || lower.endsWith('.png') || lower.endsWith('.jpg') || lower.endsWith('.jpeg')) actualTipo = 'imagem';
      else if (lower.endsWith('.pdf')) actualTipo = 'arquivo';
    }
    const tempId = -Date.now();
    const optimisticMsg: Message = {
      id: tempId,
      conversation_id: targetConv.id,
      remetente: 'atendente',
      conteudo: text,
      tipo: actualTipo as any,
      timestamp: new Date().toISOString(),
      status: 'sending',
      dados_adicionais: quotedMsg ? {
        quoted_message: {
          message_id: quotedMsg.id,
          stanza_id: quotedMsg.whatsapp_msg_id,
          sender_name: quotedMsg.remetente === 'cliente' ? (targetConv.contact?.nome || 'Cliente') : 'Você',
          text: quotedMsg.conteudo?.slice(0, 120),
          tipo: quotedMsg.tipo
        }
      } : undefined
    };

    const targetCid = targetConv.contact_id || targetConv.contact?.id;
    const targetCleanPhone = (targetConv.contact?.telefone || '').replace(/\D/g, '');

    // 1. INSTANT 0ms OPTIMISTIC UI UPDATE: Display message immediately across all linked conversations for this contact!
    setConversations(prevConvs =>
      prevConvs.map(conv => {
        const cid = conv.contact_id || conv.contact?.id;
        const phone = (conv.contact?.telefone || '').replace(/\D/g, '');

        const matches = (
          conv.id === targetConv.id ||
          (targetCid && cid && cid === targetCid) ||
          (targetCleanPhone.length >= 8 && phone.length >= 8 && phone.includes(targetCleanPhone.slice(-8)))
        );

        if (matches) {
          const currentMsgs = conv.messages || [];
          return {
            ...conv,
            messages: [...currentMsgs, optimisticMsg],
            ultima_interacao_em: new Date().toISOString()
          };
        }
        return conv;
      })
    );

    // 2. Asynchronous Network Dispatch in background without blocking UI
    (async () => {
      try {
        const rawTargetPhone = targetConv.contact?.telefone || '';
        const rawTargetName = targetConv.contact?.nome || '';
        const isGroup = Boolean(
          rawTargetPhone.includes('@g.us') ||
          rawTargetPhone.startsWith('120363') ||
          rawTargetPhone.includes('-') ||
          rawTargetPhone.length >= 18 ||
          (targetConv.dados_adicionais as any)?.is_group === true ||
          (targetConv.contact?.dados_adicionais as any)?.is_group === true ||
          rawTargetName.startsWith('SERV -') ||
          rawTargetName.includes('GRUPO') ||
          rawTargetName.includes('Servweld/Servsolda')
        );

        let finalConvId = targetConv.id;
        if (!isGroup && selectedDeptId !== 'all' && String(targetConv.whatsapp_number_id) !== String(selectedDeptId)) {
          const cid = targetConv.contact_id || targetConv.contact?.id;
          const cleanPhone = (targetConv.contact?.telefone || '').replace(/\D/g, '');
          const matchInDept = conversations.find(c => 
            String(c.whatsapp_number_id) === String(selectedDeptId) &&
            ((cid && (c.contact_id === cid || c.contact?.id === cid)) ||
             (cleanPhone.length >= 8 && (c.contact?.telefone || '').replace(/\D/g, '').includes(cleanPhone.slice(-8))))
          );
          if (matchInDept) {
            finalConvId = matchInDept.id;
          }
        }

        const res = await apiFetch(`/conversations/${finalConvId}/messages`, {
          method: 'POST',
          body: JSON.stringify({
            conversation_id: finalConvId,
            remetente: 'atendente',
            conteudo: text,
            tipo: actualTipo,
            quoted_message_id: quotedMsg?.id || undefined
          })
        });

        // 3. Confirm delivery: replace tempId with real server DB message across all linked views
        setConversations(prevConvs =>
          prevConvs.map(conv => {
            const cid = conv.contact_id || conv.contact?.id;
            const phone = (conv.contact?.telefone || '').replace(/\D/g, '');
            const matches = (
              conv.id === targetConv.id ||
              conv.id === finalConvId ||
              (targetCid && cid && cid === targetCid) ||
              (targetCleanPhone.length >= 8 && phone.length >= 8 && phone.includes(targetCleanPhone.slice(-8)))
            );

            if (matches) {
              const currentMsgs = conv.messages || [];
              return {
                ...conv,
                messages: currentMsgs.map(m => (m.id === tempId ? { ...res, status: 'sent' } : m))
              };
            }
            return conv;
          })
        );
      } catch (err: any) {
        console.error('Optimistic message send error:', err);
        // If message failed to send to server, quietly remove optimistic message so it does not clutter the chat
        setConversations(prevConvs =>
          prevConvs.map(conv => {
            const cid = conv.contact_id || conv.contact?.id;
            const phone = (conv.contact?.telefone || '').replace(/\D/g, '');
            const matches = (
              conv.id === targetConv.id ||
              (targetCid && cid && cid === targetCid) ||
              (targetCleanPhone.length >= 8 && phone.length >= 8 && phone.includes(targetCleanPhone.slice(-8)))
            );

            if (matches) {
              const currentMsgs = conv.messages || [];
              return {
                ...conv,
                messages: currentMsgs.filter(m => m.id !== tempId)
              };
            }
            return conv;
          })
        );
      }
    })();
  };

  const handleConversationCreated = (conv: Conversation) => {
    fetchConversations();
    setActiveConversationId(conv.id);
    setActiveTab('chats');
  };
  const [isChatListCollapsed, setIsChatListCollapsed] = useState(false);

  const [isMainSidebarCollapsed, setIsMainSidebarCollapsed] = useState(false);

  return (
    <div className="dashboard-layout" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', backgroundColor: 'var(--bg-primary)' }}>
      {showNotificationPrompt && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          backgroundColor: '#0f172a',
          borderBottom: '2px solid #22c55e',
          color: '#fff',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          zIndex: 100050,
          boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
          fontSize: '13px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '18px' }}>🔔</span>
            <span>
              <strong>Ativar alertas no ícone do celular:</strong> Receba avisos de chats (vermelho) e grupos (amarelo) no seu aparelho.
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            <button
              type="button"
              onClick={async () => {
                const granted = await requestNotificationPermission();
                setShowNotificationPrompt(false);
                if (granted) {
                  updateAppBadgesAndIcon(pendingBadgeCount, groupPendingBadgeCount);
                  triggerSystemNotification('✅ Alertas Ativados!', 'OminiChannel avisará sobre novas mensagens no ícone do seu celular.', false, 'perm-ok');
                }
              }}
              style={{
                backgroundColor: '#22c55e',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                padding: '6px 14px',
                fontWeight: 'bold',
                cursor: 'pointer',
                fontSize: '12px'
              }}
            >
              Ativar Agora
            </button>
            <button
              type="button"
              onClick={() => setShowNotificationPrompt(false)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: '16px',
                padding: '4px'
              }}
              title="Dispensar"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {notificationAlert && (
        <div style={{
          position: 'fixed',
          top: '16px',
          right: '16px',
          backgroundColor: '#ef4444',
          color: '#fff',
          padding: '12px 20px',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 8px 24px rgba(239,68,68,0.4)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          fontWeight: '600',
          fontSize: '14px'
        }}>
          <span>{notificationAlert}</span>
          <button
            onClick={() => setNotificationAlert(null)}
            style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontWeight: 'bold', fontSize: '16px' }}
          >
            ✕
          </button>
        </div>
      )}

      <Sidebar
        user={user}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onLogout={onLogout}
        isCollapsed={isMainSidebarCollapsed}
        onToggleCollapse={() => setIsMainSidebarCollapsed(!isMainSidebarCollapsed)}
        conversations={conversations}
        onSelectConversation={(convId) => {
          handleSelectConversation(convId);
          setActiveTab('chats');
        }}
        onRefreshConversations={fetchConversations}
      />

      {(activeTab === 'chats' || activeTab === 'groups') && (
        <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: '100%', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', boxSizing: 'border-box' }}>
          {/* DepartmentBar — always visible header on mobile */}
          <DepartmentBar
            whatsappNumbers={whatsappNumbers}
            selectedDepartmentId={selectedDeptId}
            onSelectDepartment={(id) => setSelectedDeptId(id)}
            conversations={displayedConversations}
            onOpenCalendar={() => {
              setCalendarPrefill(null);
              setIsCalendarOpen(true);
            }}
            calendarSummary={calendarSummary}
            pendingBadgeCount={pendingBadgeCount}
            groupPendingBadgeCount={groupPendingBadgeCount}
          />
          {/* Chat list + chat area row — takes remaining height */}
          <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: '100%', display: 'flex', overflow: 'hidden', boxSizing: 'border-box' }}>
            <div
              className={`chat-list-column ${activeConversationId ? 'mobile-hidden' : ''}`}
              style={{
                height: '100%',
                display: 'flex',
                boxSizing: 'border-box',
                overflow: 'hidden'
              }}
            >
              <ChatList
                conversations={displayedConversations}
                activeConversation={activeConversation}
                onSelectConversation={(conv) => handleSelectConversation(conv.id)}
                whatsappNumbers={whatsappNumbers}
                selectedDepartmentId={selectedDeptId}
                setSelectedDepartmentId={setSelectedDeptId}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                onOpenNewConversationModal={() => setIsNewConvModalOpen(true)}
                onStatusToggle={fetchConversations}
                currentUserId={user?.id}
                drafts={conversationDrafts}
                userPresences={userPresences}
                onSearch={fetchConversations}
                activeTab={activeTab}
              />
            </div>
            <div className={`chat-area-column ${!activeConversationId ? 'mobile-hidden' : ''}`} style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex' }}>
              <ChatArea
                conversation={activeConversation}
                allConversations={conversations}
                onSelectConversation={(conv) => handleSelectConversation(conv.id)}
                currentUser={user}
                userPresences={userPresences}
                onSendMessage={handleSendMessage}
                onOpenTransferModal={() => setIsTransferModalOpen(true)}
                onOpenMediaGallery={() => setIsMediaGalleryOpen(true)}
                onOpenScheduleTask={(prefill) => {
                  setCalendarPrefill(prefill);
                  setIsCalendarOpen(true);
                }}
                onStatusToggle={fetchConversations}
                onBack={() => setActiveConversationId(null)}
                isChatListCollapsed={isChatListCollapsed}
                onToggleChatList={() => setIsChatListCollapsed(!isChatListCollapsed)}
                whatsappNumbers={whatsappNumbers}
                drafts={conversationDrafts}
                onSaveDraft={handleSaveDraft}
              />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'contacts' && (
        <ContactsPanel />
      )}

      {activeTab === 'segmentation' && (
        <SegmentationPanel />
      )}

      {activeTab === 'admin' && (
        <AdminPanel initialNumbers={whatsappNumbers} onRefreshNumbers={fetchNumbers} onBack={() => setActiveTab('chats')} />
      )}

      {/* Modals */}
      <NewConversationModal
        isOpen={isNewConvModalOpen}
        onClose={() => setIsNewConvModalOpen(false)}
        whatsappNumbers={whatsappNumbers}
        onConversationCreated={handleConversationCreated}
      />

      <MediaGalleryModal
        isOpen={isMediaGalleryOpen}
        onClose={() => setIsMediaGalleryOpen(false)}
        conversation={activeConversation}
      />

      <TransferModal
        isOpen={isTransferModalOpen}
        onClose={() => setIsTransferModalOpen(false)}
        conversation={activeConversation}
        onTransferSuccess={() => {
          fetchConversations();
          setSelectedDeptId('all');
        }}
      />

      {/* Google-Calendar-style Personal Tasks & Appointments Modal */}
      <CalendarModal
        isOpen={isCalendarOpen}
        onClose={handleCloseCalendar}
        currentUser={user}
        initialEventData={calendarPrefill}
        onSelectConversation={(convId) => {
          setActiveConversationId(convId);
          setActiveTab('chats');
        }}
      />

      {/* Dedicated Mobile Bottom Navigation Bar (WhatsApp style) */}
      <MobileBottomNav
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        pendingBadgeCount={pendingBadgeCount}
        groupPendingBadgeCount={groupPendingBadgeCount}
        user={user}
      />

      {/* Global Real-time WhatsApp Sync Progress Taskbar */}
      <SyncTaskbar />
    </div>
  );
};
