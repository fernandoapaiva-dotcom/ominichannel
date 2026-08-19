import React, { useState, useMemo } from 'react';
import { Search, Phone, Bot, Headphones, Plus, ChevronDown, ChevronRight, History, Layers, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation, WhatsAppNumber, ConversationStatus } from '../types';

const formatTime = (ts: string | Date | undefined) => {
  if (!ts) return '';
  let str = String(ts).trim();
  if (str.includes(' ') && !str.includes('T')) {
    str = str.replace(' ', 'T');
  }
  if (!str.endsWith('Z') && !str.includes('+') && !str.includes('-')) {
    str = str + 'Z';
  }
  const d = new Date(str);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

interface ChatListProps {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  onSelectConversation: (conv: Conversation) => void;
  whatsappNumbers: WhatsAppNumber[];
  selectedDepartmentId: number | 'all';
  setSelectedDepartmentId: (id: number | 'all') => void;
  statusFilter: ConversationStatus | 'all';
  setStatusFilter: (status: ConversationStatus | 'all') => void;
  onOpenNewConversationModal?: () => void;
  onStatusToggle?: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

interface ContactGroup {
  contactId: number;
  contactName: string;
  contactPhone: string;
  primaryConv: Conversation;
  allConversations: Conversation[];
  hasUnread: boolean;
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
  onToggleCollapse
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedContactIds, setExpandedContactIds] = useState<number[]>([]);

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

  // Group conversations by contact
  const contactGroups = useMemo(() => {
    const map = new Map<number, Conversation[]>();

    conversations.forEach(conv => {
      const cid = conv.contact_id || conv.contact?.id || 0;
      if (!map.has(cid)) {
        map.set(cid, []);
      }
      map.get(cid)!.push(conv);
    });

    const groups: ContactGroup[] = [];

    map.forEach((convs, cid) => {
      convs.sort((a, b) => new Date(b.ultima_interacao_em).getTime() - new Date(a.ultima_interacao_em).getTime());

      const matchingConvs = convs.filter(conv => {
        const matchesDept = selectedDepartmentId === 'all' || String(conv.whatsapp_number_id) === String(selectedDepartmentId);
        const matchesStatus = statusFilter === 'all' || conv.status === statusFilter;
        const contactName = conv.contact?.nome || '';
        const contactPhone = conv.contact?.telefone || '';
        const matchesSearch = contactName.toLowerCase().includes(searchTerm.toLowerCase()) || contactPhone.includes(searchTerm);
        return matchesDept && matchesStatus && matchesSearch;
      });

      if (matchingConvs.length === 0) return;

      const primary = matchingConvs.find(c => c.status === 'com_ia' || c.status === 'com_humano') || matchingConvs[0];
      const contact = primary.contact;

      const hasUnread = matchingConvs.some(conv => {
        const lastMsg = conv.messages && conv.messages.length > 0 ? conv.messages[conv.messages.length - 1] : null;
        return lastMsg && lastMsg.remetente.toLowerCase() === 'cliente' && activeConversation?.id !== conv.id;
      });

      groups.push({
        contactId: cid,
        contactName: contact?.nome || contact?.telefone || 'Cliente sem nome',
        contactPhone: contact?.telefone || '',
        primaryConv: primary,
        allConversations: matchingConvs,
        hasUnread,
        activeCount: matchingConvs.filter(c => c.status === 'com_ia' || c.status === 'com_humano').length
      });
    });

    return groups.sort((a, b) => new Date(b.primaryConv.ultima_interacao_em).getTime() - new Date(a.primaryConv.ultima_interacao_em).getTime());
  }, [conversations, selectedDepartmentId, statusFilter, searchTerm, activeConversation]);

  const totalUnread = conversations.filter(conv => {
    const lastMsg = conv.messages && conv.messages.length > 0 ? conv.messages[conv.messages.length - 1] : null;
    return lastMsg && lastMsg.remetente.toLowerCase() === 'cliente' && activeConversation?.id !== conv.id;
  }).length;

  if (isCollapsed) return null;

  return (
    <div style={{
      width: '340px',
      minWidth: '320px',
      height: '100%',
      backgroundColor: 'var(--bg-primary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      boxSizing: 'border-box'
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
        justify: 'space-between',
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

            return (
              <div
                key={group.contactId}
                style={{
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: isGroupSelected ? 'rgba(0, 230, 153, 0.04)' : 'transparent',
                  transition: 'var(--transition-fast)'
                }}
              >
                {/* Main Contact Card */}
                <div
                  onClick={() => onSelectConversation(primaryConv)}
                  style={{
                    padding: '12px 14px',
                    borderLeft: isSelected ? '3px solid var(--accent-primary)' : (group.hasUnread ? '3px solid #ef4444' : '3px solid transparent'),
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.08)' : 'transparent'
                  }}
                >
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
                      maxWidth: '180px'
                    }}>
                      {group.contactName}
                      {group.hasUnread && (
                        <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: '#ef4444', flexShrink: 0 }} title="Mensagem não lida do cliente" />
                      )}
                    </span>
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)', flexShrink: 0 }}>
                      {formatTime(primaryConv.ultima_interacao_em)}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Phone size={11} /> {group.contactPhone}
                    </span>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <button
                        onClick={(e) => handleToggleStatus(e, primaryConv)}
                        title={primaryConv.status === 'com_ia' ? 'Alternar para Humano' : 'Alternar para IA'}
                        className={`badge badge-${primaryConv.status}`}
                        style={{ cursor: 'pointer', border: 'none', display: 'flex', alignItems: 'center', gap: '3px', padding: '2px 6px', fontSize: '9px', whiteSpace: 'nowrap' }}
                      >
                        {primaryConv.status === 'com_ia' ? <Bot size={9} /> : <Headphones size={9} />}
                        {primaryConv.status.replace('_', ' ')}
                      </button>

                      {/* Expand Sub-threads Button */}
                      {group.allConversations.length > 1 && (
                        <button
                          type="button"
                          onClick={(e) => toggleExpand(e, group.contactId)}
                          style={{
                            background: 'rgba(255, 255, 255, 0.08)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '4px',
                            color: 'var(--accent-primary)',
                            padding: '1px 5px',
                            fontSize: '9px',
                            fontWeight: '600',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '2px'
                          }}
                          title="Ver todas as conversas/histórico deste cliente"
                        >
                          <Layers size={10} /> {group.allConversations.length}
                          {isExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Last Message Preview & Dept */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <p style={{
                      fontSize: '11px',
                      color: group.hasUnread ? 'var(--text-main)' : 'var(--text-dim)',
                      fontWeight: group.hasUnread ? '600' : 'normal',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      maxWidth: '200px',
                      margin: 0
                    }}>
                      {lastMessage ? lastMessage.conteudo : 'Conversa iniciada'}
                    </p>
                    <span style={{
                      fontSize: '9px',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      backgroundColor: 'rgba(255, 255, 255, 0.05)',
                      color: 'var(--text-muted)',
                      whiteSpace: 'nowrap',
                      flexShrink: 0
                    }}>
                      {primaryConv.whatsapp_number?.nome_departamento || 'Dept'}
                    </span>
                  </div>
                </div>

                {/* Sub-threads Accordion (Conversas do Cliente: Ativas, Expiradas, Encerradas) */}
                {isExpanded && group.allConversations.length > 1 && (
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
                              <span>#{subConv.id} • {subConv.whatsapp_number?.nome_departamento || 'Geral'}</span>
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '160px' }}>
                              {subLastMsg ? subLastMsg.conteudo : 'Sem mensagens'}
                            </div>
                          </div>

                          <div style={{ textAlign: 'right' }}>
                            <span className={`badge badge-${subConv.status}`} style={{ fontSize: '9px', padding: '1px 5px' }}>
                              {subConv.status.replace('_', ' ')}
                            </span>
                            <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {formatTime(subConv.ultima_interacao_em)}
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
    </div>
  );
};
