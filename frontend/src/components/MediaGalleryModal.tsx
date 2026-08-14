import React, { useState, useEffect } from 'react';
import { X, Image, Mic, FileText, Download, ExternalLink, Paperclip } from 'lucide-react';
import { Conversation, Message } from '../types';
import { apiFetch } from '../services/api';

interface MediaGalleryModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: Conversation | null;
}

export const MediaGalleryModal: React.FC<MediaGalleryModalProps> = ({
  isOpen,
  onClose,
  conversation
}) => {
  const [filterType, setFilterType] = useState<'all' | 'imagem' | 'audio' | 'arquivo'>('all');
  const [mediaMessages, setMediaMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen && conversation) {
      fetchMedia();
    }
  }, [isOpen, conversation?.id]);

  const fetchMedia = async () => {
    if (!conversation) return;
    try {
      setLoading(true);
      const data = await apiFetch(`/conversations/${conversation.id}/media`);
      setMediaMessages(data);
    } catch (err) {
      console.error('Error fetching conversation media:', err);
      // Fallback: filter locally from loaded conversation messages
      const fallback = conversation.messages.filter(m => ['imagem', 'audio', 'arquivo'].includes(m.tipo));
      setMediaMessages(fallback);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen || !conversation) return null;

  const filtered = mediaMessages.filter(m => {
    if (filterType === 'all') return true;
    return m.tipo === filterType;
  });

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '650px',
        maxHeight: '85vh',
        borderRadius: 'var(--radius-lg)',
        padding: '24px',
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 20px 40px rgba(0, 0, 0, 0.4)'
      }}>
        {/* Modal Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              color: '#60a5fa',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Paperclip size={20} />
            </div>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-main)' }}>
                Arquivos da Conversa
              </h3>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                {conversation.contact?.nome || 'Cliente'} ({conversation.contact?.telefone})
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', color: 'var(--text-muted)', border: 'none', cursor: 'pointer' }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Filter Tabs */}
        <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px', marginBottom: '16px' }}>
          <button
            onClick={() => setFilterType('all')}
            className={filterType === 'all' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            Todas ({mediaMessages.length})
          </button>
          <button
            onClick={() => setFilterType('imagem')}
            className={filterType === 'imagem' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <Image size={14} /> Imagens ({mediaMessages.filter(m => m.tipo === 'imagem').length})
          </button>
          <button
            onClick={() => setFilterType('audio')}
            className={filterType === 'audio' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <Mic size={14} /> Áudios ({mediaMessages.filter(m => m.tipo === 'audio').length})
          </button>
          <button
            onClick={() => setFilterType('arquivo')}
            className={filterType === 'arquivo' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <FileText size={14} /> Documentos ({mediaMessages.filter(m => m.tipo === 'arquivo').length})
          </button>
        </div>

        {/* Content Stream */}
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', paddingRight: '4px' }}>
          {loading ? (
            <p style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>Carregando mídias...</p>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '40px 20px' }}>
              <Paperclip size={36} style={{ opacity: 0.3, marginBottom: '8px' }} />
              <p style={{ fontSize: '14px' }}>Nenhum arquivo ou mídia encontrado nesta conversa.</p>
            </div>
          ) : (
            filtered.map(msg => (
              <div
                key={msg.id}
                style={{
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  backgroundColor: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid var(--border-color)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1, minWidth: 0 }}>
                  {msg.tipo === 'imagem' ? (
                    <div style={{ padding: '8px', borderRadius: '6px', backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa' }}>
                      <Image size={20} />
                    </div>
                  ) : msg.tipo === 'audio' ? (
                    <div style={{ padding: '8px', borderRadius: '6px', backgroundColor: 'rgba(168, 85, 247, 0.2)', color: '#c084fc' }}>
                      <Mic size={20} />
                    </div>
                  ) : (
                    <div style={{ padding: '8px', borderRadius: '6px', backgroundColor: 'rgba(16, 185, 129, 0.2)', color: '#34d399' }}>
                      <FileText size={20} />
                    </div>
                  )}

                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {msg.conteudo || `Arquivo ${msg.tipo}`}
                    </p>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {msg.remetente === 'cliente' ? 'Enviado pelo Cliente' : 'Enviado pelo Atendente'} • {new Date(msg.timestamp).toLocaleString('pt-BR')}
                    </p>
                  </div>
                </div>

                {msg.conteudo && msg.conteudo.startsWith('http') && (
                  <a
                    href={msg.conteudo}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      padding: '6px 10px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--accent-primary)',
                      fontSize: '12px',
                      textDecoration: 'none'
                    }}
                  >
                    <ExternalLink size={13} /> Abrir
                  </a>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
