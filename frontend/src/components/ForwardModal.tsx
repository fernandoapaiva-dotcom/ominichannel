import React, { useState, useMemo } from 'react';
import { X, Search, Check, Send, Users, CornerUpRight, Image, FileText, Video, Music } from 'lucide-react';
import { Conversation, Message } from '../types';
import { apiFetch } from '../services/api';

interface ForwardModalProps {
  isOpen: boolean;
  onClose: () => void;
  messageToForward: Message | null;
  conversations: Conversation[];
  onForwardSuccess?: () => void;
}

export const ForwardModal: React.FC<ForwardModalProps> = ({
  isOpen,
  onClose,
  messageToForward,
  conversations,
  onForwardSuccess
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedConvIds, setSelectedConvIds] = useState<number[]>([]);
  const [isForwarding, setIsForwarding] = useState(false);

  // Filter conversations matching search
  const filteredConversations = useMemo(() => {
    if (!searchTerm.trim()) return conversations;
    const term = searchTerm.toLowerCase();
    return conversations.filter(c => {
      const name = (c.contact?.nome || '').toLowerCase();
      const phone = (c.contact?.telefone || '').toLowerCase();
      const dept = (c.whatsapp_number?.nome_departamento || '').toLowerCase();
      return name.includes(term) || phone.includes(term) || dept.includes(term);
    });
  }, [conversations, searchTerm]);

  const toggleSelect = (convId: number) => {
    setSelectedConvIds(prev =>
      prev.includes(convId) ? prev.filter(id => id !== convId) : [...prev, convId]
    );
  };

  const handleForward = async () => {
    if (!messageToForward || selectedConvIds.length === 0) return;

    try {
      setIsForwarding(true);

      for (const convId of selectedConvIds) {
        await apiFetch(`/conversations/${convId}/messages`, {
          method: 'POST',
          body: JSON.stringify({
            conteudo: messageToForward.conteudo,
            tipo: messageToForward.tipo || 'texto'
          })
        });
      }

      if (onForwardSuccess) onForwardSuccess();
      setSelectedConvIds([]);
      onClose();
      alert(`Mensagem encaminhada para ${selectedConvIds.length} conversa(s) com sucesso!`);
    } catch (err: any) {
      alert(`Erro ao encaminhar mensagem: ${err.message}`);
    } finally {
      setIsForwarding(false);
    }
  };

  if (!isOpen || !messageToForward) return null;

  const isMedia = ['imagem', 'video', 'audio', 'arquivo'].includes(messageToForward.tipo);
  const mediaRaw = messageToForward.conteudo || '';
  const mediaParts = mediaRaw.split('|');
  const mediaCaption = mediaParts.length > 1 ? mediaParts.slice(1).join('|') : null;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div className="glass-panel" style={{
        width: '100%',
        maxWidth: '520px',
        maxHeight: '85vh',
        backgroundColor: 'var(--bg-secondary)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5)',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '18px 22px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <CornerUpRight size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: 'var(--text-main)' }}>
                Encaminhar mensagem para...
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                Selecione as conversas ou grupos de destino
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              border: 'none',
              borderRadius: '50%',
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              cursor: 'pointer'
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Search Input */}
        <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--bg-primary)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-color)',
            padding: '0 12px'
          }}>
            <Search size={16} style={{ color: 'var(--text-muted)', marginRight: '8px' }} />
            <input
              type="text"
              placeholder="Pesquisar conversa, grupo ou cliente..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{
                flex: 1,
                padding: '10px 0',
                backgroundColor: 'transparent',
                border: 'none',
                color: 'var(--text-main)',
                fontSize: '13px',
                outline: 'none'
              }}
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px' }}
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Conversation List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}>
          {filteredConversations.length === 0 ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              Nenhuma conversa encontrada para "{searchTerm}"
            </div>
          ) : (
            filteredConversations.map(c => {
              const isSelected = selectedConvIds.includes(c.id);
              const isGroup = c.contact?.telefone?.startsWith('120363') || c.contact?.telefone?.includes('@g.us') || (c.contact?.telefone?.length || 0) > 15;
              const name = c.contact?.nome || (isGroup ? 'Grupo de WhatsApp' : 'Cliente');
              const avatar = c.contact?.foto_perfil_url;

              return (
                <div
                  key={c.id}
                  onClick={() => toggleSelect(c.id)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.12)' : 'transparent',
                    border: isSelected ? '1px solid var(--accent-primary)' : '1px solid transparent',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1, minWidth: 0 }}>
                    {avatar ? (
                      <img
                        src={avatar}
                        alt={name}
                        style={{
                          width: '42px',
                          height: '42px',
                          borderRadius: isGroup ? '12px' : '50%',
                          objectFit: 'cover',
                          border: '1px solid var(--border-color)',
                          flexShrink: 0
                        }}
                      />
                    ) : (
                      <div style={{
                        width: '42px',
                        height: '42px',
                        borderRadius: isGroup ? '12px' : '50%',
                        backgroundColor: isGroup ? '#0284c7' : '#00e699',
                        color: isGroup ? '#fff' : '#051a12',
                        fontWeight: '700',
                        fontSize: '16px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0
                      }}>
                        {isGroup ? <Users size={20} /> : name.charAt(0).toUpperCase()}
                      </div>
                    )}

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{
                          fontWeight: '600',
                          fontSize: '14px',
                          color: 'var(--text-main)',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>
                          {name}
                        </span>
                        {isGroup && (
                          <span style={{ fontSize: '10px', backgroundColor: 'rgba(2, 132, 199, 0.15)', color: '#38bdf8', padding: '1px 5px', borderRadius: '4px', fontWeight: '600' }}>
                            Grupo
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span>{c.whatsapp_number?.nome_departamento || 'Geral'}</span>
                        <span>•</span>
                        <span>{c.contact?.telefone || ''}</span>
                      </div>
                    </div>
                  </div>

                  <div style={{
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    border: isSelected ? 'none' : '2px solid var(--border-color)',
                    backgroundColor: isSelected ? 'var(--accent-primary)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#051a12',
                    flexShrink: 0
                  }}>
                    {isSelected && <Check size={14} strokeWidth={3} />}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Message Preview to Forward */}
        <div style={{
          padding: '12px 18px',
          backgroundColor: 'var(--bg-primary)',
          borderTop: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', textTransform: 'uppercase', marginBottom: '2px' }}>
              Mensagem a ser encaminhada:
            </div>
            {isMedia ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-main)' }}>
                {messageToForward.tipo === 'imagem' ? <Image size={16} /> : messageToForward.tipo === 'video' ? <Video size={16} /> : messageToForward.tipo === 'audio' ? <Music size={16} /> : <FileText size={16} />}
                <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {mediaCaption || `[Arquivo de ${messageToForward.tipo}]`}
                </span>
              </div>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {messageToForward.conteudo}
              </div>
            )}
          </div>

          <button
            onClick={handleForward}
            disabled={selectedConvIds.length === 0 || isForwarding}
            className="btn-primary"
            style={{
              padding: '10px 18px',
              fontSize: '13px',
              fontWeight: '700',
              opacity: selectedConvIds.length === 0 || isForwarding ? 0.5 : 1,
              cursor: selectedConvIds.length === 0 || isForwarding ? 'not-allowed' : 'pointer',
              whiteSpace: 'nowrap'
            }}
          >
            <Send size={15} />
            {isForwarding ? 'Encaminhando...' : `Encaminhar (${selectedConvIds.length})`}
          </button>
        </div>
      </div>
    </div>
  );
};
