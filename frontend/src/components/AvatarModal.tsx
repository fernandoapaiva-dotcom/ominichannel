import React from 'react';
import { X, ExternalLink } from 'lucide-react';

interface AvatarModalProps {
  isOpen: boolean;
  onClose: () => void;
  name: string;
  phone?: string;
  avatarUrl?: string | null;
}

export const AvatarModal: React.FC<AvatarModalProps> = ({
  isOpen,
  onClose,
  name,
  phone,
  avatarUrl
}) => {
  if (!isOpen) return null;

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
            {avatarUrl && (
              <a
                href={avatarUrl}
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
          {avatarUrl ? (
            <img
              src={avatarUrl}
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
              {(name || 'U').charAt(0).toUpperCase()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
