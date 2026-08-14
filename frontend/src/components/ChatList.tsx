import React, { useState } from 'react';
import { Search, Filter, Phone, Bot, Headphones, User as UserIcon, Clock, Plus, MessageSquare } from 'lucide-react';
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
  onStatusToggle
}) => {
  const [searchTerm, setSearchTerm] = useState('');

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

  // Helper to calculate unread/pending client conversations for each department
  const getUnreadCount = (deptId: number | 'all') => {
    return conversations.filter(conv => {
      const matchesDept = deptId === 'all' || conv.whatsapp_number_id === deptId;
      if (!matchesDept) return false;
      const lastMsg = conv.messages[conv.messages.length - 1];
      const isUnreadClientMsg = lastMsg && lastMsg.remetente.toLowerCase() === 'cliente';
      const isNotCurrentlyOpen = activeConversation?.id !== conv.id;
      return isUnreadClientMsg && isNotCurrentlyOpen;
    }).length;
  };

  const filteredConversations = conversations.filter(conv => {
    const matchesDept = selectedDepartmentId === 'all' || conv.whatsapp_number_id === selectedDepartmentId;
    const matchesStatus = statusFilter === 'all' || conv.status === statusFilter;
    const contactName = conv.contact?.nome || '';
    const contactPhone = conv.contact?.telefone || '';
    const matchesSearch = contactName.toLowerCase().includes(searchTerm.toLowerCase()) || contactPhone.includes(searchTerm);
    return matchesDept && matchesStatus && matchesSearch;
  });

  const totalUnread = getUnreadCount('all');

  return (
    <div style={{
      width: '360px',
      height: '100%',
      backgroundColor: 'var(--bg-primary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column'
    }}>
      {/* Header & Search */}
      <div style={{ padding: '20px 16px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '8px' }}>
            Conversas
            {totalUnread > 0 && (
              <span style={{
                backgroundColor: '#ef4444',
                color: '#fff',
                borderRadius: '12px',
                padding: '2px 8px',
                fontSize: '11px',
                fontWeight: '700'
              }}>
                {totalUnread} pendentes
              </span>
            )}
          </h2>
          {onOpenNewConversationModal && (
            <button
              onClick={onOpenNewConversationModal}
              className="btn-primary"
              style={{ fontSize: '12px', padding: '6px 12px', borderRadius: 'var(--radius-md)' }}
              title="Iniciar nova conversa por telefone"
            >
              <Plus size={15} /> Nova Conversa
            </button>
          )}
        </div>

        {/* Search Bar */}
        <div style={{ position: 'relative', marginBottom: '12px' }}>
          <Search size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Buscar por nome ou telefone..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              padding: '10px 12px 10px 36px',
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-main)',
              fontSize: '13px',
              outline: 'none'
            }}
          />
        </div>
      </div>

      {/* Status Filter Sub-Bar */}
      <div style={{
        padding: '10px 16px',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        gap: '8px',
        fontSize: '12px',
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
            fontSize: '12px',
            cursor: 'pointer',
            outline: 'none'
          }}
        >
          <option value="all" style={{ background: '#131b2e' }}>Todos</option>
          <option value="com_ia" style={{ background: '#131b2e' }}>Com IA Concierge</option>
          <option value="com_humano" style={{ background: '#131b2e' }}>Com Atendente Humano</option>
          <option value="encerrada" style={{ background: '#131b2e' }}>Encerradas</option>
          <option value="expirada_por_inatividade" style={{ background: '#131b2e' }}>Expiradas (Inatividade)</option>
        </select>
      </div>

      {/* List items */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {filteredConversations.length === 0 ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
            Nenhuma conversa encontrada.
          </div>
        ) : (
          filteredConversations.map(conv => {
            const isSelected = activeConversation?.id === conv.id;
            const lastMessage = conv.messages[conv.messages.length - 1];
            const isUnreadClientMsg = lastMessage && lastMessage.remetente.toLowerCase() === 'cliente' && !isSelected;

            return (
              <div
                key={conv.id}
                onClick={() => onSelectConversation(conv)}
                style={{
                  padding: '14px 16px',
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.08)' : (isUnreadClientMsg ? 'rgba(239, 68, 68, 0.05)' : 'transparent'),
                  borderLeft: isSelected ? '3px solid var(--accent-primary)' : (isUnreadClientMsg ? '3px solid #ef4444' : '3px solid transparent'),
                  cursor: 'pointer',
                  transition: 'var(--transition-fast)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {conv.contact?.nome || conv.contact?.telefone || 'Cliente sem nome'}
                    {isUnreadClientMsg && (
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#ef4444', display: 'inline-block' }} title="Mensagem não lida do cliente" />
                    )}
                  </span>
                  <span style={{ fontSize: '11px', color: isUnreadClientMsg ? '#ef4444' : 'var(--text-muted)', fontWeight: isUnreadClientMsg ? 'bold' : 'normal' }}>
                    {formatTime(conv.ultima_interacao_em)}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Phone size={12} /> {conv.contact?.telefone}
                  </span>
                  <button
                    onClick={(e) => handleToggleStatus(e, conv)}
                    title={conv.status === 'com_ia' ? 'Clique para alternar para Atendente Humano' : 'Clique para alternar para IA Concierge'}
                    className={`badge badge-${conv.status}`}
                    style={{ cursor: 'pointer', border: 'none', transition: 'transform 0.1s', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    {conv.status === 'com_ia' ? <Bot size={10} /> : <Headphones size={10} />}
                    {conv.status.replace('_', ' ')}
                  </button>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <p style={{
                    fontSize: '12px',
                    color: isUnreadClientMsg ? 'var(--text-main)' : 'var(--text-dim)',
                    fontWeight: isUnreadClientMsg ? '600' : 'normal',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: '220px'
                  }}>
                    {lastMessage ? lastMessage.conteudo : 'Conversa iniciada'}
                  </p>
                  <span style={{
                    fontSize: '10px',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                    color: 'var(--text-muted)'
                  }}>
                    {conv.whatsapp_number?.nome_departamento || 'Dept'}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
