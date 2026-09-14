import React, { useState, useEffect, useRef } from 'react';
import { X, Phone, User, MessageSquare, Search, RefreshCw, Send, ChevronDown, CheckCircle2 } from 'lucide-react';
import { WhatsAppNumber, Conversation } from '../types';
import { apiFetch } from '../services/api';

interface NewConversationModalProps {
  isOpen: boolean;
  onClose: () => void;
  whatsappNumbers: WhatsAppNumber[];
  onConversationCreated: (conv: Conversation) => void;
}

export const NewConversationModal: React.FC<NewConversationModalProps> = ({
  isOpen,
  onClose,
  whatsappNumbers,
  onConversationCreated
}) => {
  const [selectedWnId, setSelectedWnId] = useState<number>(whatsappNumbers[0]?.id || 0);
  const [searchQuery, setSearchQuery] = useState('');
  const [contacts, setContacts] = useState<any[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [syncingAgenda, setSyncingAgenda] = useState(false);
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
  const [startingPhone, setStartingPhone] = useState<string | null>(null);

  // Optional initial message
  const [showInitialMessageInput, setShowInitialMessageInput] = useState(false);
  const [initialMessage, setInitialMessage] = useState('');

  const searchInputRef = useRef<HTMLInputElement>(null);

  // Update selected line if whatsappNumbers change
  useEffect(() => {
    if (whatsappNumbers.length > 0 && !selectedWnId) {
      setSelectedWnId(whatsappNumbers[0].id);
    }
  }, [whatsappNumbers, selectedWnId]);

  // Load contacts or search with debounce
  useEffect(() => {
    if (!isOpen) return;

    // Focus search input on open
    setTimeout(() => {
      searchInputRef.current?.focus();
    }, 150);

    const timer = setTimeout(() => {
      fetchContactsList(searchQuery);
    }, searchQuery ? 200 : 0);

    return () => clearTimeout(timer);
  }, [isOpen, searchQuery]);

  const fetchContactsList = async (q: string) => {
    try {
      setLoadingContacts(true);
      const url = q.trim()
        ? `/contacts/?q=${encodeURIComponent(q.trim())}&limit=60`
        : `/contacts/?limit=80`;
      const data = await apiFetch(url);
      setContacts(data || []);
    } catch (err) {
      console.error('Error fetching contacts for modal:', err);
    } finally {
      setLoadingContacts(false);
    }
  };

  const handleSyncAgenda = async () => {
    if (syncingAgenda) return;
    try {
      setSyncingAgenda(true);
      setSyncFeedback('Puxando contatos do telefone...');
      const res = await apiFetch('/contacts/sync-agenda', { method: 'POST' });
      setSyncFeedback(res.message || 'Agenda sincronizada com sucesso!');
      await fetchContactsList(searchQuery);
      setTimeout(() => setSyncFeedback(null), 4000);
    } catch (err: any) {
      setSyncFeedback('Erro ao sincronizar: ' + (err.message || 'Falha na conexão'));
      setTimeout(() => setSyncFeedback(null), 4000);
    } finally {
      setSyncingAgenda(false);
    }
  };

  const handleStartChatWithContact = async (contactPhone: string, contactName?: string) => {
    const cleanPhone = contactPhone.replace(/\D/g, '');
    if (!cleanPhone || cleanPhone.length < 8) {
      alert('Número de telefone inválido.');
      return;
    }

    const currentWnId = selectedWnId || (whatsappNumbers[0]?.id || 0);
    if (!currentWnId) {
      alert('Selecione um departamento / linha de WhatsApp para enviar.');
      return;
    }

    try {
      setStartingPhone(cleanPhone);
      const conv = await apiFetch('/conversations/start', {
        method: 'POST',
        body: JSON.stringify({
          whatsapp_number_id: currentWnId,
          telefone: cleanPhone,
          nome: contactName?.trim() || undefined,
          mensagem_inicial: initialMessage.trim() || undefined
        })
      });

      onConversationCreated(conv);
      onClose();
      setSearchQuery('');
      setInitialMessage('');
      setShowInitialMessageInput(false);
    } catch (err: any) {
      alert(err.message || 'Erro ao iniciar nova conversa.');
    } finally {
      setStartingPhone(null);
    }
  };

  if (!isOpen) return null;

  const rawDigits = searchQuery.replace(/\D/g, '');
  const isSearchPhoneLike = rawDigits.length >= 8;

  // Format phone display e.g. +55 (61) 99999-9999
  const formatPhone = (p: string) => {
    const digits = p.replace(/\D/g, '');
    if (digits.length === 13 && digits.startsWith('55')) {
      return `+55 (${digits.slice(2, 4)}) ${digits.slice(4, 9)}-${digits.slice(9)}`;
    }
    if (digits.length === 12 && digits.startsWith('55')) {
      return `+55 (${digits.slice(2, 4)}) ${digits.slice(4, 8)}-${digits.slice(8)}`;
    }
    if (digits.length === 11) {
      return `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
    }
    return p;
  };

  const getInitials = (name?: string, phone?: string) => {
    if (name && name.trim()) {
      const parts = name.trim().split(' ');
      if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
      }
      return parts[0].slice(0, 2).toUpperCase();
    }
    return (phone || '??').slice(-2);
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1100,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '520px',
        maxHeight: '90vh',
        borderRadius: 'var(--radius-lg)',
        backgroundColor: '#0f172a',
        border: '1px solid rgba(255, 255, 255, 0.12)',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.6)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px 16px 24px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: '#131e36'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '50%',
              backgroundColor: 'rgba(0, 230, 153, 0.18)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <MessageSquare size={22} />
            </div>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: '700', color: '#f8fafc', margin: 0 }}>
                Nova Conversa
              </h3>
              <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0, marginTop: '2px' }}>
                Selecione um contato da agenda do telefone ou digite um número
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              color: '#94a3b8',
              border: 'none',
              borderRadius: '50%',
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Department / Sender line selector */}
        <div style={{
          padding: '12px 24px',
          backgroundColor: 'rgba(255, 255, 255, 0.02)',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
          <span style={{ fontSize: '12px', color: '#94a3b8', whiteSpace: 'nowrap' }}>
            Enviar pelo WhatsApp:
          </span>
          <select
            value={selectedWnId || (whatsappNumbers[0]?.id || 0)}
            onChange={(e) => setSelectedWnId(Number(e.target.value))}
            style={{
              flex: 1,
              padding: '7px 12px',
              backgroundColor: '#1e293b',
              border: '1px solid var(--border-color)',
              borderRadius: 'var(--radius-md)',
              color: '#f8fafc',
              fontSize: '13px',
              fontWeight: '600',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            {whatsappNumbers.map(wn => (
              <option key={wn.id} value={wn.id}>
                {wn.nome_departamento} ({wn.numero})
              </option>
            ))}
          </select>
        </div>

        {/* Search Bar & Sync Action */}
        <div style={{ padding: '14px 24px 10px 24px' }}>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={17} style={{ position: 'absolute', left: '14px', color: '#94a3b8' }} />
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Pesquisar por nome ou número do telefone..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '11px 40px 11px 40px',
                backgroundColor: '#1e293b',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '24px',
                color: '#f8fafc',
                fontSize: '14px',
                outline: 'none',
                boxShadow: 'inset 0 1px 3px rgba(0,0,0,0.3)'
              }}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                style={{
                  position: 'absolute',
                  right: '12px',
                  background: 'none',
                  border: 'none',
                  color: '#94a3b8',
                  cursor: 'pointer'
                }}
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* Sync Agenda Button & Status */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: '10px',
            fontSize: '11px'
          }}>
            <span style={{ color: '#94a3b8' }}>
              {contacts.length > 0 ? `${contacts.length} contatos encontrados` : 'Carregando agenda...'}
            </span>
            <button
              type="button"
              onClick={handleSyncAgenda}
              disabled={syncingAgenda}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--accent-primary)',
                cursor: syncingAgenda ? 'default' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                fontWeight: '600',
                padding: '3px 6px',
                borderRadius: '6px'
              }}
              title="Puxar contatos mais recentes salvos no chip do WhatsApp"
            >
              <RefreshCw size={12} className={syncingAgenda ? 'animate-spin' : ''} />
              {syncingAgenda ? 'Sincronizando...' : 'Puxar contatos do telefone'}
            </button>
          </div>

          {syncFeedback && (
            <div style={{
              marginTop: '6px',
              padding: '6px 12px',
              backgroundColor: 'rgba(0, 230, 153, 0.12)',
              border: '1px solid rgba(0, 230, 153, 0.25)',
              borderRadius: '6px',
              color: 'var(--accent-primary)',
              fontSize: '11px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              <CheckCircle2 size={13} />
              {syncFeedback}
            </div>
          )}
        </div>

        {/* Contacts Scrollable List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '4px 12px 12px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          minHeight: '260px',
          maxHeight: '400px'
        }}>
          {/* Direct Option: Start conversation with typed phone number if phone-like */}
          {isSearchPhoneLike && (
            <div
              onClick={() => handleStartChatWithContact(rawDigits, 'Novo Contato')}
              style={{
                padding: '12px 16px',
                backgroundColor: 'rgba(0, 230, 153, 0.12)',
                border: '1px dashed var(--accent-primary)',
                borderRadius: 'var(--radius-md)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'all 0.15s ease'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{
                  width: '40px',
                  height: '40px',
                  borderRadius: '50%',
                  backgroundColor: 'var(--accent-primary)',
                  color: '#0f172a',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: '700'
                }}>
                  <Phone size={18} />
                </div>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: '700', color: '#f8fafc' }}>
                    Conversar com {formatPhone(rawDigits)}
                  </div>
                  <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                    Número não salvo na agenda • Clique para abrir chat
                  </div>
                </div>
              </div>
              <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                {startingPhone === rawDigits ? 'Abrindo...' : 'Iniciar ➔'}
              </span>
            </div>
          )}

          {/* Loading Indicator */}
          {loadingContacts && contacts.length === 0 && (
            <div style={{ textAlign: 'center', padding: '40px 16px', color: '#94a3b8' }}>
              <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 8px auto', color: 'var(--accent-primary)' }} />
              <p style={{ fontSize: '13px' }}>Buscando contatos na agenda...</p>
            </div>
          )}

          {/* Empty State */}
          {!loadingContacts && contacts.length === 0 && !isSearchPhoneLike && (
            <div style={{ textAlign: 'center', padding: '40px 16px', color: '#94a3b8' }}>
              <User size={32} style={{ margin: '0 auto 8px auto', opacity: 0.5 }} />
              <p style={{ fontSize: '14px', fontWeight: '600', color: '#f8fafc' }}>Nenhum contato encontrado</p>
              <p style={{ fontSize: '12px', marginTop: '4px' }}>
                Você pode digitar o número com DDD acima para iniciar conversa diretamente.
              </p>
            </div>
          )}

          {/* Contact Items */}
          {contacts.map((c) => {
            const isStarting = startingPhone === c.telefone.replace(/\D/g, '');
            const isFromAgenda = c.dados_adicionais?.origin === 'phone_agenda';

            return (
              <div
                key={c.id}
                onClick={() => !isStarting && handleStartChatWithContact(c.telefone, c.nome)}
                style={{
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-md)',
                  cursor: isStarting ? 'wait' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  backgroundColor: isStarting ? 'rgba(0, 230, 153, 0.15)' : 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  transition: 'background-color 0.15s ease'
                }}
                onMouseEnter={(e) => {
                  if (!isStarting) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.08)';
                }}
                onMouseLeave={(e) => {
                  if (!isStarting) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0, flex: 1 }}>
                  {/* Avatar */}
                  <div style={{ position: 'relative', flexShrink: 0 }}>
                    {c.foto_perfil_url ? (
                      <img
                        src={c.foto_perfil_url}
                        alt={c.nome || c.telefone}
                        referrerPolicy="no-referrer"
                        style={{
                          width: '42px',
                          height: '42px',
                          borderRadius: '50%',
                          objectFit: 'cover',
                          border: '1px solid rgba(255, 255, 255, 0.1)'
                        }}
                        onError={(e) => {
                          e.currentTarget.style.display = 'none';
                        }}
                      />
                    ) : (
                      <div style={{
                        width: '42px',
                        height: '42px',
                        borderRadius: '50%',
                        backgroundColor: '#1e293b',
                        border: '1px solid rgba(0, 230, 153, 0.3)',
                        color: 'var(--accent-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontWeight: '700',
                        fontSize: '14px'
                      }}>
                        {getInitials(c.nome, c.telefone)}
                      </div>
                    )}
                  </div>

                  {/* Name and Phone */}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{
                      fontSize: '14px',
                      fontWeight: '700',
                      color: '#f8fafc',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>
                      {c.nome || 'Contato sem nome'}
                    </div>
                    <div style={{ fontSize: '12px', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px', marginTop: '2px' }}>
                      <span>{formatPhone(c.telefone)}</span>
                      {isFromAgenda && (
                        <span style={{
                          fontSize: '10px',
                          padding: '1px 6px',
                          borderRadius: '10px',
                          backgroundColor: 'rgba(59, 130, 246, 0.15)',
                          color: '#60a5fa',
                          fontWeight: '600'
                        }}>
                          Agenda
                        </span>
                      )}
                      {c.total_conversations > 0 && (
                        <span style={{ fontSize: '11px', color: '#64748b' }}>
                          • {c.total_conversations} conversa(s)
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Action button */}
                <div style={{ marginLeft: '12px', flexShrink: 0 }}>
                  {isStarting ? (
                    <span style={{ fontSize: '12px', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <RefreshCw size={13} className="animate-spin" /> Abrindo...
                    </span>
                  ) : (
                    <span style={{
                      fontSize: '12px',
                      color: 'var(--accent-primary)',
                      fontWeight: '600',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      backgroundColor: 'rgba(0, 230, 153, 0.1)',
                      padding: '5px 10px',
                      borderRadius: '16px'
                    }}>
                      Conversar
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Optional Initial Message Drawer */}
        <div style={{
          padding: '12px 20px',
          borderTop: '1px solid var(--border-color)',
          backgroundColor: '#131e36'
        }}>
          {!showInitialMessageInput ? (
            <button
              type="button"
              onClick={() => setShowInitialMessageInput(true)}
              style={{
                background: 'none',
                border: 'none',
                color: '#94a3b8',
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <span>✏️ Enviar uma mensagem inicial junto com a abertura? (Opcional)</span>
              <ChevronDown size={14} />
            </button>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ fontSize: '12px', color: '#94a3b8', fontWeight: '600' }}>
                  Mensagem Inicial (será enviada assim que clicar no contato):
                </label>
                <button
                  type="button"
                  onClick={() => {
                    setShowInitialMessageInput(false);
                    setInitialMessage('');
                  }}
                  style={{ background: 'none', border: 'none', color: '#64748b', fontSize: '11px', cursor: 'pointer' }}
                >
                  Ocultar
                </button>
              </div>
              <textarea
                rows={2}
                placeholder="Olá! Como posso ajudar você hoje?"
                value={initialMessage}
                onChange={(e) => setInitialMessage(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  backgroundColor: '#1e293b',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: 'var(--radius-md)',
                  color: '#f8fafc',
                  fontSize: '13px',
                  resize: 'none',
                  outline: 'none'
                }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
