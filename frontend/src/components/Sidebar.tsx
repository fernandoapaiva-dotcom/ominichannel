import React from 'react';
import { MessageSquare, Users, Settings, LogOut, Bot, ShieldCheck, Filter } from 'lucide-react';
import { User } from '../types';

interface SidebarProps {
  user: User;
  activeTab: 'chats' | 'contacts' | 'segmentation' | 'admin';
  setActiveTab: (tab: 'chats' | 'contacts' | 'segmentation' | 'admin') => void;
  onLogout: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ user, activeTab, setActiveTab, onLogout }) => {
  return (
    <aside style={{
      width: '80px',
      height: '100%',
      backgroundColor: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border-color)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      padding: '24px 0',
      justifyContent: 'space-between'
    }}>
      {/* Brand Icon */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '24px'
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

        {/* Navigation Tabs */}
        <nav style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '16px' }}>
          <button
            onClick={() => setActiveTab('chats')}
            title="Conversas WhatsApp"
            style={{
              width: '48px',
              height: '48px',
              borderRadius: 'var(--radius-md)',
              background: activeTab === 'chats' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
              color: activeTab === 'chats' ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: activeTab === 'chats' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <MessageSquare size={22} />
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
              justifyContent: 'center'
            }}
          >
            <Users size={22} />
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
              justifyContent: 'center'
            }}
          >
            <Filter size={22} />
          </button>

          {user.role === 'admin' && (
            <button
              onClick={() => setActiveTab('admin')}
              title="Painel Administrativo"
              style={{
                width: '48px',
                height: '48px',
                borderRadius: 'var(--radius-md)',
                background: activeTab === 'admin' ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
                color: activeTab === 'admin' ? 'var(--accent-primary)' : 'var(--text-muted)',
                border: activeTab === 'admin' ? '1px solid rgba(0, 230, 153, 0.3)' : '1px solid transparent',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              <ShieldCheck size={22} />
            </button>
          )}
        </nav>
      </div>

      {/* User Avatar & Logout */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
        <div 
          title={`${user.nome} (${user.role})`}
          style={{
            width: '40px',
            height: '40px',
            borderRadius: '50%',
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
            border: '1px solid var(--border-color)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 'bold',
            fontSize: '14px',
            color: 'var(--text-main)'
          }}
        >
          {user.nome.charAt(0).toUpperCase()}
        </div>

        <button
          onClick={onLogout}
          title="Sair do sistema"
          style={{
            width: '44px',
            height: '44px',
            borderRadius: 'var(--radius-md)',
            background: 'transparent',
            color: '#f87171',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
        >
          <LogOut size={20} />
        </button>
      </div>
    </aside>
  );
};
