import React, { useState, useEffect, useRef, useMemo } from 'react';
import { MessageSquare, Users, Settings, LogOut, Bot, ChevronLeft, ChevronRight, Contact as ContactIcon, Sun, Moon, Bell, CheckCircle2, X, MessageCircle, AlertCircle, Filter, CheckCheck } from 'lucide-react';
import { User, Conversation } from '../types';
import { apiFetch } from '../services/api';

interface SidebarProps {
  user: User;
  activeTab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin';
  setActiveTab: (tab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin') => void;
  onLogout: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  conversations?: Conversation[];
  onSelectConversation?: (convId: number) => void;
  onRefreshConversations?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  activeTab,
  setActiveTab,
  onLogout,
  isCollapsed = false,
  onToggleCollapse,
  conversations = [],
  onSelectConversation,
  onRefreshConversations
}) => {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('omni_theme') as 'dark' | 'light') || 'dark';
  });
  const [showAvatarMenu, setShowAvatarMenu] = useState(false);
  const [dismissedConvIds, setDismissedConvIds] = useState<Set<number>>(new Set());
  const avatarMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('omni_theme', theme);
  }, [theme]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (avatarMenuRef.current && !avatarMenuRef.current.contains(e.target as Node)) {
        setShowAvatarMenu(false);
      }
    };
    if (showAvatarMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showAvatarMenu]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  // Helper: check if conversation is pending a response from this attendant
  const isConversationPendingForAttendant = (conv: Conversation): boolean => {
    const isGroup = Boolean(
      conv.contact?.telefone?.startsWith('120363') ||
      (conv.contact?.telefone && conv.contact.telefone.length > 15) ||
      conv.contact?.nome?.includes('Servweld/Servsolda')
    );
    if (isGroup) return false;

    if (dismissedConvIds.has(conv.id)) return false;
    if (conv.status === 'encerrada' || conv.status === 'expirada_por_inatividade') return false;

    const isAssigned = conv.assigned_user_id === user.id ||
                       (user.role === 'admin') ||
                       (conv.status === 'aguardando_atendente');
    if (!isAssigned) return false;

    // Skip if marked as read or dismissed by attendant
    const extra = conv.dados_adicionais || {};
    if (extra.marked_as_read || extra.pending_dismissed) return false;

    const msgs = conv.messages || [];
    if (msgs.length === 0) return false;

    let lastAttendantMsgIndex = -1;
    let lastClientMsgIndex = -1;

    for (let i = 0; i < msgs.length; i++) {
      const r = String(msgs[i].remetente || '').toLowerCase();
      if (r === 'atendente') {
        lastAttendantMsgIndex = i;
      } else if (r === 'cliente') {
        lastClientMsgIndex = i;
      }
    }

    if (lastClientMsgIndex === -1) return false;

    // Recency check (last client message within 7 days or active protocol)
    const lastClientMsg = msgs[lastClientMsgIndex];
    if (lastClientMsg && lastClientMsg.timestamp) {
      const t = new Date(lastClientMsg.timestamp).getTime();
      if (!isNaN(t) && (Date.now() - t) > 7 * 24 * 60 * 60 * 1000 && !conv.protocol_number) {
        return false;
      }
    }

    // If attendant has never sent a message in this conversation, it is pending
    if (lastAttendantMsgIndex === -1) return true;

    // If customer sent a message AFTER the last attendant response
    if (lastClientMsgIndex > lastAttendantMsgIndex) return true;

    return false;
  };

  // Helper: check if a Group conversation has unread / pending activity
  const isGroupPending = (conv: Conversation): boolean => {
    const isGroup = Boolean(
      conv.contact?.telefone?.startsWith('120363') ||
      (conv.contact?.telefone && conv.contact.telefone.length > 15) ||
      conv.contact?.nome?.includes('Servweld/Servsolda')
    );
    if (!isGroup) return false;

    if (dismissedConvIds.has(conv.id)) return false;
    const extra = conv.dados_adicionais || {};
    if (extra.marked_as_read || extra.pending_dismissed) return false;

    const msgs = conv.messages || [];
    if (msgs.length === 0) return false;

    let lastAttendantMsgIndex = -1;
    let lastClientMsgIndex = -1;

    for (let i = 0; i < msgs.length; i++) {
      const r = String(msgs[i].remetente || '').toLowerCase();
      if (r === 'atendente') {
        lastAttendantMsgIndex = i;
      } else if (r === 'cliente') {
        lastClientMsgIndex = i;
      }
    }

    if (lastClientMsgIndex === -1) return false;

    const lastClientMsg = msgs[lastClientMsgIndex];
    if (lastClientMsg && lastClientMsg.timestamp) {
      const t = new Date(lastClientMsg.timestamp).getTime();
      if (!isNaN(t) && (Date.now() - t) > 7 * 24 * 60 * 60 * 1000) {
        return false;
      }
    }

    if (lastAttendantMsgIndex === -1) return true;
    if (lastClientMsgIndex > lastAttendantMsgIndex) return true;

    return false;
  };

  // List of all conversations genuinely pending response from this attendant
  const pendingConversations = useMemo(() => {
    if (!conversations || !Array.isArray(conversations)) return [];
    return conversations.filter(isConversationPendingForAttendant);
  }, [conversations, user, dismissedConvIds]);

  const groupPendingConversations = useMemo(() => {
    if (!conversations || !Array.isArray(conversations)) return [];
    return conversations.filter(isGroupPending);
  }, [conversations, dismissedConvIds]);

  const pendingBadgeCount = pendingConversations.length;
  const groupPendingBadgeCount = groupPendingConversations.length;

  const handleMarkSingleAsRead = async (e: React.MouseEvent, convId: number) => {
    e.preventDefault();
    e.stopPropagation();
    // Instantly remove from UI
    setDismissedConvIds(prev => new Set(prev).add(convId));
    try {
      await apiFetch(`/conversations/${convId}/mark_read`, { method: 'POST' });
      if (onRefreshConversations) onRefreshConversations();
    } catch (err) {
      console.error('Error marking conversation read:', err);
    }
  };

  const handleMarkAllPendingAsRead = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Instantly clear all from UI
    const idsToDismiss = pendingConversations.map(c => c.id);
    setDismissedConvIds(prev => {
      const next = new Set(prev);
      idsToDismiss.forEach(id => next.add(id));
      return next;
    });
    try {
      await apiFetch('/conversations/mark_all_read', { method: 'POST' });
      if (onRefreshConversations) onRefreshConversations();
    } catch (err) {
      console.error('Error marking all read:', err);
    }
  };

  // Extract short summary / reason for the transfer
  const getConversationReason = (conv: Conversation): string => {
    if (conv.assunto_atual) return conv.assunto_atual;
    if (conv.resumo_ia) return conv.resumo_ia;

    const msgs = conv.messages || [];
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i];
      if (m.remetente === 'sistema' && m.conteudo) {
        const lines = m.conteudo.split('\n');
        for (const line of lines) {
          if (line.toLowerCase().includes('motivo:') || line.toLowerCase().includes('problema:') || line.toLowerCase().includes('solicita') || line.toLowerCase().includes('resumo:')) {
            const clean = line.replace(/[#*`_]/g, '').trim();
            if (clean.length > 5) return clean;
          }
        }
      }
    }

    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].remetente === 'cliente' && msgs[i].conteudo) {
        return msgs[i].conteudo;
      }
    }

    return 'Atendimento transferido para suporte humano';
  };

  const handleOpenConversationFromMenu = (convId: number) => {
    setShowAvatarMenu(false);
    setActiveTab('chats');
    if (onSelectConversation) {
      onSelectConversation(convId);
    }
  };

  const renderAvatarMenu = () => {
    if (!showAvatarMenu) return null;

    return (
      <div
        ref={avatarMenuRef}
        style={{
          position: 'fixed',
          left: isCollapsed ? '52px' : '88px',
          bottom: '20px',
          width: '360px',
          maxHeight: '540px',
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 16px 40px rgba(0,0,0,0.5)',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'fadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)'
        }}
      >
        {/* Attendant Profile Header */}
        <div style={{
          padding: '16px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'rgba(0,0,0,0.2)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          {user.foto_perfil_url ? (
            <img
              src={user.foto_perfil_url}
              alt={user.nome}
              style={{
                width: '46px',
                height: '46px',
                borderRadius: '50%',
                objectFit: 'cover',
                border: '2px solid var(--accent-primary)'
              }}
            />
          ) : (
            <div style={{
              width: '46px',
              height: '46px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#051a12',
              fontSize: '18px',
              fontWeight: '700'
            }}>
              {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
            </div>
          )}

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: '700', fontSize: '15px', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {user.nome}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
              <span style={{
                display: 'inline-block',
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#10b981',
                boxShadow: '0 0 6px rgba(16, 185, 129, 0.6)'
              }} />
              <span>Online • {user.role === 'admin' ? 'Administrador' : 'Atendente'}</span>
            </div>
          </div>

          <button
            onClick={() => setShowAvatarMenu(false)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '4px'
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Submenu Title: Mensagens Pendentes */}
        <div style={{
          padding: '12px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: pendingBadgeCount > 0 ? 'rgba(239, 68, 68, 0.08)' : 'rgba(0, 230, 153, 0.05)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '700', color: 'var(--text-main)' }}>
            <MessageCircle size={16} color={pendingBadgeCount > 0 ? '#ef4444' : 'var(--accent-primary)'} />
            <span>Mensagens Pendentes de Resposta</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {pendingBadgeCount > 0 && (
              <button
                type="button"
                onClick={handleMarkAllPendingAsRead}
                style={{
                  background: 'rgba(255, 255, 255, 0.08)',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  color: '#cbd5e1',
                  borderRadius: '6px',
                  padding: '2px 8px',
                  fontSize: '11px',
                  fontWeight: '700',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  cursor: 'pointer'
                }}
                title="Marcar todas as conversas pendentes como lidas/resolvidas"
              >
                <CheckCheck size={13} color="var(--accent-primary)" /> Limpar Todas
              </button>
            )}
            <span style={{
              fontSize: '11px',
              backgroundColor: pendingBadgeCount > 0 ? '#ef4444' : 'var(--border-color)',
              color: '#fff',
              padding: '2px 8px',
              borderRadius: '12px',
              fontWeight: '800'
            }}>
              {pendingBadgeCount}
            </span>
          </div>
        </div>

        {/* Submenu List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          maxHeight: '300px',
          padding: '8px'
        }}>
          {pendingConversations.length === 0 ? (
            <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              <CheckCircle2 size={32} color="var(--accent-primary)" style={{ margin: '0 auto 10px', display: 'block' }} />
              <div style={{ fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>Tudo respondido!</div>
              Nenhuma conversa atribuída aguardando sua resposta no momento.
            </div>
          ) : (
            pendingConversations.map(conv => {
              const deptName = conv.whatsapp_number?.nome_departamento || 'Geral';
              const reason = getConversationReason(conv);
              const proto = conv.protocol_number ? `#${conv.protocol_number.slice(-4)}` : '';

              return (
                <div
                  key={conv.id}
                  onClick={() => handleOpenConversationFromMenu(conv.id)}
                  style={{
                    padding: '12px',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: '6px',
                    cursor: 'pointer',
                    backgroundColor: 'rgba(239, 68, 68, 0.06)',
                    border: '1px solid rgba(239, 68, 68, 0.25)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.12)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.06)'; }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{
                        display: 'inline-block',
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        backgroundColor: '#ef4444',
                        boxShadow: '0 0 6px rgba(239,68,68,0.8)'
                      }} />
                      <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-main)' }}>
                        {conv.contact?.nome || 'Cliente'}
                      </span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                        {proto}
                      </span>
                      <span style={{
                        fontSize: '10px',
                        padding: '2px 6px',
                        borderRadius: '4px',
                        backgroundColor: 'rgba(255,255,255,0.08)',
                        color: 'var(--text-muted)',
                        fontWeight: '600'
                      }}>
                        {deptName}
                      </span>
                    </div>
                  </div>

                  <div style={{
                    fontSize: '12px',
                    color: 'var(--text-muted)',
                    lineHeight: '1.4',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden'
                  }}>
                    <strong style={{ color: 'var(--text-main)', fontWeight: '600' }}>Motivo: </strong>
                    {reason}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px', paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                    <span style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '600' }}>
                      👉 Abrir chat
                    </span>
                    <button
                      type="button"
                      onClick={(e) => handleMarkSingleAsRead(e, conv.id)}
                      style={{
                        background: 'rgba(52, 211, 153, 0.15)',
                        border: '1px solid rgba(52, 211, 153, 0.4)',
                        color: '#34d399',
                        borderRadius: '6px',
                        padding: '3px 8px',
                        fontSize: '11px',
                        fontWeight: '700',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease'
                      }}
                      title="Marcar como lido/resolvido e dispensar deste alerta"
                    >
                      <CheckCheck size={13} /> Marcar Lido
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer Actions */}
        <div style={{
          padding: '10px 16px',
          borderTop: '1px solid var(--border-color)',
          backgroundColor: 'rgba(0,0,0,0.2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <button
            onClick={() => { setShowAvatarMenu(false); setActiveTab('admin'); }}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer'
            }}
          >
            <Settings size={14} />
            <span>Configurações</span>
          </button>

          <button
            onClick={() => { setShowAvatarMenu(false); onLogout(); }}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#ef4444',
              fontSize: '12px',
              fontWeight: '600',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              cursor: 'pointer'
            }}
          >
            <LogOut size={14} />
            <span>Sair da Conta</span>
          </button>
        </div>
      </div>
    );
  };

  if (isCollapsed) {
    return (
      <aside style={{
        width: '44px',
        minWidth: '44px',
        maxWidth: '44px',
        flex: '0 0 44px',
        flexShrink: 0,
        height: '100%',
        backgroundColor: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '16px 0',
        justifyContent: 'space-between',
        zIndex: 50,
        boxSizing: 'border-box',
        position: 'relative'
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          {onToggleCollapse && (
            <button
              onClick={onToggleCollapse}
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '50%',
                backgroundColor: 'rgba(0, 230, 153, 0.15)',
                color: 'var(--accent-primary)',
                border: '1px solid rgba(0, 230, 153, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer'
              }}
              title="Expandir menu principal"
            >
              <ChevronRight size={18} />
            </button>
          )}

          <div
            onClick={() => setActiveTab('chats')}
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--accent-gradient)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: '#051a12'
            }}
            title="Ir para Conversas"
          >
            <Bot size={18} />
          </div>
        </div>

        {/* Compact Navigation Icons */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <button
            onClick={() => setActiveTab('chats')}
            title="Conversas com Clientes"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: activeTab === 'chats' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
              color: activeTab === 'chats' ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: activeTab === 'chats' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <MessageSquare size={16} />
          </button>

          <button
            onClick={() => setActiveTab('groups')}
            title="Grupos & Comunidades WhatsApp"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: activeTab === 'groups' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
              color: activeTab === 'groups' ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: activeTab === 'groups' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <Users size={16} />
          </button>

          <button
            onClick={() => setActiveTab('contacts')}
            title="Histórico de Clientes"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: activeTab === 'contacts' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
              color: activeTab === 'contacts' ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: activeTab === 'contacts' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <ContactIcon size={16} />
          </button>

          {user.role === 'admin' && (
            <button
              onClick={() => setActiveTab('admin')}
              title="Configurações do Sistema"
              style={{
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-md)',
                background: activeTab === 'admin' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
                color: activeTab === 'admin' ? 'var(--accent-primary)' : 'var(--text-muted)',
                border: activeTab === 'admin' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer'
              }}
            >
              <Settings size={16} />
            </button>
          )}
        </nav>

        {/* Compact Theme Toggle & Avatar with Badge */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Mudar para Modo Dia (Claro)' : 'Mudar para Modo Noite (Escuro)'}
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(255, 255, 255, 0.06)',
              color: theme === 'dark' ? '#fbbf24' : '#6366f1',
              border: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>

          {/* Attendant Avatar with Red Pending Badge */}
          <div
            onClick={() => setShowAvatarMenu(!showAvatarMenu)}
            style={{ position: 'relative', cursor: 'pointer' }}
            title={`${user.nome} - ${pendingBadgeCount} conversa(s) pendente(s)`}
          >
            {user.foto_perfil_url ? (
              <img
                src={user.foto_perfil_url}
                alt={user.nome}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  objectFit: 'cover',
                  border: pendingBadgeCount > 0 ? '2px solid #ef4444' : '2px solid var(--accent-primary)'
                }}
              />
            ) : (
              <div style={{
                width: '32px',
                height: '32px',
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#051a12',
                fontSize: '13px',
                fontWeight: '700',
                border: pendingBadgeCount > 0 ? '2px solid #ef4444' : '1px solid var(--border-color)'
              }}>
                {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
              </div>
            )}

            {pendingBadgeCount > 0 && (
              <span style={{
                position: 'absolute',
                top: '-4px',
                right: '-4px',
                backgroundColor: '#ef4444',
                color: '#fff',
                fontSize: '9px',
                fontWeight: '800',
                borderRadius: '50%',
                width: '16px',
                height: '16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: '2px solid var(--bg-secondary)',
                boxShadow: '0 0 8px rgba(239,68,68,0.9)'
              }}>
                {pendingBadgeCount > 9 ? '9+' : pendingBadgeCount}
              </span>
            )}
          </div>
        </div>

        {renderAvatarMenu()}
      </aside>
    );
  }

  return (
    <aside className="sidebar-container" style={{
      width: '80px',
      minWidth: '80px',
      maxWidth: '80px',
      flex: '0 0 80px',
      flexShrink: 0,
      height: '100%',
      backgroundColor: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '24px 0',
      justifyContent: 'space-between',
      zIndex: 50,
      boxSizing: 'border-box',
      position: 'relative'
    }}>
      {/* Brand Icon & Collapse Toggle */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              border: '1px solid rgba(0, 230, 153, 0.3)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              transition: 'transform 0.15s ease'
            }}
            title="Recolher menu lateral"
            onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.1)')}
            onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
          >
            <ChevronLeft size={20} />
          </button>
        )}

        <div
          onClick={() => setActiveTab('chats')}
          style={{
            width: '48px',
            height: '48px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--accent-gradient)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: 'var(--accent-glow)',
            color: '#051a12',
            transition: 'transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1)'
          }}
          title="Ir para Conversas"
          onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
          onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
        >
          <Bot size={28} />
        </div>
      </div>

      {/* Main Navigation */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <button
          onClick={() => setActiveTab('chats')}
          title="Conversas com Clientes"
          style={{
            position: 'relative',
            width: '48px',
            height: '48px',
            borderRadius: 'var(--radius-md)',
            background: activeTab === 'chats' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
            color: activeTab === 'chats' ? 'var(--accent-primary)' : 'var(--text-muted)',
            border: activeTab === 'chats' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.15s ease'
          }}
        >
          <MessageSquare size={22} />
          {pendingBadgeCount > 0 && (
            <span style={{
              position: 'absolute',
              top: '4px',
              right: '4px',
              backgroundColor: '#ef4444',
              color: '#ffffff',
              fontSize: '10px',
              fontWeight: '800',
              borderRadius: '10px',
              minWidth: '16px',
              height: '16px',
              padding: '0 3px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 6px rgba(239,68,68,0.7)'
            }}>
              {pendingBadgeCount > 99 ? '99+' : pendingBadgeCount}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('groups')}
          title="Grupos & Comunidades WhatsApp"
          style={{
            position: 'relative',
            width: '48px',
            height: '48px',
            borderRadius: 'var(--radius-md)',
            background: activeTab === 'groups' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
            color: activeTab === 'groups' ? 'var(--accent-primary)' : 'var(--text-muted)',
            border: activeTab === 'groups' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.15s ease'
          }}
        >
          <Users size={22} />
          {groupPendingBadgeCount > 0 && (
            <span style={{
              position: 'absolute',
              top: '4px',
              right: '4px',
              backgroundColor: '#ef4444',
              color: '#ffffff',
              fontSize: '10px',
              fontWeight: '800',
              borderRadius: '10px',
              minWidth: '16px',
              height: '16px',
              padding: '0 3px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 6px rgba(239,68,68,0.7)'
            }}>
              {groupPendingBadgeCount > 99 ? '99+' : groupPendingBadgeCount}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('contacts')}
          title="Histórico de Clientes"
          style={{
            width: '48px',
            height: '48px',
            borderRadius: 'var(--radius-md)',
            background: activeTab === 'contacts' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
            color: activeTab === 'contacts' ? 'var(--accent-primary)' : 'var(--text-muted)',
            border: activeTab === 'contacts' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.15s ease'
          }}
        >
          <ContactIcon size={22} />
        </button>

        <button
          onClick={() => setActiveTab('segmentation')}
          title="Segmentação & Filtros"
          style={{
            width: '48px',
            height: '48px',
            borderRadius: 'var(--radius-md)',
            background: activeTab === 'segmentation' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
            color: activeTab === 'segmentation' ? 'var(--accent-primary)' : 'var(--text-muted)',
            border: activeTab === 'segmentation' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer'
          }}
        >
          <Filter size={22} />
        </button>

        {user.role === 'admin' && (
          <button
            onClick={() => setActiveTab('admin')}
            title="Configurações do Sistema"
            style={{
              width: '48px',
              height: '48px',
              borderRadius: 'var(--radius-md)',
              background: activeTab === 'admin' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
              color: activeTab === 'admin' ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: activeTab === 'admin' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <Settings size={22} />
          </button>
        )}
      </nav>

      {/* User Avatar with Badge, Theme Switcher & Logout */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Mudar para Modo Dia (Claro)' : 'Mudar para Modo Noite (Escuro)'}
          style={{
            width: '40px',
            height: '40px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(255, 255, 255, 0.06)',
            color: theme === 'dark' ? '#fbbf24' : '#6366f1',
            border: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'transform 0.15s ease'
          }}
          onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.1)')}
          onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
        >
          {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
        </button>

        {/* Attendant Avatar with Red Pending Badge */}
        <div
          onClick={() => setShowAvatarMenu(!showAvatarMenu)}
          style={{ position: 'relative', cursor: 'pointer', transition: 'transform 0.15s ease' }}
          title={`${user.nome} (${user.role}) - ${pendingBadgeCount} conversa(s) pendente(s)`}
          onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
          onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
        >
          {user.foto_perfil_url ? (
            <img
              src={user.foto_perfil_url}
              alt={user.nome}
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '50%',
                objectFit: 'cover',
                border: pendingBadgeCount > 0 ? '2px solid #ef4444' : '2px solid var(--accent-primary)',
                boxShadow: pendingBadgeCount > 0 ? '0 0 10px rgba(239, 68, 68, 0.4)' : '0 2px 8px rgba(0, 230, 153, 0.25)'
              }}
            />
          ) : (
            <div style={{
              width: '42px',
              height: '42px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#051a12',
              fontSize: '16px',
              fontWeight: '700',
              border: pendingBadgeCount > 0 ? '2px solid #ef4444' : '1px solid var(--border-color)',
              boxShadow: pendingBadgeCount > 0 ? '0 0 10px rgba(239, 68, 68, 0.4)' : '0 2px 8px rgba(0, 230, 153, 0.25)'
            }}>
              {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
            </div>
          )}

          {/* Glowing Red Notification Badge on Avatar */}
          {pendingBadgeCount > 0 && (
            <span style={{
              position: 'absolute',
              top: '-4px',
              right: '-4px',
              backgroundColor: '#ef4444',
              color: '#fff',
              fontSize: '10px',
              fontWeight: '800',
              borderRadius: '50%',
              minWidth: '18px',
              height: '18px',
              padding: '0 4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '2px solid var(--bg-secondary)',
              boxShadow: '0 0 8px rgba(239,68,68,0.85)',
              animation: 'pulse 2s infinite'
            }}>
              {pendingBadgeCount > 99 ? '99+' : pendingBadgeCount}
            </span>
          )}
        </div>

        <button
          onClick={onLogout}
          title="Sair da Conta"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '8px',
            borderRadius: 'var(--radius-sm)'
          }}
        >
          <LogOut size={20} />
        </button>
      </div>

      {renderAvatarMenu()}
    </aside>
  );
};
