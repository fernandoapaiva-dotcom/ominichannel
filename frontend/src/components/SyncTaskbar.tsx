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

export const SyncTaskbar: React.FC = () => {
  const [progressList, setProgressList] = useState<SyncProgressItem[]>([]);
  const [minimized, setMinimized] = useState(false);
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
    const interval = setInterval(checkProgress, 2000);

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
      top: '16px',
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

        const borderColor = isRunning ? 'rgba(0, 230, 153, 0.4)' : isCompleted ? '#10b981' : '#ef4444';
        const glowColor = isRunning ? 'rgba(0, 230, 153, 0.15)' : isCompleted ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)';

        return (
          <div
            key={item.instance}
            className="animate-fade-in"
            style={{
              backgroundColor: '#0f172a',
              border: `1px solid ${borderColor}`,
              borderRadius: '10px',
              padding: '10px 14px',
              boxShadow: `0 8px 25px ${glowColor}, 0 4px 10px rgba(0,0,0,0.6)`,
              color: '#f8fafc',
              pointerEvents: 'auto',
              backdropFilter: 'blur(8px)'
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {isRunning && (
                  <div style={{
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(0, 230, 153, 0.15)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--accent-primary)',
                    flexShrink: 0
                  }}>
                    <RefreshCw size={12} className="spin" />
                  </div>
                )}
                {isCompleted && (
                  <div style={{
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(16, 185, 129, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#34d399',
                    flexShrink: 0
                  }}>
                    <CheckCircle2 size={13} />
                  </div>
                )}
                {isError && (
                  <div style={{
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(239, 68, 68, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#f87171',
                    flexShrink: 0
                  }}>
                    <AlertCircle size={13} />
                  </div>
                )}

                <div>
                  <div style={{ fontSize: '12px', fontWeight: '700', color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {isRunning ? 'Sincronizando' : isCompleted ? 'Sincronizado!' : 'Falha na Sincronização'}
                    <span style={{
                      fontSize: '10px',
                      fontWeight: '600',
                      padding: '1px 5px',
                      borderRadius: '4px',
                      backgroundColor: 'rgba(255,255,255,0.08)',
                      color: 'var(--accent-primary)'
                    }}>
                      {item.instance}
                    </span>
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ fontSize: '11px', fontWeight: '700', color: isError ? '#f87171' : 'var(--accent-primary)' }}>
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
