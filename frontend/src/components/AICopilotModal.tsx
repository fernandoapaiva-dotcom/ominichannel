import React, { useState, useEffect, useRef } from 'react';
import { Bot, Send, X, Sparkles, Copy, Check, CornerDownLeft, RefreshCw, MessageSquare, Wrench, DollarSign, FileText, Trash2, MapPin, Clock, ArrowLeft } from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation, User } from '../types';

interface CopilotMessage {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  suggestedReply?: string;
  hasLocation?: boolean;
  locationData?: {
    name: string;
    address: string;
    latitude: number;
    longitude: number;
  };
  timestamp: string;
}

interface AICopilotModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: Conversation | null;
  currentUser: User;
  onInsertText: (text: string) => void;
}

export const AICopilotModal: React.FC<AICopilotModalProps> = ({
  isOpen,
  onClose,
  conversation,
  currentUser,
  onInsertText
}) => {
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [inputPrompt, setInputPrompt] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [insertedId, setInsertedId] = useState<string | null>(null);
  const [sendingActionId, setSendingActionId] = useState<string | null>(null);
  const [sentActionId, setSentActionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Initialize or reset when conversation changes
  useEffect(() => {
    if (isOpen && conversation) {
      if (messages.length === 0) {
        const custName = conversation.contact?.nome || conversation.contact?.telefone || 'o cliente';
        const deptName = conversation.whatsapp_number?.nome_departamento || 'Atendimento';
        setMessages([
          {
            id: 'init_1',
            sender: 'assistant',
            text: `Olá, ${currentUser.nome}! Sou seu **Copiloto IA Especialista**.\n\nAnalisei o histórico deste chamado com **${custName}** no setor de **${deptName}** e estou conectado à nossa base de manuais técnicos, procedimentos, localização e dados oficiais da Servweld.\n\nComo posso te orientar agora? Escolha uma das opções rápidas abaixo ou faça qualquer pergunta técnica/comercial!`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]);
      }
    }
  }, [isOpen, conversation?.id]);

  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen]);

  if (!isOpen || !conversation) return null;

  const handleSendPrompt = async (promptToSend?: string) => {
    const query = (promptToSend || inputPrompt).trim();
    if (!query || isLoading || !conversation) return;

    const userMsgId = `user_${Date.now()}`;
    const newMsgList: CopilotMessage[] = [
      ...messages,
      {
        id: userMsgId,
        sender: 'user',
        text: query,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ];

    setMessages(newMsgList);
    setInputPrompt('');
    setIsLoading(true);

    try {
      // Build previous copilot exchange
      const chatHistory = newMsgList.map(m => ({
        role: m.sender === 'user' ? 'user' : 'model',
        content: m.text
      }));

      const res = await apiFetch(`/conversations/${conversation.id}/copilot-chat`, {
        method: 'POST',
        body: JSON.stringify({
          user_prompt: query,
          chat_history: chatHistory
        })
      });

      if (res && res.success) {
        setMessages(prev => [
          ...prev,
          {
            id: `copilot_${Date.now()}`,
            sender: 'assistant',
            text: res.answer || 'Análise concluída.',
            suggestedReply: res.suggested_message || undefined,
            hasLocation: Boolean(res.has_location),
            locationData: res.location_data || undefined,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]);
      } else {
        setMessages(prev => [
          ...prev,
          {
            id: `copilot_err_${Date.now()}`,
            sender: 'assistant',
            text: 'Não consegui processar a consulta no momento. Por favor, tente novamente.',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
        ]);
      }
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          id: `copilot_err_${Date.now()}`,
          sender: 'assistant',
          text: `Erro ao consultar Copiloto: ${err.message || 'Falha na comunicação'}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleInsert = (id: string, text: string) => {
    onInsertText(text);
    setInsertedId(id);
    setTimeout(() => {
      setInsertedId(null);
      onClose();
    }, 400);
  };

  const handleSendTextAndLocation = async (msgId: string, textToSend: string, locData?: any) => {
    if (!conversation) return;
    setSendingActionId(msgId);
    try {
      // 1. Send the text message
      await apiFetch(`/conversations/${conversation.id}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          conteudo: textToSend,
          tipo: 'texto'
        })
      });

      // 2. Send the native interactive WhatsApp location pinpoint card
      const targetLoc = locData || {
        name: 'Servweld / Servsolda',
        address: 'SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
        latitude: -15.820418,
        longitude: -47.956467
      };

      await apiFetch(`/conversations/${conversation.id}/send-location`, {
        method: 'POST',
        body: JSON.stringify(targetLoc)
      });

      setSentActionId(msgId);
      setTimeout(() => {
        setSentActionId(null);
        onClose();
      }, 1000);
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar mensagem e localização.');
    } finally {
      setSendingActionId(null);
    }
  };

  const handleSendDirectLocationPin = async (msgId: string, locData?: any) => {
    if (!conversation) return;
    setSendingActionId(`direct_${msgId}`);
    try {
      const targetLoc = locData || {
        name: 'Servweld / Servsolda',
        address: 'SOF Sul Quadra 05 Conjunto A Lote 05 Loja 02 - Guará, Brasília - DF, 71215-226',
        latitude: -15.820418,
        longitude: -47.956467
      };

      await apiFetch(`/conversations/${conversation.id}/send-location`, {
        method: 'POST',
        body: JSON.stringify(targetLoc)
      });

      setSentActionId(`direct_${msgId}`);
      setTimeout(() => {
        setSentActionId(null);
        onClose();
      }, 1000);
    } catch (err: any) {
      alert(err.message || 'Erro ao enviar localização.');
    } finally {
      setSendingActionId(null);
    }
  };

  const handleClearHistory = () => {
    const custName = conversation.contact?.nome || conversation.contact?.telefone || 'o cliente';
    setMessages([
      {
        id: `reset_${Date.now()}`,
        sender: 'assistant',
        text: `Histórico limpo. Como posso te orientar agora no atendimento com **${custName}**?`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }
    ]);
  };

  const customerName = conversation.contact?.nome || conversation.contact?.telefone || 'Cliente';
  const deptName = conversation.whatsapp_number?.nome_departamento || 'Geral';

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(6px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px'
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '780px',
          maxWidth: '96vw',
          height: '84vh',
          backgroundColor: '#0f172a',
          borderRadius: '16px',
          border: '1px solid rgba(0, 230, 153, 0.35)',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6), 0 0 30px rgba(0, 230, 153, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'modalSlideUp 0.2s cubic-bezier(0.16, 1, 0.3, 1)'
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '12px 14px',
            backgroundColor: '#1e293b',
            borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '8px',
            flexShrink: 0,
            flexWrap: 'nowrap'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'rgba(0, 230, 153, 0.15)',
                border: '1px solid rgba(0, 230, 153, 0.3)',
                color: '#00e699',
                cursor: 'pointer',
                padding: '6px',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0
              }}
              title="Voltar para a conversa"
            >
              <ArrowLeft size={18} />
            </button>
            <div
              style={{
                width: '34px',
                height: '34px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #00e699 0%, #059669 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#051a12',
                boxShadow: '0 4px 12px rgba(0, 230, 153, 0.3)',
                flexShrink: 0
              }}
            >
              <Bot size={18} />
            </div>
            <div style={{ minWidth: 0, overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                <span style={{ fontSize: '14px', fontWeight: '800', color: '#ffffff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  Copiloto IA
                </span>
                <span
                  style={{
                    fontSize: '9px',
                    fontWeight: '700',
                    textTransform: 'uppercase',
                    backgroundColor: 'rgba(0, 230, 153, 0.15)',
                    color: 'var(--accent-primary)',
                    padding: '2px 6px',
                    borderRadius: '10px',
                    border: '1px solid rgba(0, 230, 153, 0.3)',
                    flexShrink: 0
                  }}
                >
                  Consultor
                </span>
              </div>
              <p style={{ margin: '1px 0 0 0', fontSize: '10px', color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {customerName} • {deptName}
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <button
              type="button"
              onClick={handleClearHistory}
              title="Limpar histórico de consulta"
              style={{
                background: 'transparent',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '8px',
                padding: '6px 10px',
                color: '#94a3b8',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '11px',
                transition: 'all 0.15s'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#ef4444')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#94a3b8')}
            >
              <Trash2 size={13} />
              <span>Limpar</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: 'none',
                borderRadius: '8px',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#cbd5e1',
                cursor: 'pointer'
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Quick Action Suggestion Chips (Wrap-enabled for all screen sizes) */}
        <div
          style={{
            padding: '10px 16px',
            backgroundColor: '#131d31',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '8px',
            flexShrink: 0
          }}
        >
          <button
            type="button"
            onClick={() => handleSendPrompt('Elabore a melhor sugestão de resposta para eu enviar agora ao cliente com base na última mensagem dele.')}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(0, 230, 153, 0.12)',
              border: '1px solid rgba(0, 230, 153, 0.35)',
              borderRadius: '20px',
              color: 'var(--accent-primary)',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <Sparkles size={13} /> Sugerir Próxima Resposta
          </button>

          <button
            type="button"
            onClick={() => handleSendPrompt(`Elabore uma mensagem pronta calorosa e personalizada para o cliente ${customerName} com base no histórico da conversa dele, informando o endereço oficial da Servweld, horários de funcionamento e avisando que o localizador interativo com mapa GPS está sendo enviado logo abaixo para ele apenas clicar e navegar.`)}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(16, 185, 129, 0.12)',
              border: '1px solid rgba(16, 185, 129, 0.35)',
              borderRadius: '20px',
              color: '#34d399',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <MapPin size={13} /> Endereço & Localização GPS
          </button>

          <button
            type="button"
            onClick={() => handleSendPrompt('Gere a mensagem pronta com o horário oficial de funcionamento da Servweld para eu enviar ao cliente agora.')}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(14, 165, 233, 0.12)',
              border: '1px solid rgba(14, 165, 233, 0.35)',
              borderRadius: '20px',
              color: '#38bdf8',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <Clock size={13} /> Horário de Atendimento
          </button>

          <button
            type="button"
            onClick={() => handleSendPrompt('Gere a mensagem pronta com as orientações e dados oficiais para pagamento via PIX para o cliente.')}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(168, 85, 247, 0.12)',
              border: '1px solid rgba(168, 85, 247, 0.35)',
              borderRadius: '20px',
              color: '#c084fc',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <DollarSign size={13} /> Dados PIX
          </button>

          <button
            type="button"
            onClick={() => handleSendPrompt('Faça um resumo executivo dos pontos principais tratados nesta conversa e o que o cliente precisa.')}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(59, 130, 246, 0.12)',
              border: '1px solid rgba(59, 130, 246, 0.35)',
              borderRadius: '20px',
              color: '#60a5fa',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <FileText size={13} /> Resumo dos Pontos-Chave
          </button>

          <button
            type="button"
            onClick={() => handleSendPrompt('Consulte a base técnica/manuais e me dê o diagnóstico ou passo a passo para o problema relatado.')}
            disabled={isLoading}
            style={{
              padding: '6px 12px',
              backgroundColor: 'rgba(234, 179, 8, 0.12)',
              border: '1px solid rgba(234, 179, 8, 0.35)',
              borderRadius: '20px',
              color: '#facc15',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}
          >
            <Wrench size={13} /> Diagnóstico / Manuais RAG
          </button>
        </div>

        {/* Message Stream */}
        <div
          style={{
            flex: 1,
            padding: '16px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px'
          }}
        >
          {messages.map((msg) => {
            const isUser = msg.sender === 'user';
            return (
              <div
                key={msg.id}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                  gap: '4px',
                  maxWidth: '100%'
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '11px',
                    color: '#64748b',
                    padding: '0 4px'
                  }}
                >
                  <span style={{ fontWeight: '700', color: isUser ? '#60a5fa' : 'var(--accent-primary)' }}>
                    {isUser ? `👤 ${currentUser.nome || 'Você'}` : '🤖 Copiloto IA'}
                  </span>
                  <span>•</span>
                  <span>{msg.timestamp}</span>
                </div>

                <div
                  style={{
                    maxWidth: '88%',
                    padding: '12px 16px',
                    borderRadius: isUser ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                    backgroundColor: isUser ? '#1e3a8a' : '#1e293b',
                    color: '#f8fafc',
                    fontSize: '13px',
                    lineHeight: '1.5',
                    border: isUser ? '1px solid rgba(96, 165, 250, 0.3)' : '1px solid rgba(255, 255, 255, 0.08)',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word'
                  }}
                >
                  {msg.text}

                  {/* Ready-to-Send Suggested Message Card */}
                  {msg.suggestedReply && (() => {
                    const isLocationSuggestion = Boolean(
                      msg.hasLocation ||
                      msg.suggestedReply.toLowerCase().includes('localiza') ||
                      msg.suggestedReply.includes('SOF') ||
                      msg.suggestedReply.includes('71215-226') ||
                      msg.suggestedReply.toLowerCase().includes('gps') ||
                      msg.suggestedReply.toLowerCase().includes('mapa') ||
                      msg.suggestedReply.toLowerCase().includes('endereço') ||
                      msg.suggestedReply.toLowerCase().includes('endereco')
                    );

                    return (
                      <div
                        style={{
                          marginTop: '12px',
                          padding: '12px',
                          backgroundColor: '#0a1e17',
                          border: isLocationSuggestion ? '1px solid rgba(16, 185, 129, 0.6)' : '1px solid rgba(0, 230, 153, 0.4)',
                          borderRadius: '10px',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '8px',
                          boxShadow: isLocationSuggestion ? '0 4px 16px rgba(16, 185, 129, 0.15)' : 'none'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '4px' }}>
                          <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                            <MessageSquare size={13} /> Sugestão Pronta para Enviar ao Cliente:
                          </span>
                          {isLocationSuggestion && (
                            <span style={{
                              fontSize: '10px',
                              fontWeight: '700',
                              backgroundColor: 'rgba(16, 185, 129, 0.2)',
                              color: '#34d399',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(16, 185, 129, 0.4)',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px'
                            }}>
                              <MapPin size={11} /> Inclui Localizador GPS
                            </span>
                          )}
                        </div>

                        <div
                          style={{
                            padding: '8px 10px',
                            backgroundColor: 'rgba(0, 0, 0, 0.3)',
                            borderRadius: '6px',
                            fontStyle: 'italic',
                            color: '#e2e8f0',
                            fontSize: '12px',
                            borderLeft: isLocationSuggestion ? '3px solid #10b981' : '3px solid var(--accent-primary)',
                            whiteSpace: 'pre-wrap'
                          }}
                        >
                          "{msg.suggestedReply}"
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '4px' }}>
                          {/* 1-CLICK SEND TEXT + NATIVE GPS LOCATION PIN */}
                          {isLocationSuggestion && (
                            <button
                              type="button"
                              onClick={() => handleSendTextAndLocation(msg.id, msg.suggestedReply!, msg.locationData)}
                              disabled={sendingActionId === msg.id}
                              style={{
                                width: '100%',
                                padding: '9px 14px',
                                background: 'linear-gradient(135deg, #059669 0%, #10b981 100%)',
                                color: '#ffffff',
                                border: 'none',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: '700',
                                cursor: sendingActionId === msg.id ? 'not-allowed' : 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '6px',
                                boxShadow: '0 2px 10px rgba(16, 185, 129, 0.4)',
                                transition: 'all 0.15s'
                              }}
                            >
                              {sentActionId === msg.id ? (
                                <>
                                  <Check size={15} />
                                  <span>Enviado no WhatsApp com Card GPS!</span>
                                </>
                              ) : sendingActionId === msg.id ? (
                                <>
                                  <RefreshCw size={15} className="animate-spin" />
                                  <span>Enviando Texto + Card GPS no WhatsApp...</span>
                                </>
                              ) : (
                                <>
                                  <MapPin size={15} />
                                  <span>📍 Enviar Mensagem + Localizador GPS no WhatsApp</span>
                                </>
                              )}
                            </button>
                          )}

                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <button
                              type="button"
                              onClick={() => handleInsert(msg.id, msg.suggestedReply!)}
                              style={{
                                flex: 1,
                                padding: '8px 14px',
                                backgroundColor: isLocationSuggestion ? 'rgba(255, 255, 255, 0.1)' : 'var(--accent-primary)',
                                color: isLocationSuggestion ? '#ffffff' : '#051a12',
                                border: isLocationSuggestion ? '1px solid rgba(255, 255, 255, 0.2)' : 'none',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: '700',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '6px',
                                boxShadow: isLocationSuggestion ? 'none' : '0 2px 6px rgba(0, 230, 153, 0.3)',
                                transition: 'all 0.15s'
                              }}
                            >
                              {insertedId === msg.id ? <Check size={14} /> : <CornerDownLeft size={14} />}
                              <span>{insertedId === msg.id ? 'Inserido no Chat!' : 'Inserir no Chat do Cliente'}</span>
                            </button>

                            {isLocationSuggestion && (
                              <button
                                type="button"
                                onClick={() => handleSendDirectLocationPin(msg.id, msg.locationData)}
                                disabled={sendingActionId === `direct_${msg.id}`}
                                title="Enviar apenas o pin de localização do mapa sem texto"
                                style={{
                                  padding: '8px 12px',
                                  backgroundColor: 'rgba(16, 185, 129, 0.15)',
                                  color: '#34d399',
                                  border: '1px solid rgba(16, 185, 129, 0.4)',
                                  borderRadius: '6px',
                                  fontSize: '12px',
                                  fontWeight: '600',
                                  cursor: sendingActionId === `direct_${msg.id}` ? 'not-allowed' : 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '5px'
                                }}
                              >
                                {sentActionId === `direct_${msg.id}` ? (
                                  <>
                                    <Check size={13} color="#34d399" />
                                    <span>Pin Enviado!</span>
                                  </>
                                ) : (
                                  <>
                                    <MapPin size={13} />
                                    <span>Apenas Pin GPS</span>
                                  </>
                                )}
                              </button>
                            )}

                            <button
                              type="button"
                              onClick={() => handleCopy(msg.id, msg.suggestedReply!)}
                              style={{
                                padding: '8px 12px',
                                backgroundColor: 'rgba(255, 255, 255, 0.08)',
                                color: '#f8fafc',
                                border: '1px solid rgba(255, 255, 255, 0.15)',
                                borderRadius: '6px',
                                fontSize: '12px',
                                fontWeight: '600',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '5px'
                              }}
                            >
                              {copiedId === msg.id ? <Check size={13} color="var(--accent-primary)" /> : <Copy size={13} />}
                              <span>{copiedId === msg.id ? 'Copiado!' : 'Copiar'}</span>
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            );
          })}

          {isLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-primary)', fontSize: '13px', padding: '8px 4px' }}>
              <RefreshCw size={16} className="animate-spin" />
              <span>Copiloto IA está analisando a conversa e a base técnica...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div
          style={{
            padding: '12px 16px',
            backgroundColor: '#1e293b',
            borderTop: '1px solid rgba(255, 255, 255, 0.1)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px'
          }}
        >
          <input
            type="text"
            value={inputPrompt}
            onChange={(e) => setInputPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendPrompt();
              }
            }}
            placeholder="Pergunte ao Copiloto IA sobre este cliente, peças, orçamentos, procedimentos..."
            disabled={isLoading}
            style={{
              flex: 1,
              padding: '10px 14px',
              backgroundColor: '#0f172a',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              borderRadius: '8px',
              color: '#ffffff',
              fontSize: '13px',
              outline: 'none'
            }}
          />

          <button
            type="button"
            onClick={() => handleSendPrompt()}
            disabled={!inputPrompt.trim() || isLoading}
            style={{
              padding: '10px 18px',
              backgroundColor: !inputPrompt.trim() || isLoading ? 'rgba(255, 255, 255, 0.1)' : 'var(--accent-primary)',
              color: !inputPrompt.trim() || isLoading ? '#64748b' : '#051a12',
              border: 'none',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: '700',
              cursor: !inputPrompt.trim() || isLoading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: inputPrompt.trim() && !isLoading ? '0 2px 10px rgba(0, 230, 153, 0.3)' : 'none',
              transition: 'all 0.15s'
            }}
          >
            <Send size={15} />
            <span>Consultar</span>
          </button>
        </div>
      </div>
    </div>
  );
};
