import React from 'react';
import { X, Check, CheckCheck, Users, Clock, Info } from 'lucide-react';
import { Message, Conversation } from '../types';

interface MessageInfoModalProps {
  isOpen: boolean;
  onClose: () => void;
  message: Message | null;
  conversation: Conversation | null;
}

export const MessageInfoModal: React.FC<MessageInfoModalProps> = ({
  isOpen,
  onClose,
  message,
  conversation
}) => {
  if (!isOpen || !message) return null;

  const isGroup = Boolean(
    conversation?.contact?.telefone?.startsWith('120363') ||
    (conversation?.contact?.telefone && conversation.contact.telefone.length > 15) ||
    conversation?.contact?.nome?.includes('Servweld/Servsolda')
  );

  const extra = message.dados_adicionais || {};
  const readBy = (extra.read_by || []) as Array<{ phone: string; name: string; avatar?: string; time?: string }>;
  const deliveredTo = (extra.delivered_to || []) as Array<{ phone: string; name: string; avatar?: string; time?: string }>;

  const formatMsgTime = (timestamp: string) => {
    try {
      const d = new Date(timestamp);
      return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }) + ' às ' +
        d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } catch {
      return timestamp;
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
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
        maxWidth: '480px',
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
          padding: '16px 20px',
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
              backgroundColor: 'rgba(83, 189, 235, 0.15)',
              color: '#53bdeb',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Info size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: 'var(--text-main)' }}>
                Dados da mensagem
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                {isGroup ? 'Confirmação de leitura do grupo' : 'Status de entrega e leitura'}
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

        {/* Message Snippet Card */}
        <div style={{
          padding: '14px 20px',
          backgroundColor: 'var(--bg-primary)',
          borderBottom: '1px solid var(--border-color)'
        }}>
          <div style={{
            padding: '10px 14px',
            backgroundColor: 'var(--bubble-outgoing)',
            color: 'var(--bubble-outgoing-text)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--bubble-outgoing-border)',
            fontSize: '13px',
            lineHeight: '1.4'
          }}>
            {message.conteudo}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
            <Clock size={13} />
            <span>Enviada em {formatMsgTime(message.timestamp)}</span>
          </div>
        </div>

        {/* Read & Delivered Status Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Lida por / Lida */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '700', color: '#53bdeb', marginBottom: '8px' }}>
              <CheckCheck size={18} />
              <span>Lida por {isGroup && `(${readBy.length})`}</span>
            </div>

            {isGroup ? (
              readBy.length === 0 ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '10px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
                  Nenhum participante abriu ainda
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {readBy.map((p, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {p.avatar ? (
                          <img src={p.avatar} alt={p.name} style={{ width: '32px', height: '32px', borderRadius: '50%', objectFit: 'cover' }} />
                        ) : (
                          <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: '#0284c7', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '12px' }}>
                            {p.name.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>{p.name}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.phone}</div>
                        </div>
                      </div>
                      <div style={{ fontSize: '11px', color: '#53bdeb', fontWeight: '600' }}>{p.time || 'Lida'}</div>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <div style={{ padding: '10px 14px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>
                  {conversation?.contact?.nome || 'Cliente'}
                </div>
                <div style={{ fontSize: '12px', color: message.status === 'read' ? '#53bdeb' : 'var(--text-muted)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {message.status === 'read' ? (
                    <>
                      <CheckCheck size={16} /> Lida pelo cliente
                    </>
                  ) : (
                    'Não lida ainda'
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Entregue para */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: '700', color: 'var(--text-muted)', marginBottom: '8px' }}>
              <CheckCheck size={18} />
              <span>Entregue {isGroup ? `para (${deliveredTo.length})` : ''}</span>
            </div>

            {isGroup ? (
              deliveredTo.length === 0 ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '10px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-sm)' }}>
                  Entregue no servidor do WhatsApp
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {deliveredTo.map((p, idx) => (
                    <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 12px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {p.avatar ? (
                          <img src={p.avatar} alt={p.name} style={{ width: '32px', height: '32px', borderRadius: '50%', objectFit: 'cover' }} />
                        ) : (
                          <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'var(--border-color)', color: 'var(--text-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '12px' }}>
                            {p.name.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>{p.name}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.phone}</div>
                        </div>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.time || 'Entregue'}</div>
                    </div>
                  ))}
                </div>
              )
            ) : (
              <div style={{ padding: '10px 14px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>
                  {conversation?.contact?.nome || 'Cliente'}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <CheckCheck size={16} /> Entregue no aparelho
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
