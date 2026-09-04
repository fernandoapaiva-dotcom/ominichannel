import React, { useState, useEffect } from 'react';
import { RefreshCw, CheckCircle2, AlertCircle, X, ChevronUp, ChevronDown, Database, MessageSquare, Users } from 'lucide-react';
import { apiFetch } from '../services/api';

export interface SyncProgressItem {
  instance: string;
  whatsapp_number_id?: number;
  status: 'running' | 'completed' | 'error';
  total_chats: number;
  processed_chats: number;
  contacts_synced: number;
  conversations_synced: number;
  messages_synced: number;
  percentage: number;
  current_contact?: string;
  started_at?: string;
  errors?: string[];
}

const ViteIcon: React.FC<{ size?: number; spinning?: boolean }> = ({ size = 20, spinning }) => (
  <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
    {spinning && (
      <div style={{
        position: 'absolute',
        width: `${size + 10}px`,
        height: `${size + 10}px`,
        borderRadius: '50%',
        border: '2px solid transparent',
        borderTopColor: '#BD34FE',
        borderRightColor: '#41D1FF',
        animation: 'spin 1.2s linear infinite'
      }} />
    )}
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      style={{ filter: 'drop-shadow(0 0 8px rgba(189, 52, 254, 0.6))' }}
    >
      <path
        d="M29.6 4.8L16.8 28.4C16.5 29 15.7 29.1 15.3 28.5L3.1 8.8C2.6 8 3.2 7 4.1 7.1L16.2 8.4C16.6 8.4 17 8.2 17.2 7.8L28.1 3.5C29 3.1 29.9 3.9 29.6 4.8Z"
        fill="url(#viteGrad1)"
      />
      <path
        d="M22.1 2.3L9.6 4.9C8.9 5 8.5 5.8 8.8 6.4L16.5 21.8C16.8 22.3 17.6 22.2 17.8 21.7L23.4 3.7C23.6 2.9 22.9 2.1 22.1 2.3Z"
        fill="url(#viteGrad2)"
      />
      <defs>
        <linearGradient id="viteGrad1" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="#41D1FF" />
          <stop offset="1" stopColor="#BD34FE" />
        </linearGradient>
        <linearGradient id="viteGrad2" x1="10" y1="2" x2="24" y2="22" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFEA83" />
          <stop offset="0.08" stopColor="#FFDD35" />
          <stop offset="1" stopColor="#FFA800" />
        </linearGradient>
      </defs>
    </svg>
  </div>
);

export const SyncTaskbar: React.FC = () => {
  const [progressList, setProgressList] = useState<SyncProgressItem[]>([]);
  const [closedInstances, setClosedInstances] = useState<string[]>([]);

  // Poll sync progress from backend every 2s
  useEffect(() => {
    let isMounted = true;

    const checkProgress = async () => {
      try {
        const data: SyncProgressItem[] = await apiFetch('/whatsapp-numbers/sync_progress');
        if (isMounted && Array.isArray(data)) {
          setProgressList(data);
        }
      } catch (err) {
        // silent error during logout or disconnected state
      }
    };

    checkProgress();
    const interval = setInterval(checkProgress, 5000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    // Auto-dismiss completed sync items after 4 seconds
    progressList.forEach(item => {
      if (item.status === 'completed' && !closedInstances.includes(item.instance)) {
        const timer = setTimeout(() => {
          setClosedInstances(prev => [...prev, item.instance]);
        }, 4000);
        return () => clearTimeout(timer);
      }
    });
  }, [progressList, closedInstances]);

  const activeItems = progressList.filter(item => !closedInstances.includes(item.instance));

  if (activeItems.length === 0) {
    return null;
  }

  const handleClose = (instance: string) => {
    setClosedInstances(prev => [...prev, instance]);
  };

  return (
    <div style={{
      position: 'fixed',
      top: '14px',
      right: '24px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      maxWidth: '380px',
      width: 'calc(100vw - 48px)',
      pointerEvents: 'none'
    }}>
      {activeItems.map((item) => {
        const isRunning = item.status === 'running';
        const isCompleted = item.status === 'completed';
        const isError = item.status === 'error';

        const borderColor = isRunning ? 'rgba(189, 52, 254, 0.4)' : isCompleted ? '#10b981' : '#ef4444';
        const glowColor = isRunning ? 'rgba(189, 52, 254, 0.2)' : isCompleted ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)';

        return (
          <div
            key={item.instance}
            className="animate-fade-in"
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              border: `1px solid ${borderColor}`,
              borderRadius: '12px',
              padding: '10px 14px',
              boxShadow: `0 8px 30px ${glowColor}, 0 4px 12px rgba(0,0,0,0.6)`,
              color: '#f8fafc',
              pointerEvents: 'auto',
              backdropFilter: 'blur(12px)'
            }}
          >
            {/* Header with Vite JS Logo */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ViteIcon size={20} spinning={isRunning} />

                <div>
                  <div style={{ fontSize: '12px', fontWeight: '700', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {isRunning ? 'Sincronizando' : isCompleted ? 'Sincronizado!' : 'Falha na Sincronização'}
                    <span style={{
                      fontSize: '10px',
                      fontWeight: '600',
                      padding: '1px 6px',
                      borderRadius: '4px',
                      backgroundColor: 'rgba(255,255,255,0.08)',
                      color: '#41D1FF'
                    }}>
                      {item.instance}
                    </span>
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ fontSize: '11px', fontWeight: '800', color: isError ? '#f87171' : '#FFDD35' }}>
                  {item.percentage}%
                </span>
                <button
                  onClick={() => handleClose(item.instance)}
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px', display: 'flex', alignItems: 'center' }}
                  title="Fechar"
                >
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Progress bar */}
            {isRunning && (
              <div style={{ marginTop: '8px' }}>
                <div style={{
                  width: '100%',
                  height: '4px',
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  borderRadius: '2px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${Math.min(item.percentage, 100)}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #00e699, #10b981)',
                    borderRadius: '2px',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px', fontSize: '10px', color: '#94a3b8' }}>
                  <span>{item.processed_chats} de {item.total_chats} chats</span>
                  <span>{item.messages_synced} msgs</span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
