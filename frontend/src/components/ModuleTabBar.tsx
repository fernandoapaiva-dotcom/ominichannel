import React from 'react';
import { MessageSquare, Wrench, Settings, LayoutGrid } from 'lucide-react';
import { User } from '../types';
import { DashboardTab } from './ModuleHome';

interface TabDef {
  id: DashboardTab;
  label: string;
  icon: React.ReactNode;
  // A que seção esse módulo pertence, pra destacar a aba mesmo quando a pessoa está numa
  // sub-tela dele (ex: dentro de "grupos" a aba "WhatsApp" continua marcada como ativa).
  matches: DashboardTab[];
}

interface ModuleTabBarProps {
  user: User;
  activeTab: DashboardTab;
  onSelectModule: (tab: DashboardTab) => void;
}

export const ModuleTabBar: React.FC<ModuleTabBarProps> = ({ user, activeTab, onSelectModule }) => {
  const tabs: TabDef[] = [
    { id: 'chats', label: 'WhatsApp', icon: <MessageSquare size={14} />, matches: ['chats', 'groups', 'contacts', 'segmentation'] },
    { id: 'tecnicos', label: 'Assistência Técnica', icon: <Wrench size={14} />, matches: ['tecnicos'] },
  ];
  if (user.role === 'admin') {
    tabs.push({ id: 'admin', label: 'Configurações', icon: <Settings size={14} />, matches: ['admin'] });
  }

  return (
    <div
      className="module-tab-bar"
      style={{
        flexShrink: 0,
        display: 'flex',
        alignItems: 'flex-end',
        gap: '2px',
        padding: '6px 10px 0',
        background: 'var(--bg-secondary)',
        borderBottom: '1px solid var(--border-color)',
      }}
    >
      {/* Botão de módulos - leva pra tela de blocos (tipo "nova aba") */}
      <button
        onClick={() => onSelectModule('home')}
        title="Tela inicial de módulos"
        style={{
          flexShrink: 0,
          width: '30px',
          height: '30px',
          marginBottom: '2px',
          borderRadius: 'var(--radius-sm)',
          background: activeTab === 'home' ? 'var(--bg-primary)' : 'transparent',
          color: activeTab === 'home' ? 'var(--accent-primary)' : 'var(--text-muted)',
          border: 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
        }}
      >
        <LayoutGrid size={15} />
      </button>

      {tabs.map((tab) => {
        const isActive = tab.matches.includes(activeTab);
        return (
          <button
            key={tab.id}
            onClick={() => onSelectModule(tab.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '7px',
              padding: '8px 16px',
              background: isActive ? 'var(--bg-primary)' : 'transparent',
              color: isActive ? 'var(--text-main)' : 'var(--text-muted)',
              fontWeight: isActive ? 600 : 500,
              fontSize: '13px',
              border: 'none',
              borderTopLeftRadius: 'var(--radius-sm)',
              borderTopRightRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              transition: 'var(--transition-fast)',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.background = 'transparent';
            }}
          >
            <span style={{ color: isActive ? 'var(--accent-primary)' : 'inherit', display: 'flex' }}>{tab.icon}</span>
            {tab.label}
          </button>
        );
      })}
    </div>
  );
};
