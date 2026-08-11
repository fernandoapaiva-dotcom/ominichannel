import React, { useState, useEffect, useCallback } from 'react';
import { User, Conversation, WhatsAppNumber, ConversationStatus } from '../types';
import { apiFetch } from '../services/api';
import { Sidebar } from '../components/Sidebar';
import { ChatList } from '../components/ChatList';
import { ChatArea } from '../components/ChatArea';
import { TransferModal } from '../components/TransferModal';
import { AdminPanel } from '../components/AdminPanel';

interface DashboardProps {
  user: User;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ user, onLogout }) => {
  const [activeTab, setActiveTab] = useState<'chats' | 'admin'>('chats');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null);
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<number | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<ConversationStatus | 'all'>('all');
  const [isTransferModalOpen, setIsTransferModalOpen] = useState(false);

  const fetchConversations = useCallback(async () => {
    try {
      const data = await apiFetch('/conversations/');
      setConversations(data);
      if (activeConversation) {
        const updated = data.find((c: Conversation) => c.id === activeConversation.id);
        if (updated) setActiveConversation(updated);
      }
    } catch (err) {
      console.error('Error fetching conversations:', err);
    }
  }, [activeConversation]);

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
  }, []);

  // WebSocket Live Realtime Connection
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) return;

    const wsUrl = `ws://localhost:8000/ws?token=${token}`;
    const socket = new WebSocket(wsUrl);

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'NEW_MESSAGE') {
          fetchConversations();
        }
      } catch (err) {
        console.error('WebSocket parse error:', err);
      }
    };

    return () => {
      socket.close();
    };
  }, [fetchConversations]);

  const handleSendMessage = async (text: string) => {
    if (!activeConversation) return;

    await apiFetch(`/conversations/${activeConversation.id}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: activeConversation.id,
        remetente: 'atendente',
        conteudo: text,
        tipo: 'texto'
      })
    });

    fetchConversations();
  };

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      <Sidebar
        user={user}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onLogout={onLogout}
      />

      {activeTab === 'chats' ? (
        <>
          <ChatList
            conversations={conversations}
            activeConversation={activeConversation}
            onSelectConversation={setActiveConversation}
            whatsappNumbers={whatsappNumbers}
            selectedDepartmentId={selectedDeptId}
            setSelectedDepartmentId={setSelectedDeptId}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
          />
          <ChatArea
            conversation={activeConversation}
            currentUser={user}
            onSendMessage={handleSendMessage}
            onOpenTransferModal={() => setIsTransferModalOpen(true)}
          />
        </>
      ) : (
        <AdminPanel />
      )}

      <TransferModal
        isOpen={isTransferModalOpen}
        onClose={() => setIsTransferModalOpen(false)}
        conversation={activeConversation}
        onTransferSuccess={() => {
          fetchConversations();
          setActiveConversation(null);
        }}
      />
    </div>
  );
};
