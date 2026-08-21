import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Search, User, Phone, Calendar, MessageSquare, Clock, Building, Bot,
  ChevronRight, FileText, Lock, X, Maximize2, Download, Printer, Copy,
  Check, Play, Volume2, Image as ImageIcon, Video, File, ExternalLink,
  ChevronDown, ChevronUp, Share2, ShieldCheck, ArrowLeft, RefreshCw
} from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation, Message } from '../types';

interface ContactItem {
  id: number;
  tenant_id: number;
  telefone: string;
  nome?: string;
  dados_adicionais?: Record<string, any>;
  total_conversations: number;
  ultima_interacao?: string;
}

export interface ProtocolSession {
  id: string;
  conversationId: number;
  protocolNumber: string;
  department: string;
  status: string;
  startedAt: string;
  closedAt: string | null;
  agentName?: string;
  messages: Message[];
}

export const ContactsPanel: React.FC = () => {
  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedContact, setSelectedContact] = useState<ContactItem | null>(null);
  const [contactHistory, setContactHistory] = useState<Conversation[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Sync state
  const [syncingHistory, setSyncingHistory] = useState(false);
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);

  // Modals state
  const [expandedSession, setExpandedSession] = useState<ProtocolSession | null>(null);
  const [documentExportSession, setDocumentExportSession] = useState<ProtocolSession | null>(null);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const [copiedNotification, setCopiedNotification] = useState(false);

  const printRef = useRef<HTMLDivElement>(null);

  const fetchContacts = async (query = '') => {
    try {
      setLoadingContacts(true);
      const url = query.trim() ? `/contacts/?q=${encodeURIComponent(query.trim())}` : '/contacts/';
      const data = await apiFetch(url);
      setContacts(data);
      if (data.length > 0) {
        const currentStillExists = data.find((c: ContactItem) => c.id === selectedContact?.id);
        if (!currentStillExists) {
          handleSelectContact(data[0]);
        }
      } else {
        setSelectedContact(null);
        setContactHistory([]);
      }
    } catch (err) {
      console.error('Error fetching contacts:', err);
    } finally {
      setLoadingContacts(false);
    }
  };

  const handleSyncAllHistory = async () => {
    setSyncingHistory(true);
    setSyncFeedback('Iniciando sincronização automática em massa de todas as instâncias do WhatsApp...');
    try {
      const res = await apiFetch('/whatsapp-numbers/sync_all', { method: 'POST' });
      setSyncFeedback(res.message || 'Sincronização iniciada com sucesso!');
      setTimeout(() => {
        fetchContacts(search);
      }, 3000);
      setTimeout(() => setSyncFeedback(null), 6000);
    } catch (err: any) {
      setSyncFeedback('Erro ao sincronizar: ' + (err.message || 'Falha na conexão'));
      setTimeout(() => setSyncFeedback(null), 6000);
    } finally {
      setSyncingHistory(false);
    }
  };

  useEffect(() => {
    fetchContacts();
  }, []);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setSearch(val);
    fetchContacts(val);
  };

  const handleClearSearch = () => {
    setSearch('');
    fetchContacts('');
  };

  const handleSelectContact = async (contact: ContactItem) => {
    setSelectedContact(contact);
    try {
      setLoadingHistory(true);
      const historyData = await apiFetch(`/contacts/${contact.id}/conversations`);
      setContactHistory(historyData);
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const resolveMediaUrl = (url: string): string => {
    if (!url) return '';
    if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('data:') || url.startsWith('blob:')) {
      return url;
    }
    const host = typeof window !== 'undefined' && window.location.hostname ? window.location.hostname : 'localhost';
    const clean = url.startsWith('/') ? url : `/${url}`;
    return `http://${host}:8000${clean}`;
  };

  /**
   * Partitions conversations into distinct protocol sessions from start to close
   */
  const protocolSessions = useMemo<ProtocolSession[]>(() => {
    const sessions: ProtocolSession[] = [];

    contactHistory.forEach(conv => {
      const msgs = conv.messages || [];
      if (msgs.length === 0) return;

      let currentSessionMsgs: Message[] = [];
      let currentProtoNum: string | null = (conv as any).protocol_number || null;
      let sessionStart: string = msgs[0]?.timestamp || conv.criado_em;
      let sessionEnd: string | null = null;
      let sessionAgent: string | undefined = undefined;

      msgs.forEach((m, idx) => {
        const text = typeof m.conteudo === 'string' ? m.conteudo : '';

        // Extract protocol number from opening marker
        const openMatch = text.match(/PROTOCOLO\s*(?:FORMAL\s*ABERTO:?)?\s*#?([0-9]{8}-[0-9]{4,5})/i) ||
                          text.match(/Protocolo\s*do\s*seu\s*chamado:?\s*#?([0-9]{8}-[0-9]{4,5})/i) ||
                          text.match(/\+PROTOCOLO\s*#?([0-9]{8}-[0-9]{4,5})/i);

        if (openMatch) {
          currentProtoNum = openMatch[1];
          sessionStart = m.timestamp;
        }

        const agentMatch = text.match(/Atendente:?\s*([A-Za-zÀ-ÿ\s]+)/i) || text.match(/iniciado\s*por\s*([A-Za-zÀ-ÿ\s\.]+)/i);
        if (agentMatch) {
          sessionAgent = agentMatch[1].trim();
        }

        currentSessionMsgs.push(m);

        // Check if protocol closing marker
        const isClosing = text.includes('FINALIZADO') || text.includes('ENCERRADO') || text.includes('finalizado automaticamente');
        if (isClosing || idx === msgs.length - 1) {
          sessionEnd = m.timestamp;
          if (currentProtoNum || currentSessionMsgs.length > 0) {
            sessions.push({
              id: `${conv.id}-${currentProtoNum || 'geral'}-${sessions.length}`,
              conversationId: conv.id,
              protocolNumber: currentProtoNum || 'S/N',
              department: conv.whatsapp_number?.nome_departamento || 'Atendimento Geral',
              status: conv.status,
              startedAt: sessionStart,
              closedAt: isClosing ? sessionEnd : null,
              agentName: sessionAgent,
              messages: [...currentSessionMsgs]
            });
          }
          currentSessionMsgs = [];
          currentProtoNum = null;
        }
      });
    });

    return sessions;
  }, [contactHistory]);

  /**
   * Filter sessions if search query contains protocol number or specific digits
   */
  const filteredSessions = useMemo<ProtocolSession[]>(() => {
    if (!search.trim()) return protocolSessions;
    const cleanSearch = search.trim().toLowerCase().replace('#', '');

    // Check if searching specifically for a protocol
    const matchingSessions = protocolSessions.filter(s => {
      const matchProto = s.protocolNumber.toLowerCase().replace('#', '').includes(cleanSearch);
      const matchInMsgs = s.messages.some(m => typeof m.conteudo === 'string' && m.conteudo.toLowerCase().includes(cleanSearch));
      return matchProto || matchInMsgs;
    });

    return matchingSessions.length > 0 ? matchingSessions : protocolSessions;
  }, [protocolSessions, search]);

  const handlePrintDocument = () => {
    window.print();
  };

  const handleDownloadTxt = (session: ProtocolSession) => {
    const custName = selectedContact?.nome || 'Cliente';
    const custPhone = selectedContact?.telefone || '';
    let txt = `========================================================================\n`;
    txt += `               SERVWELD - RELATÓRIO OFICIAL DE PROTOCOLO               \n`;
    txt += `========================================================================\n\n`;
    txt += `PROTOCOLO:        #${session.protocolNumber}\n`;
    txt += `CLIENTE:          ${custName}\n`;
    txt += `TELEFONE:         ${custPhone}\n`;
    txt += `DEPARTAMENTO:     ${session.department}\n`;
    txt += `ATENDENTE:        ${session.agentName || 'Equipe de Atendimento'}\n`;
    txt += `DATA DE ABERTURA: ${new Date(session.startedAt).toLocaleString('pt-BR')}\n`;
    txt += `DATA DE FECHAMENTO: ${session.closedAt ? new Date(session.closedAt).toLocaleString('pt-BR') : 'Em Aberto'}\n`;
    txt += `STATUS:           ${session.status.toUpperCase()}\n`;
    txt += `\n------------------------------------------------------------------------\n`;
    txt += `                      TRANSCRIÇÃO DAS MENSAGENS                         \n`;
    txt += `------------------------------------------------------------------------\n\n`;

    session.messages.forEach(m => {
      const time = new Date(m.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      const sender = m.remetente === 'cliente' ? custName : m.remetente === 'ia' ? 'IA Concierge' : m.remetente === 'sistema' ? 'SISTEMA' : (session.agentName || 'Atendente');
      txt += `[${time}] ${sender}:\n${m.conteudo}\n\n`;
    });

    txt += `========================================================================\n`;
    txt += `Documento emitido pelo Sistema Servweld Omnichannel em ${new Date().toLocaleString('pt-BR')}\n`;

    const blob = new Blob([txt], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Protocolo_${session.protocolNumber}_${custName.replace(/\s+/g, '_')}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyTranscript = (session: ProtocolSession) => {
    const custName = selectedContact?.nome || 'Cliente';
    let text = `📋 *PROTOCOLO #${session.protocolNumber} - SERVWELD*\n`;
    text += `👤 *Cliente:* ${custName} (${selectedContact?.telefone})\n`;
    text += `🏢 *Setor:* ${session.department}\n\n`;

    session.messages.forEach(m => {
      const time = new Date(m.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
      const sender = m.remetente === 'cliente' ? custName : m.remetente === 'ia' ? 'IA Concierge' : 'Atendente';
      text += `[${time}] *${sender}:* ${m.conteudo}\n\n`;
    });

    navigator.clipboard.writeText(text);
    setCopiedNotification(true);
    setTimeout(() => setCopiedNotification(false), 2500);
  };

  const renderMessageContent = (msg: Message) => {
    const text = typeof msg.conteudo === 'string' ? msg.conteudo : '';
    const tipo = msg.tipo || 'texto';

    const isImage = tipo === 'imagem' || text.endsWith('.png') || text.endsWith('.jpg') || text.endsWith('.jpeg') || text.endsWith('.webp') || text.includes('/uploads/img_');
    const isAudio = tipo === 'audio' || text.endsWith('.ogg') || text.endsWith('.mp3') || text.endsWith('.m4a') || text.includes('/uploads/voice_');
    const isVideo = tipo === 'video' || text.endsWith('.mp4') || text.endsWith('.webm');
    const isDocument = tipo === 'documento' || tipo === 'arquivo' || text.endsWith('.pdf') || text.endsWith('.docx') || text.endsWith('.xlsx');

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {isImage && (
          <div style={{ borderRadius: '8px', overflow: 'hidden', cursor: 'pointer', maxWidth: '280px' }} onClick={() => setLightboxImage(resolveMediaUrl(text))}>
            <img src={resolveMediaUrl(text)} alt="Mídia Anexa" style={{ width: '100%', height: 'auto', maxHeight: '220px', objectFit: 'cover', display: 'block' }} />
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <ImageIcon size={12} /> Clique para expandir imagem
            </div>
          </div>
        )}

        {isAudio && (
          <div style={{ padding: '6px 0', minWidth: '220px' }}>
            <audio controls src={resolveMediaUrl(text)} style={{ width: '100%', height: '36px' }} />
          </div>
        )}

        {isVideo && (
          <div style={{ borderRadius: '8px', overflow: 'hidden', maxWidth: '300px' }}>
            <video controls src={resolveMediaUrl(text)} style={{ width: '100%', maxHeight: '240px' }} />
          </div>
        )}

        {isDocument && (
          <a
            href={resolveMediaUrl(text)}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 12px',
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              borderRadius: '6px',
              color: 'var(--accent-primary)',
              textDecoration: 'none',
              fontSize: '12px',
              fontWeight: '600'
            }}
          >
            <File size={16} /> Ver / Baixar Documento Anexo
          </a>
        )}

        {/* Regular Text (if not a pure media URL or with caption) */}
        {!isImage && !isAudio && !isVideo && !isDocument && (
          <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{text}</div>
        )}
      </div>
    );
  };



  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', backgroundColor: 'var(--bg-primary)', overflow: 'hidden' }}>
      {/* Left List Pane: Contacts Directory */}
      <div style={{
        width: '400px',
        height: '100%',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-primary)',
        flexShrink: 0
      }}>
        <div style={{ padding: '24px 20px', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: '700', margin: 0, color: 'var(--text-main)' }}>
              Histórico de Clientes
            </h2>
            <button
              onClick={handleSyncAllHistory}
              disabled={syncingHistory}
              className="btn-secondary"
              style={{
                height: '30px',
                padding: '0 8px',
                fontSize: '11px',
                fontWeight: '600',
                color: 'var(--accent-primary)',
                borderColor: 'rgba(0, 230, 153, 0.4)',
                backgroundColor: 'rgba(0, 230, 153, 0.08)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}
              title="Puxar todo o histórico antigo e contatos dos WhatsApps conectados automaticamente"
            >
              <RefreshCw size={12} className={syncingHistory ? 'spin' : ''} />
              {syncingHistory ? 'Sincronizando...' : 'Sincronizar WA'}
            </button>
          </div>

          {syncFeedback && (
            <div style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(0, 230, 153, 0.12)',
              border: '1px solid rgba(0, 230, 153, 0.3)',
              color: 'var(--accent-primary)',
              fontSize: '11px',
              fontWeight: '600',
              marginBottom: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <Check size={13} /> {syncFeedback}
            </div>
          )}

          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Buscar por nome, telefone ou protocolo..."
              value={search}
              onChange={handleSearchChange}
              style={{
                width: '100%',
                padding: '10px 36px 10px 36px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '13px',
                outline: 'none'
              }}
            />
            {search && (
              <button
                onClick={handleClearSearch}
                style={{
                  position: 'absolute',
                  right: '10px',
                  top: '10px',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '2px'
                }}
                title="Limpar busca"
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>

        {/* Contacts List */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
          {loadingContacts ? (
            <p style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>
              Carregando contatos...
            </p>
          ) : contacts.length === 0 ? (
            <p style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>
              Nenhum cliente ou protocolo encontrado.
            </p>
          ) : (
            contacts.map(c => {
              const isSelected = selectedContact?.id === c.id;
              return (
                <div
                  key={c.id}
                  onClick={() => handleSelectContact(c)}
                  style={{
                    padding: '14px 16px',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: '8px',
                    backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                    border: isSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: '600', fontSize: '15px', color: isSelected ? 'var(--accent-primary)' : 'var(--text-main)' }}>
                      {c.nome || 'Cliente sem nome'}
                    </span>
                    <span style={{
                      fontSize: '11px',
                      backgroundColor: 'rgba(255, 255, 255, 0.08)',
                      padding: '2px 8px',
                      borderRadius: 'var(--radius-full)',
                      color: 'var(--text-muted)'
                    }}>
                      {c.total_conversations} atendimento{c.total_conversations !== 1 ? 's' : ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Phone size={12} /> {c.telefone}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Right Content Pane: Conversation Timeline Details */}
      <div style={{ flex: 1, height: '100%', overflowY: 'auto', padding: '32px', backgroundColor: 'var(--bg-secondary)' }}>
        {!selectedContact ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            <User size={48} style={{ opacity: 0.3, marginBottom: '16px' }} />
            <p>Selecione um cliente ao lado para visualizar seu histórico de conversas.</p>
          </div>
        ) : (
          <div style={{ maxWidth: '960px', margin: '0 auto' }}>
            {/* Contact Details Header */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', marginBottom: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                  <div style={{
                    width: '52px',
                    height: '52px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(0, 230, 153, 0.15)',
                    color: 'var(--accent-primary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 'bold',
                    fontSize: '20px'
                  }}>
                    {(selectedContact.nome || 'C').charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <h2 style={{ fontSize: '20px', fontWeight: '700', color: 'var(--text-main)' }}>
                      {selectedContact.nome || 'Cliente sem nome'}
                    </h2>
                    <p style={{ fontSize: '14px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                      <Phone size={14} /> Telefone: <strong>{selectedContact.telefone}</strong>
                    </p>
                  </div>
                </div>

                {search && (
                  <div style={{
                    padding: '6px 14px',
                    borderRadius: 'var(--radius-full)',
                    backgroundColor: 'rgba(0, 230, 153, 0.12)',
                    border: '1px solid rgba(0, 230, 153, 0.3)',
                    color: 'var(--accent-primary)',
                    fontSize: '12px',
                    fontWeight: '600',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <FileText size={14} /> Filtrando por: <strong>{search}</strong>
                  </div>
                )}
              </div>
            </div>

            {/* Protocol Sessions Stream */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ fontSize: '18px', fontWeight: '600', color: 'var(--text-main)' }}>
                Sessões de Protocolos Filtradas ({filteredSessions.length})
              </h3>
              {copiedNotification && (
                <span style={{ fontSize: '12px', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Check size={14} /> Transcrição copiada com sucesso!
                </span>
              )}
            </div>

            {loadingHistory ? (
              <p style={{ color: 'var(--text-muted)' }}>Carregando histórico do cliente...</p>
            ) : filteredSessions.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', padding: '20px', textAlign: 'center' }}>
                Nenhum protocolo correspondente encontrado para este cliente.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                {filteredSessions.map(session => (
                  <div
                    key={session.id}
                    className="glass-panel"
                    style={{
                      padding: '22px',
                      borderRadius: 'var(--radius-lg)',
                      border: '1px solid var(--border-color)',
                      backgroundColor: 'var(--bg-primary)'
                    }}
                  >
                    {/* Session Card Header */}
                    <div style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      paddingBottom: '14px',
                      borderBottom: '1px solid var(--border-color)',
                      marginBottom: '16px',
                      flexWrap: 'wrap',
                      gap: '12px'
                    }}>
                      <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{
                          fontSize: '13px',
                          fontWeight: '800',
                          color: 'var(--accent-primary)',
                          backgroundColor: 'rgba(0, 230, 153, 0.15)',
                          border: '1px solid rgba(0, 230, 153, 0.4)',
                          padding: '4px 10px',
                          borderRadius: '8px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px'
                        }}>
                          <FileText size={14} /> Protocolo: #{session.protocolNumber}
                        </span>

                        <span style={{ fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Building size={14} /> Dpto: <strong>{session.department}</strong>
                        </span>

                        <span style={{ fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Calendar size={14} /> Aberto: {new Date(session.startedAt).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}
                        </span>

                        {session.closedAt && (
                          <span style={{ fontSize: '13px', color: '#f59e0b', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <Lock size={13} /> Fechado: {new Date(session.closedAt).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })}
                          </span>
                        )}
                      </div>

                      {/* Action Buttons: Expand, Export, Copy */}
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button
                          onClick={() => setExpandedSession(session)}
                          className="btn-secondary"
                          style={{
                            height: '32px',
                            padding: '0 10px',
                            fontSize: '12px',
                            fontWeight: '600',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '5px'
                          }}
                          title="Expandir protocolo em tela cheia para leitura e visualização de mídias"
                        >
                          <Maximize2 size={13} /> Expandir
                        </button>

                        <button
                          onClick={() => setDocumentExportSession(session)}
                          className="btn-secondary"
                          style={{
                            height: '32px',
                            padding: '0 10px',
                            fontSize: '12px',
                            fontWeight: '600',
                            color: 'var(--accent-primary)',
                            borderColor: 'rgba(0, 230, 153, 0.4)',
                            backgroundColor: 'rgba(0, 230, 153, 0.08)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '5px'
                          }}
                          title="Gerar documento oficial / Salvar como PDF para enviar"
                        >
                          <Printer size={13} /> Salvar Documento / PDF
                        </button>

                        <button
                          onClick={() => handleCopyTranscript(session)}
                          className="btn-secondary"
                          style={{
                            height: '32px',
                            padding: '0 8px',
                            fontSize: '12px'
                          }}
                          title="Copiar transcrição"
                        >
                          <Copy size={13} />
                        </button>
                      </div>
                    </div>

                    {/* Messages Stream of this Protocol */}
                    <div style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px',
                      maxHeight: '320px',
                      overflowY: 'auto',
                      paddingRight: '6px'
                    }}>
                      {session.messages.map(msg => {
                        const isSystem = msg.remetente === 'sistema';
                        const textContent = typeof msg.conteudo === 'string' ? msg.conteudo : '';
                        const isProtocolClosed = textContent.includes('FINALIZADO') || textContent.includes('ENCERRADO') || textContent.includes('finalizado automaticamente');
                        const isProtocolOpened = textContent.includes('PROTOCOLO FORMAL ABERTO');

                        if (isProtocolClosed) {
                          return (
                            <div key={msg.id} style={{
                              alignSelf: 'center',
                              margin: '8px 0',
                              padding: '6px 14px',
                              borderRadius: 'var(--radius-full)',
                              backgroundColor: 'rgba(245, 158, 11, 0.12)',
                              border: '1px solid rgba(245, 158, 11, 0.3)',
                              color: '#f59e0b',
                              fontSize: '11px',
                              fontWeight: '600',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '6px'
                            }}>
                              <Lock size={12} />
                              <span>{textContent.replace(/[*_]/g, '')}</span>
                            </div>
                          );
                        }

                        if (isProtocolOpened) {
                          return (
                            <div key={msg.id} style={{
                              alignSelf: 'center',
                              margin: '8px 0',
                              padding: '6px 14px',
                              borderRadius: 'var(--radius-full)',
                              backgroundColor: 'rgba(0, 230, 153, 0.12)',
                              border: '1px solid rgba(0, 230, 153, 0.3)',
                              color: 'var(--accent-primary)',
                              fontSize: '11px',
                              fontWeight: '700',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '6px'
                            }}>
                              <FileText size={12} />
                              <span>{textContent.replace(/[*_]/g, '')}</span>
                            </div>
                          );
                        }

                        return (
                          <div
                            key={msg.id}
                            style={{
                              padding: '10px 14px',
                              borderRadius: 'var(--radius-md)',
                              backgroundColor: msg.remetente === 'cliente' ? '#1c283e' : isSystem ? 'rgba(59, 130, 246, 0.12)' : 'rgba(0, 230, 153, 0.12)',
                              alignSelf: msg.remetente === 'cliente' ? 'flex-start' : isSystem ? 'center' : 'flex-end',
                              maxWidth: '82%',
                              fontSize: '13px'
                            }}
                          >
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', gap: '14px' }}>
                              <span style={{ fontWeight: '700', color: msg.remetente === 'ia' ? 'var(--status-ia)' : msg.remetente === 'cliente' ? 'var(--text-muted)' : 'var(--accent-primary)' }}>
                                {msg.remetente === 'cliente' ? (selectedContact?.nome || 'Cliente') : msg.remetente === 'ia' ? 'IA Concierge' : msg.remetente === 'sistema' ? 'Sistema' : 'Atendente'}
                              </span>
                              <span>{new Date(msg.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
                            </div>
                            {renderMessageContent(msg)}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      {expandedSession && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          zIndex: 9999,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px'
        }}>
          <div style={{
            width: '90%',
            maxWidth: '1000px',
            height: '90vh',
            backgroundColor: 'var(--bg-primary)',
            borderRadius: 'var(--radius-lg)',
            border: '1px solid var(--border-color)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            boxShadow: '0 20px 50px rgba(0,0,0,0.6)'
          }}>
            {/* Modal Header */}
            <div style={{
              padding: '20px 24px',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              backgroundColor: 'var(--bg-secondary)'
            }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{
                    fontSize: '15px',
                    fontWeight: '800',
                    color: 'var(--accent-primary)',
                    backgroundColor: 'rgba(0, 230, 153, 0.15)',
                    border: '1px solid rgba(0, 230, 153, 0.4)',
                    padding: '4px 12px',
                    borderRadius: '8px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}>
                    <FileText size={16} /> PROTOCOLO #{expandedSession.protocolNumber}
                  </span>
                  <h3 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-main)' }}>
                    {selectedContact?.nome || 'Cliente'} - {expandedSession.department}
                  </h3>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Aberto em {new Date(expandedSession.startedAt).toLocaleString('pt-BR')} • {expandedSession.messages.length} mensagens
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={() => setDocumentExportSession(expandedSession)}
                  className="btn-primary"
                  style={{ height: '36px', padding: '0 14px', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <Printer size={15} /> Exportar / PDF
                </button>
                <button
                  onClick={() => setExpandedSession(null)}
                  className="btn-secondary"
                  style={{ height: '36px', width: '36px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Modal Body: Large Message Stream */}
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px', backgroundColor: 'var(--bg-secondary)' }}>
              {expandedSession.messages.map(msg => (
                <div
                  key={msg.id}
                  style={{
                    padding: '12px 16px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: msg.remetente === 'cliente' ? '#1c283e' : msg.remetente === 'sistema' ? 'rgba(59, 130, 246, 0.12)' : 'rgba(0, 230, 153, 0.12)',
                    alignSelf: msg.remetente === 'cliente' ? 'flex-start' : msg.remetente === 'sistema' ? 'center' : 'flex-end',
                    maxWidth: '75%',
                    fontSize: '14px',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
                  }}
                >
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'flex', justifyContent: 'space-between', gap: '16px' }}>
                    <span style={{ fontWeight: '700', color: msg.remetente === 'ia' ? 'var(--status-ia)' : msg.remetente === 'cliente' ? 'var(--text-muted)' : 'var(--accent-primary)' }}>
                      {msg.remetente === 'cliente' ? (selectedContact?.nome || 'Cliente') : msg.remetente === 'ia' ? '🤖 IA Concierge' : msg.remetente === 'sistema' ? '⚙️ Sistema' : '👤 Atendente'}
                    </span>
                    <span>{new Date(msg.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  {renderMessageContent(msg)}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 2. EXPORT / PRINT FORMAL DOCUMENT MODAL */}
      {documentExportSession && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100vw',
          height: '100vh',
          backgroundColor: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          zIndex: 10000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '20px'
        }}>
          <div style={{
            width: '90%',
            maxWidth: '900px',
            height: '92vh',
            backgroundColor: '#ffffff',
            color: '#111827',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            boxShadow: '0 25px 60px rgba(0,0,0,0.5)'
          }}>
            {/* Print Action Bar (Hidden when printing) */}
            <div className="no-print" style={{
              padding: '16px 24px',
              backgroundColor: '#1f2937',
              color: '#ffffff',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <ShieldCheck size={20} style={{ color: '#10b981' }} />
                <span style={{ fontWeight: '700', fontSize: '15px' }}>Documento Oficial de Atendimento</span>
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  onClick={() => handleDownloadTxt(documentExportSession)}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '6px',
                    border: '1px solid #4b5563',
                    backgroundColor: '#374151',
                    color: '#ffffff',
                    fontSize: '13px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  <Download size={15} /> Baixar .TXT
                </button>

                <button
                  onClick={handlePrintDocument}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '6px',
                    border: 'none',
                    backgroundColor: '#10b981',
                    color: '#ffffff',
                    fontSize: '13px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  <Printer size={15} /> Imprimir / Salvar como PDF
                </button>

                <button
                  onClick={() => setDocumentExportSession(null)}
                  style={{
                    padding: '8px',
                    borderRadius: '6px',
                    border: 'none',
                    backgroundColor: '#374151',
                    color: '#9ca3af',
                    cursor: 'pointer'
                  }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Printable Document Body */}
            <div ref={printRef} style={{ flex: 1, overflowY: 'auto', padding: '40px 48px', backgroundColor: '#ffffff' }}>
              {/* Document Header */}
              <div style={{ borderBottom: '2px solid #e5e7eb', paddingBottom: '20px', marginBottom: '24px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <h1 style={{ fontSize: '24px', fontWeight: '800', color: '#111827', margin: 0, letterSpacing: '-0.5px' }}>
                      SERVWELD EQUIPAMENTOS E SERVIÇOS
                    </h1>
                    <p style={{ fontSize: '13px', color: '#6b7280', margin: '4px 0 0 0' }}>
                      Sistema de Atendimento e Gestão Omnichannel • Relatório Oficial de Chamado
                    </p>
                  </div>
                  <div style={{
                    padding: '8px 16px',
                    backgroundColor: '#f0fdf4',
                    border: '2px solid #86efac',
                    borderRadius: '8px',
                    textAlign: 'right'
                  }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: '#15803d', textTransform: 'uppercase', display: 'block' }}>
                      Protocolo de Atendimento
                    </span>
                    <span style={{ fontSize: '18px', fontWeight: '900', color: '#166534' }}>
                      #{documentExportSession.protocolNumber}
                    </span>
                  </div>
                </div>
              </div>

              {/* Metadata Table */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: '12px',
                padding: '16px',
                backgroundColor: '#f9fafb',
                borderRadius: '8px',
                border: '1px solid #e5e7eb',
                marginBottom: '28px',
                fontSize: '13px'
              }}>
                <div><strong>Cliente:</strong> {selectedContact?.nome || 'Cliente'}</div>
                <div><strong>Telefone:</strong> {selectedContact?.telefone}</div>
                <div><strong>Departamento:</strong> {documentExportSession.department}</div>
                <div><strong>Atendente Responsável:</strong> {documentExportSession.agentName || 'Equipe Servweld'}</div>
                <div><strong>Data de Abertura:</strong> {new Date(documentExportSession.startedAt).toLocaleString('pt-BR')}</div>
                <div><strong>Data de Encerramento:</strong> {documentExportSession.closedAt ? new Date(documentExportSession.closedAt).toLocaleString('pt-BR') : 'Em Aberto'}</div>
              </div>

              {/* Transcript Section */}
              <h2 style={{ fontSize: '16px', fontWeight: '700', color: '#374151', marginBottom: '14px', borderBottom: '1px solid #e5e7eb', paddingBottom: '6px' }}>
                Histórico e Transcrição das Interações
              </h2>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {documentExportSession.messages.map((m, i) => {
                  const time = new Date(m.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
                  const sender = m.remetente === 'cliente' ? (selectedContact?.nome || 'Cliente') : m.remetente === 'ia' ? 'IA Concierge Servweld' : m.remetente === 'sistema' ? 'SISTEMA' : (documentExportSession.agentName || 'Atendente');
                  const isClient = m.remetente === 'cliente';

                  return (
                    <div
                      key={i}
                      style={{
                        padding: '10px 14px',
                        borderRadius: '6px',
                        backgroundColor: isClient ? '#f3f4f6' : '#ecfdf5',
                        borderLeft: `4px solid ${isClient ? '#9ca3af' : '#10b981'}`,
                        fontSize: '13px',
                        lineHeight: '1.5'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '11px', color: '#6b7280', fontWeight: '600' }}>
                        <span style={{ color: isClient ? '#374151' : '#047857' }}>{sender}</span>
                        <span>{time}</span>
                      </div>
                      <div style={{ whiteSpace: 'pre-wrap', color: '#1f2937' }}>{m.conteudo}</div>
                    </div>
                  );
                })}
              </div>

              {/* Document Footer */}
              <div style={{ marginTop: '40px', paddingTop: '20px', borderTop: '1px solid #e5e7eb', textAlign: 'center', fontSize: '11px', color: '#9ca3af' }}>
                Este documento é uma transcrição oficial gerada automaticamente pelo Sistema Servweld Omnichannel em {new Date().toLocaleString('pt-BR')}.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 3. LIGHTBOX IMAGE MODAL */}
      {lightboxImage && (
        <div
          onClick={() => setLightboxImage(null)}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100vw',
            height: '100vh',
            backgroundColor: 'rgba(0,0,0,0.92)',
            zIndex: 11000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            cursor: 'zoom-out'
          }}
        >
          <img
            src={lightboxImage}
            alt="Zoom da Imagem"
            style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain', borderRadius: '8px', boxShadow: '0 10px 30px rgba(0,0,0,0.8)' }}
          />
        </div>
      )}
    </div>
  );
};
