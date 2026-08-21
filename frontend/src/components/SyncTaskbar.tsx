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
      bottom: '20px',
      right: '24px',
      zIndex: 99999,
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      maxWidth: '480px',
      width: 'calc(100vw - 48px)'
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
            className="glass-panel"
            style={{
              backgroundColor: '#0f172a',
              border: `1px solid ${borderColor}`,
              borderRadius: '12px',
              padding: minimized ? '10px 16px' : '16px 20px',
              boxShadow: `0 12px 35px ${glowColor}, 0 4px 12px rgba(0,0,0,0.5)`,
              transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
              color: '#f8fafc'
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                {isRunning && (
                  <div style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(0, 230, 153, 0.15)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--accent-primary)'
                  }}>
                    <RefreshCw size={15} className="spin" />
                  </div>
                )}
                {isCompleted && (
                  <div style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(16, 185, 129, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#34d399'
                  }}>
                    <CheckCircle2 size={16} />
                  </div>
                )}
                {isError && (
                  <div style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(239, 68, 68, 0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#f87171'
                  }}>
                    <AlertCircle size={16} />
                  </div>
                )}

                <div>
                  <h4 style={{ fontSize: '13px', fontWeight: '700', margin: 0, color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {isRunning ? 'Sincronizando WhatsApp' : isCompleted ? 'Sincronização Concluída!' : 'Falha na Sincronização'}
                    <span style={{
                      fontSize: '11px',
                      fontWeight: '600',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor: 'rgba(255,255,255,0.08)',
                      color: 'var(--accent-primary)'
                    }}>
                      {item.instance}
                    </span>
                  </h4>
                  {minimized && (
                    <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                      {isRunning ? `${item.percentage}% (${item.processed_chats}/${item.total_chats} chats)` : `${item.messages_synced} msgs importadas`}
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button
                  onClick={() => setMinimized(!minimized)}
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '4px' }}
                  title={minimized ? 'Expandir' : 'Minimizar'}
                >
                  {minimized ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                <button
                  onClick={() => handleClose(item.instance)}
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '4px' }}
                  title="Fechar"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Body (when not minimized) */}
            {!minimized && (
              <div style={{ marginTop: '12px' }}>
                {/* Progress bar */}
                <div style={{
                  width: '100%',
                  height: '8px',
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  borderRadius: '4px',
                  overflow: 'hidden',
                  position: 'relative'
                }}>
                  <div style={{
                    width: `${Math.min(item.percentage, 100)}%`,
                    height: '100%',
                    background: isError ? '#ef4444' : isCompleted ? '#10b981' : 'linear-gradient(90deg, #00e699, #10b981)',
                    borderRadius: '4px',
                    transition: 'width 0.4s ease'
                  }} />
                </div>

                {/* Subtitle & Current Contact */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px', fontSize: '11px' }}>
                  <span style={{ color: '#94a3b8', maxWidth: '70%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {isRunning ? `Processando: ${item.current_contact || 'Varrendo contatos...'}` : isCompleted ? 'Histórico completo importado no sistema!' : (item.errors?.[0] || 'Erro desconhecido')}
                  </span>
                  <span style={{ fontWeight: '700', color: isError ? '#f87171' : 'var(--accent-primary)' }}>
                    {item.percentage}%
                  </span>
                </div>

                {/* Stats Counters */}
                <div style={{
                  display: 'flex',
                  gap: '12px',
                  marginTop: '12px',
                  paddingTop: '10px',
                  borderTop: '1px solid rgba(255, 255, 255, 0.08)',
                  fontSize: '11px',
                  color: '#cbd5e1'
                }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Database size={12} style={{ color: 'var(--accent-primary)' }} />
                    Chats: <strong>{item.processed_chats} / {item.total_chats}</strong>
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Users size={12} style={{ color: '#60a5fa' }} />
                    Contatos: <strong>{item.contacts_synced}</strong>
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <MessageSquare size={12} style={{ color: '#f59e0b' }} />
                    Mensagens: <strong>{item.messages_synced}</strong>
                  </span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};
