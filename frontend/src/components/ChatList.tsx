import React, { useState, useMemo } from 'react';
import { Search, Phone, Bot, Headphones, Plus, ChevronDown, ChevronRight, History, Layers, PanelLeftClose, PanelLeftOpen, Users, Globe, CheckCheck, Pin, Clock, AlertCircle, Building, User as UserIcon } from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation, WhatsAppNumber, ConversationStatus } from '../types';
import { AvatarModal } from './AvatarModal';

export const parseIsoDate = (ts: string | Date | undefined): Date => {
  if (!ts) return new Date();
  if (ts instanceof Date) return isNaN(ts.getTime()) ? new Date() : ts;
  let str = String(ts).trim();
  if (str.includes(' ') && !str.includes('T')) {
    str = str.replace(' ', 'T');
  }
  if (!str.endsWith('Z') && !/[+-]\d{2}(:\d{2})?$/.test(str)) {
    str = str + 'Z';
  }
  const d = new Date(str);
  return isNaN(d.getTime()) ? new Date() : d;
};

const formatTime = (ts: string | Date | undefined) => {
  if (!ts) return '';
  const d = parseIsoDate(ts);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export const formatWhatsAppPhone = (phone: string | undefined | null): string => {
  if (!phone) return '';
  const clean = String(phone).replace(/\D/g, '');
  if (clean.startsWith('120363') || clean.length > 15) {
    return 'Grupo';
  }
  if (clean.startsWith('55') && clean.length === 12) {
    return `+55 (${clean.slice(2, 4)}) ${clean.slice(4, 8)}-${clean.slice(8)}`;
  }
  if (clean.startsWith('55') && clean.length === 13) {
    return `+55 (${clean.slice(2, 4)}) ${clean.slice(4, 9)}-${clean.slice(9)}`;
  }
  if (clean.length === 10) {
    return `(${clean.slice(0, 2)}) ${clean.slice(2, 6)}-${clean.slice(6)}`;
  }
  if (clean.length === 11) {
    return `(${clean.slice(0, 2)}) ${clean.slice(2, 7)}-${clean.slice(7)}`;
  }
  return phone;
};

interface ChatListProps {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  onSelectConversation: (conv: Conversation) => void;
  whatsappNumbers: WhatsAppNumber[];
  selectedDepartmentId: number | 'all';
  setSelectedDepartmentId: (id: number | 'all') => void;
  statusFilter: ConversationStatus | 'all' | 'nao_lidas';
  setStatusFilter: (status: ConversationStatus | 'all' | 'nao_lidas') => void;
  onOpenNewConversationModal?: () => void;
  onStatusToggle?: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  currentUserId?: number | null;
}

interface ContactGroup {
  contactId: number;
  contactName: string;
  contactPhone: string;
  primaryConv: Conversation;
  allConversations: Conversation[];
  hasUnread: boolean;
  unreadCount: number;
  activeCount: number;
}

export const ChatList: React.FC<ChatListProps> = ({
  conversations,
  activeConversation,
  onSelectConversation,
  whatsappNumbers,
  selectedDepartmentId,
  setSelectedDepartmentId,
  statusFilter,
  setStatusFilter,
  onOpenNewConversationModal,
  onStatusToggle,
  isCollapsed = false,
  onToggleCollapse,
  currentUserId
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedContactIds, setExpandedContactIds] = useState<number[]>([]);
  const [avatarModalData, setAvatarModalData] = useState<{ name: string; phone?: string; avatarUrl?: string | null } | null>(null);

  const toggleExpand = (e: React.MouseEvent, contactId: number) => {
    e.stopPropagation();
    setExpandedContactIds(prev =>
      prev.includes(contactId) ? prev.filter(id => id !== contactId) : [...prev, contactId]
    );
  };

  const handleToggleStatus = async (e: React.MouseEvent, conv: Conversation) => {
    e.stopPropagation();
    const nextStatus = conv.status === 'com_ia' ? 'com_humano' : 'com_ia';
    try {
      await apiFetch(`/conversations/${conv.id}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: nextStatus })
      });
      if (onStatusToggle) onStatusToggle();
    } catch (err) {
      console.error('Failed to toggle status from list:', err);
    }
  };

  const effectiveUserId = useMemo(() => {
    if (currentUserId) return currentUserId;
    try {
      const token = localStorage.getItem('token');
      if (token) {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const uid = Number(payload.sub || payload.id);
        if (!isNaN(uid)) return uid;
      }
    } catch {}
    return null;
  }, [currentUserId]);

  const [, setTick] = useState(0);

  const isConvPinned = (conv: Conversation | null | undefined): boolean => {
    if (!conv || !conv.dados_adicionais) return false;
    const extra = conv.dados_adicionais as any;
    if (effectiveUserId) {
      if (Array.isArray(extra.pinned_by_users)) {
        return extra.pinned_by_users.includes(effectiveUserId);
      }
      if (typeof extra[`pinned_user_${effectiveUserId}`] === 'boolean') {
        return extra[`pinned_user_${effectiveUserId}`];
      }
    }
    return Boolean(extra.is_pinned);
  };

  const handleTogglePin = async (e: React.MouseEvent, conv: Conversation, allConvs?: Conversation[]) => {
    e.preventDefault();
    e.stopPropagation();
    const currentPinned = isConvPinned(conv);
    const nextPinned = !currentPinned;
    
    // Optimistic local state update per user for all sibling conversations
    const targets = allConvs && allConvs.length > 0 ? allConvs : [conv];
    targets.forEach(target => {
      const extra = { ...(target.dados_adicionais || {}) };
      let pinnedUsers: number[] = Array.isArray(extra.pinned_by_users) ? [...extra.pinned_by_users] : [];
      if (effectiveUserId) {
        if (nextPinned) {
          if (!pinnedUsers.includes(effectiveUserId)) pinnedUsers.push(effectiveUserId);
        } else {
          pinnedUsers = pinnedUsers.filter(id => id !== effectiveUserId);
        }
        extra.pinned_by_users = pinnedUsers;
        extra[`pinned_user_${effectiveUserId}`] = nextPinned;
      } else {
        extra.is_pinned = nextPinned;
      }
      delete extra.is_pinned;
      target.dados_adicionais = extra;
    });

    // Force instant React re-render with new pinned sorting
    setTick(t => t + 1);

    try {
      await apiFetch(`/conversations/${conv.id}/toggle-pin`, {
        method: 'POST'
      });
      if (onStatusToggle) onStatusToggle();
    } catch (err) {
      console.error('Failed to toggle pin from list:', err);
    }
  };

  // Group conversations by unique customer (normalized phone) to guarantee a SINGLE card per client
  const contactGroups = useMemo(() => {
    const map = new Map<string, Conversation[]>();

    conversations.forEach(conv => {
      const rawPhone = (conv.contact?.telefone || '').trim();
      const cleanDigits = rawPhone.replace(/\D/g, '');
      const isGroup = rawPhone.startsWith('120363') || cleanDigits.length > 15;
      
      let groupKey = '';
      if (isGroup) {
        groupKey = `group_${cleanDigits || rawPhone}`;
      } else if (cleanDigits.length >= 8) {
        groupKey = `client_${cleanDigits.slice(-8)}`;
      } else {
        groupKey = `contact_${conv.contact_id || conv.contact?.id || 0}`;
      }

      if (!map.has(groupKey)) {
        map.set(groupKey, []);
      }
      map.get(groupKey)!.push(conv);
    });

    const groups: ContactGroup[] = [];

    map.forEach((convs, gKey) => {
      convs.sort((a, b) => new Date(b.ultima_interacao_em).getTime() - new Date(a.ultima_interacao_em).getTime());

      const matchingConvs = convs.filter(conv => {
        const matchesDept = selectedDepartmentId === 'all' || String(conv.whatsapp_number_id) === String(selectedDepartmentId);
        
        let matchesStatus = true;
        if (statusFilter === 'nao_lidas') {
          const extra = conv.dados_adicionais || {};
          if (extra.marked_as_read) {
            matchesStatus = false;
          } else {
            const msgs = conv.messages || [];
            let lastAttendantIdx = -1;
            for (let i = 0; i < msgs.length; i++) {
              if (String(msgs[i].remetente || '').toLowerCase() === 'atendente') {
                lastAttendantIdx = i;
              }
            }
            let hasClientAfterAttendant = false;
            for (let i = lastAttendantIdx + 1; i < msgs.length; i++) {
              if (String(msgs[i].remetente || '').toLowerCase() === 'cliente') {
                hasClientAfterAttendant = true;
                break;
              }
            }
            matchesStatus = hasClientAfterAttendant || msgs.some(m => m.remetente === 'cliente' && m.status !== 'read');
          }
        } else if (statusFilter !== 'all') {
          matchesStatus = conv.status === statusFilter;
        }

        const contactName = conv.contact?.nome || '';
        const contactPhone = conv.contact?.telefone || '';
        const protoNumber = (conv as any).protocol_number || '';
        const term = searchTerm.toLowerCase().trim();
        const matchesSearch = !term ||
                              contactName.toLowerCase().includes(term) ||
                              contactPhone.includes(term) ||
                              protoNumber.toLowerCase().includes(term);
        return matchesDept && matchesStatus && matchesSearch;
      });

      if (matchingConvs.length === 0) return;

      // When a department is selected, ALWAYS prioritize the conversation belonging to that department!
      const primary = (selectedDepartmentId !== 'all'
        ? matchingConvs.find(c => String(c.whatsapp_number_id) === String(selectedDepartmentId))
        : null) || matchingConvs.find(c => c.status === 'com_ia' || c.status === 'com_humano') || matchingConvs[0];
      
      let bestName = '';
      let bestPhone = '';
      matchingConvs.forEach(c => {
        if (!bestPhone && c.contact?.telefone) bestPhone = c.contact.telefone;
        const n = c.contact?.nome;
        if (n && n !== 'WhatsApp' && !n.replace(/\D/g, '')) {
          bestName = n;
        } else if (!bestName && n) {
          bestName = n;
        }
      });

      let groupUnreadCount = 0;
      matchingConvs.forEach(conv => {
        const extra = conv.dados_adicionais || {};
        if (extra.marked_as_read) return;
        const msgs = conv.messages || [];
        if (msgs.length === 0) return;

        let lastAttendantIdx = -1;
        for (let i = 0; i < msgs.length; i++) {
          const r = String(msgs[i].remetente || '').toLowerCase();
          if (r === 'atendente') {
            lastAttendantIdx = i;
          }
        }

        let convUnread = 0;
        for (let i = lastAttendantIdx + 1; i < msgs.length; i++) {
          const r = String(msgs[i].remetente || '').toLowerCase();
          if (r === 'cliente') {
            convUnread++;
          }
        }
        groupUnreadCount += Math.max(convUnread, msgs.some(m => m.remetente === 'cliente' && m.status !== 'read') ? 1 : 0);
      });

      const hasUnread = groupUnreadCount > 0 || statusFilter === 'nao_lidas';

      groups.push({
        contactId: primary.contact_id || primary.contact?.id || 0,
        contactName: bestName || primary.contact?.nome || primary.contact?.telefone || 'Cliente sem nome',
        contactPhone: bestPhone || primary.contact?.telefone || '',
        primaryConv: primary,
        allConversations: matchingConvs,
        hasUnread,
        unreadCount: groupUnreadCount,
        activeCount: matchingConvs.filter(c => c.status === 'com_ia' || c.status === 'com_humano').length
      });
    });

    const getLatestInteraction = (g: ContactGroup): number => {
      let maxTime = parseIsoDate(g.primaryConv.ultima_interacao_em).getTime();
      for (const c of g.allConversations) {
        const t = parseIsoDate(c.ultima_interacao_em).getTime();
        if (t > maxTime) maxTime = t;
        if (c.messages && c.messages.length > 0) {
          const lastMsg = c.messages[c.messages.length - 1];
          if (lastMsg && lastMsg.timestamp) {
            const mt = parseIsoDate(lastMsg.timestamp).getTime();
            if (mt > maxTime) maxTime = mt;
          }
        }
      }
      return isNaN(maxTime) ? 0 : maxTime;
    };

    return groups.sort((a, b) => {
      const isPinnedA = isConvPinned(a.primaryConv) || a.allConversations.some(c => isConvPinned(c));
      const isPinnedB = isConvPinned(b.primaryConv) || b.allConversations.some(c => isConvPinned(c));
      if (isPinnedA && !isPinnedB) return -1;
      if (!isPinnedA && isPinnedB) return 1;
      return getLatestInteraction(b) - getLatestInteraction(a);
    });
  }, [conversations, selectedDepartmentId, statusFilter, searchTerm, activeConversation, effectiveUserId]);

  const totalUnread = useMemo(() => {
    return conversations.filter(conv => {
      const matchesDept = selectedDepartmentId === 'all' || String(conv.whatsapp_number_id) === String(selectedDepartmentId);
      if (!matchesDept) return false;
      const extra = conv.dados_adicionais || {};
      if (extra.marked_as_read) return false;
      const msgs = conv.messages || [];
      if (msgs.length === 0) return false;

      let lastAttendantIdx = -1;
      for (let i = 0; i < msgs.length; i++) {
        const r = String(msgs[i].remetente || '').toLowerCase();
        if (r === 'atendente') {
          lastAttendantIdx = i;
        }
      }

      for (let i = lastAttendantIdx + 1; i < msgs.length; i++) {
        const r = String(msgs[i].remetente || '').toLowerCase();
        if (r === 'cliente') {
          return true;
        }
      }
      return msgs.some(m => m.remetente === 'cliente' && m.status !== 'read');
    }).length;
  }, [conversations, selectedDepartmentId]);

  const [isMarkingAllRead, setIsMarkingAllRead] = useState(false);

  const handleMarkAllAsRead = async () => {
    setIsMarkingAllRead(true);
    try {
      const payload = selectedDepartmentId !== 'all' ? { whatsapp_number_id: Number(selectedDepartmentId) } : {};
      await apiFetch('/conversations/mark_all_read', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      if (onStatusToggle) onStatusToggle();
    } catch (err) {
      console.error('Failed to mark all conversations as read:', err);
    } finally {
      setIsMarkingAllRead(false);
    }
  };

  if (isCollapsed) return null;

  return (
    <div style={{
      flex: '0 0 360px',
      width: '360px',
      minWidth: '360px',
      maxWidth: '360px',
      height: '100%',
      backgroundColor: 'var(--bg-primary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      boxSizing: 'border-box',
      overflow: 'hidden'
    }}>
      {/* Header & Search */}
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '18px', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
            Clientes & Chats
            {totalUnread > 0 && (
              <span style={{
                backgroundColor: '#ef4444',
                color: '#fff',
                borderRadius: '12px',
                padding: '2px 6px',
                fontSize: '10px',
                fontWeight: '700'
              }}>
                {totalUnread}
              </span>
            )}
          </h2>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <button
              onClick={() => setStatusFilter(statusFilter === 'nao_lidas' ? 'all' : 'nao_lidas')}
              style={{
                background: statusFilter === 'nao_lidas' ? '#ef4444' : (totalUnread > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255,255,255,0.04)'),
                border: statusFilter === 'nao_lidas' ? '1px solid #ef4444' : (totalUnread > 0 ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid var(--border-color)'),
                color: statusFilter === 'nao_lidas' ? '#ffffff' : (totalUnread > 0 ? '#f87171' : 'var(--text-muted)'),
                borderRadius: 'var(--radius-md)',
                padding: '5px 8px',
                fontSize: '11px',
                fontWeight: '700',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.2s ease',
                boxShadow: statusFilter === 'nao_lidas' ? '0 0 10px rgba(239, 68, 68, 0.4)' : 'none'
              }}
              title="Filtrar apenas conversas com mensagens não lidas"
            >
              <span>Não lidas</span>
              {totalUnread > 0 && (
                <span style={{
                  backgroundColor: statusFilter === 'nao_lidas' ? '#ffffff' : '#ef4444',
                  color: statusFilter === 'nao_lidas' ? '#ef4444' : '#ffffff',
                  borderRadius: '10px',
                  padding: '1px 5px',
                  fontSize: '9px',
                  fontWeight: '800'
                }}>
                  {totalUnread}
                </span>
              )}
            </button>

            <button
              onClick={handleMarkAllAsRead}
              disabled={isMarkingAllRead || totalUnread === 0}
              style={{
                background: totalUnread > 0 ? 'rgba(0, 230, 153, 0.12)' : 'rgba(255,255,255,0.04)',
                border: totalUnread > 0 ? '1px solid rgba(0, 230, 153, 0.4)' : '1px solid var(--border-color)',
                color: totalUnread > 0 ? 'var(--accent-primary)' : 'var(--text-muted)',
                borderRadius: 'var(--radius-md)',
                padding: '5px 8px',
                fontSize: '11px',
                fontWeight: '600',
                cursor: totalUnread > 0 ? 'pointer' : 'default',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                transition: 'all 0.2s ease',
                opacity: totalUnread === 0 ? 0.6 : 1
              }}
              title="Marcar todas as mensagens como lidas"
            >
              <CheckCheck size={14} />
              {isMarkingAllRead ? '...' : 'Lidas'}
            </button>

            {onOpenNewConversationModal && (
              <button
                onClick={onOpenNewConversationModal}
                className="btn-primary"
                style={{ fontSize: '12px', padding: '5px 10px', borderRadius: 'var(--radius-md)' }}
                title="Nova conversa"
              >
                <Plus size={14} /> Nova
              </button>
            )}

            {onToggleCollapse && (
              <button
                onClick={onToggleCollapse}
                style={{
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-muted)',
                  borderRadius: 'var(--radius-md)',
                  padding: '5px 8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                title="Retrair/Recolher painel de conversas"
              >
                <PanelLeftClose size={16} />
              </button>
            )}
          </div>
        </div>

        {/* Search Bar */}
        <div style={{ position: 'relative' }}>
          <Search size={15} style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Buscar por cliente ou telefone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 10px 8px 32px',
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-main)',
              fontSize: '12px',
              outline: 'none',
              boxSizing: 'border-box'
            }}
          />
        </div>
      </div>

      {/* Status Filter Sub-Bar */}
      <div style={{
        padding: '8px 16px',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '11px',
        color: 'var(--text-muted)'
      }}>
        <span>Status:</span>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as any)}
          style={{
            background: 'transparent',
            color: 'var(--text-main)',
            border: 'none',
            fontSize: '11px',
            cursor: 'pointer',
            outline: 'none',
            fontWeight: '600'
          }}
        >
          <option value="all" style={{ background: '#131b2e' }}>Todos ({contactGroups.length} clientes)</option>
          <option value="nao_lidas" style={{ background: '#131b2e', color: '#f87171', fontWeight: '700' }}>📩 Não Lidas ({totalUnread})</option>
          <option value="com_ia" style={{ background: '#131b2e' }}>Com IA Concierge</option>
          <option value="com_humano" style={{ background: '#131b2e' }}>Com Atendente Humano</option>
          <option value="encerrada" style={{ background: '#131b2e' }}>Encerradas</option>
          <option value="expirada_por_inatividade" style={{ background: '#131b2e' }}>Expiradas (Inatividade)</option>
        </select>
      </div>

      {/* List items (Grouped by Contact) */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {contactGroups.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
            Nenhum cliente encontrado.
          </div>
        ) : (
          contactGroups.map(group => {
            const isGroupSelected = group.allConversations.some(c => c.id === activeConversation?.id);
            const isExpanded = expandedContactIds.includes(group.contactId);
            const primaryConv = group.primaryConv;
            const isSelected = activeConversation?.id === primaryConv.id;
            const lastMessage = primaryConv.messages[primaryConv.messages.length - 1];
            const isGroupPinned = isConvPinned(primaryConv) || group.allConversations.some(c => isConvPinned(c));
            const lastMsgTime = lastMessage?.timestamp ? parseIsoDate(lastMessage.timestamp).getTime() : 0;
            const isRecentMessage = lastMsgTime > 0 && (Date.now() - lastMsgTime) < 24 * 60 * 60 * 1000;

            const isWaitingAttendant = Boolean(
              !isSelected &&
              !primaryConv.dados_adicionais?.marked_as_read &&
              !primaryConv.dados_adicionais?.pending_dismissed &&
              (primaryConv.status === 'com_humano' || primaryConv.status === 'aguardando_atendente') &&
              isRecentMessage &&
              (group.hasUnread || (lastMessage && lastMessage.remetente?.toLowerCase() === 'cliente' && lastMessage.status !== 'read'))
            );

            return (
              <div
                key={group.contactId}
                style={{
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: isGroupSelected ? 'rgba(0, 230, 153, 0.04)' : (isGroupPinned ? 'rgba(234, 179, 8, 0.03)' : 'transparent'),
                  transition: 'var(--transition-fast)'
                }}
              >
                {/* Main Contact Card */}
                <div
                  onClick={() => onSelectConversation(primaryConv)}
                  style={{
                    padding: '12px 14px',
                    borderLeft: isSelected ? '3px solid var(--accent-primary)' : (isGroupPinned ? '3px solid #eab308' : (isWaitingAttendant ? '3px solid #ef4444' : (group.hasUnread ? '3px solid #ef4444' : '3px solid transparent'))),
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.08)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px'
                  }}
                >
                  {/* WhatsApp Profile Avatar with Click-to-Zoom & Waiting Indicator */}
                  <div style={{ position: 'relative', flexShrink: 0, display: 'inline-flex' }}>
                    {primaryConv.contact?.foto_perfil_url ? (
                      <img
                        src={primaryConv.contact.foto_perfil_url}
                        alt={group.contactName}
                        onClick={(e) => {
                          e.stopPropagation();
                          setAvatarModalData({
                            name: group.contactName,
                            phone: group.contactPhone,
                            avatarUrl: primaryConv.contact?.foto_perfil_url
                          });
                        }}
                        title={isWaitingAttendant ? "⚠️ Aguardando resposta de atendente humano! Clique para expandir foto" : "Clique para expandir a foto de perfil"}
                        style={{
                          width: '38px',
                          height: '38px',
                          borderRadius: '50%',
                          objectFit: 'cover',
                          border: isWaitingAttendant ? '2.5px solid #ef4444' : (isGroupPinned ? '1.5px solid #eab308' : '1.5px solid var(--accent-primary)'),
                          boxShadow: isWaitingAttendant ? '0 0 10px rgba(239, 68, 68, 0.7)' : 'none',
                          flexShrink: 0,
                          cursor: 'pointer',
                          transition: 'transform 0.15s ease'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
                        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                      />
                    ) : (
                      <div
                        onClick={(e) => {
                          e.stopPropagation();
                          setAvatarModalData({
                            name: group.contactName,
                            phone: group.contactPhone,
                            avatarUrl: null
                          });
                        }}
                        title={isWaitingAttendant ? "⚠️ Aguardando resposta de atendente humano! Clique para expandir foto" : "Clique para expandir a foto de perfil"}
                        style={{
                          width: '38px',
                          height: '38px',
                          borderRadius: '50%',
                          background: isWaitingAttendant ? 'linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)' : (isGroupPinned ? 'linear-gradient(135deg, #eab308 0%, #ca8a04 100%)' : 'linear-gradient(135deg, #00e699 0%, #00b377 100%)'),
                          color: isWaitingAttendant ? '#ffffff' : '#051a12',
                          fontWeight: '700',
                          fontSize: '15px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0,
                          boxShadow: isWaitingAttendant ? '0 0 10px rgba(239, 68, 68, 0.7)' : (isGroupPinned ? '0 2px 6px rgba(234, 179, 8, 0.3)' : '0 2px 6px rgba(0, 230, 153, 0.25)'),
                          border: isWaitingAttendant ? '2.5px solid #ef4444' : 'none',
                          cursor: 'pointer'
                        }}
                      >
                        {group.contactName.charAt(0).toUpperCase()}
                      </div>
                    )}

                    {/* Visual Waiting Indicator Flag on Avatar */}
                    {isWaitingAttendant && (
                      <span
                        title="Aguardando resposta do atendente humano"
                        style={{
                          position: 'absolute',
                          bottom: '-2px',
                          right: '-2px',
                          backgroundColor: '#ef4444',
                          color: '#ffffff',
                          border: '2px solid #0f172a',
                          borderRadius: '50%',
                          width: '15px',
                          height: '15px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '9px',
                          fontWeight: '900',
                          boxShadow: '0 0 8px rgba(239, 68, 68, 0.9)'
                        }}
                      >
                        !
                      </span>
                    )}
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{
                        fontWeight: '700',
                        fontSize: '13px',
                        color: 'var(--text-main)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        maxWidth: '140px'
                      }}>
                        {isGroupPinned && (
                          <span title="Conversa Fixada no Topo" style={{ display: 'inline-flex', alignItems: 'center', color: '#eab308', flexShrink: 0 }}>
                            <Pin size={12} fill="#eab308" />
                          </span>
                        )}
                        {group.contactName}
                        {group.hasUnread && (
                          <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: '#ef4444', flexShrink: 0 }} title="Mensagem não lida do cliente" />
                        )}
                      </span>
                      <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>
                        {formatTime(primaryConv.ultima_interacao_em)}
                      </span>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Phone size={11} /> {formatWhatsAppPhone(group.contactPhone)}
                      </span>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      {/* Pin / Fix Button */}
                      <button
                        type="button"
                        onClick={(e) => handleTogglePin(e, primaryConv, group.allConversations)}
                        title={isGroupPinned ? "Desafixar do topo" : "Fixar no topo"}
                        style={{
                          background: isGroupPinned ? 'rgba(234, 179, 8, 0.22)' : 'rgba(255, 255, 255, 0.06)',
                          border: isGroupPinned ? '1px solid rgba(234, 179, 8, 0.6)' : '1px solid rgba(255, 255, 255, 0.15)',
                          borderRadius: '5px',
                          color: isGroupPinned ? '#eab308' : 'var(--text-muted)',
                          padding: '2px 6px',
                          cursor: 'pointer',
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '3px',
                          fontSize: '10px',
                          fontWeight: '700',
                          zIndex: 5,
                          transition: 'all 0.15s ease'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = isGroupPinned ? 'rgba(234, 179, 8, 0.35)' : 'rgba(255, 255, 255, 0.15)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = isGroupPinned ? 'rgba(234, 179, 8, 0.22)' : 'rgba(255, 255, 255, 0.06)';
                        }}
                      >
                        <Pin size={11} fill={isGroupPinned ? '#eab308' : 'none'} color={isGroupPinned ? '#eab308' : 'currentColor'} />
                        <span>{isGroupPinned ? 'Fixado' : 'Fixar'}</span>
                      </button>

                      <button
                        onClick={(e) => handleToggleStatus(e, primaryConv)}
                        title={primaryConv.status === 'com_ia' ? 'Alternar para Humano' : 'Alternar para IA'}
                        className={`badge badge-${primaryConv.status}`}
                        style={{ cursor: 'pointer', border: 'none', display: 'flex', alignItems: 'center', gap: '3px', padding: '2px 6px', fontSize: '9px', whiteSpace: 'nowrap' }}
                      >
                        {primaryConv.status === 'com_ia' ? <Bot size={9} /> : <Headphones size={9} />}
                        {primaryConv.status.replace('_', ' ')}
                      </button>

                      {/* Expand Sub-threads or Community Groups Button */}
                      {(group.allConversations.length > 1 || (group.contactPhone === '120363424944423399' || group.contactName.includes('Servweld/Servsolda'))) && (
                        <button
                          type="button"
                          onClick={(e) => toggleExpand(e, group.contactId)}
                          style={{
                            background: 'rgba(0, 230, 153, 0.12)',
                            border: '1px solid rgba(0, 230, 153, 0.3)',
                            borderRadius: '4px',
                            color: 'var(--accent-primary)',
                            padding: '1px 6px',
                            fontSize: '9px',
                            fontWeight: '700',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}
                          title="Ver grupos desta comunidade / chamados deste cliente"
                        >
                          {(group.contactPhone === '120363424944423399' || group.contactName.includes('Servweld/Servsolda')) ? (
                            <>
                              <Users size={11} /> Grupos
                            </>
                          ) : (
                            <>
                              <Layers size={10} /> {group.allConversations.length}
                            </>
                          )}
                          {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Attendant & Waiting Alert Row */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    {primaryConv.status === 'com_humano' || primaryConv.status === 'aguardando_atendente' ? (
                      <span style={{
                        fontSize: '9px',
                        fontWeight: '700',
                        color: '#93c5fd',
                        backgroundColor: 'rgba(59, 130, 246, 0.15)',
                        border: '1px solid rgba(59, 130, 246, 0.35)',
                        padding: '1px 6px',
                        borderRadius: '4px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        maxWidth: '170px',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}>
                        <UserIcon size={9} />
                        Atendente: {primaryConv.assigned_user_name || 'Sem Atendente'}
                      </span>
                    ) : (
                      <span style={{
                        fontSize: '9px',
                        fontWeight: '700',
                        color: '#c084fc',
                        backgroundColor: 'rgba(168, 85, 247, 0.15)',
                        border: '1px solid rgba(168, 85, 247, 0.35)',
                        padding: '1px 6px',
                        borderRadius: '4px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px'
                      }}>
                        <Bot size={9} /> Atendimento IA
                      </span>
                    )}

                    {/* Pending / Unreplied Alert Badge */}
                    {isWaitingAttendant && (
                      <span style={{
                        fontSize: '9px',
                        fontWeight: '800',
                        backgroundColor: '#ef4444',
                        color: '#ffffff',
                        padding: '1px 5px',
                        borderRadius: '4px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '3px',
                        boxShadow: '0 0 6px rgba(239, 68, 68, 0.6)'
                      }}>
                        <AlertCircle size={9} /> AGUARDANDO
                      </span>
                    )}
                  </div>

                  {/* Last Message Preview & WhatsApp Unread Badge */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                    <p style={{
                      fontSize: '11px',
                      color: group.hasUnread ? '#ffffff' : 'var(--text-dim)',
                      fontWeight: group.hasUnread ? '700' : 'normal',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      flex: 1,
                      margin: 0
                    }}>
                      {lastMessage ? lastMessage.conteudo : 'Conversa iniciada'}
                    </p>

                    {group.unreadCount > 0 && (
                      <span
                        title={`${group.unreadCount} mensagem(ns) não lida(s)`}
                        style={{
                          backgroundColor: '#22c55e',
                          color: '#ffffff',
                          fontSize: '10px',
                          fontWeight: '800',
                          borderRadius: '10px',
                          minWidth: '18px',
                          height: '18px',
                          padding: '0 5px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0,
                          boxShadow: '0 2px 6px rgba(34, 197, 94, 0.45)'
                        }}
                      >
                        {group.unreadCount > 99 ? '99+' : group.unreadCount}
                      </span>
                    )}
                  </div>
                  </div>
                </div>

                {/* WhatsApp Community Sub-Groups (Identical to WhatsApp Web 'Grupos em Comum') */}
                {(group.contactPhone === '120363424944423399' || group.contactName.includes('Servweld/Servsolda')) && isExpanded && (
                  <div style={{
                    backgroundColor: 'rgba(0,0,0,0.3)',
                    padding: '8px 12px 10px 16px',
                    borderTop: '1px solid rgba(0, 230, 153, 0.2)',
                    borderLeft: '3px solid var(--accent-primary)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px'
                  }}>
                    <div style={{ fontSize: '10px', fontWeight: '700', color: 'var(--accent-primary)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '2px' }}>
                      <Users size={11} /> Grupos da Comunidade:
                    </div>

                    {conversations
                      .filter(c => c.contact?.telefone === '120363421689967835' || c.contact?.telefone === '120363405705656894')
                      .map(subGroupConv => {
                        const isSubSelected = activeConversation?.id === subGroupConv.id;
                        const subLastMsg = subGroupConv.messages && subGroupConv.messages.length > 0 ? subGroupConv.messages[subGroupConv.messages.length - 1] : null;

                        return (
                          <div
                            key={`subgroup_${subGroupConv.id}`}
                            onClick={() => onSelectConversation(subGroupConv)}
                            style={{
                              padding: '6px 8px',
                              borderRadius: '6px',
                              backgroundColor: isSubSelected ? 'rgba(0, 230, 153, 0.15)' : 'rgba(255, 255, 255, 0.04)',
                              border: isSubSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px'
                            }}
                          >
                            {subGroupConv.contact?.foto_perfil_url ? (
                              <img
                                src={subGroupConv.contact.foto_perfil_url}
                                alt={subGroupConv.contact.nome}
                                style={{ width: '26px', height: '26px', borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }}
                              />
                            ) : (
                              <div style={{ width: '26px', height: '26px', borderRadius: '50%', backgroundColor: 'var(--accent-primary)', color: '#000', fontWeight: '700', fontSize: '11px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                G
                              </div>
                            )}

                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: '11px', fontWeight: '700', color: isSubSelected ? 'var(--accent-primary)' : 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {subGroupConv.contact?.nome || 'Grupo'}
                              </div>
                              <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {subLastMsg ? subLastMsg.conteudo : 'Conversa iniciada'}
                              </div>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <button
                                type="button"
                                onClick={(e) => handleTogglePin(e, subGroupConv)}
                                title={isConvPinned(subGroupConv) ? "Desafixar grupo do topo" : "Fixar grupo no topo"}
                                style={{
                                  background: isConvPinned(subGroupConv) ? 'rgba(234, 179, 8, 0.22)' : 'rgba(255, 255, 255, 0.06)',
                                  border: isConvPinned(subGroupConv) ? '1px solid rgba(234, 179, 8, 0.6)' : '1px solid rgba(255, 255, 255, 0.15)',
                                  borderRadius: '4px',
                                  color: isConvPinned(subGroupConv) ? '#eab308' : 'var(--text-muted)',
                                  padding: '2px 5px',
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '3px',
                                  fontSize: '9px',
                                  fontWeight: '700'
                                }}
                              >
                                <Pin size={10} fill={isConvPinned(subGroupConv) ? '#eab308' : 'none'} color={isConvPinned(subGroupConv) ? '#eab308' : 'currentColor'} />
                                <span>{isConvPinned(subGroupConv) ? 'Fixado' : 'Fixar'}</span>
                              </button>

                              <span className={`badge badge-${subGroupConv.status}`} style={{ fontSize: '8px', padding: '1px 4px' }}>
                                {subGroupConv.status.replace('_', ' ')}
                              </span>
                            </div>
                          </div>
                        );
                      })}
                  </div>
                )}

                {/* Sub-threads Accordion (Conversas do Cliente: Ativas, Expiradas, Encerradas) */}
                {isExpanded && group.allConversations.length > 1 && !(group.contactPhone === '120363424944423399' || group.contactName.includes('Servweld/Servsolda')) && (
                  <div style={{
                    backgroundColor: 'rgba(0,0,0,0.25)',
                    padding: '8px 12px 10px 20px',
                    borderTop: '1px dashed var(--border-color)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px'
                  }}>
                    <div style={{ fontSize: '10px', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <History size={10} /> Histórico de Chamados ({group.allConversations.length}):
                    </div>

                    {group.allConversations.map((subConv) => {
                      const isSubActive = activeConversation?.id === subConv.id;
                      const subLastMsg = subConv.messages && subConv.messages.length > 0 ? subConv.messages[subConv.messages.length - 1] : null;

                      return (
                        <div
                          key={subConv.id}
                          onClick={() => onSelectConversation(subConv)}
                          style={{
                            padding: '6px 10px',
                            borderRadius: '6px',
                            backgroundColor: isSubActive ? 'rgba(0, 230, 153, 0.15)' : 'rgba(255, 255, 255, 0.03)',
                            border: isSubActive ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                            cursor: 'pointer',
                            display: 'flex',
                            justify: 'space-between',
                            alignItems: 'center'
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '11px', fontWeight: '600', color: isSubActive ? 'var(--accent-primary)' : 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                              {isConvPinned(subConv) && (
                                <Pin size={10} fill="#eab308" color="#eab308" />
                              )}
                              <span>#{subConv.id} • {subConv.whatsapp_number?.nome_departamento || 'Geral'}</span>
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '160px' }}>
                              {subLastMsg ? subLastMsg.conteudo : 'Sem mensagens'}
                            </div>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <button
                              type="button"
                              onClick={(e) => handleTogglePin(e, subConv)}
                              title={isConvPinned(subConv) ? "Desafixar do topo" : "Fixar no topo"}
                              style={{
                                background: isConvPinned(subConv) ? 'rgba(234, 179, 8, 0.18)' : 'transparent',
                                border: 'none',
                                color: isConvPinned(subConv) ? '#eab308' : 'var(--text-muted)',
                                padding: '2px',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center'
                              }}
                            >
                              <Pin size={10} fill={isConvPinned(subConv) ? '#eab308' : 'none'} />
                            </button>
                            <div style={{ textAlign: 'right' }}>
                              <span className={`badge badge-${subConv.status}`} style={{ fontSize: '9px', padding: '1px 5px' }}>
                                {subConv.status.replace('_', ' ')}
                              </span>
                              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                {formatTime(subConv.ultima_interacao_em)}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <AvatarModal
        isOpen={!!avatarModalData}
        onClose={() => setAvatarModalData(null)}
        name={avatarModalData?.name || ''}
        phone={avatarModalData?.phone}
        avatarUrl={avatarModalData?.avatarUrl}
      />
    </div>
  );
};
