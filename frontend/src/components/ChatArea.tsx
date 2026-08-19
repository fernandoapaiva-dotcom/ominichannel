import React, { useState, useEffect, useRef } from 'react';
import {
  Send, UserCheck, Headphones, ArrowRightLeft, Bot, Phone, Building,
  AlertCircle, Paperclip, X, FileText, Image as ImageIcon, Video, Music, Download, UploadCloud, Eye, ArrowLeft,
  ChevronLeft, ChevronRight, ChevronDown, Clock, Check, Pencil, RefreshCw, Upload, MapPin,
  QrCode, Share2, Zap, Plus
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
  const [previewMediaIndex, setPreviewMediaIndex] = useState<number | null>(null);
  const [isUserScrolledUp, setIsUserScrolledUp] = useState(false);
  const [isVideoModalOpen, setIsVideoModalOpen] = useState(false);
  const [activeCallUrl, setActiveCallUrl] = useState<string | null>(null);
  const [showAttachmentMenu, setShowAttachmentMenu] = useState(false);

  // Edit Contact Name State
  const [isEditingContact, setIsEditingContact] = useState(false);
  const [editingContactName, setEditingContactName] = useState('');
  const [savingContact, setSavingContact] = useState(false);

  const handleSaveContactName = async () => {
    if (!conversation?.contact || !editingContactName.trim()) return;

    try {
      setSavingContact(true);
      await apiFetch(`/contacts/${conversation.contact.id}`, {
        method: 'PUT',
        body: JSON.stringify({ nome: editingContactName.trim() })
      });
      conversation.contact.nome = editingContactName.trim();
      setIsEditingContact(false);
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      alert(`Erro ao atualizar nome do contato: ${err.message}`);
    } finally {
      setSavingContact(false);
    }
  };

  const [isSyncingHistory, setIsSyncingHistory] = useState(false);

  const handleSyncHistory = async () => {
    if (!conversation) return;
    try {
      setIsSyncingHistory(true);
      const res = await apiFetch(`/conversations/${conversation.id}/sync-history`, {
        method: 'POST'
      });
      if (onStatusToggle) onStatusToggle();
      alert(res.message || 'Histórico sincronizado com sucesso!');
    } catch (err: any) {
      alert(`Erro ao sincronizar histórico: ${err.message}`);
    } finally {
      setIsSyncingHistory(false);
    }
  };

  const backupFileInputRef = useRef<HTMLInputElement>(null);
  const [isImportingBackup, setIsImportingBackup] = useState(false);

  const handleBackupFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !conversation) return;

    try {
      setIsImportingBackup(true);
      const res = await apiUpload(`/conversations/${conversation.id}/import-backup-file`, file);
      if (onStatusToggle) onStatusToggle();
      alert(res.message || 'Backup importado com sucesso!');
    } catch (err: any) {
      alert(`Erro ao importar backup: ${err.message}`);
    } finally {
      setIsImportingBackup(false);
      if (backupFileInputRef.current) backupFileInputRef.current.value = '';
    }
  };

  const handleStartVideoCall = async () => {
    if (!conversation) return;
    const roomName = `OminiChannel-Call-${conversation.id}-${Date.now().toString().slice(-6)}`;
    const callUrl = `https://meet.jit.si/${roomName}`;
    setActiveCallUrl(callUrl);
    setIsVideoModalOpen(true);

    try {
      const inviteMsg = `🎥 *CHAMADA DE VÍDEO / VOZ AO VIVO*\n\nOlá, *${conversation.contact?.nome || 'Cliente'}*!\n\nPor favor, clique no link abaixo para entrar na sala de chamada de vídeo com o nosso atendente:\n👉 ${callUrl}`;
      await onSendMessage(inviteMsg);
    } catch (err) {
      console.error('Error sending video call invitation link:', err);
    }
  };

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  // Extract all media items in conversation for universal gallery navigation (Images, Videos, Audios, Files)
  const conversationMedia = (conversation?.messages || [])
    .filter(m => ['imagem', 'video', 'audio', 'arquivo'].includes(m.tipo))
    .map(m => {
      const parts = (m.conteudo || '').split('|');
      const mediaPath = parts[0];
      const caption = parts.length > 1 ? parts.slice(1).join('|') : null;
      const fullUrl = mediaPath.startsWith('http') ? mediaPath : `http://localhost:8000${mediaPath}`;
      const fileName = mediaPath.split('/').pop() || 'Arquivo';
      return {
        id: m.id,
        tipo: m.tipo,
        url: fullUrl,
        fileName,
        caption,
        timestamp: m.timestamp,
        sender: m.remetente
      };
    });

  const handlePrevMedia = () => {
    if (previewMediaIndex === null || conversationMedia.length === 0) return;
    setPreviewMediaIndex(prev => (prev! > 0 ? prev! - 1 : conversationMedia.length - 1));
  };

  const handleNextMedia = () => {
    if (previewMediaIndex === null || conversationMedia.length === 0) return;
    setPreviewMediaIndex(prev => (prev! < conversationMedia.length - 1 ? prev! + 1 : 0));
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (previewMediaIndex === null) return;
      if (e.key === 'ArrowLeft') handlePrevMedia();
      if (e.key === 'ArrowRight') handleNextMedia();
      if (e.key === 'Escape') setPreviewMediaIndex(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewMediaIndex, conversationMedia.length]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleContainerScroll = () => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    // Mark as scrolled up if distance to bottom > 120px
    const isFar = scrollHeight - scrollTop - clientHeight > 120;
    setIsUserScrolledUp(isFar);
  };

  useEffect(() => {
    // Only auto-scroll if user is NOT manually reading past chat history!
    if (!isUserScrolledUp) {
      scrollToBottom();
    }
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
    if (!inputText.trim() && pendingFiles.length === 0) return;

    const textToSend = inputText.trim();
    setSendError(null);

    try {
      if (pendingFiles.length > 0) {
        setIsSending(true);
        for (let i = 0; i < pendingFiles.length; i++) {
          const file = pendingFiles[i];
          const formData = new FormData();
          formData.append('file', file);
          if (i === 0 && textToSend) {
            formData.append('caption', textToSend);
          }
          await apiUpload(`/conversations/${conversation?.id}/media`, formData);
        }
        setPendingFiles([]);
        setInputText('');
        setIsSending(false);
      } else if (textToSend) {
        // INSTANT UI CLEAR (0ms Delay)
        setInputText('');
        onSendMessage(textToSend);
      }
    } catch (err: any) {
      console.error('Send error:', err);
      setSendError(err.message || 'Falha ao enviar arquivo ou mensagem.');
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
        justifyContent: 'center',
        alignItems: 'center',
        color: 'var(--text-muted)'
      }}>
        <Bot size={48} style={{ opacity: 0.3, marginBottom: '16px' }} />
        <p style={{ fontSize: '15px' }}>Selecione uma conversa ao lado para iniciar o atendimento.</p>
      </div>
    );
  }

  const renderMediaContent = (msg: any) => {
    const raw = msg.conteudo || '';
    const parts = raw.split('|');
    const mediaPath = parts[0];
    const caption = parts.length > 1 ? parts.slice(1).join('|') : null;
    const fullUrl = mediaPath.startsWith('http') ? mediaPath : `http://localhost:8000${mediaPath}`;
    const mediaIndex = conversationMedia.findIndex(item => item.id === msg.id);

    switch (msg.tipo) {
      case 'imagem':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ position: 'relative', cursor: 'pointer', borderRadius: '8px', overflow: 'hidden', maxWidth: '320px', border: '1px solid rgba(255,255,255,0.1)' }} onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}>
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
            <div style={{ position: 'relative', cursor: 'pointer', borderRadius: '8px', overflow: 'hidden', maxWidth: '320px' }} onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}>
              <video src={fullUrl} controls style={{ width: '100%', maxWidth: '320px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }} />
            </div>
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
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '10px 14px',
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
                borderRadius: '8px',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                maxWidth: '300px',
                cursor: 'pointer'
              }}
              onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}
            >
              <FileText size={28} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {fileName}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Clique para ver detalhes
                </div>
              </div>
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'localizacao':
        const safeRawLoc = typeof raw === 'string' ? raw : String(raw || '');
        const mapsLinkMatch = safeRawLoc.match(/(https?:\/\/[^\s]+maps[^\s]+)/i);
        const mapsUrl = mapsLinkMatch ? mapsLinkMatch[0] : null;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px', backgroundColor: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '10px', maxWidth: '320px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#34d399', fontWeight: '700', fontSize: '13px' }}>
              <MapPin size={18} /> Localização GPS (WhatsApp Map)
            </div>
            <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'var(--text-main)', margin: 0, whiteSpace: 'pre-wrap' }}>
              {safeRawLoc}
            </p>
            {mapsUrl && (
              <a
                href={mapsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary"
                style={{ fontSize: '12px', padding: '6px 12px', textDecoration: 'none', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '4px' }}
              >
                <MapPin size={14} /> Abrir no Google Maps / GPS
              </a>
            )}
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

  const currentMedia = previewMediaIndex !== null ? conversationMedia[previewMediaIndex] : null;

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

      {previewMediaIndex !== null && currentMedia && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.93)',
          zIndex: 1000,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '0 20px',
            color: '#fff'
          }}>
            <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ textTransform: 'capitalize', color: 'var(--accent-primary)', fontWeight: 'bold' }}>
                {currentMedia.tipo}
              </span>
              <span>•</span>
              <span>Mídia {previewMediaIndex + 1} de {conversationMedia.length}</span>
            </div>
            <button
              onClick={() => setPreviewMediaIndex(null)}
              style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: '8px' }}
            >
              <X size={28} />
            </button>
          </div>

          <div style={{
            flex: 1,
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'relative',
            padding: '10px 0'
          }}>
            {conversationMedia.length > 1 ? (
              <button
                onClick={handlePrevMedia}
                title="Mídia anterior (Seta para a esquerda)"
                style={{
                  background: 'rgba(255, 255, 255, 0.12)',
                  border: 'none',
                  color: '#fff',
                  borderRadius: '50%',
                  width: '48px',
                  height: '48px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  margin: '0 16px',
                  transition: 'background 0.2s'
                }}
              >
                <ChevronLeft size={32} />
              </button>
            ) : <div style={{ width: '48px' }} />}

            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', maxHeight: '80vh', maxWidth: '85vw' }}>
              {currentMedia.tipo === 'imagem' && (
                <img
                  src={currentMedia.url}
                  alt="Imagem"
                  style={{ maxHeight: '72vh', maxWidth: '85vw', objectFit: 'contain', borderRadius: '8px', boxShadow: '0 8px 30px rgba(0,0,0,0.8)' }}
                />
              )}
              {currentMedia.tipo === 'video' && (
                <video
                  src={currentMedia.url}
                  controls
                  autoPlay
                  style={{ maxHeight: '72vh', maxWidth: '85vw', borderRadius: '8px', boxShadow: '0 8px 30px rgba(0,0,0,0.8)' }}
                />
              )}
              {currentMedia.tipo === 'audio' && (
                <div style={{
                  padding: '32px 40px',
                  backgroundColor: 'var(--bg-secondary)',
                  borderRadius: '16px',
                  border: '1px solid var(--border-color)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '20px',
                  boxShadow: '0 8px 30px rgba(0,0,0,0.8)'
                }}>
                  <Music size={56} style={{ color: 'var(--accent-primary)' }} />
                  <div style={{ fontSize: '15px', fontWeight: '600', color: '#fff' }}>Áudio de {currentMedia.sender === 'cliente' ? 'Cliente' : 'Atendente'}</div>
                  <audio src={currentMedia.url} controls autoPlay style={{ width: '320px', outline: 'none' }} />
                </div>
              )}
              {currentMedia.tipo === 'arquivo' && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', width: '100%' }}>
                  {currentMedia.fileName.toLowerCase().endsWith('.pdf') || currentMedia.url.toLowerCase().includes('.pdf') ? (
                    <iframe
                      src={currentMedia.url}
                      title="Visualizador de PDF"
                      style={{
                        width: '78vw',
                        height: '62vh',
                        borderRadius: '12px',
                        border: '1px solid var(--border-color)',
                        backgroundColor: '#fff',
                        boxShadow: '0 8px 30px rgba(0,0,0,0.8)'
                      }}
                    />
                  ) : (
                    <div style={{
                      padding: '32px 40px',
                      backgroundColor: 'var(--bg-secondary)',
                      borderRadius: '16px',
                      border: '1px solid var(--border-color)',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '16px',
                      boxShadow: '0 8px 30px rgba(0,0,0,0.8)',
                      maxWidth: '450px',
                      textAlign: 'center'
                    }}>
                      <FileText size={64} style={{ color: 'var(--accent-primary)' }} />
                      <div style={{ fontSize: '16px', fontWeight: '600', color: '#fff', wordBreak: 'break-word' }}>
                        {currentMedia.fileName}
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <a
                      href={currentMedia.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-primary"
                      style={{ textDecoration: 'none', padding: '10px 20px', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}
                    >
                      <Eye size={18} /> Visualizar no Navegador
                    </a>
                    <a
                      href={currentMedia.url}
                      download
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-secondary"
                      style={{ textDecoration: 'none', padding: '10px 20px', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}
                    >
                      <Download size={18} /> Baixar Arquivo
                    </a>
                  </div>
                </div>
              )}
              {currentMedia.caption && (
                <p style={{
                  marginTop: '16px',
                  color: '#fff',
                  fontSize: '14px',
                  textAlign: 'center',
                  backgroundColor: 'rgba(0,0,0,0.6)',
                  padding: '8px 16px',
                  borderRadius: '8px',
                  maxWidth: '600px'
                }}>
                  {currentMedia.caption}
                </p>
              )}
            </div>

            {conversationMedia.length > 1 ? (
              <button
                onClick={handleNextMedia}
                title="Próxima mídia (Seta para a direita)"
                style={{
                  background: 'rgba(255, 255, 255, 0.12)',
                  border: 'none',
                  color: '#fff',
                  borderRadius: '50%',
                  width: '48px',
                  height: '48px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  margin: '0 16px',
                  transition: 'background 0.2s'
                }}
              >
                <ChevronRight size={32} />
              </button>
            ) : <div style={{ width: '48px' }} />}
          </div>

          {conversationMedia.length > 1 && (
            <div style={{
              display: 'flex',
              gap: '10px',
              overflowX: 'auto',
              padding: '10px 20px',
              maxWidth: '90vw',
              backgroundColor: 'rgba(0,0,0,0.5)',
              borderRadius: '12px'
            }}>
              {conversationMedia.map((item, idx) => (
                <div
                  key={item.id}
                  onClick={() => setPreviewMediaIndex(idx)}
                  style={{
                    width: '56px',
                    height: '56px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    opacity: idx === previewMediaIndex ? 1 : 0.4,
                    border: idx === previewMediaIndex ? '2px solid var(--accent-primary)' : '2px solid transparent',
                    transition: 'all 0.2s ease',
                    overflow: 'hidden',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff'
                  }}
                >
                  {item.tipo === 'imagem' ? (
                    <img src={item.url} alt="Thumb" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : item.tipo === 'video' ? (
                    <Video size={24} style={{ color: '#60a5fa' }} />
                  ) : item.tipo === 'audio' ? (
                    <Music size={24} style={{ color: '#c084fc' }} />
                  ) : (
                    <FileText size={24} style={{ color: 'var(--accent-primary)' }} />
                  )}
                </div>
              ))}
            </div>
          )}
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
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {isEditingContact ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <input
                    type="text"
                    value={editingContactName}
                    onChange={(e) => setEditingContactName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSaveContactName();
                      if (e.key === 'Escape') setIsEditingContact(false);
                    }}
                    autoFocus
                    style={{
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-active)',
                      color: 'var(--text-main)',
                      fontSize: '14px'
                    }}
                  />
                  <button
                    onClick={handleSaveContactName}
                    disabled={savingContact}
                    className="btn-primary"
                    style={{ padding: '4px 10px', fontSize: '12px' }}
                  >
                    Salvar
                  </button>
                  <button
                    onClick={() => setIsEditingContact(false)}
                    className="btn-secondary"
                    style={{ padding: '4px 8px', fontSize: '12px' }}
                  >
                    <X size={14} />
                  </button>
                </div>
              ) : (
                <>
                  <h3 style={{ fontSize: '16px', fontWeight: '600', color: 'var(--text-main)' }}>{conversation.contact?.nome || 'Cliente'}</h3>
                  <button
                    onClick={() => {
                      setEditingContactName(conversation.contact?.nome || '');
                      setIsEditingContact(true);
                    }}
                    title="Editar Nome do Cliente"
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      padding: '2px',
                      display: 'inline-flex',
                      alignItems: 'center'
                    }}
                  >
                    <Pencil size={14} />
                  </button>
                </>
              )}
            </div>
            <div style={{ display: 'flex', gap: '16px', fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Phone size={13} /> {conversation.contact?.telefone}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Building size={13} /> {conversation.whatsapp_number?.nome_departamento || 'Geral'}</span>
              {conversation.assigned_user_name && (
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#60a5fa', fontWeight: '600' }}>
                  <UserCheck size={13} /> Atendente: {conversation.assigned_user_name}
                </span>
              )}
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

          <button
            onClick={handleStartVideoCall}
            className="btn-secondary"
            style={{
              fontSize: '13px',
              padding: '8px 14px',
              backgroundColor: 'rgba(0, 230, 153, 0.12)',
              color: 'var(--accent-primary)',
              border: '1px solid var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
            title="Iniciar chamada de vídeo / voz WebRTC e enviar link para o cliente"
          >
            <Video size={15} /> Chamada Vídeo/Voz
          </button>

          {onOpenMediaGallery && (
            <button onClick={onOpenMediaGallery} className="btn-secondary" style={{ fontSize: '13px', padding: '8px 14px' }}>
              <Paperclip size={15} /> Arquivos ({conversationMedia.length})
            </button>
          )}

          <input
            type="file"
            ref={backupFileInputRef}
            onChange={handleBackupFileSelected}
            accept=".txt,.zip"
            style={{ display: 'none' }}
          />

          <button
            onClick={() => backupFileInputRef.current?.click()}
            disabled={isImportingBackup}
            className="btn-secondary"
            style={{ fontSize: '13px', padding: '8px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
            title="Importar arquivo de conversa exportado do WhatsApp (.txt ou .zip)"
          >
            <Upload size={15} style={{ animation: isImportingBackup ? 'spin 1s linear infinite' : 'none' }} />
            {isImportingBackup ? 'Importando...' : 'Importar Backup'}
          </button>


          <button
            onClick={handleSyncHistory}
            disabled={isSyncingHistory}
            className="btn-secondary"
            style={{ fontSize: '13px', padding: '8px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
            title="Sincronizar mensagens anteriores do WhatsApp"
          >
            <RefreshCw size={15} style={{ animation: isSyncingHistory ? 'spin 1s linear infinite' : 'none' }} />
            {isSyncingHistory ? 'Sincronizando...' : 'Histórico WA'}
          </button>

          <button onClick={onOpenTransferModal} className="btn-secondary" style={{ fontSize: '13px', padding: '8px 14px' }}>
            <ArrowRightLeft size={15} /> Transferir
          </button>
        </div>
      </div>

      {conversation.resumo_ia && (
        <div style={{
          padding: '12px 20px',
          backgroundColor: 'rgba(234, 179, 8, 0.12)',
          borderBottom: '1px solid rgba(234, 179, 8, 0.3)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          color: '#facc15'
        }}>
          <Bot size={22} style={{ color: '#facc15', flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '12px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '2px' }}>
              📌 Resumo da Transferência da IA:
            </div>
            <div style={{ fontSize: '13px', color: '#ffffff', lineHeight: '1.4' }}>
              {conversation.resumo_ia}
            </div>
          </div>
        </div>
      )}

      <div
        ref={scrollContainerRef}
        onScroll={handleContainerScroll}
        style={{
          flex: 1,
          padding: '20px 24px',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          position: 'relative'
        }}
      >
        {(conversation?.messages || []).map((msg, idx) => {
          const isCustomer = msg.remetente === 'cliente';
          const isAI = msg.remetente === 'ia';
          const isSystem = msg.remetente === 'sistema';
          const msgKey = msg.id ? `msg_${msg.id}_${idx}` : `msg_${idx}`;

          if (isSystem) {
            return (
              <div key={msgKey} className="animate-fade-in" style={{
                alignSelf: 'center',
                margin: '8px 0',
                padding: '6px 14px',
                borderRadius: 'var(--radius-full)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.25)',
                color: '#60a5fa',
                fontSize: '12px',
                fontWeight: '500',
                textAlign: 'center',
                maxWidth: '85%'
              }}>
                {renderMediaContent(msg)}
              </div>
            );
          }

          const bubbleBg = isCustomer ? '#1c283e' : isAI ? 'rgba(168, 85, 247, 0.12)' : 'rgba(0, 230, 153, 0.15)';
          const border = isCustomer ? '1px solid var(--border-color)' : isAI ? '1px solid rgba(168, 85, 247, 0.3)' : '1px solid rgba(0, 230, 153, 0.3)';

          return (
            <div key={msgKey} className="animate-fade-in" style={{
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
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {formatTime(msg.timestamp)}
                  {!isCustomer && (
                    msg.status === 'sending' ? (
                      <Clock size={12} style={{ color: 'var(--text-muted)' }} title="Enviando..." />
                    ) : msg.status === 'failed' ? (
                      <AlertCircle size={12} style={{ color: '#ef4444' }} title="Falha no envio" />
                    ) : (
                      <Check size={12} style={{ color: 'var(--accent-primary)' }} title="Enviado" />
                    )
                  )}
                </span>
              </div>
              {renderMediaContent(msg)}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
        {isUserScrolledUp && (
          <button
            onClick={() => { scrollToBottom(); setIsUserScrolledUp(false); }}
            style={{
              position: 'sticky',
              bottom: '16px',
              alignSelf: 'center',
              zIndex: 20,
              backgroundColor: 'var(--bg-primary)',
              color: 'var(--accent-primary)',
              border: '1px solid var(--accent-primary)',
              borderRadius: 'var(--radius-full)',
              padding: '8px 16px',
              fontSize: '12px',
              fontWeight: '600',
              boxShadow: '0 4px 16px rgba(0,0,0,0.6)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <ChevronDown size={16} /> Ir para o fim da conversa
          </button>
        )}
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

      {/* WhatsApp-Style Attachment & Quick Actions Popover Menu */}
      {showAttachmentMenu && (
        <div
          className="animate-fade-in"
          style={{
            position: 'absolute',
            bottom: '80px',
            left: '24px',
            zIndex: 100,
            backgroundColor: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 'var(--radius-lg)',
            padding: '16px',
            boxShadow: '0 12px 32px rgba(0, 0, 0, 0.6)',
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '14px',
            width: '340px'
          }}
        >
          {/* 1. Galeria / Mídia */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              fileInputRef.current?.click();
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(59, 130, 246, 0.1)',
              border: '1px solid rgba(59, 130, 246, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#3b82f6', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <ImageIcon size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Galeria / Mídia</span>
          </div>

          {/* 2. Documento */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              fileInputRef.current?.click();
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(168, 85, 247, 0.1)',
              border: '1px solid rgba(168, 85, 247, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#a855f7', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FileText size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Documento</span>
          </div>

          {/* 3. Localização */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              setInputText(prev => (prev ? prev + '\n' : '') + '📍 *Localização da Loja Servweld / Servsolda:* SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226\nhttps://maps.google.com/?q=-15.820418,-47.956467');
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(0, 230, 153, 0.1)',
              border: '1px solid rgba(0, 230, 153, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#00e699', color: '#0b0f19', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <MapPin size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Localização</span>
          </div>

          {/* 4. Dados Pix */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              setInputText(prev => (prev ? prev + '\n' : '') + '💸 *Dados para Pagamento via Pix:* Servweld / Servsolda\nChave CNPJ / E-mail: (Solicite os dados ao especialista)');
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(234, 179, 8, 0.1)',
              border: '1px solid rgba(234, 179, 8, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#eab308', color: '#0b0f19', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <QrCode size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Dados Pix</span>
          </div>

          {/* 5. Contato */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              if (conversation?.contact) {
                setInputText(prev => (prev ? prev + '\n' : '') + `👤 *Cartão de Contato:* ${conversation.contact.nome || 'Cliente'} (Telefone: ${conversation.contact.telefone})`);
              }
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(14, 165, 233, 0.1)',
              border: '1px solid rgba(14, 165, 233, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#0ea5e9', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Share2 size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Contato</span>
          </div>

          {/* 6. Horário Loja */}
          <div
            onClick={() => {
              setShowAttachmentMenu(false);
              setInputText(prev => (prev ? prev + '\n' : '') + '⏰ *Horário de Atendimento Servweld:* Segunda a Sexta-feira das 08h00 às 18h00.');
            }}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '8px',
              padding: '12px 8px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(236, 72, 153, 0.1)',
              border: '1px solid rgba(236, 72, 153, 0.25)',
              cursor: 'pointer'
            }}
          >
            <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#ec4899', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Zap size={20} />
            </div>
            <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Horário Loja</span>
          </div>
        </div>
      )}

      <input type="file" ref={fileInputRef} onChange={handleFileSelect} multiple style={{ display: 'none' }} />

      <form onSubmit={handleSend} style={{ padding: '16px 24px', borderTop: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', display: 'flex', gap: '12px', alignItems: 'center' }}>
        <button type="button" onClick={() => setShowAttachmentMenu(!showAttachmentMenu)} className="btn-secondary" disabled={conversation.status === 'expirada_por_inatividade'} style={{ padding: '10px 12px' }} title="Menu de Anexos e Ações Rápidas"><Paperclip size={18} /></button>
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

      {/* WebRTC Live Video / Audio Call Modal */}
      {isVideoModalOpen && activeCallUrl && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.9)',
          zIndex: 2000,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <div style={{
            width: '92vw',
            height: '88vh',
            backgroundColor: 'var(--bg-secondary)',
            borderRadius: '16px',
            border: '1px solid var(--accent-primary)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            boxShadow: '0 8px 32px rgba(0, 230, 153, 0.25)'
          }}>
            <div style={{
              padding: '12px 20px',
              backgroundColor: 'var(--bg-primary)',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontWeight: '600', color: 'var(--accent-primary)' }}>
                <Video size={20} />
                <span>Chamada de Vídeo/Voz ao Vivo com {conversation.contact?.nome || 'Cliente'}</span>
              </div>
              <button
                onClick={() => setIsVideoModalOpen(false)}
                className="btn-secondary"
                style={{ padding: '6px 12px', fontSize: '13px' }}
              >
                <X size={18} /> Encerrar Chamada
              </button>
            </div>
            <iframe
              src={activeCallUrl}
              allow="camera; microphone; display-capture; autoplay"
              title="Chamada de Vídeo ao Vivo"
              style={{ width: '100%', flex: 1, border: 'none', backgroundColor: '#000' }}
            />
          </div>
        </div>
      )}
    </div>
  );
};
