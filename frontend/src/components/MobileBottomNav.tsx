import React from 'react';
import { MessageSquare, Users, Contact as ContactIcon, Settings } from 'lucide-react';
import { User } from '../types';

interface MobileBottomNavProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  pendingBadgeCount: number;
  groupPendingBadgeCount: number;
  user: User;
}

export const MobileBottomNav: React.FC<MobileBottomNavProps> = ({
  activeTab,
  setActiveTab,
  pendingBadgeCount,
  groupPendingBadgeCount,
  user
}) => {
  const tabs = [
    {
      id: 'chats',
      label: 'Chats',
      icon: MessageSquare,
      badge: pendingBadgeCount,
      badgeColor: '#ef4444'
    },
    {
      id: 'groups',
      label: 'Grupos',
      icon: Users,
      badge: groupPendingBadgeCount,
      badgeColor: '#f59e0b'
    },
    {
      id: 'contacts',
      label: 'Clientes',
      icon: ContactIcon,
      badge: 0
    },
    ...(user.role === 'admin' ? [{
      id: 'admin',
      label: 'Config',
      icon: Settings,
      badge: 0
    }] : [])
  ];

  return (
    <nav
      className="mobile-bottom-nav"
      style={{
        display: 'none', // Controlled by media query in index.css
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: '60px',
        backgroundColor: '#131b2e',
        borderTop: '1px solid rgba(255, 255, 255, 0.08)',
        zIndex: 9999,
        justifyContent: 'space-around',
        alignItems: 'center',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        boxShadow: '0 -4px 20px rgba(0,0,0,0.4)'
      }}
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;

        return (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              flex: 1,
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '3px',
              background: 'transparent',
              border: 'none',
              color: isActive ? 'var(--accent-primary)' : 'var(--text-muted)',
              position: 'relative',
              cursor: 'pointer',
              padding: '6px 0'
            }}
          >
            <div style={{ position: 'relative', display: 'inline-flex' }}>
              <Icon size={22} strokeWidth={isActive ? 2.5 : 1.8} />
              {tab.badge > 0 && (
                <span
                  style={{
                    position: 'absolute',
                    top: '-4px',
                    right: '-8px',
                    backgroundColor: tab.badgeColor || '#ef4444',
                    color: '#ffffff',
                    fontSize: '9px',
                    fontWeight: '800',
                    borderRadius: '10px',
                    minWidth: '16px',
                    height: '16px',
                    padding: '0 3px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: '0 0 6px rgba(0,0,0,0.5)',
                    border: '1.5px solid #131b2e'
                  }}
                >
                  {tab.badge > 99 ? '99+' : tab.badge}
                </span>
              )}
            </div>
            <span
              style={{
                fontSize: '11px',
                fontWeight: isActive ? '700' : '500',
                letterSpacing: '0.2px'
              }}
            >
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
};
