import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Send, UserCheck, Headphones, ArrowRightLeft, Bot, Phone, Building,
  AlertCircle, Paperclip, X, FileText, Image as ImageIcon, Video, Music, Download, UploadCloud, Eye, ArrowLeft,
  ChevronLeft, ChevronRight, ChevronDown, Clock, Check, CheckCheck, Pencil, RefreshCw, Upload, MapPin,
  QrCode, Share2, Zap, Plus, PanelLeftOpen, PanelLeftClose, CornerUpRight, Reply, Smile, Copy, MoreHorizontal, CornerDownRight, Info, Star,
  Lock, Unlock, Pin
} from 'lucide-react';
import { apiFetch, apiUpload } from '../services/api';
import { LocationPickerModal } from './LocationPickerModal';
import { ContactPickerModal } from './ContactPickerModal';
import { PixModal } from './PixModal';
import { AvatarModal } from './AvatarModal';
import { ForwardModal } from './ForwardModal';
import { MessageInfoModal } from './MessageInfoModal';
import { EmojiGifStickerPicker } from './EmojiGifStickerPicker';
import { Conversation, User, Message } from '../types';

interface ChatAreaProps {
  conversation: Conversation | null;
  allConversations?: Conversation[];
  onSelectConversation?: (conv: Conversation) => void;
  currentUser: User;
  onSendMessage: (text: string, tipo?: string) => Promise<void>;
  onOpenTransferModal: () => void;
  onOpenMediaGallery?: () => void;
  onStatusToggle?: () => void;
  onBack?: () => void;
  isChatListCollapsed?: boolean;
  onToggleChatList?: () => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  conversation,
  allConversations,
  onSelectConversation,
  currentUser,
  onSendMessage,
  onOpenTransferModal,
  onOpenMediaGallery,
  onStatusToggle,
  onBack,
  isChatListCollapsed = false,
  onToggleChatList
}) => {
  const [showThreadDropdown, setShowThreadDropdown] = useState(false);
  const [showMoreMenu, setShowMoreMenu] = useState(false);

  // WhatsApp-style Message Actions, Multi-Select & Forwarding State
  const [activeActionMenuMsgId, setActiveActionMenuMsgId] = useState<number | null>(null);
  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [selectedMessagesForForward, setSelectedMessagesForForward] = useState<Message[]>([]);
  const [showForwardModal, setShowForwardModal] = useState(false);
  const [selectedMessageForInfo, setSelectedMessageForInfo] = useState<Message | null>(null);
  const [replyingToMessage, setReplyingToMessage] = useState<Message | null>(null);
  const [messageReactions, setMessageReactions] = useState<{ [msgId: number]: string }>({});

  const handleStartForwardSelection = (msg: Message) => {
    setIsSelectionMode(true);
    setSelectedMessagesForForward([msg]);
    setActiveActionMenuMsgId(null);
  };

  const toggleMessageSelection = (msg: Message) => {
    setSelectedMessagesForForward(prev => {
      const exists = prev.some(m => (m.id && m.id === msg.id) || m === msg);
      if (exists) {
        const next = prev.filter(m => (m.id && m.id !== msg.id) || (!m.id && m !== msg));
        if (next.length === 0) {
          setIsSelectionMode(false);
        }
        return next;
      } else {
        return [...prev, msg];
      }
    });
  };

  // WhatsApp Full Emoji, GIF & Sticker Picker State
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [reactingMsgForPicker, setReactingMsgForPicker] = useState<number | null>(null);

  // WhatsApp Floating Sticky Date Timeline State (shows when scrolling, fades when stopped)
  const [floatingDate, setFloatingDate] = useState<string>('Hoje');
  const [isFloatingDateVisible, setIsFloatingDateVisible] = useState<boolean>(false);
  const scrollDateTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const contactConversations = useMemo(() => {
    if (!conversation || !allConversations) return [];
    const cid = conversation.contact_id || conversation.contact?.id;
    return allConversations.filter(c => (c.contact_id || c.contact?.id) === cid);
  }, [conversation, allConversations]);
  const [inputText, setInputText] = useState('');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isTogglingStatus, setIsTogglingStatus] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [previewMediaIndex, setPreviewMediaIndex] = useState<number | null>(null);
  const [isUserScrolledUp, setIsUserScrolledUp] = useState(false);
  const [isVideoModalOpen, setIsVideoModalOpen] = useState(false);
  const [activeTabMedia, setActiveTabMedia] = useState<'all' | 'imagem' | 'video' | 'audio' | 'arquivo'>('all');
  const [dismissedSummaries, setDismissedSummaries] = useState<number[]>([]);
  const [showAttachmentMenu, setShowAttachmentMenu] = useState(false);
  const [showLocationModal, setShowLocationModal] = useState(false);
  const [showContactModal, setShowContactModal] = useState(false);
  const [showPixModal, setShowPixModal] = useState(false);
  const [showAvatarZoom, setShowAvatarZoom] = useState(false);
  const [isConsultingIA, setIsConsultingIA] = useState(false);
  const [isAssumingControl, setIsAssumingControl] = useState(false);

  const isAdmin = currentUser.role === 'admin' || (currentUser.role as any)?.value === 'admin';
  const isAssignedToOther = Boolean(
    conversation &&
    conversation.status === 'com_humano' &&
    conversation.assigned_user_id &&
    conversation.assigned_user_id !== currentUser.id &&
    !isAdmin
  );
  const assignedAttendantName = conversation?.assigned_user_name || (conversation?.assigned_user ? conversation.assigned_user.nome : (conversation?.assigned_user_id ? `Atendente #${conversation.assigned_user_id}` : 'outro atendente'));

  const handleAssumeControl = async () => {
    if (!conversation) return;
    try {
      setIsAssumingControl(true);
      const updated = await apiFetch(`/conversations/${conversation.id}/assume`, {
        method: 'POST'
      });
      if (updated) {
        conversation.status = 'com_humano';
        conversation.assigned_user_id = currentUser.id;
        conversation.assigned_user_name = currentUser.nome;
        if (onStatusToggle) onStatusToggle();
      }
    } catch (err: any) {
      alert(err.message || 'Erro ao assumir controle do atendimento');
    } finally {
      setIsAssumingControl(false);
    }
  };

  const handleConsultarIA = async () => {
    if (!conversation?.id || isConsultingIA) return;
    setIsConsultingIA(true);
    try {
      const res = await apiFetch(`/conversations/${conversation.id}/suggest-reply`, {
        method: 'POST'
      });
      if (res && res.suggested_reply) {
        setInputText(res.suggested_reply);
      }
    } catch (err: any) {
      console.error('Erro ao consultar IA:', err);
      alert(`Erro ao consultar IA: ${err.message || 'Falha na resposta'}`);
    } finally {
      setIsConsultingIA(false);
    }
  };

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

    // Calculate current visible date at top of viewport
    const containerTop = scrollContainerRef.current.getBoundingClientRect().top;
    const messageElements = scrollContainerRef.current.querySelectorAll('[data-msg-time]');
    let currentDate = 'Hoje';

    for (let i = 0; i < messageElements.length; i++) {
      const el = messageElements[i] as HTMLElement;
      const rect = el.getBoundingClientRect();
      const msgTimestamp = el.getAttribute('data-msg-time');
      if (rect.top <= containerTop + 100 && msgTimestamp) {
        currentDate = formatDateDivider(msgTimestamp);
      }
    }

    setFloatingDate(currentDate);
    setIsFloatingDateVisible(true);

    if (scrollDateTimeoutRef.current) {
      clearTimeout(scrollDateTimeoutRef.current);
    }
    scrollDateTimeoutRef.current = setTimeout(() => {
      setIsFloatingDateVisible(false);
    }, 1500);
  };

  useEffect(() => {
    setIsUserScrolledUp(false);
    scrollToBottom();
  }, [conversation?.id]);

  useEffect(() => {
    if (!isUserScrolledUp) {
      scrollToBottom();
    }
    setSendError(null);
  }, [conversation?.messages]);

  const [isOperatingProtocol, setIsOperatingProtocol] = useState(false);

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

  const handleOpenProtocol = async () => {
    if (!conversation || isOperatingProtocol) return;
    try {
      setIsOperatingProtocol(true);
      const res = await apiFetch(`/conversations/${conversation.id}/open_protocol`, {
        method: 'POST'
      });
      if (res && res.protocol_number) {
        (conversation as any).protocol_number = res.protocol_number;
        conversation.status = 'com_humano';
      }
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      console.error('Failed to open protocol:', err);
      alert('Erro ao abrir protocolo: ' + (err.message || err));
    } finally {
      setIsOperatingProtocol(false);
    }
  };

  const handleCloseProtocol = async () => {
    if (!conversation || isOperatingProtocol) return;
    const currentProto = (conversation as any).protocol_number || '';
    const confirmClose = window.confirm(`Deseja realmente finalizar o Protocolo #${currentProto}?\n\nA conversa continuará aberta normalmente para você enviar mensagens quando quiser.`);
    if (!confirmClose) return;

    try {
      setIsOperatingProtocol(true);
      await apiFetch(`/conversations/${conversation.id}/close_protocol`, {
        method: 'POST'
      });
      (conversation as any).protocol_number = undefined;
      (conversation as any).resumo_ia = undefined;
      setDismissedSummaries(prev => [...prev, conversation.id]);
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      console.error('Failed to close protocol:', err);
      alert('Erro ao fechar protocolo: ' + (err.message || err));
    } finally {
      setIsOperatingProtocol(false);
    }
  };

  const [isMarkingRead, setIsMarkingRead] = useState(false);

  const handleMarkAsRead = async () => {
    if (!conversation || isMarkingRead) return;
    try {
      setIsMarkingRead(true);
      await apiFetch(`/conversations/${conversation.id}/mark_read`, { method: 'POST' });
      const extra = (conversation as any).dados_adicionais || {};
      extra.marked_as_read = true;
      extra.pending_dismissed = true;
      (conversation as any).dados_adicionais = extra;
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      console.error('Error marking conversation as read:', err);
    } finally {
      setIsMarkingRead(false);
    }
  };

  const [isTogglingPin, setIsTogglingPin] = useState(false);

  const handleTogglePin = async () => {
    if (!conversation || isTogglingPin) return;
    const currentPinned = Boolean((conversation as any).dados_adicionais?.is_pinned);
    const nextPinned = !currentPinned;
    try {
      setIsTogglingPin(true);
      const extra = (conversation as any).dados_adicionais || {};
      extra.is_pinned = nextPinned;
      if (nextPinned) {
        extra.pinned_at = new Date().toISOString();
      } else {
        delete extra.pinned_at;
      }
      (conversation as any).dados_adicionais = extra;

      await apiFetch(`/conversations/${conversation.id}/toggle-pin`, { method: 'POST' });
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      console.error('Error toggling pin in ChatArea:', err);
    } finally {
      setIsTogglingPin(false);
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

    // Validation for unfulfilled placeholder brackets [...]
    const placeholderMatch = inputText.match(/\[(.*?)\]/);
    if (placeholderMatch) {
      alert(`⚠️ Você esqueceu de preencher um campo na mensagem:\n"${placeholderMatch[0]}"\n\nPor favor, substitua ou remova os colchetes antes de enviar ao cliente.`);
      return;
    }

    let textToSend = inputText.trim();
    if (replyingToMessage) {
      const quoteSender = replyingToMessage.remetente === 'cliente' ? (conversation?.contact?.nome || 'Cliente') : 'Atendente';
      let quoteSnippet = (replyingToMessage.conteudo || '').split('|')[0];
      if (quoteSnippet.length > 50) quoteSnippet = quoteSnippet.slice(0, 50) + '...';
      textToSend = `> *${quoteSender}:* ${quoteSnippet}\n\n` + textToSend;
      setReplyingToMessage(null);
    }

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
        const textCopy = textToSend;
        setInputText('');
        
        // Immediate 0ms synchronous optimistic append
        if (conversation) {
          const tempMsg: Message = {
            id: -Date.now(),
            conversation_id: conversation.id,
            remetente: 'atendente',
            conteudo: textCopy,
            tipo: 'texto' as any,
            timestamp: new Date().toISOString(),
            status: 'sending'
          };
          if (!conversation.messages) {
            conversation.messages = [];
          }
          conversation.messages.push(tempMsg);
          scrollToBottom();
        }

        onSendMessage(textCopy);
      }
    } catch (err: any) {
      console.error('Send error:', err);
      setSendError(err.message || 'Falha ao enviar arquivo ou mensagem.');
      setIsSending(false);
    }
  };

  const normalizeIsoDate = (ts: string | Date | undefined): Date => {
    if (!ts) return new Date();
    if (ts instanceof Date) return isNaN(ts.getTime()) ? new Date() : ts;
    let str = String(ts).trim();
    if (str.includes(' ') && !str.includes('T')) {
      str = str.replace(' ', 'T');
    }
    if (!str.endsWith('Z') && !/[+-]\d{2}(:\d{2})?$/.test(str)) {
      str = str + 'Z';
    }
    const d = new Date(str);
    return isNaN(d.getTime()) ? new Date() : d;
  };

  const formatDateDivider = (timestampStr: string): string => {
    try {
      const msgDate = normalizeIsoDate(timestampStr);
      const today = new Date();
      const yesterday = new Date();
      yesterday.setDate(today.getDate() - 1);

      const isToday = msgDate.toDateString() === today.toDateString();
      const isYesterday = msgDate.toDateString() === yesterday.toDateString();

      if (isToday) return 'Hoje';
      if (isYesterday) return 'Ontem';

      const diffTime = today.getTime() - msgDate.getTime();
      const diffDays = Math.floor(diffTime / (1000 * 3600 * 24));
      
      if (diffDays < 7 && diffDays >= 2) {
        const weekdays = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
        return weekdays[msgDate.getDay()];
      }

      return msgDate.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
    } catch {
      return 'Hoje';
    }
  };

  const getMessageDateKey = (timestampStr: string): string => {
    try {
      const d = normalizeIsoDate(timestampStr);
      return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
    } catch {
      return '';
    }
  };

  const handleCopyMessage = (msg: Message) => {
    let text = msg.conteudo || '';
    if (text.includes('|')) text = text.split('|')[1] || text;
    navigator.clipboard.writeText(text);
    setActiveActionMenuMsgId(null);
  };

  const handleDownloadMedia = (msg: Message) => {
    let path = (msg.conteudo || '').split('|')[0];
    const url = path.startsWith('http') ? path : `http://localhost:8000${path}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = path.split('/').pop() || 'arquivo';
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setActiveActionMenuMsgId(null);
  };

  const handleSaveSticker = (stickerUrl: string) => {
    try {
      const existing: string[] = JSON.parse(localStorage.getItem('saved_stickers_bank') || '[]');
      if (!existing.includes(stickerUrl)) {
        existing.unshift(stickerUrl);
        localStorage.setItem('saved_stickers_bank', JSON.stringify(existing));
        window.dispatchEvent(new Event('saved_stickers_updated'));
        alert('⭐ Figurinha adicionada ao seu Banco de Figurinhas com sucesso!');
      } else {
        alert('Esta figurinha já está salva no seu Banco de Figurinhas!');
      }
    } catch (e) {
      console.error('Error saving sticker:', e);
    }
  };

  const handleReact = async (msgId: number, emoji: string) => {
    const newEmoji = messageReactions[msgId] === emoji ? '' : emoji;
    setMessageReactions(prev => ({
      ...prev,
      [msgId]: newEmoji
    }));
    setActiveActionMenuMsgId(null);

    if (conversation?.id && msgId > 0) {
      try {
        await apiFetch(`/conversations/${conversation.id}/messages/${msgId}/reaction`, {
          method: 'POST',
          body: JSON.stringify({ reaction: newEmoji })
        });
      } catch (err) {
        console.error('Error dispatching reaction to WhatsApp:', err);
      }
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
    let raw = msg.conteudo || '';
    let mediaPath = '';
    let caption: string | null = null;

    if (raw.includes('|')) {
      const parts = raw.split('|');
      mediaPath = parts[0].trim();
      caption = parts.slice(1).join('|').trim();
    } else if (raw.startsWith('[') && raw.includes(']')) {
      const match = raw.match(/^\[(.*?)\]\s*([\s\S]*)$/);
      if (match) {
        mediaPath = match[1].trim();
        caption = match[2].trim() || null;
      } else {
        mediaPath = raw.trim();
      }
    } else {
      mediaPath = raw.trim();
    }

    mediaPath = mediaPath.replace(/^\[/, '').replace(/\]$/, '');
    const fullUrl = mediaPath.startsWith('http') ? mediaPath : `http://localhost:8000${mediaPath}`;
    const mediaIndex = conversationMedia.findIndex(item => item.id === msg.id);

    switch (msg.tipo) {
      case 'imagem':
      case 'sticker':
      case 'figurinha':
        const isSticker = fullUrl.toLowerCase().endsWith('.webp') || fullUrl.toLowerCase().includes('sticker') || msg.tipo === 'sticker' || msg.tipo === 'figurinha';
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div
              style={{
                position: 'relative',
                cursor: isSticker ? 'default' : 'pointer',
                borderRadius: isSticker ? '0' : '8px',
                overflow: 'hidden',
                maxWidth: isSticker ? '170px' : '320px',
                border: isSticker ? 'none' : '1px solid rgba(255,255,255,0.1)',
                backgroundColor: 'transparent'
              }}
              onClick={() => {
                if (!isSticker) {
                  setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0);
                }
              }}
            >
              <img
                src={fullUrl}
                alt={isSticker ? "Figurinha do WhatsApp" : "Imagem"}
                style={{
                  width: isSticker ? '150px' : '100%',
                  maxHeight: isSticker ? '150px' : '300px',
                  objectFit: isSticker ? 'contain' : 'cover',
                  display: 'block'
                }}
              />
              {isSticker ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSaveSticker(fullUrl);
                  }}
                  title="⭐ Salvar no Banco de Figurinhas"
                  style={{
                    position: 'absolute',
                    top: '4px',
                    right: '4px',
                    background: 'rgba(0, 0, 0, 0.75)',
                    border: '1px solid rgba(255, 255, 255, 0.25)',
                    borderRadius: '50%',
                    width: '28px',
                    height: '28px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#f59e0b',
                    cursor: 'pointer',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
                    transition: 'transform 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.15)')}
                  onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  <Star size={14} fill="#f59e0b" />
                </button>
              ) : (
                <div style={{ position: 'absolute', bottom: '8px', right: '8px', background: 'rgba(0,0,0,0.6)', padding: '4px 8px', borderRadius: '4px', color: '#fff', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Eye size={12} /> Ampliar
                </div>
              )}
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'video':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ position: 'relative', cursor: 'pointer', borderRadius: '8px', overflow: 'hidden', maxWidth: '320px' }} onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}>
              <video src={fullUrl} controls style={{ width: '100%', maxWidth: '320px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)' }} />
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'audio':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxWidth: '300px' }}>
            <audio controls style={{ width: '100%', height: '40px', outline: 'none' }}>
              <source src={fullUrl} type="audio/ogg" />
              <source src={fullUrl} type="audio/mpeg" />
              <source src={fullUrl} />
              Seu navegador não suporta reprodução de áudio.
            </audio>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>{caption}</p>}
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
                backgroundColor: 'rgba(0, 0, 0, 0.05)',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                maxWidth: '300px',
                cursor: 'pointer'
              }}
              onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}
            >
              <FileText size={28} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
              <div style={{ flex: 1, overflow: 'hidden' }}>
                <div style={{ fontSize: '13px', fontWeight: '600', color: 'inherit', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {fileName}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Clique para ver detalhes
                </div>
              </div>
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>{caption}</p>}
          </div>
        );

      case 'localizacao':
        const safeRawLoc = typeof raw === 'string' ? raw : String(raw || '');
        const mapsLinkMatch = safeRawLoc.match(/(https?:\/\/[^\s]+maps[^\s]+)/i);
        const mapsUrl = mapsLinkMatch ? mapsLinkMatch[0] : null;
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px', backgroundColor: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', borderRadius: '10px', maxWidth: '320px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#10b981', fontWeight: '700', fontSize: '13px' }}>
              <MapPin size={18} /> Localização GPS (WhatsApp Map)
            </div>
            <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', margin: 0, whiteSpace: 'pre-wrap' }}>
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
          <p style={{ fontSize: '14px', lineHeight: '1.4', color: 'inherit', whiteSpace: 'pre-wrap' }}>
            {raw}
          </p>
        );
    }
  };

  const formatTime = (ts: string | Date | undefined) => {
    if (!ts) return '';
    const d = normalizeIsoDate(ts);
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
        minWidth: 0,
        maxWidth: '100%',
        width: '100%',
        height: '100%',
        backgroundColor: 'var(--bg-secondary)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'hidden',
        boxSizing: 'border-box'
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
        padding: '0 16px',
        height: '64px',
        width: '100%',
        boxSizing: 'border-box',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '12px',
        position: 'relative',
        zIndex: 100,
        overflow: 'visible',
        whiteSpace: 'nowrap',
        flexShrink: 0
      }}>
        {/* Left Section: Avatar & Customer Metadata */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
          {onToggleChatList && isChatListCollapsed && (
            <button
              onClick={onToggleChatList}
              className="btn-secondary"
              style={{
                height: '34px',
                padding: '0 10px',
                fontSize: '11px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px'
              }}
              title="Expandir/Mostrar lista de conversas"
            >
              <PanelLeftOpen size={15} /> Ver Conversas
            </button>
          )}

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
              <ArrowLeft size={20} />
            </button>
          )}

          {/* WhatsApp Profile Avatar in Header with Click-to-Zoom */}
          {conversation.contact?.foto_perfil_url ? (
            <img
              src={conversation.contact.foto_perfil_url}
              alt={conversation.contact.nome || 'Cliente'}
              onClick={() => setShowAvatarZoom(true)}
              title="Clique para expandir a foto de perfil"
              style={{ width: '40px', height: '40px', borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--accent-primary)', flexShrink: 0, cursor: 'pointer', transition: 'transform 0.15s ease' }}
              onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
              onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
            />
          ) : (
            <div
              onClick={() => setShowAvatarZoom(true)}
              title="Clique para expandir a foto de perfil"
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
                color: '#051a12',
                fontWeight: '700',
                fontSize: '17px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                boxShadow: '0 2px 8px rgba(0, 230, 153, 0.3)',
                cursor: 'pointer'
              }}
            >
              {(conversation.contact?.nome || conversation.contact?.telefone || 'U').charAt(0).toUpperCase()}
            </div>
          )}

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
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
                      padding: '3px 8px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-active)',
                      color: 'var(--text-main)',
                      fontSize: '13px'
                    }}
                  />
                  <button
                    onClick={handleSaveContactName}
                    disabled={savingContact}
                    className="btn-primary"
                    style={{ padding: '3px 8px', fontSize: '11px' }}
                  >
                    Salvar
                  </button>
                  <button
                    onClick={() => setIsEditingContact(false)}
                    className="btn-secondary"
                    style={{ padding: '3px 6px', fontSize: '11px' }}
                  >
                    <X size={13} />
                  </button>
                </div>
              ) : (
                <>
                  <h3 style={{ fontSize: '15px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                    {conversation.contact?.nome || 'Cliente'}
                  </h3>
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
                    <Pencil size={13} />
                  </button>
                </>
              )}
            </div>

            <div style={{ display: 'flex', gap: '12px', fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', alignItems: 'center' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}><Phone size={11} /> {conversation.contact?.telefone}</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}><Building size={11} /> {conversation.whatsapp_number?.nome_departamento || 'Geral'}</span>
              {conversation.assigned_user_name && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', color: '#60a5fa', fontWeight: '600' }}>
                  <UserCheck size={11} /> Atendente: {conversation.assigned_user_name}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Right Section: Action Buttons Toolbar (Responsive, sleek 32px height without overflow clipping) */}
        <div style={{
          display: 'flex',
          gap: '5px',
          alignItems: 'center',
          flexShrink: 1,
          minWidth: 0,
          overflowX: 'auto',
          scrollbarWidth: 'none',
          padding: '2px 0',
          justifyContent: 'flex-end'
        }}>
          {/* Thread Switcher Dropdown */}
          {contactConversations.length > 1 && onSelectConversation && (
            <div style={{ position: 'relative', flexShrink: 0 }}>
              <button
                type="button"
                onClick={() => setShowThreadDropdown(!showThreadDropdown)}
                style={{
                  height: '32px',
                  padding: '0 8px',
                  background: 'rgba(0, 230, 153, 0.12)',
                  border: '1px solid var(--accent-primary)',
                  color: 'var(--accent-primary)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '11px',
                  fontWeight: '700',
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  whiteSpace: 'nowrap'
                }}
                title="Alternar entre chamados deste cliente"
              >
                <span>📁 #{conversation.id} ({conversation.status.replace('_', ' ')})</span>
                <ChevronDown size={12} />
              </button>

              {showThreadDropdown && (
                <>
                  <div
                    onClick={() => setShowThreadDropdown(false)}
                    style={{
                      position: 'fixed',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      zIndex: 999
                    }}
                  />
                  <div style={{
                    position: 'absolute',
                    top: 'calc(100% + 6px)',
                    right: 0,
                    backgroundColor: '#0f172a',
                    border: '1px solid rgba(0, 230, 153, 0.3)',
                    borderRadius: 'var(--radius-md)',
                    boxShadow: '0 16px 36px rgba(0,0,0,0.85)',
                    zIndex: 1000,
                    minWidth: '260px',
                    overflow: 'hidden'
                  }}>
                    <div style={{ padding: '8px 12px', fontSize: '10px', fontWeight: '700', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)', textTransform: 'uppercase' }}>
                      Conversas do Cliente ({contactConversations.length}):
                    </div>
                    {contactConversations.map(c => {
                      const isCurrent = c.id === conversation.id;
                      return (
                        <div
                          key={c.id}
                          onClick={() => {
                            onSelectConversation(c);
                            setShowThreadDropdown(false);
                          }}
                          style={{
                            padding: '8px 12px',
                            backgroundColor: isCurrent ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
                            borderBottom: '1px solid rgba(255,255,255,0.05)',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center'
                          }}
                        >
                          <div>
                            <div style={{ fontSize: '11px', fontWeight: '600', color: isCurrent ? 'var(--accent-primary)' : 'var(--text-main)' }}>
                              Chamado #{c.id} • {c.whatsapp_number?.nome_departamento || 'Geral'}
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                              {formatTime(c.ultima_interacao_em)}
                            </div>
                          </div>
                          <span className={`badge badge-${c.status}`} style={{ fontSize: '9px', padding: '2px 6px' }}>
                            {c.status.replace('_', ' ')}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Protocol Management Button (Abrir / Fechar Protocolo) */}
          {(conversation as any).protocol_number ? (
            <button
              onClick={handleCloseProtocol}
              disabled={isOperatingProtocol}
              style={{
                height: '32px',
                padding: '0 10px',
                borderRadius: 'var(--radius-md)',
                fontSize: '11px',
                fontWeight: '700',
                border: '1px solid #ef4444',
                backgroundColor: 'rgba(239, 68, 68, 0.25)',
                color: '#fca5a5',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                boxShadow: '0 0 10px rgba(239, 68, 68, 0.3)'
              }}
              title="Finalizar este atendimento e registrar marco do protocolo"
            >
              <Lock size={13} /> Fechar Protocolo
            </button>
          ) : (
            <button
              onClick={handleOpenProtocol}
              disabled={isOperatingProtocol}
              style={{
                height: '32px',
                padding: '0 10px',
                borderRadius: 'var(--radius-md)',
                fontSize: '11px',
                fontWeight: '800',
                border: '1px solid var(--accent-primary)',
                backgroundColor: 'rgba(0, 230, 153, 0.22)',
                color: 'var(--accent-primary)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                boxShadow: '0 0 12px rgba(0, 230, 153, 0.3)'
              }}
              title="Iniciar protocolo formal para este atendimento (associa mensagens retroativas)"
            >
              <FileText size={13} /> Abrir Protocolo
            </button>
          )}

          {/* Pin / Fix Conversation Button */}
          {(() => {
            const isPinned = Boolean((conversation as any).dados_adicionais?.is_pinned);
            return (
              <button
                onClick={handleTogglePin}
                disabled={isTogglingPin}
                className="btn-secondary"
                style={{
                  height: '32px',
                  padding: '0 9px',
                  fontSize: '11px',
                  fontWeight: '600',
                  borderRadius: 'var(--radius-md)',
                  backgroundColor: isPinned ? 'rgba(234, 179, 8, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                  color: isPinned ? '#eab308' : 'var(--text-main)',
                  border: isPinned ? '1px solid rgba(234, 179, 8, 0.5)' : '1px solid var(--border-color)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '4px',
                  cursor: 'pointer',
                  flexShrink: 0,
                  whiteSpace: 'nowrap'
                }}
                title={isPinned ? "Desafixar esta conversa do topo" : "Fixar esta conversa no topo da lista"}
              >
                <Pin size={12} fill={isPinned ? '#eab308' : 'none'} color={isPinned ? '#eab308' : 'currentColor'} />
                {isPinned ? 'Fixado' : 'Fixar'}
              </button>
            );
          })()}

          <button
            onClick={handleMarkAsRead}
            disabled={isMarkingRead}
            className="btn-secondary"
            style={{
              height: '32px',
              padding: '0 9px',
              fontSize: '11px',
              fontWeight: '600',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              color: '#34d399',
              border: '1px solid rgba(52, 211, 153, 0.4)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              cursor: 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap'
            }}
            title="Marcar todas as mensagens deste cliente como lidas/resolvidas sem precisar responder"
          >
            <CheckCheck size={13} /> {isMarkingRead ? '...' : 'Lido'}
          </button>

          <button
            onClick={handleToggleStatus}
            disabled={isTogglingStatus}
            style={{
              height: '32px',
              padding: '0 9px',
              borderRadius: 'var(--radius-md)',
              fontSize: '11px',
              fontWeight: '700',
              border: '1px solid var(--border-color)',
              backgroundColor: conversation.status === 'com_ia' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(59, 130, 246, 0.2)',
              color: conversation.status === 'com_ia' ? '#c084fc' : '#60a5fa',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              cursor: 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap'
            }}
          >
            {conversation.status === 'com_ia' ? <><Bot size={13} /> COM IA</> : <><Headphones size={13} /> HUMANO</>}
          </button>

          {conversation.status === 'com_ia' && (
            <button
              onClick={handleAssumeControl}
              disabled={isAssumingControl}
              style={{
                height: '32px',
                padding: '0 10px',
                borderRadius: 'var(--radius-md)',
                fontSize: '11px',
                fontWeight: '800',
                border: '1px solid #f59e0b',
                backgroundColor: 'rgba(245, 158, 11, 0.22)',
                color: '#fbbf24',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                boxShadow: '0 0 10px rgba(245, 158, 11, 0.25)'
              }}
              title="Intervir no atendimento da IA e assumir o controle da conversa agora"
            >
              <Zap size={13} className={isAssumingControl ? "animate-spin" : ""} />
              <span>{isAssumingControl ? '...' : 'Assumir'}</span>
            </button>
          )}

          <button
            onClick={handleStartVideoCall}
            className="btn-secondary"
            style={{
              height: '32px',
              padding: '0 9px',
              fontSize: '11px',
              fontWeight: '600',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(0, 230, 153, 0.12)',
              color: 'var(--accent-primary)',
              border: '1px solid var(--accent-primary)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              cursor: 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap'
            }}
            title="Iniciar chamada de vídeo / voz WebRTC e enviar link para o cliente"
          >
            <Video size={13} /> Vídeo/Voz
          </button>

          {onOpenMediaGallery && (
            <button
              onClick={onOpenMediaGallery}
              className="btn-secondary"
              style={{
                height: '32px',
                padding: '0 9px',
                fontSize: '11px',
                fontWeight: '600',
                borderRadius: 'var(--radius-md)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap'
              }}
            >
              <Paperclip size={13} /> Mídia ({conversationMedia.length})
            </button>
          )}

          {/* Mais Ações Dropdown */}
          <div style={{ position: 'relative', flexShrink: 0 }}>
            <button
              type="button"
              onClick={() => setShowMoreMenu(!showMoreMenu)}
              className="btn-secondary"
              style={{
                height: '32px',
                padding: '0 8px',
                fontSize: '11px',
                fontWeight: '600',
                borderRadius: 'var(--radius-md)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '3px',
                cursor: 'pointer',
                whiteSpace: 'nowrap'
              }}
              title="Mais ações do atendimento"
            >
              <span>Mais</span>
              <ChevronDown size={12} />
            </button>

            {showMoreMenu && (
              <>
                <div
                  onClick={() => setShowMoreMenu(false)}
                  style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    zIndex: 999
                  }}
                />
                <div style={{
                  position: 'absolute',
                  top: 'calc(100% + 6px)',
                  right: 0,
                  backgroundColor: '#0f172a',
                  border: '1px solid rgba(0, 230, 153, 0.3)',
                  borderRadius: 'var(--radius-md)',
                  boxShadow: '0 16px 36px rgba(0,0,0,0.85)',
                  zIndex: 1000,
                  minWidth: '200px',
                  overflow: 'hidden',
                  display: 'flex',
                  flexDirection: 'column',
                  padding: '4px 0'
                }}>
                  <button
                    onClick={() => {
                      backupFileInputRef.current?.click();
                      setShowMoreMenu(false);
                    }}
                    disabled={isImportingBackup}
                    style={{
                      padding: '8px 12px',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-main)',
                      fontSize: '12px',
                      textAlign: 'left',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}
                  >
                    <Upload size={14} /> {isImportingBackup ? 'Importando...' : 'Importar Backup'}
                  </button>

                  <button
                    onClick={() => {
                      handleSyncHistory();
                      setShowMoreMenu(false);
                    }}
                    disabled={isSyncingHistory}
                    style={{
                      padding: '8px 12px',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-main)',
                      fontSize: '12px',
                      textAlign: 'left',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px'
                    }}
                  >
                    <RefreshCw size={14} /> {isSyncingHistory ? 'Sincronizando...' : 'Histórico WA'}
                  </button>

                  <button
                    onClick={() => {
                      onOpenTransferModal();
                      setShowMoreMenu(false);
                    }}
                    style={{
                      padding: '8px 12px',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-main)',
                      fontSize: '12px',
                      textAlign: 'left',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      borderTop: '1px solid rgba(255,255,255,0.05)'
                    }}
                  >
                    <ArrowRightLeft size={14} /> Transferir
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {isAssignedToOther && (
        <div style={{
          backgroundColor: 'rgba(245, 158, 11, 0.15)',
          borderBottom: '1px solid rgba(245, 158, 11, 0.35)',
          padding: '10px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          color: '#fef3c7',
          fontSize: '12px',
          fontWeight: '600'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Lock size={16} color="#fbbf24" style={{ flexShrink: 0 }} />
            <span>
              🔒 <strong>Chamado atendido pelo atendente {assignedAttendantName}</strong> — Você pode acompanhar o teor da conversa em tempo real, mas o envio de mensagens está bloqueado.
            </span>
          </div>
          <span style={{ fontSize: '11px', opacity: 0.9, backgroundColor: 'rgba(0,0,0,0.3)', padding: '2px 8px', borderRadius: '4px', border: '1px solid rgba(245,158,11,0.3)', flexShrink: 0 }}>
            Modo Espectador
          </span>
        </div>
      )}

      {Boolean((conversation as any).protocol_number && conversation.resumo_ia && !dismissedSummaries.includes(conversation.id)) && (
        <div style={{
          padding: '10px 16px',
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          borderBottom: '1px solid rgba(245, 158, 11, 0.3)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1 }}>
            <Bot size={20} style={{ color: '#d97706', flexShrink: 0 }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '11px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '2px', color: '#d97706' }}>
                📌 Resumo da Transferência da IA:
              </div>
              <div style={{ fontSize: '12px', color: 'var(--text-main)', lineHeight: '1.4', fontWeight: '500' }}>
                {conversation.resumo_ia}
              </div>
            </div>
          </div>
          <button
            onClick={() => setDismissedSummaries(prev => [...prev, conversation.id])}
            title="Ocultar resumo da IA"
            style={{
              background: 'none',
              border: 'none',
              color: '#d97706',
              cursor: 'pointer',
              padding: '4px',
              display: 'flex',
              alignItems: 'center',
              borderRadius: '4px'
            }}
          >
            <X size={15} />
          </button>
        </div>
      )}

      <div
        ref={scrollContainerRef}
        onScroll={handleContainerScroll}
        style={{
          flex: 1,
          minWidth: 0,
          width: '100%',
          boxSizing: 'border-box',
          padding: '20px 24px',
          overflowY: 'auto',
          overflowX: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          position: 'relative',
          backgroundColor: 'var(--chat-bg)'
        }}
      >
        {/* WhatsApp Web Floating Sticky Date Header Badge (appears on scroll, fades when stopped) */}
        <div
          style={{
            position: 'sticky',
            top: '8px',
            alignSelf: 'center',
            zIndex: 100,
            pointerEvents: 'none',
            transition: 'opacity 0.3s cubic-bezier(0.4, 0, 0.2, 1), transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
            opacity: isFloatingDateVisible ? 1 : 0,
            transform: isFloatingDateVisible ? 'translateY(0)' : 'translateY(-8px)'
          }}
        >
          <div
            style={{
              padding: '5px 14px',
              borderRadius: '8px',
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              boxShadow: '0 4px 16px rgba(0, 0, 0, 0.25)',
              color: 'var(--text-main)',
              fontSize: '12px',
              fontWeight: '700',
              letterSpacing: '0.3px',
              textTransform: 'uppercase',
              userSelect: 'none',
              backdropFilter: 'blur(12px)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            {floatingDate}
          </div>
        </div>

        {(conversation?.messages || []).map((msg, idx, arr) => {
          const prevMsg = idx > 0 ? arr[idx - 1] : null;
          const showDateDivider = !prevMsg || (msg.timestamp && prevMsg.timestamp && getMessageDateKey(msg.timestamp) !== getMessageDateKey(prevMsg.timestamp));
          const dateLabel = showDateDivider && msg.timestamp ? formatDateDivider(msg.timestamp) : null;

          const isCustomer = msg.remetente === 'cliente';
          const isAI = msg.remetente === 'ia';
          const isSystem = msg.remetente === 'sistema';
          const msgKey = msg.id ? `msg_${msg.id}_${idx}` : `msg_${idx}`;

          return (
            <React.Fragment key={msgKey}>
              {showDateDivider && dateLabel && (
                <div style={{
                  alignSelf: 'center',
                  margin: '14px 0 6px 0',
                  padding: '5px 14px',
                  borderRadius: '8px',
                  backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  boxShadow: '0 1px 4px rgba(0, 0, 0, 0.1)',
                  color: 'var(--text-muted)',
                  fontSize: '12px',
                  fontWeight: '600',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 2,
                  userSelect: 'none'
                }}>
                  {dateLabel}
                </div>
              )}

              {isSystem ? (() => {
                const textContent = typeof msg.conteudo === 'string' ? msg.conteudo : '';
                const isProtocolClosed = textContent.includes('FINALIZADO') || textContent.includes('ENCERRADO') || textContent.includes('finalizado automaticamente');
                const isProtocolOpened = textContent.includes('PROTOCOLO FORMAL ABERTO');

                if (isProtocolClosed) {
                  return (
                    <div className="animate-fade-in" data-msg-time={msg.timestamp} style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '18px 0',
                      gap: '12px',
                      width: '100%'
                    }}>
                      <div style={{ flex: 1, height: '1px', backgroundColor: 'rgba(255, 255, 255, 0.12)' }} />
                      <div style={{
                        padding: '8px 16px',
                        borderRadius: 'var(--radius-full)',
                        backgroundColor: 'rgba(245, 158, 11, 0.12)',
                        border: '1px solid rgba(245, 158, 11, 0.35)',
                        color: '#f59e0b',
                        fontSize: '12px',
                        fontWeight: '600',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        boxShadow: '0 2px 10px rgba(0,0,0,0.35)',
                        textAlign: 'center',
                        maxWidth: '80%'
                      }}>
                        <Lock size={15} style={{ flexShrink: 0 }} />
                        <span>{textContent.replace(/[*_]/g, '')}</span>
                      </div>
                      <div style={{ flex: 1, height: '1px', backgroundColor: 'rgba(255, 255, 255, 0.12)' }} />
                    </div>
                  );
                }

                if (isProtocolOpened) {
                  return (
                    <div className="animate-fade-in" data-msg-time={msg.timestamp} style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      margin: '18px 0',
                      gap: '12px',
                      width: '100%'
                    }}>
                      <div style={{ flex: 1, height: '1px', backgroundColor: 'rgba(0, 230, 153, 0.25)' }} />
                      <div style={{
                        padding: '8px 16px',
                        borderRadius: 'var(--radius-full)',
                        backgroundColor: 'rgba(0, 230, 153, 0.12)',
                        border: '1px solid rgba(0, 230, 153, 0.4)',
                        color: 'var(--accent-primary)',
                        fontSize: '12px',
                        fontWeight: '700',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        boxShadow: '0 2px 10px rgba(0,0,0,0.35)',
                        textAlign: 'center',
                        maxWidth: '80%'
                      }}>
                        <FileText size={15} style={{ flexShrink: 0 }} />
                        <span>{textContent.replace(/[*_]/g, '')}</span>
                      </div>
                      <div style={{ flex: 1, height: '1px', backgroundColor: 'rgba(0, 230, 153, 0.25)' }} />
                    </div>
                  );
                }

                return (
                  <div className="animate-fade-in" data-msg-time={msg.timestamp} style={{
                    alignSelf: 'center',
                    margin: '8px 0',
                    padding: '6px 14px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'rgba(59, 130, 246, 0.12)',
                    border: '1px solid rgba(59, 130, 246, 0.25)',
                    color: '#3b82f6',
                    fontSize: '12px',
                    fontWeight: '600',
                    textAlign: 'center',
                    maxWidth: '85%'
                  }}>
                    {renderMediaContent(msg)}
                  </div>
                );
              })() : (() => {
                const bubbleBg = isCustomer ? 'var(--bubble-incoming)' : isAI ? 'var(--bubble-ai)' : 'var(--bubble-outgoing)';
                const bubbleColor = isCustomer ? 'var(--bubble-incoming-text)' : isAI ? 'var(--bubble-ai-text)' : 'var(--bubble-outgoing-text)';
                const border = isCustomer ? '1px solid var(--bubble-incoming-border)' : isAI ? '1px solid var(--bubble-ai-border)' : '1px solid var(--bubble-outgoing-border)';

                const isMediaMsg = ['imagem', 'video', 'audio', 'arquivo'].includes(msg.tipo);
                const reaction = (msg.id ? messageReactions[msg.id] : null) || (msg as any).dados_adicionais?.reaction;
                const isMenuOpen = activeActionMenuMsgId === (msg.id || idx);
                const isMsgSelected = selectedMessagesForForward.some(m => (m.id && m.id === msg.id) || m === msg);

                return (
            <div
              key={msgKey}
              data-msg-time={msg.timestamp}
              className="animate-fade-in msg-row-container"
              style={{
                alignSelf: isCustomer ? 'flex-start' : 'flex-end',
                maxWidth: '70%',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                flexDirection: isCustomer ? 'row' : 'row-reverse',
                position: 'relative'
              }}
            >
              {/* WhatsApp Multi-Select Checkbox or Quick Forward Button */}
              {isSelectionMode ? (
                <div
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleMessageSelection(msg);
                  }}
                  title={isMsgSelected ? "Desmarcar mensagem" : "Selecionar para encaminhar"}
                  style={{
                    width: '26px',
                    height: '26px',
                    borderRadius: '50%',
                    border: isMsgSelected ? 'none' : '2px solid var(--border-color)',
                    backgroundColor: isMsgSelected ? 'var(--accent-primary)' : 'var(--bg-secondary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#051a12',
                    cursor: 'pointer',
                    flexShrink: 0,
                    boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
                    transition: 'all 0.15s ease'
                  }}
                >
                  {isMsgSelected && <Check size={16} strokeWidth={3} />}
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => handleStartForwardSelection(msg)}
                  title="Encaminhar / Compartilhar esta mensagem"
                  style={{
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '50%',
                    width: '30px',
                    height: '30px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.12)',
                    flexShrink: 0,
                    transition: 'transform 0.15s ease, color 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = 'var(--accent-primary)';
                    e.currentTarget.style.transform = 'scale(1.1)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = 'var(--text-muted)';
                    e.currentTarget.style.transform = 'scale(1)';
                  }}
                >
                  <CornerUpRight size={15} />
                </button>
              )}

              {/* Main Message Bubble */}
              <div
                onClick={() => {
                  if (isSelectionMode) {
                    toggleMessageSelection(msg);
                  }
                }}
                style={{
                  position: 'relative',
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  backgroundColor: bubbleBg,
                  color: bubbleColor,
                  border: isMsgSelected ? '2px solid var(--accent-primary)' : border,
                  boxShadow: isMsgSelected ? '0 0 12px rgba(0, 230, 153, 0.35)' : '0 1px 4px rgba(0, 0, 0, 0.08)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  minWidth: '160px',
                  cursor: isSelectionMode ? 'pointer' : 'default',
                  transition: 'border 0.15s ease, box-shadow 0.15s ease'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', fontSize: '11px', color: 'var(--text-muted)' }}>
                  <span style={{ fontWeight: '700', color: isAI ? 'var(--status-ia)' : isCustomer ? 'var(--text-muted)' : 'var(--accent-primary)' }}>
                    {isCustomer ? (conversation.contact?.nome || 'Cliente') : isAI ? '🤖 IA Concierge' : '👤 Atendente'}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>{formatTime(msg.timestamp)}</span>
                    {!isCustomer && (
                      msg.status === 'sending' || msg.status === 'pending' ? (
                        <Clock size={12} style={{ color: 'var(--text-muted)' }} title="Enviando..." />
                      ) : msg.status === 'failed' ? (
                        <AlertCircle size={12} style={{ color: '#ef4444' }} title="Falha no envio" />
                      ) : msg.status === 'sent' ? (
                        <Check size={14} style={{ color: 'var(--text-muted)' }} title="Enviada ao servidor" />
                      ) : msg.status === 'delivered' ? (
                        <CheckCheck size={15} style={{ color: 'var(--text-muted)' }} title="Entregue no WhatsApp" />
                      ) : (
                        <CheckCheck size={15} style={{ color: '#53bdeb' }} title="Lida / Visualizada pelo cliente" />
                      )
                    )}

                    {/* WhatsApp Action Menu Chevron Button */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveActionMenuMsgId(isMenuOpen ? null : (msg.id || idx));
                      }}
                      title="Mais opções da mensagem"
                      style={{
                        background: 'transparent',
                        border: 'none',
                        color: 'var(--text-muted)',
                        cursor: 'pointer',
                        padding: '2px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: '4px'
                      }}
                    >
                      <ChevronDown size={14} />
                    </button>
                  </div>
                </div>

                {renderMediaContent(msg)}

                {/* Reaction Emoji Badge on Bubble Bottom */}
                {reaction && (
                  <div style={{
                    position: 'absolute',
                    bottom: '-10px',
                    right: isCustomer ? '10px' : 'auto',
                    left: isCustomer ? 'auto' : '10px',
                    backgroundColor: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '12px',
                    padding: '2px 6px',
                    fontSize: '13px',
                    boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                    zIndex: 10
                  }} onClick={() => handleReact(msg.id, reaction)}>
                    {reaction}
                  </div>
                )}

                {/* WhatsApp Web Context Popover Menu */}
                {isMenuOpen && (
                  <>
                    <div
                      onClick={() => setActiveActionMenuMsgId(null)}
                      style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 1000 }}
                    />
                    <div className="glass-panel" style={{
                      position: 'absolute',
                      top: '28px',
                      right: isCustomer ? 'auto' : '0',
                      left: isCustomer ? '0' : 'auto',
                      zIndex: 1001,
                      backgroundColor: 'var(--bg-secondary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-md)',
                      boxShadow: '0 10px 30px rgba(0, 0, 0, 0.4)',
                      padding: '6px',
                      minWidth: '210px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px'
                    }}>
                      {/* Top Reaction Emojis Bar */}
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '2px',
                        padding: '6px 8px',
                        backgroundColor: 'var(--bg-primary)',
                        borderRadius: 'var(--radius-sm)',
                        borderBottom: '1px solid var(--border-color)',
                        marginBottom: '4px'
                      }}>
                        {['👍', '❤️', '😂', '😮', '😢', '🙏'].map(emoji => (
                          <button
                            key={emoji}
                            type="button"
                            onClick={() => handleReact(msg.id, emoji)}
                            style={{
                              background: 'transparent',
                              border: 'none',
                              fontSize: '17px',
                              cursor: 'pointer',
                              padding: '2px 4px',
                              borderRadius: '4px',
                              transition: 'transform 0.1s ease'
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.25)')}
                            onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                          >
                            {emoji}
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={() => {
                            setReactingMsgForPicker(msg.id);
                            setShowEmojiPicker(true);
                            setActiveActionMenuMsgId(null);
                          }}
                          title="Mais emojis..."
                          style={{
                            background: 'rgba(255, 255, 255, 0.08)',
                            border: 'none',
                            borderRadius: '50%',
                            width: '24px',
                            height: '24px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            cursor: 'pointer',
                            color: 'var(--text-muted)'
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent-primary)')}
                          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
                        >
                          <Plus size={14} />
                        </button>
                      </div>

                      {/* Menu Actions */}
                      <button
                        type="button"
                        onClick={() => {
                          setReplyingToMessage(msg);
                          setActiveActionMenuMsgId(null);
                        }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '8px 12px',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-main)',
                          fontSize: '13px',
                          fontWeight: '500',
                          textAlign: 'left',
                          cursor: 'pointer',
                          borderRadius: 'var(--radius-sm)'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.1)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <Reply size={15} style={{ color: 'var(--accent-primary)' }} />
                        <span>Responder</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleStartForwardSelection(msg)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '8px 12px',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-main)',
                          fontSize: '13px',
                          fontWeight: '500',
                          textAlign: 'left',
                          cursor: 'pointer',
                          borderRadius: 'var(--radius-sm)'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.1)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <CornerUpRight size={15} style={{ color: 'var(--accent-primary)' }} />
                        <span>Encaminhar / Compartilhar</span>
                      </button>

                      {isMediaMsg && (
                        <button
                          type="button"
                          onClick={() => handleDownloadMedia(msg)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            padding: '8px 12px',
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-main)',
                            fontSize: '13px',
                            fontWeight: '500',
                            textAlign: 'left',
                            cursor: 'pointer',
                            borderRadius: 'var(--radius-sm)'
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.1)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <Download size={15} style={{ color: 'var(--accent-primary)' }} />
                          <span>Baixar Arquivo</span>
                        </button>
                      )}

                      {isMediaMsg && ((msg.conteudo || '').toLowerCase().includes('.webp') || msg.tipo === 'sticker' || msg.tipo === 'figurinha') && (
                        <button
                          type="button"
                          onClick={() => {
                            const parts = (msg.conteudo || '').split('|');
                            const url = parts[0].startsWith('http') ? parts[0] : `http://localhost:8000${parts[0]}`;
                            handleSaveSticker(url);
                            setActiveActionMenuMsgId(null);
                          }}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            padding: '8px 12px',
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--text-main)',
                            fontSize: '13px',
                            fontWeight: '500',
                            textAlign: 'left',
                            cursor: 'pointer',
                            borderRadius: 'var(--radius-sm)'
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.15)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <Star size={15} style={{ color: '#f59e0b' }} />
                          <span>Salvar no Banco de Figurinhas</span>
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => {
                          setSelectedMessageForInfo(msg);
                          setActiveActionMenuMsgId(null);
                        }}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '8px 12px',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-main)',
                          fontSize: '13px',
                          fontWeight: '500',
                          textAlign: 'left',
                          cursor: 'pointer',
                          borderRadius: 'var(--radius-sm)'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.1)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <Info size={15} style={{ color: 'var(--accent-primary)' }} />
                        <span>Dados da mensagem</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handleCopyMessage(msg)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '8px 12px',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-main)',
                          fontSize: '13px',
                          fontWeight: '500',
                          textAlign: 'left',
                          cursor: 'pointer',
                          borderRadius: 'var(--radius-sm)'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.1)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <Copy size={15} style={{ color: 'var(--accent-primary)' }} />
                        <span>Copiar Texto</span>
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          );
        })()}
      </React.Fragment>
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
              setShowLocationModal(true);
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
              setShowPixModal(true);
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
              setShowContactModal(true);
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

      {/* WhatsApp-Style Quoted Reply Preview Bar */}
      {replyingToMessage && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 18px',
          backgroundColor: 'var(--bg-secondary)',
          borderTop: '1px solid var(--border-color)',
          borderLeft: '4px solid var(--accent-primary)',
          boxShadow: '0 -2px 10px rgba(0,0,0,0.05)',
          flexShrink: 0
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Reply size={13} />
              <span>Respondendo a {replyingToMessage.remetente === 'cliente' ? (conversation.contact?.nome || 'Cliente') : 'Atendente'}:</span>
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {replyingToMessage.conteudo}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setReplyingToMessage(null)}
            title="Cancelar resposta"
            style={{
              background: 'rgba(255, 255, 255, 0.08)',
              border: 'none',
              borderRadius: '50%',
              width: '24px',
              height: '24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              cursor: 'pointer'
            }}
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* WhatsApp-Style Multi-Select Forwarding Bottom Action Bar or Normal Chat Input */}
      {isSelectionMode ? (
        <div style={{
          width: '100%',
          boxSizing: 'border-box',
          padding: '14px 24px',
          backgroundColor: 'var(--bg-secondary)',
          borderTop: '2px solid var(--accent-primary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
          boxShadow: '0 -10px 30px rgba(0, 0, 0, 0.4)',
          zIndex: 100
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <button
              type="button"
              onClick={() => {
                setIsSelectionMode(false);
                setSelectedMessagesForForward([]);
              }}
              style={{
                background: 'rgba(255, 255, 255, 0.08)',
                border: 'none',
                borderRadius: '50%',
                width: '34px',
                height: '34px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-main)',
                cursor: 'pointer'
              }}
              title="Cancelar seleção"
            >
              <X size={18} />
            </button>
            <div>
              <span style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-main)' }}>
                {selectedMessagesForForward.length} {selectedMessagesForForward.length === 1 ? 'mensagem selecionada' : 'mensagens selecionadas'}
              </span>
              <p style={{ margin: '2px 0 0 0', fontSize: '11px', color: 'var(--text-muted)' }}>
                Clique em outras mensagens para selecionar mais ou desmarcar
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              type="button"
              onClick={() => {
                if (selectedMessagesForForward.length > 0) {
                  setShowForwardModal(true);
                }
              }}
              disabled={selectedMessagesForForward.length === 0}
              className="btn-primary"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 22px',
                fontSize: '13px',
                fontWeight: '700',
                boxShadow: '0 4px 15px rgba(0, 230, 153, 0.35)'
              }}
            >
              <CornerUpRight size={16} />
              <span>Encaminhar ({selectedMessagesForForward.length})</span>
            </button>
          </div>
        </div>
      ) : isAssignedToOther ? (
        <div style={{
          width: '100%',
          boxSizing: 'border-box',
          padding: '16px 20px',
          borderTop: '1px solid rgba(245, 158, 11, 0.3)',
          backgroundColor: 'rgba(245, 158, 11, 0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '10px',
          color: '#fbbf24',
          fontSize: '13px',
          fontWeight: '600'
        }}>
          <Lock size={16} />
          <span>Chamado em atendimento por <strong>{assignedAttendantName}</strong>. Apenas visualização em tempo real permitida.</span>
        </div>
      ) : (() => {
        const isGroupChat = Boolean(
          conversation.contact?.telefone?.startsWith('120363') ||
          (conversation.contact?.telefone && conversation.contact.telefone.length > 15) ||
          conversation.contact?.nome?.includes('Servweld/Servsolda')
        );

        return (
          <form onSubmit={handleSend} style={{ width: '100%', boxSizing: 'border-box', padding: '16px 20px', borderTop: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0, position: 'relative' }}>
            <button
              type="button"
              onClick={() => {
                setReactingMsgForPicker(null);
                setShowEmojiPicker(!showEmojiPicker);
              }}
              className="btn-secondary"
              style={{
                padding: '10px 12px',
                color: showEmojiPicker ? 'var(--accent-primary)' : 'var(--text-muted)'
              }}
              title="Emojis, GIFs e Figurinhas do WhatsApp"
            >
              <Smile size={18} />
            </button>
            <button type="button" onClick={() => setShowAttachmentMenu(!showAttachmentMenu)} className="btn-secondary" style={{ padding: '10px 12px' }} title="Menu de Anexos e Ações Rápidas"><Paperclip size={18} /></button>
            <input
              type="text"
              placeholder={isGroupChat ? 'Enviar mensagem no grupo...' : 'Digite sua mensagem para o cliente...'}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              style={{ flex: 1, padding: '12px 16px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
            />
            <button
              type="button"
              onClick={handleConsultarIA}
              disabled={isConsultingIA}
              className="btn-secondary"
              style={{
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                color: 'var(--accent-primary)',
                borderColor: 'rgba(0, 230, 153, 0.4)',
                backgroundColor: 'rgba(0, 230, 153, 0.08)',
                fontWeight: '600',
                fontSize: '13px'
              }}
              title="Consultar IA (Gera rascunho de resposta no campo de texto para você revisar antes de enviar)"
            >
              <Bot size={16} className={isConsultingIA ? 'animate-spin' : ''} />
              <span>{isConsultingIA ? 'Gerando...' : 'Consultar IA'}</span>
            </button>
            <button type="submit" className="btn-primary" disabled={(!inputText.trim() && pendingFiles.length === 0) || isSending}>
              <Send size={16} /> {isSending ? 'Enviando...' : 'Enviar'}
            </button>
          </form>
        );
      })()}

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
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 'bold', color: 'var(--accent-primary)' }}>
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

      {/* 1. Forward & Share Modal (Estilo WhatsApp Web Oficial com Multi-Seleção) */}
      <ForwardModal
        isOpen={showForwardModal}
        onClose={() => {
          setShowForwardModal(false);
          setIsSelectionMode(false);
          setSelectedMessagesForForward([]);
        }}
        messagesToForward={selectedMessagesForForward}
        conversations={allConversations || []}
        onForwardSuccess={() => {
          setIsSelectionMode(false);
          setSelectedMessagesForForward([]);
          if (onStatusToggle) onStatusToggle();
        }}
      />

      {/* 2. Location Picker Modal (Estilo WhatsApp Mapa) */}
      <LocationPickerModal
        isOpen={showLocationModal}
        onClose={() => setShowLocationModal(false)}
        conversationId={conversation?.id || null}
        onLocationSent={() => {
          if (conversation?.id) {
            apiFetch(`/conversations/${conversation.id}`).then(data => {
              if (data && data.messages) {
                conversation.messages = data.messages;
              }
            }).catch(() => {});
          }
        }}
      />

      {/* 3. Contact Picker Modal (Estilo WhatsApp Agenda) */}
      <ContactPickerModal
        isOpen={showContactModal}
        onClose={() => setShowContactModal(false)}
        onSelectContact={(contact) => {
          setInputText(prev => (prev ? prev + '\n' : '') + `👤 *Cartão de Contato Compartilhado:*\n• *Nome:* ${contact.nome}\n• *Telefone:* ${contact.telefone}`);
        }}
      />

      {/* 4. Pix Generator Modal (Oficial Servweld + Chaves Dinâmicas + Valor e Imagem do QR Code) */}
      <PixModal
        isOpen={showPixModal}
        onClose={() => setShowPixModal(false)}
        conversationId={conversation?.id || null}
        onPixSent={() => {
          if (conversation?.id) {
            apiFetch(`/conversations/${conversation.id}`).then(data => {
              if (data && data.messages) {
                conversation.messages = data.messages;
              }
            }).catch(() => {});
          }
        }}
      />

      {/* 5. Contact / Group Avatar Fullscreen Lightbox Modal */}
      <AvatarModal
        isOpen={showAvatarZoom}
        onClose={() => setShowAvatarZoom(false)}
        name={conversation.contact?.nome || 'Cliente'}
        phone={conversation.contact?.telefone}
        avatarUrl={conversation.contact?.foto_perfil_url}
      />

      {/* 6. Message Info Modal (Dados da Mensagem / Quem leu no grupo) */}
      <MessageInfoModal
        isOpen={Boolean(selectedMessageForInfo)}
        onClose={() => setSelectedMessageForInfo(null)}
        message={selectedMessageForInfo}
        conversation={conversation}
      />

      {/* 7. Complete WhatsApp Emojis, Animated GIFs & Stickers Picker Drawer */}
      <EmojiGifStickerPicker
        isOpen={showEmojiPicker}
        onClose={() => {
          setShowEmojiPicker(false);
          setReactingMsgForPicker(null);
        }}
        onSelectEmoji={(emoji) => {
          if (reactingMsgForPicker) {
            handleReact(reactingMsgForPicker, emoji);
            setReactingMsgForPicker(null);
            setShowEmojiPicker(false);
          } else {
            setInputText(prev => prev + emoji);
          }
        }}
        onSelectGif={(gifUrl) => {
          setShowEmojiPicker(false);
          onSendMessage(gifUrl, 'video');
        }}
        onSelectSticker={(stickerUrl) => {
          setShowEmojiPicker(false);
          onSendMessage(stickerUrl, 'imagem');
        }}
      />
    </div>
  );
};
