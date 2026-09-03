import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Send, UserCheck, Headphones, ArrowRightLeft, Bot, Phone, Building,
  AlertCircle, AlertTriangle, Paperclip, X, FileText, Image as ImageIcon, Video, Music, Download, UploadCloud, Eye, ArrowLeft, Camera,
  ChevronLeft, ChevronRight, ChevronDown, Clock, Check, CheckCheck, Pencil, RefreshCw, Upload, MapPin,
  QrCode, Share2, Zap, Plus, PanelLeftOpen, PanelLeftClose, CornerUpRight, Reply, Smile, Copy, MoreHorizontal, CornerDownRight, Info, Star,
  Lock, Unlock, Pin, ZoomIn, ZoomOut, RotateCw, Maximize2, ExternalLink, Calendar, Users, User as UserIcon, AtSign, MessageSquare,
  Globe, Navigation
} from 'lucide-react';
import { apiFetch, apiUpload } from '../services/api';
import { LocationPickerModal } from './LocationPickerModal';
import { ContactPickerModal } from './ContactPickerModal';
import { PixModal } from './PixModal';
import { AvatarModal } from './AvatarModal';
import { ForwardModal } from './ForwardModal';
import { MessageInfoModal } from './MessageInfoModal';
import { EmojiGifStickerPicker } from './EmojiGifStickerPicker';
import { AICopilotModal } from './AICopilotModal';
import { WhatsAppAudioPlayer } from './WhatsAppAudioPlayer';
import { AudioRecorder } from './AudioRecorder';
import { StickyAudioPlayer } from './StickyAudioPlayer';
import { getCleanDisplayName } from './ChatList';
import { Conversation, User, Message, CalendarEvent, WhatsAppNumber } from '../types';

interface ChatAreaProps {
  conversation: Conversation | null;
  allConversations?: Conversation[];
  onSelectConversation?: (conv: Conversation) => void;
  currentUser: User;
  onSendMessage: (text: string, tipo?: string) => Promise<void>;
  onOpenTransferModal: () => void;
  onOpenMediaGallery?: () => void;
  onOpenScheduleTask?: (prefill: Partial<CalendarEvent>) => void;
  onStatusToggle?: () => void;
  onBack?: () => void;
  isChatListCollapsed?: boolean;
  onToggleChatList?: () => void;
  whatsappNumbers?: WhatsAppNumber[];
  drafts?: { [convId: number]: string };
  userPresences?: { [convId: number]: { status: string; agentName?: string; expiresAt: number } };
  onSaveDraft?: (convId: number, text: string) => void;
}

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

export const formatWhatsAppPhone = (phone: string | undefined | null): string => {
  if (!phone) return '';
  const str = String(phone);
  const clean = str.replace(/\D/g, '');
  if (str.includes('@g.us') || clean.startsWith('120363')) {
    return 'Grupo';
  }
  if (clean.startsWith('55') && clean.length === 12) {
    return `+55 (${clean.slice(2, 4)}) ${clean.slice(4, 8)}-${clean.slice(8)}`;
  }
  if (clean.startsWith('55') && clean.length === 13) {
    return `+55 (${clean.slice(2, 4)}) ${clean.slice(4, 9)}-${clean.slice(9)}`;
  }
  if (clean.length === 10) {
    return `(${clean.slice(0, 2)}) ${clean.slice(2, 6)}-${clean.slice(6)}`;
  }
  if (clean.length === 11) {
    return `(${clean.slice(0, 2)}) ${clean.slice(2, 7)}-${clean.slice(7)}`;
  }
  return str.replace('@lid', '').replace('@s.whatsapp.net', '');
};

// Global memory cache for link preview across all components and renders
const globalLinkPreviewCache = new Map<string, any>();

export const LinkPreviewCardComponent: React.FC<{ url: string; initialData?: any }> = ({ url, initialData }) => {
  const [preview, setPreview] = useState<any>(() => {
    if (initialData && (initialData.title || initialData.image)) return initialData;
    if (globalLinkPreviewCache.has(url)) return globalLinkPreviewCache.get(url);
    return null;
  });

  useEffect(() => {
    if (preview && (preview.title || preview.image)) return;
    if (globalLinkPreviewCache.has(url)) {
      setPreview(globalLinkPreviewCache.get(url));
      return;
    }

    let isMounted = true;
    apiFetch(`/conversations/link_preview?url=${encodeURIComponent(url)}`)
      .then((res: any) => {
        if (isMounted && res) {
          globalLinkPreviewCache.set(url, res);
          setPreview(res);
        }
      })
      .catch(() => {
        try {
          const u = new URL(url.startsWith('http') ? url : `https://${url}`);
          const fallback = { url, domain: u.hostname.replace('www.', ''), title: u.hostname };
          globalLinkPreviewCache.set(url, fallback);
          if (isMounted) setPreview(fallback);
        } catch {
          // ignore
        }
      });

    return () => {
      isMounted = false;
    };
  }, [url]);

  if (!preview) {
    return null;
  }

  const domainName = preview?.domain || (preview?.url ? (() => { try { return new URL(preview.url).hostname.replace('www.', ''); } catch { return ''; } })() : '');

  // Hide empty boxes without image or descriptive title
  if (!preview.image && (!preview.title || preview.title.toLowerCase() === domainName.toLowerCase() || preview.title.toLowerCase() === `www.${domainName.toLowerCase()}`)) {
    return null;
  }

  return (
    <a
      href={preview.url || url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        maxWidth: '340px',
        backgroundColor: 'rgba(0, 0, 0, 0.35)',
        borderRadius: '10px',
        overflow: 'hidden',
        margin: '4px 0 8px 0',
        textDecoration: 'none',
        color: 'inherit',
        border: '1px solid rgba(255, 255, 255, 0.12)',
        boxShadow: '0 3px 10px rgba(0, 0, 0, 0.25)',
        transition: 'background-color 0.15s ease, transform 0.15s ease',
        cursor: 'pointer'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'rgba(0, 0, 0, 0.35)';
        e.currentTarget.style.transform = 'none';
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {preview.image && (
        <div style={{
          width: '100%',
          maxHeight: '190px',
          overflow: 'hidden',
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}>
          <img
            src={preview.image}
            alt={preview.title || 'Prévia do Link'}
            style={{
              width: '100%',
              height: 'auto',
              maxHeight: '190px',
              objectFit: 'cover',
              display: 'block'
            }}
            onError={(e) => (e.currentTarget.style.display = 'none')}
          />
        </div>
      )}
      <div style={{ padding: '9px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {preview.title && (
          <div style={{
            fontSize: '13px',
            fontWeight: '700',
            color: '#ffffff',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            lineHeight: '1.3'
          }}>
            {preview.title}
          </div>
        )}
        {preview.description && (
          <div style={{
            fontSize: '11.5px',
            color: 'rgba(255, 255, 255, 0.75)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            lineHeight: '1.35'
          }}>
            {preview.description}
          </div>
        )}
        <div style={{
          fontSize: '10.5px',
          color: 'rgba(255, 255, 255, 0.5)',
          marginTop: '2px',
          display: 'flex',
          alignItems: 'center',
          gap: '4px'
        }}>
          <Globe size={11} />
          <span>{domainName}</span>
        </div>
      </div>
    </a>
  );
};

export const ChatArea: React.FC<ChatAreaProps> = ({
  conversation,
  allConversations,
  onSelectConversation,
  currentUser,
  onSendMessage,
  onOpenTransferModal,
  onOpenMediaGallery,
  onOpenScheduleTask,
  onStatusToggle,
  onBack,
  isChatListCollapsed = false,
  onToggleChatList,
  whatsappNumbers,
  drafts = {},
  onSaveDraft,
  userPresences = {}
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

  // WhatsApp Message Edit State (Imagem 3)
  const [editingMessage, setEditingMessage] = useState<Message | null>(null);
  const [editingMessageText, setEditingMessageText] = useState<string>('');
  const [isSavingEdit, setIsSavingEdit] = useState<boolean>(false);

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

  const isGroupChat = useMemo(() => {
    if (!conversation) return false;
    const phone = conversation.contact?.telefone || '';
    const name = conversation.contact?.nome || '';
    return Boolean(
      phone.includes('@g.us') ||
      phone.startsWith('120363') ||
      phone.includes('-') ||
      phone.length >= 18 ||
      conversation.dados_adicionais?.is_group ||
      (conversation.contact?.dados_adicionais as any)?.is_group ||
      name.startsWith('SERV -') ||
      name.includes('GRUPO') ||
      name.includes('Servweld/Servsolda')
    );
  }, [conversation]);

  type RenderGroup = 
    | { type: 'single'; message: Message; originalIndex: number }
    | { type: 'image_album'; messages: Message[]; originalIndices: number[] };

  const processedMessageGroups = useMemo<RenderGroup[]>(() => {
    const rawMsgs = conversation?.messages || [];
    const groups: RenderGroup[] = [];
    let i = 0;

    while (i < rawMsgs.length) {
      const msg = rawMsgs[i];
      const isImg = msg.tipo === 'imagem' || (msg.conteudo && (msg.conteudo.endsWith('.jpg') || msg.conteudo.endsWith('.png') || msg.conteudo.endsWith('.jpeg') || msg.conteudo.endsWith('.webp')) && !msg.conteudo.includes('figurinha'));
      
      if (isImg) {
        // Collect consecutive images from the same sender within 3 minutes
        const album: Message[] = [msg];
        const indices: number[] = [i];
        let j = i + 1;

        while (j < rawMsgs.length) {
          const nextMsg = rawMsgs[j];
          const nextIsImg = nextMsg.tipo === 'imagem' || (nextMsg.conteudo && (nextMsg.conteudo.endsWith('.jpg') || nextMsg.conteudo.endsWith('.png') || nextMsg.conteudo.endsWith('.jpeg') || nextMsg.conteudo.endsWith('.webp')) && !nextMsg.conteudo.includes('figurinha'));
          
          if (nextIsImg && nextMsg.remetente === msg.remetente) {
            const t1 = normalizeIsoDate(msg.timestamp).getTime();
            const t2 = normalizeIsoDate(nextMsg.timestamp).getTime();
            if (Math.abs(t2 - t1) <= 180000) {
              album.push(nextMsg);
              indices.push(j);
              j++;
              continue;
            }
          }
          break;
        }

        if (album.length > 1) {
          groups.push({ type: 'image_album', messages: album, originalIndices: indices });
          i = j;
          continue;
        }
      }

      groups.push({ type: 'single', message: msg, originalIndex: i });
      i++;
    }

    return groups;
  }, [conversation?.messages]);

  const [inputText, setInputText] = useState(() => {
    if (conversation?.id && drafts && drafts[conversation.id]) {
      return drafts[conversation.id];
    }
    return '';
  });
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isTogglingStatus, setIsTogglingStatus] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    if (sendError) {
      const timer = setTimeout(() => setSendError(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [sendError]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const dragCounterRef = useRef(0);
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
  const [showCopilotModal, setShowCopilotModal] = useState(false);
  const [isConsultingIA, setIsConsultingIA] = useState(false);
  const [isAssumingControl, setIsAssumingControl] = useState(false);
  
  // Feedback / Continuous improvement modal
  const [showReportAIModal, setShowReportAIModal] = useState(false);
  const [reportErrorCategory, setReportErrorCategory] = useState('alucinacao_nome');
  const [reportCorrectResponse, setReportCorrectResponse] = useState('');
  const [reportLastAIReply, setReportLastAIReply] = useState('');
  const [isSubmittingReport, setIsSubmittingReport] = useState(false);
  const [reportSuccessMessage, setReportSuccessMessage] = useState<string | null>(null);

  // Group Participants State
  const [groupParticipants, setGroupParticipants] = useState<any[]>([]);
  const [showParticipantsModal, setShowParticipantsModal] = useState<boolean>(false);
  const [participantsSearch, setParticipantsSearch] = useState<string>('');

  // Real-time Link Preview state for input composer (like WhatsApp)
  const [inputLinkPreview, setInputLinkPreview] = useState<{
    url: string;
    title?: string | null;
    description?: string | null;
    image?: string | null;
    domain?: string | null;
    loading?: boolean;
  } | null>(null);
  const [dismissedUrls, setDismissedUrls] = useState<string[]>([]);

  // Unified Sub-Layer Close Handler for Back Button & Esc key
  const closeTopmostSublayer = useCallback(() => {
    if (showCopilotModal) { setShowCopilotModal(false); return true; }
    if (showAttachmentMenu) { setShowAttachmentMenu(false); return true; }
    if (showEmojiPicker) { setShowEmojiPicker(false); return true; }
    if (showLocationModal) { setShowLocationModal(false); return true; }
    if (showContactModal) { setShowContactModal(false); return true; }
    if (showPixModal) { setShowPixModal(false); return true; }
    if (showAvatarZoom) { setShowAvatarZoom(false); return true; }
    if (showParticipantsModal) { setShowParticipantsModal(false); return true; }
    if (showReportAIModal) { setShowReportAIModal(false); return true; }
    if (isSelectionMode) { setIsSelectionMode(false); setSelectedMessagesForForward([]); return true; }
    return false;
  }, [
    showCopilotModal, showAttachmentMenu, showEmojiPicker,
    showLocationModal, showContactModal, showPixModal,
    showAvatarZoom, showParticipantsModal, showReportAIModal, isSelectionMode
  ]);

  // Sync browser history state (pushState) whenever a modal/sub-layer opens
  const hasSublayer = 
    showCopilotModal || showAttachmentMenu || showEmojiPicker ||
    showLocationModal || showContactModal || showPixModal ||
    showAvatarZoom || showParticipantsModal || showReportAIModal || isSelectionMode;

  useEffect(() => {
    if (hasSublayer) {
      try {
        window.history.pushState({ page: 'sublayer', sublayerOpen: true }, '');
      } catch {}
    }
  }, [hasSublayer]);

  useEffect(() => {
    const handlePopState = (e: PopStateEvent) => {
      const closed = closeTopmostSublayer();
      if (closed) {
        e.stopImmediatePropagation();
        e.preventDefault();
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeTopmostSublayer();
      }
    };

    window.addEventListener('popstate', handlePopState, true);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('popstate', handlePopState, true);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [closeTopmostSublayer]);

  useEffect(() => {
    if (!conversation) {
      setGroupParticipants([]);
      return;
    }
    let isMounted = true;
    const fetchParticipants = async () => {
      try {
        const res = await apiFetch(`/conversations/${conversation.id}/participants`);
        if (isMounted && res && Array.isArray(res.participants)) {
          setGroupParticipants(res.participants);
        }
      } catch (err) {
        console.debug('Error fetching conversation participants:', err);
      }
    };
    fetchParticipants();
    return () => { isMounted = false; };
  }, [conversation?.id]);

  // Real-time link preview detector for message input (identical to WhatsApp)
  useEffect(() => {
    const urlMatch = inputText.match(/https?:\/\/[^\s]+/i);
    if (!urlMatch) {
      if (inputLinkPreview) setInputLinkPreview(null);
      return;
    }

    const detectedUrl = urlMatch[0];
    if (dismissedUrls.includes(detectedUrl)) {
      return;
    }

    if (inputLinkPreview && inputLinkPreview.url === detectedUrl) {
      return;
    }

    let domain = '';
    try {
      domain = new URL(detectedUrl).hostname.replace('www.', '');
    } catch {}

    const cached = linkPreviewCacheRef.current.get(detectedUrl);
    if (cached) {
      setInputLinkPreview({ ...cached, loading: false });
      return;
    }

    setInputLinkPreview({
      url: detectedUrl,
      title: domain,
      description: detectedUrl,
      domain: domain,
      loading: true
    });

    let isMounted = true;
    const timer = setTimeout(() => {
      apiFetch(`/conversations/link_preview?url=${encodeURIComponent(detectedUrl)}`)
        .then((res: any) => {
          if (isMounted && res) {
            linkPreviewCacheRef.current.set(detectedUrl, res);
            setInputLinkPreview({ ...res, loading: false });
          }
        })
        .catch(() => {
          if (isMounted) {
            setInputLinkPreview({
              url: detectedUrl,
              title: domain,
              description: detectedUrl,
              domain: domain,
              loading: false
            });
          }
        });
    }, 250);

    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [inputText, dismissedUrls]);

  // Lightbox Zoom, Pan & Rotation State
  const [zoomScale, setZoomScale] = useState<number>(1);
  const [imageRotation, setImageRotation] = useState<number>(0);
  const [panPosition, setPanPosition] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isDraggingImage, setIsDraggingImage] = useState<boolean>(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

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
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const documentInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const extractMediaAndCaption = (raw: string | undefined | null) => {
    if (!raw) return { mediaPath: '', caption: null as string | null };
    let str = String(raw).trim();
    let mediaPath = '';
    let caption: string | null = null;

    if (str.includes('|')) {
      const parts = str.split('|');
      mediaPath = parts[0].trim();
      caption = parts.slice(1).join('|').trim() || null;
    } else if (str.startsWith('[') && str.includes(']')) {
      const match = str.match(/^\[(.*?)\]\s*([\s\S]*)$/);
      if (match) {
        mediaPath = match[1].trim();
        caption = match[2].trim() || null;
      } else {
        mediaPath = str.trim();
      }
    } else if (str.startsWith('/uploads/') || str.startsWith('http://') || str.startsWith('https://')) {
      const lines = str.split('\n');
      mediaPath = lines[0].trim();
      caption = lines.slice(1).join('\n').trim() || null;
    } else {
      mediaPath = str;
    }

    mediaPath = mediaPath.replace(/^\[/, '').replace(/\]$/, '').trim();
    return { mediaPath, caption };
  };

  // Extract all media items in conversation for universal gallery navigation (Images, Videos, Audios, Files)
  const conversationMedia = (conversation?.messages || [])
    .filter(m => ['imagem', 'video', 'audio', 'arquivo'].includes(m.tipo))
    .map(m => {
      const { mediaPath, caption } = extractMediaAndCaption(m.conteudo);
      const fullUrl = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
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

  useEffect(() => {
    setZoomScale(1);
    setImageRotation(0);
    setPanPosition({ x: 0, y: 0 });
    setIsDraggingImage(false);
  }, [previewMediaIndex]);

  const handleZoomIn = () => {
    setZoomScale(prev => Math.min(Number((prev + 0.35).toFixed(2)), 5));
  };
  const handleZoomOut = () => {
    setZoomScale(prev => {
      const next = Math.max(Number((prev - 0.35).toFixed(2)), 1);
      if (next === 1) setPanPosition({ x: 0, y: 0 });
      return next;
    });
  };
  const handleResetZoom = () => {
    setZoomScale(1);
    setImageRotation(0);
    setPanPosition({ x: 0, y: 0 });
  };
  const handleRotateImage = () => {
    setImageRotation(prev => (prev + 90) % 360);
  };

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
      if (e.key === 'ArrowLeft' && zoomScale <= 1) handlePrevMedia();
      if (e.key === 'ArrowRight' && zoomScale <= 1) handleNextMedia();
      if (e.key === 'Escape') setPreviewMediaIndex(null);
      if (e.key === '+' || e.key === '=') handleZoomIn();
      if (e.key === '-' || e.key === '_') handleZoomOut();
      if (e.key === '0') handleResetZoom();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewMediaIndex, conversationMedia.length, zoomScale]);

  const scrollToBottom = (behavior: 'smooth' | 'auto' = 'auto') => {
    if (scrollContainerRef.current) {
      if (behavior === 'smooth') {
        scrollContainerRef.current.scrollTo({
          top: scrollContainerRef.current.scrollHeight,
          behavior: 'smooth'
        });
      } else {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      }
    }
  };

  const handleContainerScroll = () => {
    if (!scrollContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollContainerRef.current;
    // Mark as scrolled up only if user explicitly scrolls up significantly (>200px)
    const isFar = scrollHeight - scrollTop - clientHeight > 200;
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

  // Keep pinned to bottom when images/media/previews load
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      if (!isUserScrolledUp && scrollContainerRef.current) {
        scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [conversation?.id, isUserScrolledUp]);

  // Send "composing" presence to WhatsApp & system when attendant types
  const lastPresenceSentRef = useRef<number>(0);
  useEffect(() => {
    if (!conversation?.id || !inputText.trim()) return;
    const now = Date.now();
    if (now - lastPresenceSentRef.current > 3500) {
      lastPresenceSentRef.current = now;
      apiFetch(`/conversations/${conversation.id}/presence`, {
        method: 'POST',
        body: JSON.stringify({ presence: 'composing' })
      }).catch(() => {});
    }
  }, [inputText, conversation?.id]);

  // Auto-mark conversation as read, load draft, and scroll to the absolute bottom on conversation change
  useEffect(() => {
    setIsUserScrolledUp(false);
    scrollToBottom('auto');

    // Load draft specific to this conversation
    const currentDraft = (conversation?.id && drafts) ? (drafts[conversation.id] || '') : '';
    setInputText(currentDraft);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const nextH = Math.min(textareaRef.current.scrollHeight, 140);
      textareaRef.current.style.height = `${Math.max(nextH, 42)}px`;
    }

    if (conversation?.id) {
      const extra = (conversation as any).dados_adicionais || {};
      const msgs = conversation.messages || [];
      const hasUnread = !extra.marked_as_read || !extra.pending_dismissed || msgs.some(m => m.remetente === 'cliente' && m.status !== 'read');

      if (hasUnread) {
        extra.marked_as_read = true;
        extra.pending_dismissed = true;
        (conversation as any).dados_adicionais = extra;

        // Call backend silently to persist read status
        apiFetch(`/conversations/${conversation.id}/mark_read`, { method: 'POST' })
          .then(() => {
            if (onStatusToggle) onStatusToggle();
          })
          .catch(err => console.debug('Auto mark_read error:', err));
      }
    }
  }, [conversation?.id]);

  useEffect(() => {
    if (!isUserScrolledUp && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = scrollContainerRef.current.scrollHeight;
    }
    setSendError(null);
  }, [conversation?.messages, isUserScrolledUp]);

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

  const isConvPinned = (conv: Conversation | null): boolean => {
    if (!conv || !conv.dados_adicionais) return false;
    const extra = conv.dados_adicionais;
    if (currentUser?.id) {
      if (Array.isArray(extra.pinned_by_users) && extra.pinned_by_users.includes(currentUser.id)) return true;
      if (extra[`pinned_user_${currentUser.id}`] === true) return true;
      return false;
    }
    return Boolean(extra.is_pinned);
  };

  const handleTogglePin = async () => {
    if (!conversation || isTogglingPin) return;
    const currentPinned = isConvPinned(conversation);
    const nextPinned = !currentPinned;
    try {
      setIsTogglingPin(true);
      const extra = { ...((conversation as any).dados_adicionais || {}) };
      let pinnedUsers: number[] = Array.isArray(extra.pinned_by_users) ? [...extra.pinned_by_users] : [];
      if (currentUser?.id) {
        if (nextPinned) {
          if (!pinnedUsers.includes(currentUser.id)) pinnedUsers.push(currentUser.id);
        } else {
          pinnedUsers = pinnedUsers.filter(id => id !== currentUser.id);
        }
        extra.pinned_by_users = pinnedUsers;
        extra[`pinned_user_${currentUser.id}`] = nextPinned;
      } else {
        extra.is_pinned = nextPinned;
      }
      delete extra.is_pinned;
      (conversation as any).dados_adicionais = extra;

      await apiFetch(`/conversations/${conversation.id}/toggle-pin`, { method: 'POST' });
      if (onStatusToggle) onStatusToggle();
    } catch (err: any) {
      console.error('Error toggling pin in ChatArea:', err);
    } finally {
      setIsTogglingPin(false);
    }
  };

  const handleRetryMessage = async (msgId: number) => {
    setActiveActionMenuMsgId(null);
    setMessages(prev => prev.map(m => m.id === msgId ? { ...m, status: 'sending' } : m));
    try {
      const res: any = await apiFetch(`/conversations/messages/${msgId}/retry`, { method: 'POST' });
      if (res && res.status) {
        setMessages(prev => prev.map(m => m.id === msgId ? { ...m, status: res.status } : m));
      }
    } catch (err) {
      console.error('Failed to retry message:', err);
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, status: 'failed' } : m));
    }
  };

  const handleSendAudioMessage = async (audioUrl: string) => {
    if (!conversation) return;
    try {
      if (onSendMessage) {
        await onSendMessage(audioUrl, 'audio');
      } else {
        const payload = {
          tipo: 'audio',
          conteudo: audioUrl
        };
        const newMsg: any = await apiFetch(`/conversations/${conversation.id}/messages`, {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        if (newMsg) {
          setMessages(prev => [...prev, newMsg]);
          scrollToBottom();
        }
      }
    } catch (err) {
      console.error('Error sending audio message:', err);
    }
  };

  const [showMentionMenu, setShowMentionMenu] = useState(false);


  const handleInsertMention = (mentionTag: string) => {
    const target = textareaRef.current;
    if (!target) {
      setInputText(prev => prev + mentionTag);
      setShowMentionMenu(false);
      return;
    }
    const cursor = target.selectionStart || inputText.length;
    const val = inputText;
    const textBeforeCursor = val.substring(0, cursor);
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');

    let newVal = '';
    let newCursorPos = 0;
    if (lastAtIndex !== -1) {
      newVal = val.substring(0, lastAtIndex) + mentionTag + val.substring(cursor);
      newCursorPos = lastAtIndex + mentionTag.length;
    } else {
      newVal = val + mentionTag;
      newCursorPos = newVal.length;
    }

    setInputText(newVal);
    setShowMentionMenu(false);
    setTimeout(() => {
      target.focus();
      target.selectionStart = target.selectionEnd = newCursorPos;
    }, 0);
  };

  // Link Preview client-side memory cache
  const linkPreviewCacheRef = useRef<Map<string, any>>(new Map());

  const LinkPreviewCardComponent: React.FC<{ url: string; initialData?: any }> = ({ url, initialData }) => {
    const [preview, setPreview] = useState<any>(() => {
      if (initialData && (initialData.title || initialData.image)) return initialData;
      if (linkPreviewCacheRef.current.has(url)) return linkPreviewCacheRef.current.get(url);
      return null;
    });

    useEffect(() => {
      if (preview && (preview.title || preview.image)) return;
      if (linkPreviewCacheRef.current.has(url)) {
        setPreview(linkPreviewCacheRef.current.get(url));
        return;
      }

      let isMounted = true;
      apiFetch(`/conversations/link_preview?url=${encodeURIComponent(url)}`)
        .then((res: any) => {
          if (isMounted && res) {
            linkPreviewCacheRef.current.set(url, res);
            setPreview(res);
          }
        })
        .catch(() => {
          try {
            const u = new URL(url.startsWith('http') ? url : `https://${url}`);
            const fallback = { url, domain: u.hostname.replace('www.', ''), title: u.hostname };
            linkPreviewCacheRef.current.set(url, fallback);
            if (isMounted) setPreview(fallback);
          } catch {
            // ignore
          }
        });

      return () => {
        isMounted = false;
      };
    }, [url]);

    const domainName = preview?.domain || (preview?.url ? (() => { try { return new URL(preview.url).hostname.replace('www.', ''); } catch { return ''; } })() : '');

    if (!preview || (!preview.image && (!preview.title || preview.title.toLowerCase() === domainName.toLowerCase() || preview.title.toLowerCase() === `www.${domainName.toLowerCase()}`))) {
      return null;
    }

    return (
      <a
        href={preview.url || url}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          maxWidth: '340px',
          backgroundColor: 'rgba(0, 0, 0, 0.3)',
          borderRadius: '10px',
          overflow: 'hidden',
          margin: '4px 0 8px 0',
          textDecoration: 'none',
          color: 'inherit',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          boxShadow: '0 3px 10px rgba(0, 0, 0, 0.25)',
          transition: 'background-color 0.15s ease, transform 0.15s ease',
          cursor: 'pointer'
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.backgroundColor = 'rgba(0, 0, 0, 0.45)';
          e.currentTarget.style.transform = 'translateY(-1px)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.backgroundColor = 'rgba(0, 0, 0, 0.3)';
          e.currentTarget.style.transform = 'none';
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {preview.image && (
          <div style={{
            width: '100%',
            maxHeight: '190px',
            overflow: 'hidden',
            backgroundColor: 'rgba(0, 0, 0, 0.5)',
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <img
              src={preview.image}
              alt={preview.title || 'Prévia do Link'}
              style={{
                width: '100%',
                height: 'auto',
                maxHeight: '190px',
                objectFit: 'cover',
                display: 'block'
              }}
              onError={(e) => (e.currentTarget.style.display = 'none')}
            />
          </div>
        )}
        <div style={{ padding: '9px 12px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {preview.title && (
            <div style={{
              fontSize: '13px',
              fontWeight: '700',
              color: '#ffffff',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              lineHeight: '1.3'
            }}>
              {preview.title}
            </div>
          )}
          {preview.description && (
            <div style={{
              fontSize: '11.5px',
              color: 'rgba(255, 255, 255, 0.75)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              lineHeight: '1.35'
            }}>
              {preview.description}
            </div>
          )}
          <div style={{
            fontSize: '10.5px',
            color: 'rgba(255, 255, 255, 0.5)',
            marginTop: '2px',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}>
            <Globe size={11} />
            <span>{domainName}</span>
          </div>
        </div>
      </a>
    );
  };

  const renderFormattedMessageText = (text: string) => {
    if (!text || typeof text !== 'string') return null;

    // Check WhatsApp quoted reply format (e.g. "> *Sender:* Quote text\n\nActual message")
    if (text.startsWith('> ')) {
      const splitIdx = text.indexOf('\n\n');
      if (splitIdx !== -1) {
        const quotePart = text.substring(2, splitIdx).trim();
        const bodyPart = text.substring(splitIdx + 2).trim();

        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{
              padding: '6px 10px',
              borderLeft: '3px solid var(--accent-primary)',
              backgroundColor: 'rgba(0, 0, 0, 0.2)',
              borderRadius: '0 6px 6px 0',
              fontSize: '12px',
              color: 'rgba(255, 255, 255, 0.85)',
              marginBottom: '2px'
            }}>
              {quotePart.replace(/^\*|\*$/g, '')}
            </div>
            <div>{renderFormattedMessageText(bodyPart)}</div>
          </div>
        );
      }
    }

    // Tokenize text for @mentions AND clickable URLs
    const tokenRegex = /(https?:\/\/[^\s]+)|@([a-zA-Z0-9À-ÿ_.-]+|\d{10,20})/g;
    const participantMap: { [key: string]: string } = {};
    groupParticipants.forEach(p => {
      if (p.lid) participantMap[p.lid] = p.name;
      if (p.phone) participantMap[p.phone] = p.name;
      if (p.id) participantMap[String(p.id).split('@')[0]] = p.name;
    });

    const parts: React.ReactNode[] = [];
    let lastIndex = 0;
    let match;
    let keyIdx = 0;

    while ((match = tokenRegex.exec(text)) !== null) {
      const matchStart = match.index;
      const matchEnd = tokenRegex.lastIndex;
      const urlMatch = match[1];
      const rawTag = match[2];

      if (matchStart > lastIndex) {
        parts.push(text.substring(lastIndex, matchStart));
      }

      if (urlMatch) {
        parts.push(
          <a
            key={`url-link-${keyIdx++}`}
            href={urlMatch}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: '#00e699',
              textDecoration: 'underline',
              wordBreak: 'break-all',
              fontWeight: '500',
              cursor: 'pointer',
              display: 'inline'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {urlMatch}
          </a>
        );
      } else if (rawTag) {
        const isAll = ['todos', 'everyone', 'all'].includes(rawTag.toLowerCase());
        const resolvedName = isAll ? 'todos' : (participantMap[rawTag] || rawTag);

        parts.push(
          <span
            key={`mention-${keyIdx++}`}
            style={{
              color: isAll ? '#00e699' : '#38bdf8',
              backgroundColor: isAll ? 'rgba(0, 230, 153, 0.18)' : 'rgba(56, 189, 248, 0.18)',
              padding: '1px 5px',
              borderRadius: '4px',
              fontWeight: '700',
              display: 'inline-flex',
              alignItems: 'center',
              margin: '0 2px'
            }}
            title={isAll ? 'Mencionou todos os membros' : `Mencionou @${resolvedName}`}
          >
            @{resolvedName}
          </span>
        );
      }

      lastIndex = matchEnd;
    }

    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
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

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current += 1;
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
      setIsDraggingOver(true);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer) {
      e.dataTransfer.dropEffect = 'copy';
    }
    if (!isDraggingOver) {
      setIsDraggingOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDraggingOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDraggingOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files);
      setPendingFiles(prev => [...prev, ...droppedFiles]);
    }
  };

  // Captura global na janela quando a conversa está aberta para evitar que o navegador abra o arquivo
  useEffect(() => {
    if (!conversation) return;

    const onGlobalDragOver = (e: DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'copy';
      }
    };

    const onGlobalDrop = (e: DragEvent) => {
      // Se soltar em qualquer parte da tela do chat
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        e.preventDefault();
        dragCounterRef.current = 0;
        setIsDraggingOver(false);
        const droppedFiles = Array.from(e.dataTransfer.files);
        setPendingFiles(prev => [...prev, ...droppedFiles]);
      }
    };

    window.addEventListener('dragover', onGlobalDragOver);
    window.addEventListener('drop', onGlobalDrop);

    return () => {
      window.removeEventListener('dragover', onGlobalDragOver);
      window.removeEventListener('drop', onGlobalDrop);
    };
  }, [conversation?.id]);

  const handlePaste = (e: React.ClipboardEvent<any>) => {
    const clipboardData = e.clipboardData;
    if (!clipboardData) return;

    const files: File[] = [];

    // Process clipboard items
    if (clipboardData.items && clipboardData.items.length > 0) {
      for (let i = 0; i < clipboardData.items.length; i++) {
        const item = clipboardData.items[i];
        if (item.kind === 'file' || item.type.startsWith('image/') || item.type.startsWith('video/') || item.type.startsWith('audio/')) {
          const file = item.getAsFile();
          if (file) {
            const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
            const fileName = file.name && file.name !== 'image.png' && file.name.includes('.') ? file.name : `imagem_${Date.now()}_${files.length + 1}.${ext}`;
            const renamedFile = new File([file], fileName, { type: file.type || 'image/png' });
            files.push(renamedFile);
          }
        }
      }
    } else if (clipboardData.files && clipboardData.files.length > 0) {
      for (let i = 0; i < clipboardData.files.length; i++) {
        files.push(clipboardData.files[i]);
      }
    }

    if (files.length > 0) {
      e.preventDefault();
      e.stopPropagation();
      setPendingFiles(prev => [...prev, ...files]);
    }
  };

  // Client-side image compression helper for ultra-fast mobile uploading
  const compressImageIfNeeded = async (file: File): Promise<File> => {
    if (!file.type.startsWith('image/') || file.type === 'image/gif' || file.type.includes('webp')) {
      return file;
    }
    if (file.size < 350 * 1024) return file; // Skip compression if already under 350KB

    return new Promise((resolve) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const canvas = document.createElement('canvas');
        let width = img.width;
        let height = img.height;
        const maxDim = 1920;
        if (width > maxDim || height > maxDim) {
          if (width > height) {
            height = Math.round((height * maxDim) / width);
            width = maxDim;
          } else {
            width = Math.round((width * maxDim) / height);
            height = maxDim;
          }
        }
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return resolve(file);
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob(
          (blob) => {
            if (!blob || blob.size >= file.size) return resolve(file);
            resolve(new File([blob], file.name, { type: 'image/jpeg', lastModified: Date.now() }));
          },
          'image/jpeg',
          0.82
        );
      };
      img.onerror = () => resolve(file);
      img.src = url;
    });
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
      let quoteSnippet = '';
      if (replyingToMessage.tipo === 'imagem') {
        const { caption } = extractMediaAndCaption(replyingToMessage.conteudo);
        quoteSnippet = caption ? `📷 Foto: ${caption}` : '📷 Foto';
      } else if (replyingToMessage.tipo === 'video') {
        const { caption } = extractMediaAndCaption(replyingToMessage.conteudo);
        quoteSnippet = caption ? `🎥 Vídeo: ${caption}` : '🎥 Vídeo';
      } else if (replyingToMessage.tipo === 'audio') {
        quoteSnippet = '🎵 Áudio';
      } else if (replyingToMessage.tipo === 'arquivo') {
        const { caption, mediaPath } = extractMediaAndCaption(replyingToMessage.conteudo);
        const fileName = mediaPath.split('/').pop() || 'Documento';
        quoteSnippet = `📄 ${caption || fileName}`;
      } else {
        quoteSnippet = (replyingToMessage.conteudo || '').trim();
      }
      if (quoteSnippet.length > 60) quoteSnippet = quoteSnippet.slice(0, 60) + '...';
      textToSend = `> *${quoteSender}:* ${quoteSnippet}\n\n` + textToSend;
      setReplyingToMessage(null);
    }

    setSendError(null);

    try {
      if (conversation?.id && onSaveDraft) {
        onSaveDraft(conversation.id, '');
      }

      if (pendingFiles.length > 0) {
        setIsSending(true);
        const filesToUpload = [...pendingFiles];
        const captionText = textToSend;

        // Clear UI immediately for instant feedback
        setPendingFiles([]);
        setInputText('');
        setInputLinkPreview(null);
        if (textareaRef.current) textareaRef.current.style.height = '42px';
        setIsUserScrolledUp(false);
        scrollToBottom('smooth');

        // Parallel compressed upload
        const uploadPromises = filesToUpload.map(async (file, idx) => {
          const compressed = await compressImageIfNeeded(file);
          const formData = new FormData();
          formData.append('file', compressed);
          if (idx === 0 && captionText) {
            formData.append('caption', captionText);
          }
          return apiUpload(`/conversations/${conversation?.id}/media`, formData);
        });

        const uploadedMsgs: any[] = await Promise.all(uploadPromises);

        // Atualizar imediatamente as mensagens na tela para feedback instantâneo ao atendente
        if (conversation && uploadedMsgs && uploadedMsgs.length > 0) {
          if (!conversation.messages) conversation.messages = [];
          uploadedMsgs.forEach((newMsg: any) => {
            if (newMsg && newMsg.id) {
              const exists = conversation.messages!.some(m => m.id === newMsg.id);
              if (!exists) {
                conversation.messages!.push({
                  ...newMsg,
                  status: newMsg.status || 'sent'
                });
              }
            }
          });
        }

        setIsSending(false);
        if (onStatusToggle) onStatusToggle();
        scrollToBottom('smooth');
        setTimeout(() => scrollToBottom('smooth'), 100);
      } else if (textToSend) {
        const textCopy = textToSend;
        setInputText('');
        setInputLinkPreview(null);
        if (textareaRef.current) textareaRef.current.style.height = '42px';
        setIsUserScrolledUp(false);
        scrollToBottom('smooth');
        setTimeout(() => scrollToBottom('smooth'), 50);
        setTimeout(() => scrollToBottom('smooth'), 200);
        await onSendMessage(textCopy);
        setIsUserScrolledUp(false);
        scrollToBottom('smooth');
        setTimeout(() => scrollToBottom('smooth'), 100);
      }
    } catch (err: any) {
      console.error('Send error:', err);
      setSendError(err.message || 'Falha ao enviar arquivo ou mensagem.');
      setIsSending(false);
    }
  };


  const handleCopyMessage = (msg: Message) => {
    const { caption, mediaPath } = extractMediaAndCaption(msg.conteudo);
    const text = caption || mediaPath || msg.conteudo || '';
    navigator.clipboard.writeText(text);
    setActiveActionMenuMsgId(null);
  };

  const handleDownloadMedia = (msg: Message) => {
    const { mediaPath } = extractMediaAndCaption(msg.conteudo);
    const url = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = mediaPath.split('/').pop() || 'arquivo';
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

  // WhatsApp Message Edit Handler (Imagem 3)
  const handleStartEdit = (msg: Message) => {
    let raw = msg.conteudo || '';
    if (raw.includes('|') && ['imagem', 'video', 'audio', 'arquivo'].includes(msg.tipo)) {
      raw = raw.split('|')[1] || raw;
    }
    setEditingMessage(msg);
    setEditingMessageText(raw);
    setActiveActionMenuMsgId(null);
  };

  const handleSaveEdit = async () => {
    if (!editingMessage || !editingMessageText.trim()) return;
    setIsSavingEdit(true);
    try {
      await apiFetch(`/conversations/messages/${editingMessage.id}`, {
        method: 'PUT',
        body: JSON.stringify({ new_text: editingMessageText.trim() })
      });

      // Update message in conversation state in real-time
      if (conversation?.messages) {
        const target = conversation.messages.find(m => m.id === editingMessage.id);
        if (target) {
          target.conteudo = editingMessageText.trim();
          target.status = 'edited';
        }
      }
      setEditingMessage(null);
      setEditingMessageText('');
    } catch (err) {
      console.error('Erro ao editar mensagem:', err);
      alert('Não foi possível salvar a edição no momento.');
    } finally {
      setIsSavingEdit(false);
    }
  };

  const handleCancelEdit = () => {
    setEditingMessage(null);
    setEditingMessageText('');
  };

  // WhatsApp Group Private Reply (Imagem 1)
  const handlePrivateReply = async (msg: Message, participantPhone?: string, participantName?: string) => {
    setActiveActionMenuMsgId(null);
    const phoneToUse = participantPhone || (msg as any).dados_adicionais?.participant_phone || (conversation?.contact?.telefone);
    const nameToUse = participantName || (msg as any).dados_adicionais?.participant_name || 'Participante';
    const cleanDigits = (phoneToUse || '').replace(/\D/g, '');

    let targetConv = allConversations?.find(c => {
      const p = (c.contact?.telefone || '').replace(/\D/g, '');
      const isNotGroup = !c.contact?.telefone?.startsWith('120363') && !c.contact?.telefone?.includes('@g.us');
      return isNotGroup && cleanDigits.length >= 8 && p.includes(cleanDigits.slice(-8));
    });

    if (!targetConv && onSelectConversation && phoneToUse) {
      try {
        targetConv = await apiFetch('/conversations/', {
          method: 'POST',
          body: JSON.stringify({
            whatsapp_number_id: conversation?.whatsapp_number_id,
            contact_phone: phoneToUse,
            contact_name: nameToUse
          })
        });
      } catch (err) {
        console.error('Erro ao abrir conversa particular:', err);
      }
    }

    if (targetConv && onSelectConversation) {
      onSelectConversation(targetConv);
      const quoteContent = msg.conteudo?.includes('|') ? (msg.conteudo.split('|')[1] || msg.conteudo) : msg.conteudo;
      setReplyingToMessage({
        ...msg,
        conteudo: `[No grupo ${conversation?.contact?.nome || 'Grupo'}]: "${quoteContent}"`
      });
    }
  };

  // WhatsApp Group Start Direct Chat (Imagem 1)
  const handleStartDirectChat = async (participantPhone?: string, participantName?: string) => {
    setActiveActionMenuMsgId(null);
    const phoneToUse = participantPhone || (msg as any)?.dados_adicionais?.participant_phone || (conversation?.contact?.telefone);
    const nameToUse = participantName || (msg as any)?.dados_adicionais?.participant_name || 'Participante';
    const cleanDigits = (phoneToUse || '').replace(/\D/g, '');

    let targetConv = allConversations?.find(c => {
      const p = (c.contact?.telefone || '').replace(/\D/g, '');
      const isNotGroup = !c.contact?.telefone?.startsWith('120363') && !c.contact?.telefone?.includes('@g.us');
      return isNotGroup && cleanDigits.length >= 8 && p.includes(cleanDigits.slice(-8));
    });

    if (!targetConv && onSelectConversation && phoneToUse) {
      try {
        targetConv = await apiFetch('/conversations/', {
          method: 'POST',
          body: JSON.stringify({
            whatsapp_number_id: conversation?.whatsapp_number_id,
            contact_phone: phoneToUse,
            contact_name: nameToUse
          })
        });
      } catch (err) {
        console.error('Erro ao criar conversa direta:', err);
      }
    }

    if (targetConv && onSelectConversation) {
      onSelectConversation(targetConv);
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

  const renderLocationCard = (rawLoc: string, extra?: any) => {
    const safeRawLoc = typeof rawLoc === 'string' ? rawLoc : String(rawLoc || '');

    // Extract coordinates:
    let lat = -15.820418;
    let lng = -47.956467;


    if (extra && extra.latitude && extra.longitude) {
      lat = parseFloat(extra.latitude);
      lng = parseFloat(extra.longitude);
    } else {
      const qMatch = safeRawLoc.match(/q=(-?\d+\.\d+),(-?\d+\.\d+)/i);
      if (qMatch) {
        lat = parseFloat(qMatch[1]);
        lng = parseFloat(qMatch[2]);
      } else {
        const coordMatch = safeRawLoc.match(/(-?\d+\.\d+)[\s,]+(-?\d+\.\d+)/);
        if (coordMatch) {
          lat = parseFloat(coordMatch[1]);
          lng = parseFloat(coordMatch[2]);
        }
      }
    }

    // Extract place name and address from raw text:
    let placeName = 'Servweld / Servsolda';
    let addressText = 'SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226';

    const lines = safeRawLoc.split('\n').map(l => l.trim()).filter(Boolean);
    const cleanLines = lines.filter(l =>
      !l.startsWith('http') &&
      !l.includes('LOCALIZAÇÃO') &&
      !l.includes('Localização GPS') &&
      !l.includes('WhatsApp Map')
    );

    if (cleanLines.length > 0) {
      placeName = cleanLines[0].replace(/\*/g, '');
      if (cleanLines.length > 1) {
        addressText = cleanLines.slice(1).join(' - ').replace(/\*/g, '');
      }
    }

    const googleMapsUrl = `https://maps.google.com/?q=${lat},${lng}`;
    const wazeUrl = `https://waze.com/ul?ll=${lat},${lng}&navigate=yes`;
    const mapBbox = `${lng - 0.004},${lat - 0.0022},${lng + 0.004},${lat + 0.0022}`;
    const mapIframeUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${mapBbox}&layer=mapnik&marker=${lat},${lng}`;

    return (
      <div style={{
        width: '320px',
        maxWidth: '100%',
        backgroundColor: '#0a1e17',
        border: '1px solid rgba(16, 185, 129, 0.45)',
        borderRadius: '12px',
        overflow: 'hidden',
        boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
        display: 'flex',
        flexDirection: 'column'
      }}>
        {/* Interactive Map Frame / Preview */}
        <div style={{ position: 'relative', width: '100%', height: '160px', backgroundColor: '#131d31', overflow: 'hidden' }}>
          <iframe
            title="Mapa de Localização"
            src={mapIframeUrl}
            style={{ width: '100%', height: '100%', border: 'none' }}
            loading="lazy"
          />
          <div style={{
            position: 'absolute',
            top: '8px',
            left: '8px',
            backgroundColor: 'rgba(10, 30, 23, 0.9)',
            backdropFilter: 'blur(6px)',
            padding: '4px 10px',
            borderRadius: '20px',
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            fontSize: '11px',
            fontWeight: '700',
            color: '#34d399',
            border: '1px solid rgba(16, 185, 129, 0.5)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
            pointerEvents: 'none'
          }}>
            <MapPin size={13} color="#10b981" />
            <span>Localização WhatsApp</span>
          </div>
        </div>

        {/* Place Details */}
        <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ fontSize: '13px', fontWeight: '800', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>{placeName}</span>
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', lineHeight: '1.4' }}>
            {addressText}
          </div>

          {/* GPS Action Buttons */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '6px' }}>
            <a
              href={googleMapsUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: '8px 10px',
                backgroundColor: '#059669',
                color: '#ffffff',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: '700',
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                boxShadow: '0 2px 6px rgba(5, 150, 105, 0.35)',
                transition: 'background-color 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = '#047857'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = '#059669'}
            >
              <MapPin size={13} />
              <span>Google Maps</span>
            </a>

            <a
              href={wazeUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: '8px 10px',
                backgroundColor: 'rgba(59, 130, 246, 0.2)',
                color: '#60a5fa',
                border: '1px solid rgba(59, 130, 246, 0.4)',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: '700',
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '5px',
                transition: 'all 0.15s'
              }}
              onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.3)'}
              onMouseLeave={e => e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.2)'}
            >
              <Navigation size={13} />
              <span>Waze GPS</span>
            </a>
          </div>
        </div>
      </div>
    );
  };

  const renderMediaContent = (msg: any) => {
    const raw = msg.conteudo || '';
    const { mediaPath, caption } = extractMediaAndCaption(raw);
    let fullUrl = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
    if ((mediaPath.includes('mmg.whatsapp.net') || mediaPath.includes('.enc') || (!mediaPath.startsWith('/uploads/') && !mediaPath.startsWith('http'))) && msg.id && msg.id > 0) {
      fullUrl = `/api/v1/conversations/messages/${msg.id}/media`;
    }
    const mediaIndex = conversationMedia.findIndex(item => item.id === msg.id);
    const isCustomer = msg.remetente === 'cliente' || msg.remetente === 'contact';

    let effectiveTipo = (msg.tipo || '').toLowerCase();
    if ((!effectiveTipo || effectiveTipo === 'texto' || effectiveTipo === 'text') && raw) {
      const c = raw.toLowerCase();
      if (c.includes('/uploads/') || c.startsWith('http')) {
        if (c.endsWith('.ogg') || c.endsWith('.webm') || c.endsWith('.mp3') || c.endsWith('.wav') || c.endsWith('.m4a') || c.includes('voice_note')) {
          effectiveTipo = 'audio';
        } else if (c.endsWith('.png') || c.endsWith('.jpg') || c.endsWith('.jpeg') || c.endsWith('.webp')) {
          effectiveTipo = 'imagem';
        } else if (c.endsWith('.mp4') || c.endsWith('.mov') || c.endsWith('.avi')) {
          effectiveTipo = 'video';
        } else if (c.endsWith('.pdf')) {
          effectiveTipo = 'arquivo';
        }
      }
    }

    switch (effectiveTipo) {
      case 'imagem':
      case 'sticker':
      case 'figurinha':
        const isSticker = fullUrl.toLowerCase().endsWith('.webp') || fullUrl.toLowerCase().includes('sticker') || msg.tipo === 'sticker' || msg.tipo === 'figurinha';
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxWidth: isSticker ? '170px' : '280px' }}>
            <div
              style={{
                position: 'relative',
                cursor: isSticker ? 'default' : 'pointer',
                borderRadius: isSticker ? '0' : '8px',
                overflow: 'hidden',
                maxWidth: isSticker ? '170px' : '280px',
                border: isSticker ? 'none' : '1px solid rgba(255,255,255,0.1)',
                backgroundColor: 'rgba(0,0,0,0.15)'
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
                  maxHeight: isSticker ? '150px' : '260px',
                  objectFit: isSticker ? 'contain' : 'cover',
                  display: 'block',
                  borderRadius: isSticker ? '0' : '8px'
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
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap', marginTop: '2px' }}>{caption}</p>}
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
          <div style={{ width: '100%', maxWidth: '280px', minWidth: 0, overflow: 'hidden', boxSizing: 'border-box' }}>
            <WhatsAppAudioPlayer
              message={msg}
              conversation={conversation || undefined}
              allMessages={conversation?.messages || []}
              isCustomer={isCustomer}
            />
          </div>
        );

      case 'arquivo':
        const rawFileName = mediaPath.split('/').pop() || 'Arquivo';
        const isPdf = fullUrl.toLowerCase().endsWith('.pdf') || fullUrl.toLowerCase().includes('.pdf') || rawFileName.toLowerCase().endsWith('.pdf');
        
        let displayFileName = caption && !caption.startsWith('http') ? caption : rawFileName;
        if (displayFileName.length > 32 && !displayFileName.includes(' ')) {
          displayFileName = displayFileName.substring(0, 24) + '...' + (isPdf ? '.pdf' : '');
        }

        if (isPdf) {
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxWidth: '340px' }}>
              <div
                style={{
                  borderRadius: '10px',
                  overflow: 'hidden',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  backgroundColor: 'rgba(0, 0, 0, 0.25)',
                  boxShadow: '0 4px 14px rgba(0, 0, 0, 0.3)',
                  cursor: 'pointer',
                  transition: 'transform 0.15s ease, border-color 0.15s ease'
                }}
                onClick={() => setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0)}
                onMouseEnter={e => {
                  e.currentTarget.style.transform = 'translateY(-2px)';
                  e.currentTarget.style.borderColor = 'var(--accent-primary)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.transform = 'translateY(0)';
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.15)';
                }}
              >
                {/* 1st Page Live Preview of PDF */}
                <div style={{ position: 'relative', width: '100%', height: '170px', backgroundColor: '#ffffff', overflow: 'hidden' }}>
                  <iframe
                    src={`${fullUrl}#page=1&view=FitH&toolbar=0&navpanes=0&scrollbar=0`}
                    title="Pré-visualização do PDF"
                    style={{
                      width: '100%',
                      height: '100%',
                      border: 'none',
                      pointerEvents: 'none',
                      display: 'block'
                    }}
                  />
                  {/* Hover Overlay Badge */}
                  <div style={{
                    position: 'absolute',
                    inset: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.04)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    <div style={{
                      position: 'absolute',
                      bottom: '8px',
                      right: '8px',
                      backgroundColor: 'rgba(0, 0, 0, 0.75)',
                      color: '#fff',
                      fontSize: '11px',
                      padding: '3px 8px',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      <Eye size={12} /> 1ª Página • Abrir
                    </div>
                  </div>
                </div>

                {/* Footer bar with file title and download button */}
                <div style={{
                  padding: '10px 14px',
                  backgroundColor: 'rgba(20, 20, 20, 0.95)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '10px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                    <span style={{
                      backgroundColor: '#ef4444',
                      color: '#fff',
                      fontSize: '10px',
                      fontWeight: 'bold',
                      padding: '2px 5px',
                      borderRadius: '4px',
                      letterSpacing: '0.5px'
                    }}>
                      PDF
                    </span>
                    <span style={{ fontSize: '13px', fontWeight: '600', color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {displayFileName}
                    </span>
                  </div>

                  <a
                    href={fullUrl}
                    download
                    onClick={e => e.stopPropagation()}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Baixar PDF"
                    style={{
                      color: 'var(--accent-primary)',
                      padding: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: '4px'
                    }}
                  >
                    <Download size={16} />
                  </a>
                </div>
              </div>
              {caption && caption !== displayFileName && (
                <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>
                  {caption}
                </p>
              )}
            </div>
          );
        }

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
                  {displayFileName}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Clique para ver detalhes
                </div>
              </div>
            </div>
            {caption && <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', opacity: 0.95, whiteSpace: 'pre-wrap' }}>{renderFormattedMessageText(caption)}</p>}
          </div>
        );

      case 'localizacao':
        return renderLocationCard(raw, msg.dados_adicionais);

      default:
        // WhatsApp Contact Card renderer
        if (typeof raw === 'string' && (raw.startsWith('[CONTATO]|') || raw.startsWith('[CONTATOS_MULTIPLOS]|') || raw.includes('BEGIN:VCARD') || raw === '[contactMessage]')) {
          let contactName = 'Contato Compartilhado';
          let contactPhone = '';
          let vcardData = '';

          if (raw.startsWith('[CONTATO]|')) {
            const parts = raw.split('|');
            contactName = parts[1] || 'Contato';
            contactPhone = parts[2] || '';
            vcardData = parts.slice(3).join('|') || '';
          } else if (raw.includes('BEGIN:VCARD')) {
            const fnM = raw.match(/FN:(.+)/);
            if (fnM) contactName = fnM[1].trim();
            const waidM = raw.match(/waid=(\d+)/);
            if (waidM) contactPhone = waidM[1].trim();
            else {
              const telM = raw.match(/TEL[^:]*:(.+)/);
              if (telM) contactPhone = telM[1].trim();
            }
            vcardData = raw;
          }

          const cleanDigits = contactPhone.replace(/\D/g, '');

          const handleDownloadVcard = () => {
            const vcfContent = vcardData || `BEGIN:VCARD\nVERSION:3.0\nFN:${contactName}\nTEL;type=CELL:${contactPhone}\nEND:VCARD`;
            const blob = new Blob([vcfContent], { type: 'text/vcard;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${contactName.replace(/\s+/g, '_')}.vcf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          };

          return (
            <div style={{
              width: '280px',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              borderRadius: '12px',
              overflow: 'hidden',
              boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
              display: 'flex',
              flexDirection: 'column'
            }}>
              {/* Header with Avatar & Details */}
              <div style={{
                padding: '14px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                borderBottom: '1px solid rgba(255, 255, 255, 0.08)'
              }}>
                <div style={{
                  width: '46px',
                  height: '46px',
                  borderRadius: '50%',
                  backgroundColor: 'rgba(16, 185, 129, 0.2)',
                  border: '1px solid #10b981',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: '#10b981',
                  fontWeight: '700',
                  fontSize: '18px',
                  flexShrink: 0
                }}>
                  {contactName.charAt(0).toUpperCase() || <UserIcon size={22} />}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '14px', fontWeight: '700', color: 'inherit', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {contactName}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Phone size={12} /> {contactPhone || 'Sem número'}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: cleanDigits ? '1fr 1fr' : '1fr',
                backgroundColor: 'rgba(0, 0, 0, 0.2)'
              }}>
                {cleanDigits && (
                  <a
                    href={`https://wa.me/${cleanDigits}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      padding: '10px 8px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      fontSize: '12px',
                      fontWeight: '600',
                      color: '#10b981',
                      textDecoration: 'none',
                      borderRight: '1px solid rgba(255, 255, 255, 0.08)',
                      transition: 'background 0.15s ease'
                    }}
                    onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.15)'}
                    onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <MessageSquare size={14} /> Conversar
                  </a>
                )}
                <button
                  type="button"
                  onClick={handleDownloadVcard}
                  style={{
                    padding: '10px 8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    fontSize: '12px',
                    fontWeight: '600',
                    color: 'var(--text-color)',
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    transition: 'background 0.15s ease'
                  }}
                  onMouseEnter={e => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.08)'}
                  onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
                >
                  <Download size={14} /> Salvar Contato
                </button>
              </div>
            </div>
          );
        }

        const rawText = typeof raw === 'string' ? raw : String(raw || '');
        const isLocationText = (
          rawText.includes('LOCALIZAÇÃO ENVIADA') ||
          rawText.startsWith('📍 *LOCALIZAÇÃO') ||
          rawText.includes('Localização GPS (WhatsApp Map)')
        );
        if (isLocationText) {
          return renderLocationCard(rawText, msg.dados_adicionais);
        }

        const firstUrlMatch = rawText.match(/https?:\/\/[^\s]+/i);
        const linkPreviewData = msg.dados_adicionais?.link_preview;

        return (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {(linkPreviewData || firstUrlMatch) && (
              <LinkPreviewCardComponent
                url={linkPreviewData?.url || (firstUrlMatch ? firstUrlMatch[0] : '')}
                initialData={linkPreviewData}
              />
            )}
            <p style={{ fontSize: '14px', lineHeight: '1.4', color: 'inherit', whiteSpace: 'pre-wrap', margin: 0 }}>
              {renderFormattedMessageText(rawText)}
            </p>
          </div>
        );
    }
  };
  const renderImageAlbum = (albumMessages: Message[]) => {
    const total = albumMessages.length;
    const displayCount = Math.min(total, 4);
    const displayed = albumMessages.slice(0, displayCount);
    const extraCount = total - 4;

    // Find caption if any
    let captionText = '';
    for (const m of albumMessages) {
      const { caption } = extractMediaAndCaption(m.conteudo);
      if (caption) {
        captionText = caption;
        break;
      }
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: total === 2 ? 'repeat(2, 1fr)' : 'repeat(2, 1fr)',
          gap: '4px',
          borderRadius: '8px',
          overflow: 'hidden',
          maxWidth: '320px'
        }}>
          {displayed.map((m, idx) => {
            const { mediaPath } = extractMediaAndCaption(m.conteudo);
            let fullUrl = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
            if ((mediaPath.includes('mmg.whatsapp.net') || mediaPath.includes('.enc') || (!mediaPath.startsWith('/uploads/') && !mediaPath.startsWith('http'))) && m.id && m.id > 0) {
              fullUrl = `/api/v1/conversations/messages/${m.id}/media`;
            }
            const mediaIndex = conversationMedia.findIndex(item => item.id === m.id);
            const isLastOfFour = idx === 3 && extraCount > 0;

            return (
              <div
                key={m.id || idx}
                style={{
                  position: 'relative',
                  width: total === 3 && idx === 0 ? '100%' : '140px',
                  height: total === 3 && idx === 0 ? '180px' : '140px',
                  gridColumn: total === 3 && idx === 0 ? 'span 2' : 'auto',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  backgroundColor: 'rgba(0,0,0,0.3)',
                  borderRadius: '4px'
                }}
                onClick={() => {
                  setPreviewMediaIndex(mediaIndex >= 0 ? mediaIndex : 0);
                }}
              >
                <img
                  src={fullUrl}
                  alt={`Imagem ${idx + 1}`}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    display: 'block',
                    transition: 'transform 0.2s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.05)')}
                  onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                />

                {isLastOfFour && (
                  <div style={{
                    position: 'absolute',
                    top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: 'rgba(0, 0, 0, 0.75)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#ffffff',
                    fontSize: '22px',
                    fontWeight: '800',
                    letterSpacing: '1px'
                  }}>
                    +{extraCount}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {captionText && (
          <p style={{ fontSize: '13px', lineHeight: '1.4', color: 'inherit', margin: '4px 0 0 0', whiteSpace: 'pre-wrap' }}>
            {captionText}
          </p>
        )}
      </div>
    );
  };

  const formatTime = (ts: string | Date | undefined) => {
    if (!ts) return '';
    const d = normalizeIsoDate(ts);
    return isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const currentMedia = previewMediaIndex !== null ? conversationMedia[previewMediaIndex] : null;

  return (
    <div
      onDragEnter={handleDragEnter}
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
          backgroundColor: 'rgba(5, 26, 18, 0.88)',
          border: '3px dashed var(--accent-primary)',
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '16px',
          color: 'var(--accent-primary)',
          pointerEvents: 'none',
          backdropFilter: 'blur(2px)',
          transition: 'all 0.15s ease'
        }}>
          <UploadCloud size={64} className="animate-bounce" style={{ pointerEvents: 'none' }} />
          <h3 style={{ fontSize: '20px', fontWeight: '700', pointerEvents: 'none' }}>Solte seus arquivos aqui para anexar</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', pointerEvents: 'none' }}>PDFs, imagens, vídeos, áudios e documentos</p>
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
            color: '#fff',
            zIndex: 10
          }}>
            <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ textTransform: 'capitalize', color: 'var(--accent-primary)', fontWeight: 'bold' }}>
                {currentMedia.tipo}
              </span>
              <span>•</span>
              <span>Mídia {previewMediaIndex + 1} de {conversationMedia.length}</span>
            </div>

            {/* Floating Zoom & Action Toolbar for Images */}
            {currentMedia.tipo === 'imagem' && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                backgroundColor: 'rgba(20, 20, 20, 0.85)',
                padding: '6px 14px',
                borderRadius: '30px',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                boxShadow: '0 4px 20px rgba(0,0,0,0.5)'
              }}>
                <button
                  type="button"
                  onClick={handleZoomOut}
                  disabled={zoomScale <= 1}
                  title="Diminuir Zoom (-)"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: zoomScale <= 1 ? 'rgba(255,255,255,0.3)' : '#fff',
                    cursor: zoomScale <= 1 ? 'not-allowed' : 'pointer',
                    padding: '6px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'all 0.15s'
                  }}
                >
                  <ZoomOut size={18} />
                </button>

                <button
                  type="button"
                  onClick={handleResetZoom}
                  title="Redefinir Zoom (100% ou Tecla 0)"
                  style={{
                    background: 'rgba(255, 255, 255, 0.1)',
                    border: 'none',
                    color: '#fff',
                    cursor: 'pointer',
                    padding: '4px 10px',
                    borderRadius: '12px',
                    fontSize: '12px',
                    fontWeight: 'bold',
                    minWidth: '52px',
                    textAlign: 'center'
                  }}
                >
                  {Math.round(zoomScale * 100)}%
                </button>

                <button
                  type="button"
                  onClick={handleZoomIn}
                  disabled={zoomScale >= 5}
                  title="Aumentar Zoom (+)"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: zoomScale >= 5 ? 'rgba(255,255,255,0.3)' : '#fff',
                    cursor: zoomScale >= 5 ? 'not-allowed' : 'pointer',
                    padding: '6px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'all 0.15s'
                  }}
                >
                  <ZoomIn size={18} />
                </button>

                <div style={{ width: '1px', height: '18px', backgroundColor: 'rgba(255,255,255,0.2)', margin: '0 4px' }} />

                <button
                  type="button"
                  onClick={handleRotateImage}
                  title="Girar Imagem 90°"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#fff',
                    cursor: 'pointer',
                    padding: '6px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}
                >
                  <RotateCw size={18} />
                </button>

                <a
                  href={currentMedia.url}
                  download
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Baixar Imagem"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#fff',
                    cursor: 'pointer',
                    padding: '6px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    textDecoration: 'none'
                  }}
                >
                  <Download size={18} />
                </a>

                <a
                  href={currentMedia.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Abrir em Nova Aba"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#fff',
                    cursor: 'pointer',
                    padding: '6px',
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    textDecoration: 'none'
                  }}
                >
                  <ExternalLink size={18} />
                </a>
              </div>
            )}

            <button
              onClick={() => setPreviewMediaIndex(null)}
              style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: '8px' }}
              title="Fechar (Esc)"
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
                  zIndex: 10,
                  transition: 'background 0.2s'
                }}
              >
                <ChevronLeft size={32} />
              </button>
            ) : <div style={{ width: '48px' }} />}

            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '75vh',
                width: '85vw',
                overflow: 'hidden',
                position: 'relative'
              }}
              onWheel={(e) => {
                if (currentMedia.tipo === 'imagem') {
                  e.preventDefault();
                  if (e.deltaY < 0) {
                    setZoomScale(prev => Math.min(Number((prev + 0.25).toFixed(2)), 5));
                  } else {
                    setZoomScale(prev => {
                      const next = Math.max(Number((prev - 0.25).toFixed(2)), 1);
                      if (next === 1) setPanPosition({ x: 0, y: 0 });
                      return next;
                    });
                  }
                }
              }}
            >
              {currentMedia.tipo === 'imagem' && (
                <div
                  style={{
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    overflow: 'hidden',
                    cursor: zoomScale > 1 ? (isDraggingImage ? 'grabbing' : 'grab') : 'zoom-in'
                  }}
                  onMouseDown={(e) => {
                    if (zoomScale > 1) {
                      e.preventDefault();
                      setIsDraggingImage(true);
                      setDragStart({ x: e.clientX - panPosition.x, y: e.clientY - panPosition.y });
                    }
                  }}
                  onMouseMove={(e) => {
                    if (isDraggingImage && zoomScale > 1) {
                      setPanPosition({
                        x: e.clientX - dragStart.x,
                        y: e.clientY - dragStart.y
                      });
                    }
                  }}
                  onMouseUp={() => setIsDraggingImage(false)}
                  onMouseLeave={() => setIsDraggingImage(false)}
                  onDoubleClick={() => {
                    if (zoomScale > 1) {
                      handleResetZoom();
                    } else {
                      setZoomScale(2.5);
                    }
                  }}
                >
                  <img
                    src={currentMedia.url}
                    alt="Imagem"
                    draggable={false}
                    style={{
                      maxHeight: '72vh',
                      maxWidth: '85vw',
                      objectFit: 'contain',
                      borderRadius: '8px',
                      boxShadow: '0 8px 30px rgba(0,0,0,0.8)',
                      transform: `translate(${panPosition.x}px, ${panPosition.y}px) scale(${zoomScale}) rotate(${imageRotation}deg)`,
                      transformOrigin: 'center center',
                      transition: isDraggingImage ? 'none' : 'transform 0.15s cubic-bezier(0.2, 0, 0.2, 1)',
                      userSelect: 'none'
                    }}
                  />
                </div>
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
        padding: '8px 16px',
        minHeight: '64px',
        height: 'auto',
        width: '100%',
        boxSizing: 'border-box',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '10px',
        position: 'relative',
        zIndex: 100,
        overflow: 'visible',
        flexWrap: 'wrap',
        flexShrink: 0
      }}>
        {/* Left Section: Avatar & Customer Metadata */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0, minWidth: 0, maxWidth: '100%' }}>
          {onToggleChatList && isChatListCollapsed && (
            <button
              onClick={onToggleChatList}
              className="btn-secondary"
              style={{
                height: '32px',
                padding: '0 8px',
                fontSize: '11px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}
              title="Expandir/Mostrar lista de conversas"
            >
              <PanelLeftOpen size={14} /> <span className="hide-on-mobile">Conversas</span>
            </button>
          )}

          {onBack && (
            <button
              onClick={() => {
                const closed = closeTopmostSublayer();
                if (!closed && onBack) {
                  onBack();
                }
              }}
              title="Voltar"
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
              onError={(e) => {
                e.currentTarget.style.display = 'none';
              }}
              onClick={() => setShowAvatarZoom(true)}
              title="Clique para expandir a foto de perfil"
              style={{ width: '38px', height: '38px', borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--accent-primary)', flexShrink: 0, cursor: 'pointer', transition: 'transform 0.15s ease' }}
              onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
              onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
            />
          ) : (
            <div
              onClick={() => setShowAvatarZoom(true)}
              title="Clique para expandir a foto de perfil"
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
                color: '#051a12',
                fontWeight: '700',
                fontSize: '16px',
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

          <div style={{ minWidth: 0 }}>
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
                  <h3 style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-main)', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {getCleanDisplayName(conversation.contact?.nome, conversation.contact?.telefone)}
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
                    <Pencil size={12} />
                  </button>
                </>
              )}
            </div>

            {isGroupChat ? (
              <div
                onClick={() => setShowParticipantsModal(true)}
                title="Clique para ver todos os integrantes do grupo"
                style={{
                  display: 'flex',
                  gap: '6px',
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                  marginTop: '2px',
                  alignItems: 'center',
                  cursor: 'pointer',
                  maxWidth: '320px',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis'
                }}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', color: 'var(--accent-primary)', fontWeight: '700' }}>
                  <Users size={12} /> {groupParticipants.length > 0 ? `${groupParticipants.length} participantes` : 'Grupo'}
                </span>
                {groupParticipants.length > 0 && (
                  <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    : {groupParticipants.slice(0, 3).map(p => p.name).join(', ')}{groupParticipants.length > 3 ? ` e +${groupParticipants.length - 3}` : ''}
                  </span>
                )}
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '8px', fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}><Phone size={11} /> {formatWhatsAppPhone(conversation.contact?.telefone)}</span>
                {conversation.assigned_user_name && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', color: '#60a5fa', fontWeight: '600' }}>
                    <UserCheck size={11} /> Atendente: {conversation.assigned_user_name}
                  </span>
                )}
                {(() => {
                  const activeP = userPresences ? userPresences[conversation.id] : null;
                  const isActive = activeP && activeP.expiresAt > Date.now();
                  if (!isActive) return null;
                  return (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#00a884', fontWeight: '700' }} className="animate-pulse">
                      {activeP.status === 'recording' ? '🎙️ gravando áudio...' :
                       activeP.status === 'ai_composing' ? '🤖 IA digitando...' :
                       activeP.status === 'ai_recording' ? '🤖 IA gravando áudio...' :
                       activeP.status.startsWith('attendant_') ? `👤 ${activeP.agentName || 'Atendente'} digitando...` :
                       'digitando...'}
                    </span>
                  );
                })()}
              </div>
            )}
          </div>
        </div>

        {/* Right Section: Action Buttons Toolbar (Fully responsive, wrapped, and complete) */}
        <div style={{
          display: 'flex',
          gap: '5px',
          alignItems: 'center',
          flexShrink: 0,
          padding: '2px 0',
          justifyContent: 'flex-end',
          flexWrap: 'wrap'
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
                <span>📁 #{conversation.id}</span>
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
              className="btn-secondary"
              style={{
                height: '32px',
                padding: '0 9px',
                borderRadius: 'var(--radius-md)',
                fontSize: '11px',
                fontWeight: '600',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap'
              }}
              title="Finalizar este atendimento e registrar marco do protocolo"
            >
              <Lock size={12} /> <span>Fechar Protocolo</span>
            </button>
          ) : (
            <button
              onClick={handleOpenProtocol}
              disabled={isOperatingProtocol}
              style={{
                height: '32px',
                padding: '0 9px',
                borderRadius: 'var(--radius-md)',
                fontSize: '11px',
                fontWeight: '800',
                border: '1px solid var(--accent-primary)',
                backgroundColor: 'rgba(0, 230, 153, 0.22)',
                color: 'var(--accent-primary)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap',
                boxShadow: '0 0 12px rgba(0, 230, 153, 0.3)'
              }}
              title="Iniciar protocolo formal para este atendimento (associa mensagens retroativas)"
            >
              <FileText size={12} /> <span>Abrir Protocolo</span>
            </button>
          )}

          {/* Transfer Conversation Button (Always Visible in Header) */}
          <button
            onClick={onOpenTransferModal}
            className="btn-secondary"
            style={{
              height: '32px',
              padding: '0 9px',
              fontSize: '11px',
              fontWeight: '700',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              color: '#93c5fd',
              border: '1px solid rgba(59, 130, 246, 0.45)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              cursor: 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap',
              boxShadow: '0 0 8px rgba(59, 130, 246, 0.2)'
            }}
            title="Transferir chamado para outro setor ou atendente humano"
          >
            <ArrowRightLeft size={12} />
            <span>Transferir</span>
          </button>

          {/* Pin / Fix Conversation Button (Particular do Atendente) */}
          {(() => {
            const isPinned = isConvPinned(conversation);
            return (
              <button
                onClick={handleTogglePin}
                disabled={isTogglingPin}
                className="btn-secondary"
                style={{
                  height: '32px',
                  padding: '0 8px',
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
                <span>{isPinned ? 'Fixado' : 'Fixar'}</span>
              </button>
            );
          })()}

          <button
            onClick={handleMarkAsRead}
            disabled={isMarkingRead}
            className="btn-secondary"
            style={{
              height: '32px',
              padding: '0 8px',
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
            title="Marcar todas as mensagens deste cliente como lidas"
          >
            <CheckCheck size={12} /> <span>{isMarkingRead ? '...' : 'Lido'}</span>
          </button>

          <button
            onClick={handleToggleStatus}
            disabled={isTogglingStatus}
            style={{
              height: '32px',
              padding: '0 8px',
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
            {conversation.status === 'com_ia' ? <><Bot size={12} /> <span>COM IA</span></> : <><Headphones size={12} /> <span>HUMANO</span></>}
          </button>

          {conversation.status === 'com_ia' && (
            <button
              onClick={handleAssumeControl}
              disabled={isAssumingControl}
              style={{
                height: '32px',
                padding: '0 9px',
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
              <Zap size={12} className={isAssumingControl ? "animate-spin" : ""} />
              <span>{isAssumingControl ? '...' : 'Assumir'}</span>
            </button>
          )}

          <button
            onClick={handleStartVideoCall}
            className="btn-secondary"
            style={{
              height: '32px',
              padding: '0 8px',
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
            <Video size={12} /> <span>Vídeo/Voz</span>
          </button>

          {onOpenMediaGallery && (
            <button
              onClick={onOpenMediaGallery}
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
                gap: '4px',
                cursor: 'pointer',
                flexShrink: 0,
                whiteSpace: 'nowrap'
              }}
            >
              <Paperclip size={12} /> <span>Mídia ({conversationMedia.length})</span>
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
                padding: '0 7px',
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

                  <button
                    onClick={() => {
                      setShowReportAIModal(true);
                      setShowMoreMenu(false);
                    }}
                    style={{
                      padding: '8px 12px',
                      background: 'none',
                      border: 'none',
                      color: '#f87171',
                      fontSize: '12px',
                      textAlign: 'left',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      borderTop: '1px solid rgba(255,255,255,0.05)'
                    }}
                  >
                    <AlertTriangle size={14} /> Reportar Erro da IA
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
            }}
          >
            <X size={15} />
          </button>
        </div>
      )}

      <StickyAudioPlayer />

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

        {processedMessageGroups.map((group, groupIdx, groupArr) => {
          const msg = group.type === 'single' ? group.message : group.messages[0];
          const lastMsg = group.type === 'single' ? group.message : group.messages[group.messages.length - 1];
          const idx = group.type === 'single' ? group.originalIndex : group.originalIndices[0];
          const prevGroup = groupIdx > 0 ? groupArr[groupIdx - 1] : null;
          const prevMsg = prevGroup ? (prevGroup.type === 'single' ? prevGroup.message : prevGroup.messages[0]) : null;

          const showDateDivider = !prevMsg || (msg.timestamp && prevMsg.timestamp && getMessageDateKey(msg.timestamp) !== getMessageDateKey(prevMsg.timestamp));
          const dateLabel = showDateDivider && msg.timestamp ? formatDateDivider(msg.timestamp) : null;

          const isCustomer = msg.remetente === 'cliente';
          const isAI = msg.remetente === 'ia';
          const isSystem = msg.remetente === 'sistema';
          const msgKey = group.type === 'single' 
            ? (msg.id ? `msg_${msg.id}_${idx}` : `msg_${idx}`)
            : `album_${group.messages.map(m => m.id || 0).join('_')}_${idx}`;

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
                    <div data-msg-time={msg.timestamp} style={{
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
                    <div data-msg-time={msg.timestamp} style={{
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
                  <div data-msg-time={msg.timestamp} style={{
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

                const participantName = (msg as any).dados_adicionais?.participant_name || 
                                        (msg as any).dados_adicionais?.push_name || 
                                        (isGroupChat ? ((msg as any).dados_adicionais?.participant_phone ? `+${(msg as any).dados_adicionais.participant_phone}` : (conversation?.contact?.nome || 'Participante')) : (conversation?.contact?.nome || 'Cliente'));

                const participantPhone = (msg as any).dados_adicionais?.participant_phone || 
                                         ((msg as any).dados_adicionais?.participant ? (msg as any).dados_adicionais.participant.split('@')[0] : (isCustomer ? conversation?.contact?.telefone : ''));

                return (
            <div
              key={msgKey}
              data-msg-time={msg.timestamp}
              className="msg-row-container"
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
                  <span style={{ fontWeight: '700', color: isAI ? 'var(--status-ia)' : isCustomer ? (isGroupChat ? '#38bdf8' : 'var(--text-muted)') : 'var(--accent-primary)' }}>
                    {isCustomer ? (isGroupChat ? (participantName || 'Participante') : (conversation.contact?.nome || 'Cliente')) : isAI ? '🤖 IA Concierge' : '👤 Atendente'}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span>{formatTime(lastMsg.timestamp)}</span>
                    {!isCustomer && (
                      lastMsg.status === 'sending' || lastMsg.status === 'pending' ? (
                        <Clock size={12} style={{ color: 'var(--text-muted)' }} title="Enviando..." />
                      ) : lastMsg.status === 'failed' ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRetryMessage(lastMsg.id);
                          }}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0 2px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px',
                            color: '#ef4444'
                          }}
                          title="Falha no envio. Clique para reenviar a mensagem!"
                        >
                          <AlertCircle size={13} style={{ color: '#ef4444' }} />
                          <span style={{ fontSize: '10px', fontWeight: 'bold', color: '#ef4444', textDecoration: 'underline' }}>Reenviar</span>
                        </button>
                      ) : lastMsg.status === 'sent' ? (
                        <Check size={14} style={{ color: 'var(--text-muted)' }} title="Enviada ao servidor" />
                      ) : lastMsg.status === 'delivered' ? (
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

                {group.type === 'image_album' ? renderImageAlbum(group.messages) : renderMediaContent(msg)}

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

                      {/* 0. Reenviar Mensagem (se falhou no envio) */}
                      {msg.status === 'failed' && (
                        <button
                          type="button"
                          onClick={() => handleRetryMessage(msg.id)}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            padding: '8px 12px',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            color: '#ef4444',
                            fontSize: '13px',
                            fontWeight: '600',
                            textAlign: 'left',
                            cursor: 'pointer',
                            borderRadius: 'var(--radius-sm)',
                            marginBottom: '4px'
                          }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.25)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.15)')}
                        >
                          <RotateCw size={15} style={{ color: '#ef4444' }} />
                          <span>Reenviar mensagem</span>
                        </button>
                      )}


                      {/* Menu Actions (Idêntico ao WhatsApp Web) */}

                      {/* 1. Responder (Imagem 1, 2, 3) */}
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

                      {/* 2. Responder em particular (Imagem 1 - apenas em Grupos para mensagens do participante) */}
                      {isGroupChat && isCustomer && (
                        <button
                          type="button"
                          onClick={() => handlePrivateReply(msg, participantPhone, participantName)}
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
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.15)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <UserCheck size={15} style={{ color: '#38bdf8' }} />
                          <span>Responder em particular</span>
                        </button>
                      )}

                      {/* 3. Conversar com [Nome do Participante] (Imagem 1 - apenas em Grupos para mensagens do participante) */}
                      {isGroupChat && isCustomer && (
                        <button
                          type="button"
                          onClick={() => handleStartDirectChat(participantPhone, participantName)}
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
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(168, 85, 247, 0.15)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <MessageSquare size={15} style={{ color: '#c084fc' }} />
                          <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '180px' }}>
                            Conversar com {participantName}
                          </span>
                        </button>
                      )}

                      {/* 4. Copiar Texto (Imagem 1, 2, 3) */}
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
                        <span>Copiar</span>
                      </button>

                      {/* 5. Editar Mensagem (Imagem 3 - para mensagens enviadas pelo atendente/sistema) */}
                      {!isCustomer && (
                        <button
                          type="button"
                          onClick={() => handleStartEdit(msg)}
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
                          <Pencil size={15} style={{ color: '#f59e0b' }} />
                          <span>Editar</span>
                        </button>
                      )}

                      {/* 6. Encaminhar / Compartilhar */}
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
                        <span>Encaminhar</span>
                      </button>

                      {/* 7. Agendar no Calendário / Criar Tarefa */}
                      {onOpenScheduleTask && (
                        <button
                          type="button"
                          onClick={() => {
                            setActiveActionMenuMsgId(null);
                            const customerName = conversation?.contact?.nome || 'Cliente';
                            const rawMsg = msg.conteudo || '';
                            const cleanText = rawMsg.replace(/^https?:\/\/\S+/i, '').replace(/\|.*/, '').trim();
                            const summaryText = cleanText
                              ? (cleanText.length > 40 ? cleanText.substring(0, 40) + '...' : cleanText)
                              : `Mensagem ${msg.tipo}`;

                            onOpenScheduleTask({
                              title: `Atendimento ${customerName} - ${summaryText}`,
                              description: `💬 Mensagem do WhatsApp:\n"${rawMsg}"\n\n👤 Cliente: ${customerName}\n📞 Telefone: ${conversation?.contact?.telefone || ''}\n📋 Protocolo: ${conversation?.protocol_number || 'Sem protocolo'}`,
                              contact_id: conversation?.contact_id || conversation?.contact?.id,
                              conversation_id: conversation?.id,
                              message_id: msg.id,
                              contact_name: customerName,
                              contact_phone: conversation?.contact?.telefone,
                              start_time: new Date().toISOString(),
                              color: '#10b981',
                              priority: 'media',
                              status: 'pendente'
                            });
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
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(16, 185, 129, 0.15)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                        >
                          <Calendar size={15} style={{ color: 'var(--accent-primary)' }} />
                          <span>Agendar no Calendário</span>
                        </button>
                      )}

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
                            const url = parts[0].startsWith('http') ? parts[0] : `${parts[0]}`;
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

                      {/* 7. Dados da mensagem */}
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



      {pendingFiles.length > 0 && (
        <div style={{
          padding: '12px 20px',
          backgroundColor: 'rgba(15, 23, 42, 0.95)',
          borderTop: '1px solid rgba(0, 230, 153, 0.3)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          boxShadow: '0 -6px 20px rgba(0, 0, 0, 0.35)',
          zIndex: 90
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <ImageIcon size={14} />
              <span>{pendingFiles.length === 1 ? '1 mídia pronta para envio' : `${pendingFiles.length} mídias prontas para envio em lote`}</span>
            </span>
            <button
              type="button"
              onClick={() => setPendingFiles([])}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '11px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#ef4444')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
            >
              <X size={12} /> Cancelar todas
            </button>
          </div>

          <div style={{ display: 'flex', gap: '10px', overflowX: 'auto', alignItems: 'center', paddingBottom: '4px' }}>
            {pendingFiles.map((file, idx) => {
              const isImg = file.type.startsWith('image/');
              const isVid = file.type.startsWith('video/');
              const isAud = file.type.startsWith('audio/');
              const previewUrl = isImg ? URL.createObjectURL(file) : null;

              return (
                <div
                  key={idx}
                  style={{
                    position: 'relative',
                    width: '80px',
                    height: '80px',
                    borderRadius: '10px',
                    overflow: 'hidden',
                    border: '2px solid rgba(0, 230, 153, 0.4)',
                    backgroundColor: '#1e293b',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
                    transition: 'transform 0.15s ease'
                  }}
                >
                  {isImg && previewUrl ? (
                    <img
                      src={previewUrl}
                      alt="Prévia da imagem"
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', padding: '6px', textAlign: 'center' }}>
                      {isVid ? <Video size={24} color="#60a5fa" /> : isAud ? <Music size={24} color="#c084fc" /> : <FileText size={24} color="#34d399" />}
                      <span style={{ fontSize: '9px', maxWidth: '68px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>
                        {file.name}
                      </span>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => removePendingFile(idx)}
                    title="Remover este anexo"
                    style={{
                      position: 'absolute',
                      top: '3px',
                      right: '3px',
                      background: 'rgba(0, 0, 0, 0.75)',
                      border: '1px solid rgba(255, 255, 255, 0.3)',
                      borderRadius: '50%',
                      width: '20px',
                      height: '20px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#f87171',
                      cursor: 'pointer',
                      boxShadow: '0 2px 4px rgba(0,0,0,0.5)'
                    }}
                  >
                    <X size={11} />
                  </button>

                  <span style={{
                    position: 'absolute',
                    bottom: '2px',
                    left: '2px',
                    backgroundColor: 'rgba(0,0,0,0.6)',
                    color: '#fff',
                    fontSize: '9px',
                    padding: '1px 4px',
                    borderRadius: '4px',
                    fontWeight: '700'
                  }}>
                    #{idx + 1}
                  </span>
                </div>
              );
            })}

            {/* Add More Media Button */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              title="Adicionar mais imagens ou arquivos ao lote"
              style={{
                width: '80px',
                height: '80px',
                borderRadius: '10px',
                border: '2px dashed rgba(255, 255, 255, 0.25)',
                backgroundColor: 'rgba(255, 255, 255, 0.03)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                flexShrink: 0,
                transition: 'all 0.15s ease'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent-primary)';
                e.currentTarget.style.color = 'var(--accent-primary)';
                e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.05)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.25)';
                e.currentTarget.style.color = 'var(--text-muted)';
                e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
              }}
            >
              <Plus size={20} />
              <span style={{ fontSize: '10px', fontWeight: '600' }}>Adicionar</span>
            </button>
          </div>
        </div>
      )}

      {/* WhatsApp-Style Attachment & Quick Actions Popover / BottomSheet Menu */}
      {showAttachmentMenu && (
        <>
          <div className="chat-attachment-backdrop" onClick={() => setShowAttachmentMenu(false)} />
          <div
            className="chat-attachment-menu animate-fade-in"
            style={{
              position: 'absolute',
              bottom: '80px',
              left: '24px',
              zIndex: 10000,
              backgroundColor: 'var(--bg-secondary)',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-lg)',
              padding: '18px',
              boxShadow: '0 12px 36px rgba(0, 0, 0, 0.7)',
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '14px',
              width: '340px'
            }}
          >
            {/* 1. Galeria / Mídia (Opens Native Media Picker directly) */}
            <div
              onClick={() => {
                setShowAttachmentMenu(false);
                mediaInputRef.current?.click();
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 8px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(59, 130, 246, 0.12)',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#3b82f6', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(59, 130, 246, 0.4)' }}>
                <ImageIcon size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Galeria / Mídia</span>
            </div>

            {/* 2. Câmera (Opens Camera directly on mobile) */}
            <div
              onClick={() => {
                setShowAttachmentMenu(false);
                cameraInputRef.current?.click();
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 8px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(236, 72, 153, 0.12)',
                border: '1px solid rgba(236, 72, 153, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#ec4899', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(236, 72, 153, 0.4)' }}>
                <Camera size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Câmera</span>
            </div>

            {/* 3. Documento (Opens File Manager for PDF/DOC/etc) */}
            <div
              onClick={() => {
                setShowAttachmentMenu(false);
                documentInputRef.current?.click();
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 8px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'rgba(168, 85, 247, 0.12)',
                border: '1px solid rgba(168, 85, 247, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#a855f7', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(168, 85, 247, 0.4)' }}>
                <FileText size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Documento</span>
            </div>

            {/* 4. Localização */}
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
                backgroundColor: 'rgba(0, 230, 153, 0.12)',
                border: '1px solid rgba(0, 230, 153, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#00e699', color: '#0b0f19', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(0, 230, 153, 0.3)' }}>
                <MapPin size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Localização</span>
            </div>

            {/* 5. Dados Pix */}
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
                backgroundColor: 'rgba(234, 179, 8, 0.12)',
                border: '1px solid rgba(234, 179, 8, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#eab308', color: '#0b0f19', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(234, 179, 8, 0.3)' }}>
                <QrCode size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Dados Pix</span>
            </div>

            {/* 6. Contato */}
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
                backgroundColor: 'rgba(14, 165, 233, 0.12)',
                border: '1px solid rgba(14, 165, 233, 0.3)',
                cursor: 'pointer'
              }}
            >
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: '#0ea5e9', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(14, 165, 233, 0.3)' }}>
                <Share2 size={22} />
              </div>
              <span style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-main)' }}>Contato</span>
            </div>
          </div>
        </>
      )}

      {/* Hidden File Input Pickers for Native OS Integration */}
      <input type="file" ref={fileInputRef} onChange={handleFileSelect} multiple style={{ display: 'none' }} />
      <input type="file" ref={mediaInputRef} accept="image/*,video/*" onChange={handleFileSelect} multiple style={{ display: 'none' }} />
      <input type="file" ref={cameraInputRef} accept="image/*" capture="environment" onChange={handleFileSelect} style={{ display: 'none' }} />
      <input type="file" ref={documentInputRef} accept="*/*,.pdf,.doc,.docx,.xls,.xlsx,.zip,.txt,application/pdf" onChange={handleFileSelect} multiple style={{ display: 'none' }} />


      {/* WhatsApp-Style Quoted Reply Preview Bar */}
      {replyingToMessage && (() => {
        const { mediaPath, caption } = extractMediaAndCaption(replyingToMessage.conteudo);
        let fullUrl = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
        if ((mediaPath.includes('mmg.whatsapp.net') || mediaPath.includes('.enc') || (!mediaPath.startsWith('/uploads/') && !mediaPath.startsWith('http'))) && replyingToMessage.id && replyingToMessage.id > 0) {
          fullUrl = `/api/v1/conversations/messages/${replyingToMessage.id}/media`;
        }

        const isImg = replyingToMessage.tipo === 'imagem';
        const isVid = replyingToMessage.tipo === 'video';
        const isAud = replyingToMessage.tipo === 'audio';
        const isFile = replyingToMessage.tipo === 'arquivo';

        let snippetText = caption || replyingToMessage.conteudo || '';
        if (isImg && !caption) snippetText = 'Foto';
        if (isVid && !caption) snippetText = 'Vídeo';
        if (isAud) snippetText = 'Áudio';
        if (isFile && !caption) snippetText = mediaPath.split('/').pop() || 'Documento';

        return (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 16px',
            backgroundColor: 'var(--bg-secondary)',
            borderTop: '1px solid var(--border-color)',
            borderLeft: '4px solid var(--accent-primary)',
            boxShadow: '0 -2px 10px rgba(0,0,0,0.05)',
            flexShrink: 0,
            gap: '12px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
              {isImg && (
                <div style={{ width: '38px', height: '38px', borderRadius: '6px', overflow: 'hidden', flexShrink: 0, border: '1px solid var(--border-color)', backgroundColor: '#000' }}>
                  <img src={fullUrl} alt="Foto" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </div>
              )}
              {isVid && (
                <div style={{ width: '38px', height: '38px', borderRadius: '6px', overflow: 'hidden', flexShrink: 0, border: '1px solid var(--border-color)', backgroundColor: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Video size={18} color="var(--accent-primary)" />
                </div>
              )}
              {isAud && (
                <div style={{ width: '38px', height: '38px', borderRadius: '6px', overflow: 'hidden', flexShrink: 0, border: '1px solid var(--border-color)', backgroundColor: 'rgba(168, 85, 247, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Music size={18} color="#c084fc" />
                </div>
              )}
              {isFile && (
                <div style={{ width: '38px', height: '38px', borderRadius: '6px', overflow: 'hidden', flexShrink: 0, border: '1px solid var(--border-color)', backgroundColor: 'rgba(239, 68, 68, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <FileText size={18} color="#ef4444" />
                </div>
              )}

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Reply size={13} />
                  <span>Respondendo a {replyingToMessage.remetente === 'cliente' ? (conversation.contact?.nome || 'Cliente') : 'Atendente'}:</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {snippetText}
                </div>
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
        );
      })()}

      {/* WhatsApp-Style Message Edit Bar (Imagem 3) */}
      {editingMessage && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 18px',
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          borderTop: '1px solid rgba(245, 158, 11, 0.35)',
          borderLeft: '4px solid #f59e0b',
          boxShadow: '0 -4px 15px rgba(0,0,0,0.1)',
          flexShrink: 0,
          gap: '12px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1, minWidth: 0 }}>
            <div style={{
              width: '34px',
              height: '34px',
              borderRadius: '50%',
              backgroundColor: 'rgba(245, 158, 11, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#f59e0b',
              flexShrink: 0
            }}>
              <Pencil size={17} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '11px', fontWeight: '700', color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                ✏️ Editando Mensagem Enviada
              </div>
              <input
                type="text"
                value={editingMessageText}
                onChange={(e) => setEditingMessageText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSaveEdit();
                  } else if (e.key === 'Escape') {
                    handleCancelEdit();
                  }
                }}
                autoFocus
                placeholder="Edite o texto da mensagem e pressione Enter para salvar..."
                style={{
                  width: '100%',
                  marginTop: '4px',
                  padding: '7px 12px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid rgba(245, 158, 11, 0.4)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-main)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              onClick={handleSaveEdit}
              disabled={isSavingEdit || !editingMessageText.trim()}
              className="btn-primary"
              style={{
                padding: '7px 14px',
                fontSize: '12px',
                fontWeight: '700',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: '#22c55e',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                boxShadow: '0 2px 8px rgba(34, 197, 94, 0.3)'
              }}
              title="Salvar alteração (Enter)"
            >
              <Check size={15} /> {isSavingEdit ? 'Salvando...' : 'Salvar'}
            </button>
            <button
              type="button"
              onClick={handleCancelEdit}
              style={{
                background: 'rgba(255, 255, 255, 0.08)',
                border: 'none',
                color: 'var(--text-muted)',
                borderRadius: '50%',
                width: '28px',
                height: '28px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Cancelar edição (Esc)"
            >
              <X size={16} />
            </button>
          </div>
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
        const phone = conversation.contact?.telefone || '';
        const isGroupChat = Boolean(
          phone.includes('@g.us') ||
          phone.startsWith('120363') ||
          conversation.contact?.nome?.includes('Servweld/Servsolda') ||
          conversation.dados_adicionais?.is_group
        );

        return (
          <div style={{ width: '100%', display: 'flex', flexDirection: 'column', flexShrink: 0, position: 'relative' }}>
            {/* WhatsApp Link Preview Banner in Input Composer */}
            {inputLinkPreview && (
              <div style={{
                margin: '0 20px',
                padding: '10px 14px',
                backgroundColor: 'rgba(15, 23, 42, 0.96)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                borderBottom: 'none',
                borderTopLeftRadius: '10px',
                borderTopRightRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '12px',
                boxShadow: '0 -3px 12px rgba(0, 0, 0, 0.3)',
                backdropFilter: 'blur(8px)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
                  {inputLinkPreview.image ? (
                    <img
                      src={inputLinkPreview.image}
                      alt="Prévia do Link"
                      style={{
                        width: '130px',
                        height: '74px',
                        borderRadius: '8px',
                        objectFit: 'cover',
                        flexShrink: 0,
                        backgroundColor: 'rgba(0,0,0,0.3)',
                        border: '1px solid rgba(255, 255, 255, 0.1)'
                      }}
                      onError={(e) => (e.currentTarget.style.display = 'none')}
                    />
                  ) : (
                    <div style={{
                      width: '52px',
                      height: '52px',
                      borderRadius: '8px',
                      backgroundColor: 'rgba(0, 230, 153, 0.15)',
                      color: 'var(--accent-primary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0
                    }}>
                      <Globe size={24} />
                    </div>
                  )}

                  <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <div style={{
                      fontSize: '13.5px',
                      fontWeight: '700',
                      color: '#ffffff',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 1,
                      WebkitBoxOrient: 'vertical'
                    }}>
                      {inputLinkPreview.title || inputLinkPreview.domain || inputLinkPreview.url}
                    </div>
                    {inputLinkPreview.description && inputLinkPreview.description !== inputLinkPreview.url && (
                      <div style={{
                        fontSize: '11.5px',
                        color: 'rgba(255, 255, 255, 0.75)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        lineHeight: '1.3'
                      }}>
                        {inputLinkPreview.description}
                      </div>
                    )}
                    <div style={{
                      fontSize: '10.5px',
                      color: 'rgba(255, 255, 255, 0.45)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap'
                    }}>
                      {inputLinkPreview.domain || inputLinkPreview.url}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    if (inputLinkPreview) {
                      setDismissedUrls(prev => [...prev, inputLinkPreview.url]);
                      setInputLinkPreview(null);
                    }
                  }}
                  style={{
                    background: 'rgba(255, 255, 255, 0.08)',
                    border: 'none',
                    borderRadius: '50%',
                    width: '30px',
                    height: '30px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'rgba(255, 255, 255, 0.75)',
                    cursor: 'pointer',
                    flexShrink: 0,
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.2)';
                    e.currentTarget.style.color = '#ffffff';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.08)';
                    e.currentTarget.style.color = 'rgba(255, 255, 255, 0.75)';
                  }}
                  title="Fechar prévia do link"
                >
                  <X size={16} />
                </button>
              </div>
            )}

            <form
              onSubmit={handleSend}
              className="chat-input-form"
              style={{ width: '100%', boxSizing: 'border-box', padding: '12px 20px', borderTop: inputLinkPreview ? 'none' : '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', display: 'flex', gap: '10px', alignItems: 'flex-end', flexShrink: 0, position: 'relative' }}
            >
              <button
                type="button"
                onClick={() => {
                  setReactingMsgForPicker(null);
                  setShowEmojiPicker(!showEmojiPicker);
                }}
                className="btn-secondary chat-emoji-btn"
                style={{
                  height: '42px',
                  padding: '0 12px',
                  color: showEmojiPicker ? 'var(--accent-primary)' : 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                title="Emojis, GIFs e Figurinhas do WhatsApp"
              >
                <Smile size={18} />
              </button>
              <button
                type="button"
                onClick={() => setShowAttachmentMenu(!showAttachmentMenu)}
                className="btn-secondary chat-attach-btn"
                style={{ height: '42px', padding: '0 12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                title="Menu de Anexos e Ações Rápidas"
              >
                <Paperclip size={18} />
              </button>

            {showMentionMenu && (() => {
              const cursor = textareaRef.current ? (textareaRef.current.selectionStart || inputText.length) : inputText.length;
              const textBeforeCursor = inputText.substring(0, cursor);
              const lastAtIndex = textBeforeCursor.lastIndexOf('@');
              const mentionQuery = lastAtIndex !== -1 ? textBeforeCursor.substring(lastAtIndex + 1).toLowerCase() : '';

              const filteredParticipants = groupParticipants.filter(p => {
                if (!mentionQuery) return true;
                const nameMatch = p.name && p.name.toLowerCase().includes(mentionQuery);
                const phoneMatch = p.phone && p.phone.includes(mentionQuery);
                const lidMatch = p.lid && p.lid.includes(mentionQuery);
                return nameMatch || phoneMatch || lidMatch;
              });

              const showTodos = isGroupChat && (!mentionQuery || 'todos'.includes(mentionQuery) || 'all'.includes(mentionQuery) || 'everyone'.includes(mentionQuery));

              return (
                <>
                  <div
                    onClick={() => setShowMentionMenu(false)}
                    style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 999 }}
                  />
                  <div
                    style={{
                      position: 'absolute',
                      bottom: 'calc(100% + 8px)',
                      left: '20px',
                      backgroundColor: '#0f172a',
                      border: '1px solid rgba(0, 230, 153, 0.3)',
                      borderRadius: 'var(--radius-md)',
                      boxShadow: '0 16px 36px rgba(0,0,0,0.85)',
                      zIndex: 1000,
                      minWidth: '280px',
                      maxWidth: '360px',
                      maxHeight: '260px',
                      overflowY: 'auto',
                      padding: '6px 0'
                    }}
                  >
                  <div style={{ padding: '6px 12px', fontSize: '10px', fontWeight: '700', color: 'var(--accent-primary)', borderBottom: '1px solid var(--border-color)', textTransform: 'uppercase' }}>
                    Integrantes do Grupo ({filteredParticipants.length})
                  </div>

                  {showTodos && (
                    <div
                      onClick={() => {
                        const cursor = textareaRef.current ? textareaRef.current.selectionStart : inputText.length;
                        const lastAtIndex = inputText.lastIndexOf('@');
                        const prefix = lastAtIndex !== -1 ? inputText.substring(0, lastAtIndex) : inputText;
                        const nextText = `${prefix}@todos `;
                        setInputText(nextText);
                        setShowMentionMenu(false);
                        if (textareaRef.current) {
                          textareaRef.current.focus();
                        }
                      }}
                      style={{
                        padding: '8px 12px',
                        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: '12px',
                        color: 'var(--text-main)',
                        backgroundColor: 'rgba(0, 230, 153, 0.08)'
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.18)')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.08)')}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--accent-primary)', color: '#051a12', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: '800' }}>
                          @
                        </div>
                        <div>
                          <div style={{ fontWeight: '700', color: 'var(--accent-primary)' }}>@todos</div>
                          <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Notificar todos os {groupParticipants.length} membros</div>
                        </div>
                      </div>
                      <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', backgroundColor: 'rgba(0, 230, 153, 0.2)', color: 'var(--accent-primary)', fontWeight: '700' }}>
                        Geral
                      </span>
                    </div>
                  )}

                  {filteredParticipants.length > 0 ? (
                    filteredParticipants.map(p => (
                      <div
                        key={p.phone || p.lid || p.name}
                        onClick={() => {
                          const cursor = textareaRef.current ? textareaRef.current.selectionStart : inputText.length;
                          const lastAtIndex = inputText.lastIndexOf('@');
                          const prefix = lastAtIndex !== -1 ? inputText.substring(0, lastAtIndex) : inputText;
                          const nextText = `${prefix}@${p.name} `;
                          setInputText(nextText);
                          setShowMentionMenu(false);
                          if (textareaRef.current) {
                            textareaRef.current.focus();
                          }
                        }}
                        style={{
                          padding: '8px 12px',
                          borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: '12px',
                          color: 'var(--text-main)',
                          transition: 'background-color 0.15s ease'
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.12)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                          <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'rgba(0, 230, 153, 0.2)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: '700', flexShrink: 0 }}>
                            {(p.name || 'M').charAt(0).toUpperCase()}
                          </div>
                          <div style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <div style={{ fontWeight: '600', overflow: 'hidden', textOverflow: 'ellipsis' }}>@{p.name}</div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>+{p.phone}</div>
                          </div>
                        </div>
                        {p.is_admin && (
                          <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', backgroundColor: 'rgba(234, 179, 8, 0.2)', color: '#eab308', fontWeight: '700' }}>
                            Admin
                          </span>
                        )}
                      </div>
                    ))
                  ) : !showTodos ? (
                    <div style={{ padding: '12px 10px', fontSize: '12px', color: 'var(--text-muted)', textAlign: 'center' }}>
                      Nenhum integrante encontrado para "{mentionQuery}"
                    </div>
                  ) : null}
                </div>
                </>
              );
            })()}
            
            <textarea
              ref={textareaRef}
              className="chat-input-textarea"
              rows={1}
              placeholder={isGroupChat ? 'Enviar mensagem no grupo... (@ menciona alguém ou @todos)' : 'Digite sua mensagem... (Cole Ctrl+V imagens/arquivos aqui)'}
              value={inputText}
              spellCheck={true}
              lang="pt-BR"
              autoCorrect="on"
              autoCapitalize="sentences"
              autoComplete="on"
              onPaste={handlePaste}
              onChange={(e) => {
                const val = e.target.value;
                setInputText(val);
                if (conversation?.id && onSaveDraft) {
                  onSaveDraft(conversation.id, val);
                }
                e.target.style.height = 'auto';
                const nextH = Math.min(e.target.scrollHeight, 140);
                e.target.style.height = `${Math.max(nextH, 42)}px`;

                // Detect if user typed '@'
                const cursor = e.target.selectionStart || 0;
                if (cursor > 0 && val.charAt(cursor - 1) === '@') {
                  setShowMentionMenu(true);
                } else if (showMentionMenu && !val.includes('@')) {
                  setShowMentionMenu(false);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && showMentionMenu) {
                  setShowMentionMenu(false);
                  return;
                }
                if (e.key === 'Enter') {
                  if (e.ctrlKey || e.shiftKey) {
                    if (e.ctrlKey && !e.shiftKey) {
                      e.preventDefault();
                      const target = e.currentTarget;
                      const start = target.selectionStart;
                      const end = target.selectionEnd;
                      const val = target.value;
                      const newVal = val.substring(0, start) + '\n' + val.substring(end);
                      setInputText(newVal);
                      setTimeout(() => {
                        target.selectionStart = target.selectionEnd = start + 1;
                        target.style.height = 'auto';
                        const nextH = Math.min(target.scrollHeight, 140);
                        target.style.height = `${Math.max(nextH, 42)}px`;
                      }, 0);
                    }
                  } else {
                    e.preventDefault();
                    handleSend(e);
                  }
                }
              }}
              style={{
                flex: 1,
                minHeight: '42px',
                maxHeight: '140px',
                height: '42px',
                padding: '10px 14px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '14px',
                lineHeight: '1.4',
                fontFamily: 'inherit',
                resize: 'none',
                outline: 'none',
                overflowY: 'auto',
                boxSizing: 'border-box',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word'
              }}
            />

            <AudioRecorder onSendAudio={handleSendAudioMessage} />

            <button
              type="button"
              onClick={() => setShowCopilotModal(true)}
              className="btn-secondary chat-consultar-ia-btn"
              style={{
                height: '42px',
                padding: '0 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                color: 'var(--accent-primary)',
                borderColor: 'rgba(0, 230, 153, 0.4)',
                backgroundColor: 'rgba(0, 230, 153, 0.1)',
                fontWeight: '700',
                fontSize: '13px',
                boxShadow: '0 2px 8px rgba(0, 230, 153, 0.15)',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
              title="Conversar com a IA (Abre o Copiloto IA para analisar todo o teor da conversa, consultar manuais e ajudar a responder o cliente)"
            >
              <Bot size={16} />
              <span className="chat-btn-text">Consultar IA</span>
            </button>
            <button
              type="submit"
              className="btn-primary chat-enviar-btn"
              disabled={(!inputText.trim() && pendingFiles.length === 0) || isSending}
              style={{ height: '42px', padding: '0 16px', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Send size={16} /> <span className="chat-btn-text">{isSending ? 'Enviando...' : 'Enviar'}</span>
            </button>
          </form>

        </div>
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
        whatsappNumbers={whatsappNumbers}
        currentDepartmentId={conversation?.whatsapp_number_id}
        activeConversation={conversation}
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

      {/* 8. Interactive AI Copilot Modal (Conversar com a IA Consultora em Tempo Real) */}
      <AICopilotModal
        isOpen={showCopilotModal}
        onClose={() => setShowCopilotModal(false)}
        conversation={conversation}
        currentUser={currentUser}
        onInsertText={(text) => {
          setInputText(prev => (prev ? prev + '\n' + text : text));
        }}
      />

      {/* 9. Modal de Reportar Erro da IA (Loop de Melhoria Contínua) */}
      {showReportAIModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1100,
          padding: '16px'
        }}>
          <div style={{
            backgroundColor: '#0f172a',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            borderRadius: '12px',
            width: '100%',
            maxWidth: '520px',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.9)',
            overflow: 'hidden'
          }}>
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              backgroundColor: 'rgba(239, 68, 68, 0.08)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertTriangle size={20} color="#f87171" />
                <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 'bold', color: '#f87171' }}>
                  Marcar / Reportar Erro da IA
                </h3>
              </div>
              <button
                onClick={() => {
                  setShowReportAIModal(false);
                  setReportSuccessMessage(null);
                }}
                style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {reportSuccessMessage ? (
                <div style={{
                  padding: '14px',
                  backgroundColor: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid #10b981',
                  borderRadius: '8px',
                  color: '#34d399',
                  fontSize: '13px',
                  textAlign: 'center'
                }}>
                  {reportSuccessMessage}
                </div>
              ) : (
                <>
                  <div>
                    <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '6px', fontWeight: 'bold' }}>
                      Categoria do Erro da IA:
                    </label>
                    <select
                      value={reportErrorCategory}
                      onChange={(e) => setReportErrorCategory(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        backgroundColor: '#1e293b',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '8px',
                        color: '#f8fafc',
                        fontSize: '13px',
                        outline: 'none'
                      }}
                    >
                      <option value="alucinacao_nome">Alucinação de Nome (ex: inventou título, sobrenome ou nome estranho)</option>
                      <option value="alucinacao_historico">Alucinação de Histórico (afirmou contato anterior que não existia)</option>
                      <option value="tom_errado">Tom / Postura Inadequada</option>
                      <option value="informacao_incorreta">Informação Incorreta / Erro de Preço ou Procedimento</option>
                      <option value="outro">Outro Motivo</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '6px', fontWeight: 'bold' }}>
                      O que a IA respondeu de errado (opcional):
                    </label>
                    <textarea
                      value={reportLastAIReply}
                      onChange={(e) => setReportLastAIReply(e.target.value)}
                      placeholder="Cole aqui ou descreva a resposta que a IA deu..."
                      rows={3}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        backgroundColor: '#1e293b',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '8px',
                        color: '#f8fafc',
                        fontSize: '13px',
                        resize: 'none',
                        outline: 'none',
                        boxSizing: 'border-box'
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '6px', fontWeight: 'bold' }}>
                      Como ela DEVERIA ter respondido? (Resposta Correta):
                    </label>
                    <textarea
                      value={reportCorrectResponse}
                      onChange={(e) => setReportCorrectResponse(e.target.value)}
                      placeholder="Ex: 'Olá! Seja bem-vindo à Servweld. Como posso te ajudar hoje?'"
                      rows={4}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        backgroundColor: '#1e293b',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '8px',
                        color: '#f8fafc',
                        fontSize: '13px',
                        resize: 'none',
                        outline: 'none',
                        boxSizing: 'border-box'
                      }}
                    />
                  </div>
                </>
              )}
            </div>

            <div style={{
              padding: '14px 20px',
              borderTop: '1px solid rgba(255,255,255,0.08)',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: '10px',
              backgroundColor: 'rgba(0,0,0,0.2)'
            }}>
              <button
                type="button"
                onClick={() => {
                  setShowReportAIModal(false);
                  setReportSuccessMessage(null);
                }}
                className="btn-secondary"
                style={{ padding: '8px 16px', fontSize: '13px' }}
              >
                Fechar
              </button>

              {!reportSuccessMessage && (
                <button
                  type="button"
                  disabled={isSubmittingReport || !reportCorrectResponse.trim()}
                  onClick={async () => {
                    if (!conversation || !reportCorrectResponse.trim()) return;
                    try {
                      setIsSubmittingReport(true);
                      await apiFetch(`/conversations/${conversation.id}/report-ai-error`, {
                        method: 'POST',
                        body: JSON.stringify({
                          resposta_ia: reportLastAIReply || undefined,
                          resposta_correta: reportCorrectResponse.trim(),
                          categoria_erro: reportErrorCategory
                        })
                      });
                      setReportSuccessMessage('Obrigado! A correção foi gravada com sucesso e servirá para treinar e aprimorar a IA.');
                      setReportCorrectResponse('');
                      setReportLastAIReply('');
                      setTimeout(() => {
                        setShowReportAIModal(false);
                        setReportSuccessMessage(null);
                      }, 2000);
                    } catch (err: any) {
                      alert('Erro ao registrar correção da IA: ' + (err.message || err));
                    } finally {
                      setIsSubmittingReport(false);
                    }
                  }}
                  className="btn-primary"
                  style={{
                    padding: '8px 16px',
                    fontSize: '13px',
                    backgroundColor: '#ef4444',
                    borderColor: '#ef4444',
                    opacity: (!reportCorrectResponse.trim() || isSubmittingReport) ? 0.6 : 1
                  }}
                >
                  {isSubmittingReport ? 'Salvando...' : 'Gravar Correção'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {showParticipantsModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.8)',
          zIndex: 1100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <div style={{
            backgroundColor: '#0f172a',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '12px',
            width: '100%',
            maxWidth: '480px',
            maxHeight: '80vh',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            boxShadow: '0 20px 50px rgba(0,0,0,0.7)'
          }}>
            <div style={{
              padding: '16px 20px',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between'
            }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Users size={18} color="var(--accent-primary)" /> Integrantes do Grupo
                </h3>
                <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                  {groupParticipants.length} membros no WhatsApp • {conversation?.contact?.nome || 'Grupo'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowParticipantsModal(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: '12px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <input
                type="text"
                value={participantsSearch}
                onChange={(e) => setParticipantsSearch(e.target.value)}
                placeholder="Buscar por nome ou telefone..."
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  backgroundColor: '#1e293b',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: '6px',
                  color: 'var(--text-main)',
                  fontSize: '13px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '10px 20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {groupParticipants
                .filter(p => {
                  if (!participantsSearch) return true;
                  const q = participantsSearch.toLowerCase();
                  return (p.name && p.name.toLowerCase().includes(q)) || (p.phone && p.phone.includes(q));
                })
                .map((p, idx) => (
                  <div
                    key={p.id || idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 12px',
                      backgroundColor: 'rgba(255,255,255,0.03)',
                      borderRadius: '8px',
                      border: '1px solid rgba(255,255,255,0.05)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
                      {p.avatar_url ? (
                        <img src={p.avatar_url} alt={p.name} style={{ width: '32px', height: '32px', borderRadius: '50%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{
                          width: '32px',
                          height: '32px',
                          borderRadius: '50%',
                          backgroundColor: p.is_admin ? 'rgba(234, 179, 8, 0.2)' : 'rgba(0, 230, 153, 0.2)',
                          color: p.is_admin ? '#eab308' : 'var(--accent-primary)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: '700',
                          fontSize: '13px',
                          flexShrink: 0
                        }}>
                          {(p.name || 'M').charAt(0).toUpperCase()}
                        </div>
                      )}
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</span>
                          {p.is_admin && (
                            <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', backgroundColor: 'rgba(234, 179, 8, 0.2)', color: '#eab308', fontWeight: '700' }}>
                              Admin
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>+{p.phone}</div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => {
                          handleInsertMention(`@${p.name} `);
                          setShowParticipantsModal(false);
                        }}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-primary)' }}
                        title="Mencionar participante no chat"
                      >
                        <AtSign size={12} /> Mencionar
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowParticipantsModal(false);
                          handlePrivateReply({ conteudo: '' } as any, p.phone, p.name);
                        }}
                        className="btn-secondary"
                        style={{ padding: '4px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                        title="Conversar no privado com este participante"
                      >
                        Privado
                      </button>
                    </div>
                  </div>
                ))}
            </div>

            <div style={{ padding: '12px 20px', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.2)' }}>
              <button
                type="button"
                onClick={() => setShowParticipantsModal(false)}
                className="btn-secondary"
                style={{ padding: '6px 16px', fontSize: '13px' }}
              >
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
