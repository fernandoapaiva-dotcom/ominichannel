import React, { useState, useEffect, useRef } from 'react';
import { Send, UserCheck, ArrowRightLeft, Bot, Phone, Building, AlertCircle } from 'lucide-react';
import { Conversation, User } from '../types';

interface ChatAreaProps {
  conversation: Conversation | null;
  currentUser: User;
  onSendMessage: (text: string) => Promise<void>;
  onOpenTransferModal: () => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  conversation,
  currentUser,
  onSendMessage,
  onOpenTransferModal
}) => {
  const [inputText, setInputText] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
    setSendError(null);
  }, [conversation?.messages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || isSending) return;

    setSendError(null);
    try {
      setIsSending(true);
      await onSendMessage(inputText);
      setInputText('');
    } catch (err: any) {
      console.error(err);
      setSendError(err.message || 'Falha ao entregar mensagem via Evolution API.');
    } finally {
      setIsSending(false);
    }
  };

  if (!conversation) {
    return (
      <div style={{
        flex: 1,
        height: '100%',
        backgroundColor: 'var(--bg-secondary)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-muted)'
      }}>
        <Bot size={48} style={{ opacity: 0.3, marginBottom: '16px' }} />
        <p style={{ fontSize: '15px' }}>Selecione uma conversa ao lado para iniciar o atendimento.</p>
      </div>
    );
  }

  return (
    <div style={{
      flex: 1,
      height: '100%',
      backgroundColor: 'var(--bg-secondary)',
      display: 'flex',
      flexDirection: 'column'
    }}>
      {/* Top Bar Header */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <h3 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-main)' }}>
            {conversation.contact?.nome || 'Cliente'}
          </h3>
          <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Phone size={13} /> {conversation.contact?.telefone}
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Building size={13} /> {conversation.whatsapp_number?.nome_departamento || 'Geral'}
            </span>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <span className={`badge badge-${conversation.status}`}>
            {conversation.status.replace('_', ' ')}
          </span>

          <button
            onClick={onOpenTransferModal}
            className="btn-secondary"
            title="Transferir conversa"
            style={{ fontSize: '13px', padding: '8px 14px' }}
          >
            <ArrowRightLeft size={15} /> Transferir
          </button>
        </div>
      </div>

      {/* Messages Stream Container */}
      <div style={{
        flex: 1,
        padding: '20px 24px',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px'
      }}>
        {conversation.messages.map((msg) => {
          const isCustomer = msg.remetente === 'cliente';
          const isAI = msg.remetente === 'ia';

          let bubbleBg = 'rgba(255, 255, 255, 0.05)';
          let alignSelf: 'flex-start' | 'flex-end' = 'flex-start';
          let border = '1px solid var(--border-color)';

          if (isCustomer) {
            alignSelf = 'flex-start';
            bubbleBg = '#1c283e';
          } else if (isAI) {
            alignSelf = 'flex-end';
            bubbleBg = 'rgba(168, 85, 247, 0.12)';
            border = '1px solid rgba(168, 85, 247, 0.3)';
          } else {
            // Human Agent
            alignSelf = 'flex-end';
            bubbleBg = 'rgba(0, 230, 153, 0.15)';
            border = '1px solid rgba(0, 230, 153, 0.3)';
          }

          return (
            <div
              key={msg.id}
              className="animate-fade-in"
              style={{
                alignSelf,
                maxWidth: '65%',
                padding: '12px 16px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: bubbleBg,
                border,
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', fontSize: '11px', color: 'var(--text-muted)' }}>
                <span style={{ fontWeight: '600', color: isAI ? '#c084fc' : isCustomer ? '#94a3b8' : 'var(--accent-primary)' }}>
                  {isCustomer ? (conversation.contact?.nome || 'Cliente') : isAI ? '🤖 IA Concierge' : '👤 Atendente'}
                </span>
                <span>
                  {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>

              <p style={{ fontSize: '14px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>
                {msg.conteudo}
              </p>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Delivery Error Alert Banner */}
      {sendError && (
        <div style={{
          padding: '10px 16px',
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          borderTop: '1px solid rgba(239, 68, 68, 0.3)',
          color: '#f87171',
          fontSize: '13px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          <AlertCircle size={16} /> {sendError}
        </div>
      )}

      {/* Input Message Form */}
      <form
        onSubmit={handleSend}
        style={{
          padding: '16px 24px',
          borderTop: '1px solid var(--border-color)',
          backgroundColor: 'var(--bg-primary)',
          display: 'flex',
          gap: '12px',
          alignItems: 'center'
        }}
      >
        <input
          type="text"
          placeholder={
            conversation.status === 'expirada_por_inatividade'
              ? 'Conversa expirada por inatividade...'
              : 'Digite sua mensagem para o cliente...'
          }
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={conversation.status === 'expirada_por_inatividade'}
          style={{
            flex: 1,
            padding: '12px 16px',
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--text-main)',
            fontSize: '14px',
            outline: 'none'
          }}
        />

        <button
          type="submit"
          className="btn-primary"
          disabled={!inputText.trim() || isSending || conversation.status === 'expirada_por_inatividade'}
          style={{
            opacity: (!inputText.trim() || isSending) ? 0.5 : 1
          }}
        >
          <Send size={16} /> Enviar
        </button>
      </form>
    </div>
  );
};
