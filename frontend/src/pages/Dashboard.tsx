import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { User, Conversation, WhatsAppNumber, ConversationStatus } from '../types';
import { apiFetch } from '../services/api';
import { Sidebar } from '../components/Sidebar';
import { ChatList } from '../components/ChatList';
import { ChatArea } from '../components/ChatArea';
import { TransferModal } from '../components/TransferModal';
import { AdminPanel } from '../components/AdminPanel';
import { ContactsPanel } from '../components/ContactsPanel';
import { SegmentationPanel } from '../components/SegmentationPanel';
import { NewConversationModal } from '../components/NewConversationModal';
import { MediaGalleryModal } from '../components/MediaGalleryModal';
import { SyncTaskbar } from '../components/SyncTaskbar';

import { DepartmentBar } from '../components/DepartmentBar';

interface DashboardProps {
  user: User;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ user, onLogout }) => {
  const [activeTab, setActiveTab] = useState<'chats' | 'groups' | 'contacts' | 'segmentation' | 'admin'>('chats');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<number | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<ConversationStatus | 'all' | 'nao_lidas'>('all');

  const displayedConversations = React.useMemo(() => {
    return conversations.filter(c => {
      const isGroup = Boolean(
        c.contact?.telefone?.startsWith('120363') ||
        (c.contact?.telefone && c.contact.telefone.length > 15) ||
        c.contact?.nome?.includes('Servweld/Servsolda')
      );

      if (activeTab === 'groups') {
        return isGroup;
      }
      if (activeTab === 'chats') {
        return !isGroup;
      }
      return true;
    });
  }, [conversations, activeTab]);
  
  // Computes active conversation prioritizing selected department
  const activeConversation = useMemo(() => {
    if (activeConversationId) {
      const found = displayedConversations.find(c => c.id === activeConversationId);
      if (found) {
        // If a specific department is selected and the active conversation belongs to another department:
        if (selectedDeptId !== 'all' && String(found.whatsapp_number_id) !== String(selectedDeptId)) {
          const cid = found.contact_id || found.contact?.id;
          const cleanPhone = (found.contact?.telefone || '').replace(/\D/g, '');
          const sameContactInDept = displayedConversations.find(c =>
            String(c.whatsapp_number_id) === String(selectedDeptId) &&
            ((cid && (c.contact_id === cid || c.contact?.id === cid)) ||
             (cleanPhone.length >= 8 && (c.contact?.telefone || '').replace(/\D/g, '').includes(cleanPhone.slice(-8))))
          );
          if (sameContactInDept) return sameContactInDept;
        }
        return found;
      }
    }

    if (selectedDeptId !== 'all') {
      const deptConvs = displayedConversations.filter(c => String(c.whatsapp_number_id) === String(selectedDeptId));
      if (deptConvs.length > 0) return deptConvs[0];
    }

    return displayedConversations.length > 0 ? displayedConversations[0] : null;
  }, [displayedConversations, activeConversationId, selectedDeptId]);

  // Modals state
  const [isTransferModalOpen, setIsTransferModalOpen] = useState(false);
  const [isNewConvModalOpen, setIsNewConvModalOpen] = useState(false);
  const [isMediaGalleryOpen, setIsMediaGalleryOpen] = useState(false);

  const fetchConversations = useCallback(async () => {
    try {
      const data = await apiFetch('/conversations/');
      setConversations(data);
    } catch (err) {
      console.error('Error fetching conversations:', err);
    }
  }, []);

  const fetchNumbers = async () => {
    try {
      const data = await apiFetch('/whatsapp-numbers/');
      setWhatsappNumbers(data);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchConversations();
    fetchNumbers();
  }, [fetchConversations]);

  const [notificationAlert, setNotificationAlert] = useState<string | null>(null);

  const playNotificationSound = () => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, ctx.currentTime);
      osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.4);
    } catch (e) {
      console.error(e);
    }
  };

  // 1. Polling Fallback Safety Net (Every 3s)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchConversations();
    }, 3000);
    return () => clearInterval(interval);
  }, [fetchConversations]);

  // 2. WebSocket Live Realtime Connection with Auto-Reconnect & Dynamic Host
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    let socket: WebSocket | null = null;
    let isSubscribed = true;
    let reconnectTimeout: any = null;

    const connectWebSocket = () => {
      if (!isSubscribed) return;

      const host = window.location.hostname || 'localhost';
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${host}:8000/ws?token=${token}`;

      socket = new WebSocket(wsUrl);

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'CONVERSATION_ESCALATED') {
            fetchConversations();
            playNotificationSound();
            setNotificationAlert(payload.message || "🚨 ATENÇÃO: Nova conversa transferida para atendimento humano!");
            setTimeout(() => setNotificationAlert(null), 10000);
          } else if (payload.type === 'NEW_MESSAGE') {
            fetchConversations();
            if (payload.remetente === 'cliente') {
              playNotificationSound();
            }
          } else if (
            payload.type === 'MESSAGE_STATUS_UPDATE' ||
            payload.type === 'MESSAGE_REACTION_UPDATE' ||
            payload.type === 'CONVERSATIONS_MARKED_READ' ||
            payload.type === 'conversation_pinned_toggled'
          ) {
            fetchConversations();
          }
        } catch (err) {
          console.error('WebSocket parse error:', err);
        }
      };

      socket.onclose = () => {
        if (isSubscribed) {
          reconnectTimeout = setTimeout(connectWebSocket, 2000);
        }
      };
    };

    connectWebSocket();

    return () => {
      isSubscribed = false;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (socket) socket.close();
    };
  }, [fetchConversations]);

  const handleSendMessage = async (text: string, tipo: string = 'texto') => {
    if (!activeConversation) return;

    let targetConv = activeConversation;

    // REGRA DE OURO DO DEPARTAMENTO SELECIONADO:
    // Se o departamento está selecionado lá em cima (ex: Assistência Técnica),
    // a mensagem DEVE sair pelo número do departamento selecionado!
    if (selectedDeptId !== 'all' && String(targetConv.whatsapp_number_id) !== String(selectedDeptId)) {
      const cid = targetConv.contact_id || targetConv.contact?.id;
      const cleanPhone = (targetConv.contact?.telefone || '').replace(/\D/g, '');
      
      const matchInDept = conversations.find(c => 
        String(c.whatsapp_number_id) === String(selectedDeptId) &&
        ((cid && (c.contact_id === cid || c.contact?.id === cid)) ||
         (cleanPhone.length >= 8 && (c.contact?.telefone || '').replace(/\D/g, '').includes(cleanPhone.slice(-8))))
      );

      if (matchInDept) {
        targetConv = matchInDept;
        setActiveConversationId(matchInDept.id);
      } else if (targetConv.contact) {
        try {
          const createdConv = await apiFetch('/conversations/', {
            method: 'POST',
            body: JSON.stringify({
              whatsapp_number_id: Number(selectedDeptId),
              contact_phone: targetConv.contact.telefone,
              contact_name: targetConv.contact.nome
            })
          });
          if (createdConv && createdConv.id) {
            targetConv = createdConv;
            setActiveConversationId(createdConv.id);
            setConversations(prev => [createdConv, ...prev.filter(c => c.id !== createdConv.id)]);
          }
        } catch (err) {
          console.error("Erro ao criar conversa no departamento selecionado:", err);
        }
      }
    }

    const isMedia = tipo !== 'texto' || text.endsWith('.webp') || text.endsWith('.gif') || text.includes('/uploads/');
    const actualTipo = isMedia ? (text.endsWith('.gif') ? 'video' : 'imagem') : (tipo || 'texto');
    const tempId = -Date.now();
    const optimisticMsg: Message = {
      id: tempId,
      conversation_id: targetConv.id,
      remetente: 'atendente',
      conteudo: text,
      tipo: actualTipo as any,
      timestamp: new Date().toISOString(),
      status: 'sending'
    };

    // 1. Instantly append message to local state (0ms instant UI update!)
    setConversations(prevConvs =>
      prevConvs.map(conv => {
        if (conv.id === targetConv.id) {
          const currentMsgs = conv.messages || [];
          return {
            ...conv,
            messages: [...currentMsgs, optimisticMsg],
            ultima_interacao_em: new Date().toISOString()
          };
        }
        return conv;
      })
    );

    try {
      // 2. Dispatch network HTTP request asynchronously
      const res = await apiFetch(`/conversations/${targetConv.id}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          conversation_id: targetConv.id,
          remetente: 'atendente',
          conteudo: text,
          tipo: actualTipo
        })
      });

      // 3. Confirm delivery: replace tempId with real server DB message
      setConversations(prevConvs =>
        prevConvs.map(conv => {
          if (conv.id === targetConv.id) {
            const currentMsgs = conv.messages || [];
            return {
              ...conv,
              messages: currentMsgs.map(m => (m.id === tempId ? { ...res, status: 'sent' } : m))
            };
          }
          return conv;
        })
      );
    } catch (err: any) {
      console.error('Optimistic message send error:', err);
      setNotificationAlert(err.message || 'Erro ao enviar mensagem no WhatsApp.');
      setTimeout(() => setNotificationAlert(null), 7000);
      // Mark as failed if connection drops
      setConversations(prevConvs =>
        prevConvs.map(conv => {
          if (conv.id === targetConv.id) {
            const currentMsgs = conv.messages || [];
            return {
              ...conv,
              messages: currentMsgs.map(m => (m.id === tempId ? { ...m, status: 'failed' } : m))
            };
          }
          return conv;
        })
      );
    }
  };

  const handleConversationCreated = (conv: Conversation) => {
    fetchConversations();
    setActiveConversationId(conv.id);
    setActiveTab('chats');
  };
  const [isChatListCollapsed, setIsChatListCollapsed] = useState(false);

  const [isMainSidebarCollapsed, setIsMainSidebarCollapsed] = useState(false);

  return (
    <div className="dashboard-layout" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden', backgroundColor: 'var(--bg-primary)' }}>
      {notificationAlert && (
        <div style={{
          position: 'fixed',
          top: '16px',
          right: '16px',
          backgroundColor: '#ef4444',
          color: '#fff',
          padding: '12px 20px',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 8px 24px rgba(239,68,68,0.4)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          fontWeight: '600',
          fontSize: '14px'
        }}>
          <span>{notificationAlert}</span>
          <button
            onClick={() => setNotificationAlert(null)}
            style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer', fontWeight: 'bold', fontSize: '16px' }}
          >
            ✕
          </button>
        </div>
      )}

      <Sidebar
        user={user}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onLogout={onLogout}
        isCollapsed={isMainSidebarCollapsed}
        onToggleCollapse={() => setIsMainSidebarCollapsed(!isMainSidebarCollapsed)}
        conversations={conversations}
        onSelectConversation={(convId) => {
          setActiveConversationId(convId);
          setActiveTab('chats');
        }}
        onRefreshConversations={fetchConversations}
      />

      {(activeTab === 'chats' || activeTab === 'groups') && (
        <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: '100%', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', boxSizing: 'border-box' }}>
          <DepartmentBar
            whatsappNumbers={whatsappNumbers}
            selectedDepartmentId={selectedDeptId}
            onSelectDepartment={(id) => setSelectedDeptId(id)}
            conversations={displayedConversations}
          />
          <div style={{ flex: 1, minWidth: 0, width: '100%', maxWidth: '100%', display: 'flex', overflow: 'hidden', boxSizing: 'border-box' }}>
            <div
              className={`chat-list-column ${activeConversationId ? 'mobile-hidden' : ''}`}
              style={{
                height: '100%',
                flex: '0 0 360px',
                width: '360px',
                minWidth: '360px',
                maxWidth: '360px',
                flexShrink: 0,
                display: 'flex',
                boxSizing: 'border-box',
                overflow: 'hidden'
              }}
            >
              <ChatList
                conversations={displayedConversations}
                activeConversation={activeConversation}
                onSelectConversation={(conv) => setActiveConversationId(conv.id)}
                whatsappNumbers={whatsappNumbers}
                selectedDepartmentId={selectedDeptId}
                setSelectedDepartmentId={setSelectedDeptId}
                statusFilter={statusFilter}
                setStatusFilter={setStatusFilter}
                onOpenNewConversationModal={() => setIsNewConvModalOpen(true)}
                onStatusToggle={fetchConversations}
              />
            </div>
            <div className={`chat-area-column ${!activeConversationId ? 'mobile-hidden' : ''}`} style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex' }}>
              <ChatArea
                conversation={activeConversation}
                allConversations={conversations}
                onSelectConversation={(conv) => setActiveConversationId(conv.id)}
                currentUser={user}
                onSendMessage={handleSendMessage}
                onOpenTransferModal={() => setIsTransferModalOpen(true)}
                onOpenMediaGallery={() => setIsMediaGalleryOpen(true)}
                onStatusToggle={fetchConversations}
                onBack={() => setActiveConversationId(null)}
                isChatListCollapsed={isChatListCollapsed}
                onToggleChatList={() => setIsChatListCollapsed(!isChatListCollapsed)}
              />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'contacts' && (
        <ContactsPanel />
      )}

      {activeTab === 'segmentation' && (
        <SegmentationPanel />
      )}

      {activeTab === 'admin' && (
        <AdminPanel />
      )}

      {/* Modals */}
      <NewConversationModal
        isOpen={isNewConvModalOpen}
        onClose={() => setIsNewConvModalOpen(false)}
        whatsappNumbers={whatsappNumbers}
        onConversationCreated={handleConversationCreated}
      />

      <MediaGalleryModal
        isOpen={isMediaGalleryOpen}
        onClose={() => setIsMediaGalleryOpen(false)}
        conversation={activeConversation}
      />

      <TransferModal
        isOpen={isTransferModalOpen}
        onClose={() => setIsTransferModalOpen(false)}
        conversation={activeConversation}
        onTransferSuccess={() => {
          fetchConversations();
          setSelectedDeptId('all');
        }}
      />

      {/* Global Real-time WhatsApp Sync Progress Taskbar */}
      <SyncTaskbar />
    </div>
  );
};
