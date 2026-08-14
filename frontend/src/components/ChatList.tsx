import React, { useState } from 'react';
import { Search, Filter, Phone, Bot, User as UserIcon, Clock, Plus } from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation, WhatsAppNumber, ConversationStatus } from '../types';

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

  const filteredConversations = conversations.filter(conv => {
    const matchesDept = selectedDepartmentId === 'all' || conv.whatsapp_number_id === selectedDepartmentId;
    const matchesStatus = statusFilter === 'all' || conv.status === statusFilter;
    const contactName = conv.contact?.nome || '';
    const contactPhone = conv.contact?.telefone || '';
    const matchesSearch = contactName.toLowerCase().includes(searchTerm.toLowerCase()) || contactPhone.includes(searchTerm);
    return matchesDept && matchesStatus && matchesSearch;
  });

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
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: '700' }}>
            Conversas
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
        <div style={{
          position: 'relative',
          marginBottom: '12px'
        }}>
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

        {/* Department Filter Pills */}
        <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', paddingBottom: '4px' }}>
          <button
            onClick={() => setSelectedDepartmentId('all')}
            style={{
              padding: '6px 12px',
              borderRadius: 'var(--radius-full)',
              fontSize: '12px',
              fontWeight: '500',
              whiteSpace: 'nowrap',
              background: selectedDepartmentId === 'all' ? 'var(--accent-primary)' : 'var(--bg-secondary)',
              color: selectedDepartmentId === 'all' ? '#051a12' : 'var(--text-muted)',
              border: '1px solid var(--border-color)'
            }}
          >
            Todos Dptos
          </button>
          {whatsappNumbers.map(wn => (
            <button
              key={wn.id}
              onClick={() => setSelectedDepartmentId(wn.id)}
              style={{
                padding: '6px 12px',
                borderRadius: 'var(--radius-full)',
                fontSize: '12px',
                fontWeight: '500',
                whiteSpace: 'nowrap',
                background: selectedDepartmentId === wn.id ? 'var(--accent-primary)' : 'var(--bg-secondary)',
                color: selectedDepartmentId === wn.id ? '#051a12' : 'var(--text-muted)',
                border: '1px solid var(--border-color)'
              }}
            >
              {wn.nome_departamento}
            </button>
          ))}
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

            return (
              <div
                key={conv.id}
                onClick={() => onSelectConversation(conv)}
                style={{
                  padding: '14px 16px',
                  borderBottom: '1px solid var(--border-color)',
                  backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.08)' : 'transparent',
                  borderLeft: isSelected ? '3px solid var(--accent-primary)' : '3px solid transparent',
                  cursor: 'pointer',
                  transition: 'var(--transition-fast)'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)' }}>
                    {conv.contact?.nome || conv.contact?.telefone || 'Cliente sem nome'}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {conv.ultima_interacao_em ? new Date(String(conv.ultima_interacao_em).endsWith('Z') || String(conv.ultima_interacao_em).includes('+') ? String(conv.ultima_interacao_em) : String(conv.ultima_interacao_em) + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
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
                    style={{ cursor: 'pointer', border: 'none', transition: 'transform 0.1s' }}
                  >
                    {conv.status === 'com_ia' && <Bot size={10} />}
                    {conv.status.replace('_', ' ')}
                  </button>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <p style={{
                    fontSize: '12px',
                    color: 'var(--text-dim)',
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
