import React, { useState, useEffect, useRef, useMemo } from 'react';
import { MessageSquare, Users, Settings, LogOut, Bot, ShieldCheck, Filter, ChevronLeft, ChevronRight, Menu, Contact as ContactIcon, Sun, Moon, Bell, CheckCircle2, Clock, UserCheck, X } from 'lucide-react';
import { User, Conversation } from '../types';

interface SidebarProps {
  user: User;
  activeTab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin';
  setActiveTab: (tab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin') => void;
  onLogout: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
  conversations?: Conversation[];
  onSelectConversation?: (convId: number) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  activeTab,
  setActiveTab,
  onLogout,
  isCollapsed = false,
  onToggleCollapse,
  conversations = [],
  onSelectConversation
}) => {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('omni_theme') as 'dark' | 'light') || 'dark';
  });
  const [showAvatarMenu, setShowAvatarMenu] = useState(false);
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

  // Attendant assigned conversations & unread calculation
  const myAssignedConversations = useMemo(() => {
    if (!conversations || !Array.isArray(conversations)) return [];
    return conversations.filter(c => 
      c.assigned_user_id === user.id || 
      (c.status === 'com_humano' && c.assigned_user_id === user.id) ||
      (user.role === 'admin' && (c.status === 'aguardando_atendente' || c.status === 'com_humano'))
    );
  }, [conversations, user]);

  const totalUnreadCount = useMemo(() => {
    return myAssignedConversations.reduce((acc, c) => acc + (c.unread_count || 0), 0);
  }, [myAssignedConversations]);

  const pendingRepliesCount = useMemo(() => {
    return myAssignedConversations.filter(c => {
      const lastMsg = c.messages && c.messages.length > 0 ? c.messages[c.messages.length - 1] : null;
      return lastMsg && lastMsg.remetente === 'cliente';
    }).length;
  }, [myAssignedConversations]);

  const totalBadge = totalUnreadCount > 0 ? totalUnreadCount : (pendingRepliesCount > 0 ? pendingRepliesCount : 0);

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
          width: '340px',
          maxHeight: '520px',
          backgroundColor: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: '0 12px 36px rgba(0,0,0,0.45)',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'fadeIn 0.2s ease-out'
        }}
      >
        {/* Profile Header */}
        <div style={{
          padding: '16px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'rgba(0,0,0,0.15)',
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
                backgroundColor: '#10b981'
              }} />
              <span>Online • {user.role === 'admin' ? 'Administrador' : 'Atendente'}</span>
            </div>
            {user.departamento && (
              <div style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '600', marginTop: '2px' }}>
                Setor: {user.departamento}
              </div>
            )}
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

        {/* Submenu Title */}
        <div style={{
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'rgba(0, 230, 153, 0.05)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: '700', color: 'var(--text-main)' }}>
            <Bell size={14} color="var(--accent-primary)" />
            <span>Minhas Mensagens & Conversas</span>
          </div>
          <span style={{
            fontSize: '11px',
            backgroundColor: totalBadge > 0 ? '#ef4444' : 'var(--border-color)',
            color: '#fff',
            padding: '2px 8px',
            borderRadius: '10px',
            fontWeight: '700'
          }}>
            {myAssignedConversations.length}
          </span>
        </div>

        {/* Submenu List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          maxHeight: '260px',
          padding: '6px'
        }}>
          {myAssignedConversations.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              <CheckCircle2 size={28} color="var(--accent-primary)" style={{ margin: '0 auto 8px', display: 'block' }} />
              Nenhuma mensagem pendente no momento. Você está em dia!
            </div>
          ) : (
            myAssignedConversations.map(conv => {
              const lastMsg = conv.messages && conv.messages.length > 0 ? conv.messages[conv.messages.length - 1] : null;
              const isUnread = (conv.unread_count || 0) > 0 || (lastMsg && lastMsg.remetente === 'cliente');

              return (
                <div
                  key={conv.id}
                  onClick={() => handleOpenConversationFromMenu(conv.id)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: '4px',
                    cursor: 'pointer',
                    backgroundColor: isUnread ? 'rgba(0, 230, 153, 0.08)' : 'transparent',
                    border: isUnread ? '1px solid rgba(0, 230, 153, 0.25)' : '1px solid transparent',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.06)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = isUnread ? 'rgba(0, 230, 153, 0.08)' : 'transparent'; }}
                >
                  <div style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '50%',
                    background: 'var(--accent-gradient)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#051a12',
                    fontWeight: '700',
                    fontSize: '13px',
                    flexShrink: 0
                  }}>
                    {conv.contact?.nome ? conv.contact.nome.charAt(0).toUpperCase() : 'C'}
                  </div>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '2px' }}>
                      <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {conv.contact?.nome || 'Cliente'}
                      </span>
                      {conv.protocol_number && (
                        <span style={{ fontSize: '10px', color: 'var(--accent-primary)', fontWeight: '600' }}>
                          #{conv.protocol_number.slice(-4)}
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {lastMsg ? lastMsg.conteudo : 'Conversa em andamento'}
                    </div>
                  </div>

                  {conv.unread_count && conv.unread_count > 0 ? (
                    <span style={{
                      backgroundColor: '#ef4444',
                      color: '#fff',
                      fontSize: '10px',
                      fontWeight: '800',
                      padding: '2px 6px',
                      borderRadius: '10px',
                      flexShrink: 0
                    }}>
                      {conv.unread_count}
                    </span>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        {/* Footer Actions */}
        <div style={{
          padding: '10px 16px',
          borderTop: '1px solid var(--border-color)',
          backgroundColor: 'rgba(0,0,0,0.15)',
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
            <span>Sair</span>
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

          {/* Avatar with notification badge */}
          <div
            onClick={() => setShowAvatarMenu(!showAvatarMenu)}
            style={{ position: 'relative', cursor: 'pointer' }}
            title={`${user.nome} - Clique para ver mensagens atribuídas`}
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
                  border: '2px solid var(--accent-primary)'
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
                fontWeight: '700'
              }}>
                {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
              </div>
            )}

            {totalBadge > 0 && (
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
                boxShadow: '0 0 6px rgba(239,68,68,0.8)'
              }}>
                {totalBadge > 9 ? '9+' : totalBadge}
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
        </button>

        <button
          onClick={() => setActiveTab('groups')}
          title="Grupos & Comunidades WhatsApp"
          style={{
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

        {/* Attendant Avatar with Real-time Notification Badge */}
        <div
          onClick={() => setShowAvatarMenu(!showAvatarMenu)}
          style={{ position: 'relative', cursor: 'pointer', transition: 'transform 0.15s ease' }}
          title={`${user.nome} (${user.role}) - Clique para ver mensagens e conversas atribuídas`}
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
                border: '2px solid var(--accent-primary)',
                boxShadow: '0 2px 8px rgba(0, 230, 153, 0.25)'
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
              border: '1px solid var(--border-color)',
              boxShadow: '0 2px 8px rgba(0, 230, 153, 0.25)'
            }}>
              {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
            </div>
          )}

          {/* Glowing Notification Badge on Avatar */}
          {totalBadge > 0 && (
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
              {totalBadge > 99 ? '99+' : totalBadge}
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
