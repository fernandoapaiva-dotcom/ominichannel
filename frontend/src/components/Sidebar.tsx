import React, { useState, useEffect } from 'react';
import { MessageSquare, Users, Settings, LogOut, Bot, ShieldCheck, Filter, ChevronLeft, ChevronRight, Menu, Contact as ContactIcon, Sun, Moon } from 'lucide-react';
import { User } from '../types';

interface SidebarProps {
  user: User;
  activeTab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin';
  setActiveTab: (tab: 'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin') => void;
  onLogout: () => void;
  isCollapsed?: boolean;
  onToggleCollapse?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  user,
  activeTab,
  setActiveTab,
  onLogout,
  isCollapsed = false,
  onToggleCollapse
}) => {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('omni_theme') as 'dark' | 'light') || 'dark';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('omni_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
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
        boxSizing: 'border-box'
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

        {/* Compact Theme Toggle & Logout */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
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

          <button
            onClick={onLogout}
            title="Sair da Conta"
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-md)',
              background: 'transparent',
              color: '#ef4444',
              border: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <LogOut size={16} />
          </button>
        </div>
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
      padding: '20px 0',
      justifyContent: 'space-between',
      transition: 'var(--transition-fast)',
      boxSizing: 'border-box'
    }}>
      {/* Brand Icon & Collapse Toggle */}
      <div className="sidebar-brand" style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '16px'
      }}>
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--accent-gradient)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: 'var(--accent-glow)',
          color: '#051a12'
        }}>
          <Bot size={28} />
        </div>

        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '50%',
              backgroundColor: 'rgba(255,255,255,0.06)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
            title="Retrair/Recolher menu principal"
          >
            <ChevronLeft size={16} />
          </button>
        )}
      </div>

      {/* Navigation Tabs */}
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
            cursor: 'pointer'
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
            cursor: 'pointer'
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
            cursor: 'pointer'
          }}
        >
          <ContactIcon size={22} />
        </button>

        <button
          onClick={() => setActiveTab('segmentation')}
          title="Segmentação & Tags"
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

      {/* User Avatar / Role, Theme Switcher & Logout */}
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

        {user.foto_perfil_url ? (
          <img
            src={user.foto_perfil_url}
            alt={user.nome}
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '50%',
              objectFit: 'cover',
              border: '2px solid var(--accent-primary)',
              boxShadow: '0 2px 8px rgba(0, 230, 153, 0.25)',
              cursor: 'pointer'
            }}
            title={`${user.nome} (${user.role})`}
          />
        ) : (
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#051a12',
            fontSize: '15px',
            fontWeight: '700',
            border: '1px solid var(--border-color)',
            boxShadow: '0 2px 8px rgba(0, 230, 153, 0.25)'
          }} title={`${user.nome} (${user.role})`}>
            {user.nome ? user.nome.charAt(0).toUpperCase() : 'U'}
          </div>
        )}

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
    </aside>
  );
};
