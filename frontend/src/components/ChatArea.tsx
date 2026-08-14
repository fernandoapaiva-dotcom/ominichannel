import React, { useState, useEffect, useRef } from 'react';
import {
  Send, UserCheck, Headphones, ArrowRightLeft, Bot, Phone, Building,
  AlertCircle, Paperclip, X, FileText, Image as ImageIcon, Video, Music, Download, UploadCloud, Eye, ArrowLeft
} from 'lucide-react';
import { apiFetch, apiUpload } from '../services/api';
import { Conversation, User } from '../types';

interface ChatAreaProps {
  conversation: Conversation | null;
  currentUser: User;
  onSendMessage: (text: string) => Promise<void>;
  onOpenTransferModal: () => void;
  onOpenMediaGallery?: () => void;
  onStatusToggle?: () => void;
  onBack?: () => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  conversation,
  currentUser,
  onSendMessage,
  onOpenTransferModal,
  onOpenMediaGallery,
  onStatusToggle,
  onBack
}) => {
  const [inputText, setInputText] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isTogglingStatus, setIsTogglingStatus] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [previewMediaUrl, setPreviewMediaUrl] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
    setSendError(null);
  }, [conversation?.messages]);

  const handleToggleStatus = async () => {
    if (!conversation || isTogglingStatus) return;
    const nextStatus = conversation.status === 'com_ia' ? 'com_humano' : 'com_ia';
    try {
      setIsTogglingStatus(true);
      await apiFetch(`/conversations/${conversation.id}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: nextStatus })
      });
      if (onStatusToggle) onStatusToggle();
    } catch (err) {
      console.error('Failed to toggle conversation status:', err);
    } finally {
      setIsTogglingStatus(false);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = Array.from(e.target.files);
      setPendingFiles(prev => [...prev, ...selected]);
    }
  };

  const removePendingFile = (index: number) => {
    setPendingFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files);
      setPendingFiles(prev => [...prev, ...droppedFiles]);
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if ((!inputText.trim() && pendingFiles.length === 0) || isSending) return;

    setIsSending(true);
    setSendError(null);

    try {
      if (pendingFiles.length > 0) {
        for (let i = 0; i < pendingFiles.length; i++) {
          const file = pendingFiles[i];
          const formData = new FormData();
          formData.append('file', file);
          if (i === 0 && inputText.trim()) {
            formData.append('caption', inputText.trim());
          }
          await apiUpload(`/conversations/${conversation?.id}/media`, formData);
        }
        setPendingFiles([]);
        setInputText('');
      } else if (inputText.trim()) {
        await onSendMessage(inputText.trim());
        setInputText('');
      }
    } catch (err: any) {
      console.error('Send error:', err);
      setSendError(err.message || 'Falha ao enviar arquivo ou mensagem.');
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

  const mediaCount = conversation.messages.filter(m => ['imagem', 'audio', 'video', 'arquivo'].includes(m.tipo)).length;

  const renderMediaContent = (msg: any) => {
    const raw = msg.conteudo || '';
    const parts = raw.split('|');
    const mediaPath = parts[0];
    const caption = parts.length > 1 ? parts.slice(1).join('|') : null;
    const fullUrl = mediaPath.startsWith('http') ? mediaPath : `http://localhost:8000${mediaPath}`;

    switch (msg.tipo) {
      case 'imagem':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ position: 'relative', cursor: 'pointer', borderRadius: '8px', overflow: 'hidden', maxWidth: '320px', border: '1px solid rgba(255,255,255,0.1)' }} onClick={() => setPreviewMediaUrl(fullUrl)}>
              <img src={fullUrl} alt="Imagem" style={{ width: '100%', maxHeight: '300px', objectFit: 'cover', display: 'block' }} />
              <div style={{ position: 'absolute', bottom: '8px', right: '8px', background: 'rgba(0,0,0,0.6)', padding: '4px 8px', borderRadius: '4px', color: '#fff', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Eye size={12} /> Ampliar
              </div>
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'video':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <video src={fullUrl} controls style={{ width: '100%', maxWidth: '320px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }} />
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'audio':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <audio src={fullUrl} controls style={{ width: '260px', height: '40px', outline: 'none' }} />
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'arquivo':
        const fileName = mediaPath.split('/').pop() || 'Arquivo';
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '10px 14px',
              backgroundColor: 'rgba(255, 255, 255, 0.06)',
              borderRadius: '8px',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              maxWidth: '300px'
            }}>
              <FileText size={28} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {fileName}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Documento / Anexo
                </div>
              </div>
              <a href={fullUrl} download target="_blank" rel="noopener noreferrer" style={{
                color: 'var(--accent-primary)',
                padding: '6px',
                borderRadius: '6px',
                backgroundColor: 'rgba(0, 230, 153, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }} title="Baixar Arquivo">
                <Download size={16} />
              </a>
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      default:
        return (
          <p style={{ fontSize: '14px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>
            {raw}
          </p>
        );
    }
  };

const formatTime = (ts: string | Date | undefined) => {
  if (!ts) return '';
  let str = String(ts).trim();
  if (str.includes(' ') && !str.includes('T')) {
    str = str.replace(' ', 'T');
  }
  if (!str.endsWith('Z') && !str.includes('+') && !str.includes('-')) {
    str = str + 'Z';
  }
  const d = new Date(str);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        flex: 1,
        height: '100%',
        backgroundColor: 'var(--bg-secondary)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative'
      }}
    >
      {isDraggingOver && (
        <div style={{
          position: 'absolute',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(5, 26, 18, 0.9)',
          border: '3px dashed var(--accent-primary)',
          zIndex: 100,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '16px',
          color: 'var(--accent-primary)'
        }}>
          <UploadCloud size={64} className="animate-bounce" />
          <h3 style={{ fontSize: '20px', fontWeight: '700' }}>Solte seus arquivos aqui para anexar</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Imagens, vídeos, áudios e documentos</p>
        </div>
      )}

      {previewMediaUrl && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.85)',
          zIndex: 200,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '40px'
        }} onClick={() => setPreviewMediaUrl(null)}>
          <img src={previewMediaUrl} alt="Visualização" style={{ maxWidth: '90vw', maxHeight: '90vh', borderRadius: '8px', objectFit: 'contain' }} />
          <button onClick={() => setPreviewMediaUrl(null)} style={{
            position: 'absolute', top: '20px', right: '20px',
            background: 'none', border: 'none', color: '#fff', cursor: 'pointer'
          }}>
            <X size={32} />
          </button>
        </div>
      )}

      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {onBack && (
            <button
              onClick={onBack}
              title="Voltar para a lista de conversas"
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--accent-primary)',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <ArrowLeft size={22} />
            </button>
          )}
          <div>
            <h3 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-main)' }}>{conversation.contact?.nome || 'Cliente'}</h3>
            <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Phone size={13} /> {conversation.contact?.telefone}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Building size={13} /> {conversation.whatsapp_number?.nome_departamento || 'Geral'}</span>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <button
            onClick={handleToggleStatus}
            disabled={isTogglingStatus}
            style={{
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              borderRadius: 'var(--radius-full)',
              fontSize: '12px',
              fontWeight: '600',
              border: '1px solid var(--border-color)',
              backgroundColor: conversation.status === 'com_ia' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(59, 130, 246, 0.2)',
              color: conversation.status === 'com_ia' ? '#c084fc' : '#60a5fa'
            }}
          >
            {conversation.status === 'com_ia' ? <><Bot size={14} /> COM IA</> : <><Headphones size={14} /> COM HUMANO</>}
          </button>

          {onOpenMediaGallery && (
            <button onClick={onOpenMediaGallery} className="btn-secondary" style={{ fontSize: '13px', padding: '8px 14px' }}>
              <Paperclip size={15} /> Arquivos ({mediaCount})
            </button>
          )}

          <button onClick={onOpenTransferModal} className="btn-secondary" style={{ fontSize: '13px', padding: '8px 14px' }}>
            <ArrowRightLeft size={15} /> Transferir
          </button>
        </div>
      </div>

      <div style={{ flex: 1, padding: '20px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {conversation.messages.map((msg) => {
          const isCustomer = msg.remetente === 'cliente';
          const isAI = msg.remetente === 'ia';
          const bubbleBg = isCustomer ? '#1c283e' : isAI ? 'rgba(168, 85, 247, 0.12)' : 'rgba(0, 230, 153, 0.15)';
          const border = isCustomer ? '1px solid var(--border-color)' : isAI ? '1px solid rgba(168, 85, 247, 0.3)' : '1px solid rgba(0, 230, 153, 0.3)';

          return (
            <div key={msg.id} className="animate-fade-in" style={{
              alignSelf: isCustomer ? 'flex-start' : 'flex-end',
              maxWidth: '65%',
              padding: '12px 16px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: bubbleBg,
              border,
              display: 'flex',
              flexDirection: 'column',
              gap: '6px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', fontSize: '11px', color: 'var(--text-muted)' }}>
                <span style={{ fontWeight: '600', color: isAI ? '#c084fc' : isCustomer ? '#94a3b8' : 'var(--accent-primary)' }}>
                  {isCustomer ? (conversation.contact?.nome || 'Cliente') : isAI ? '🤖 IA Concierge' : '👤 Atendente'}
                </span>
                <span>{formatTime(msg.timestamp)}</span>
              </div>
              {renderMediaContent(msg)}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {sendError && (
        <div style={{ padding: '10px 16px', backgroundColor: 'rgba(239, 68, 68, 0.15)', borderTop: '1px solid rgba(239, 68, 68, 0.3)', color: '#f87171', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertCircle size={16} /> {sendError}
        </div>
      )}

      {pendingFiles.length > 0 && (
        <div style={{ padding: '10px 16px', backgroundColor: 'rgba(0, 230, 153, 0.05)', borderTop: '1px solid rgba(0, 230, 153, 0.2)', display: 'flex', gap: '10px', overflowX: 'auto', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--accent-primary)', whiteSpace: 'nowrap' }}>Anexos ({pendingFiles.length}):</span>
          {pendingFiles.map((file, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', fontSize: '12px' }}>
              {file.type.startsWith('image/') ? <img src={URL.createObjectURL(file)} alt="Preview" style={{ width: '24px', height: '24px', objectFit: 'cover', borderRadius: '4px' }} /> : <FileText size={16} />}
              <span style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.name}</span>
              <button type="button" onClick={() => removePendingFile(idx)} style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}><X size={14} /></button>
            </div>
          ))}
        </div>
      )}

      <input type="file" ref={fileInputRef} onChange={handleFileSelect} multiple style={{ display: 'none' }} />

      <form onSubmit={handleSend} style={{ padding: '16px 24px', borderTop: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', display: 'flex', gap: '12px', alignItems: 'center' }}>
        <button type="button" onClick={() => fileInputRef.current?.click()} className="btn-secondary" disabled={conversation.status === 'expirada_por_inatividade'} style={{ padding: '10px 12px' }}><Paperclip size={18} /></button>
        <input
          type="text"
          placeholder={conversation.status === 'expirada_por_inatividade' ? 'Conversa expirada...' : 'Digite sua mensagem...'}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={conversation.status === 'expirada_por_inatividade'}
          style={{ flex: 1, padding: '12px 16px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
        />
        <button type="submit" className="btn-primary" disabled={(!inputText.trim() && pendingFiles.length === 0) || isSending || conversation.status === 'expirada_por_inatividade'}>
          <Send size={16} /> {isSending ? 'Enviando...' : 'Enviar'}
        </button>
      </form>
    </div>
  );
};
