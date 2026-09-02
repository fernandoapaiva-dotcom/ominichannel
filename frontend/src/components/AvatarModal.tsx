import React, { useState } from 'react';
import { X, ExternalLink, RefreshCw } from 'lucide-react';
import { apiFetch } from '../services/api';

interface AvatarModalProps {
  isOpen: boolean;
  onClose: () => void;
  name: string;
  phone?: string;
  avatarUrl?: string | null;
  contactId?: number;
  onAvatarUpdated?: (newUrl: string) => void;
}

export const AvatarModal: React.FC<AvatarModalProps> = ({
  isOpen,
  onClose,
  name,
  phone,
  avatarUrl,
  contactId,
  onAvatarUpdated
}) => {
  const [currentUrl, setCurrentUrl] = useState<string | null | undefined>(avatarUrl);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncStatusMsg, setSyncStatusMsg] = useState<string | null>(null);

  React.useEffect(() => {
    setCurrentUrl(avatarUrl);
    setSyncStatusMsg(null);
  }, [avatarUrl, isOpen]);

  if (!isOpen) return null;

  const handleSyncAvatar = async () => {
    if (!contactId) return;
    setIsSyncing(true);
    setSyncStatusMsg(null);
    try {
      const res = await apiFetch(`/contacts/${contactId}/sync_avatar`, { method: 'POST' });
      if (res.status === 'success' && res.foto_perfil_url) {
        setCurrentUrl(res.foto_perfil_url);
        setSyncStatusMsg('✅ Foto de perfil importada com sucesso!');
        if (onAvatarUpdated) onAvatarUpdated(res.foto_perfil_url);
      } else {
        setSyncStatusMsg(res.message || '⚠️ Foto restrita pela privacidade do WhatsApp do cliente.');
      }
    } catch (err: any) {
      setSyncStatusMsg('❌ Erro ao buscar foto no WhatsApp.');
    } finally {
      setIsSyncing(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(8px)',
        zIndex: 99999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          backgroundColor: '#0f172a',
          border: '1px solid rgba(0, 230, 153, 0.3)',
          borderRadius: '16px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.9)',
          maxWidth: '90vw',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative'
        }}
      >
        {/* Header */}
        <div style={{
          padding: '14px 20px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'rgba(255, 255, 255, 0.03)',
          gap: '16px'
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '15px', fontWeight: '700', color: 'var(--text-main)' }}>
              {name}
            </h3>
            {phone && (
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                {phone}
              </span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {contactId && (
              <button
                onClick={handleSyncAvatar}
                disabled={isSyncing}
                style={{
                  background: 'rgba(0, 230, 153, 0.12)',
                  border: '1px solid rgba(0, 230, 153, 0.3)',
                  color: 'var(--accent-primary)',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: isSyncing ? 'not-allowed' : 'pointer'
                }}
                title="Importar foto oficial do perfil do WhatsApp"
              >
                <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
                {isSyncing ? 'Buscando...' : 'Buscar Foto'}
              </button>
            )}
            {currentUrl && (
              <a
                href={currentUrl}
                target="_blank"
                rel="noreferrer"
                style={{
                  color: 'var(--text-muted)',
                  padding: '6px',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'rgba(255,255,255,0.05)',
                  textDecoration: 'none'
                }}
                title="Abrir imagem original"
              >
                <ExternalLink size={16} />
              </a>
            )}
            <button
              onClick={onClose}
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: 'none',
                color: 'var(--text-muted)',
                padding: '6px',
                borderRadius: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Fechar"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Sync Status Banner */}
        {syncStatusMsg && (
          <div style={{
            padding: '8px 16px',
            backgroundColor: syncStatusMsg.startsWith('✅') ? 'rgba(34, 197, 94, 0.15)' : 'rgba(234, 179, 8, 0.15)',
            borderBottom: '1px solid rgba(255,255,255,0.05)',
            color: syncStatusMsg.startsWith('✅') ? '#4ade80' : '#facc15',
            fontSize: '12px',
            textAlign: 'center',
            fontWeight: '600'
          }}>
            {syncStatusMsg}
          </div>
        )}

        {/* Image Content */}
        <div style={{
          padding: '24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: '#050c14',
          minWidth: '280px',
          minHeight: '280px'
        }}>
          {currentUrl ? (
            <img
              src={currentUrl}
              alt={name}
              style={{
                maxWidth: '80vw',
                maxHeight: '70vh',
                objectFit: 'contain',
                borderRadius: '12px',
                boxShadow: '0 8px 30px rgba(0,0,0,0.5)'
              }}
            />
          ) : (
            <div style={{
              width: '180px',
              height: '180px',
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
              color: '#051a12',
              fontWeight: '700',
              fontSize: '64px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 10px 30px rgba(0, 230, 153, 0.3)'
            }}>
              {(name || '').replace(/[\[\]]/g, '').trim().charAt(0).toUpperCase() || 'C'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
