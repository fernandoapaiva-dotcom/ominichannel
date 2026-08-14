import React, { useState, useEffect } from 'react';
import { Search, User, Phone, Calendar, MessageSquare, Clock, Building, Bot, ChevronRight } from 'lucide-react';
import { apiFetch } from '../services/api';
import { Conversation } from '../types';

interface ContactItem {
  id: number;
  tenant_id: number;
  telefone: string;
  nome?: string;
  dados_adicionais?: Record<string, any>;
  total_conversations: number;
  ultima_interacao?: string;
}

export const ContactsPanel: React.FC = () => {
  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedContact, setSelectedContact] = useState<ContactItem | null>(null);
  const [contactHistory, setContactHistory] = useState<Conversation[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const fetchContacts = async (query = '') => {
    try {
      setLoadingContacts(true);
      const url = query.trim() ? `/contacts/?q=${encodeURIComponent(query.trim())}` : '/contacts/';
      const data = await apiFetch(url);
      setContacts(data);
      if (data.length > 0 && !selectedContact) {
        handleSelectContact(data[0]);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoadingContacts(false);
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

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', backgroundColor: 'var(--bg-primary)', overflow: 'hidden' }}>
      {/* Left List Pane: Contacts Directory */}
      <div style={{
        width: '380px',
        height: '100%',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-primary)'
      }}>
        <div style={{ padding: '24px 20px', borderBottom: '1px solid var(--border-color)' }}>
          <h2 style={{ fontFamily: 'var(--font-heading)', fontSize: '22px', fontWeight: '700', marginBottom: '16px' }}>
            Histórico de Clientes
          </h2>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Buscar cliente por nome ou telefone..."
              value={search}
              onChange={handleSearchChange}
              style={{
                width: '100%',
                padding: '10px 12px 10px 36px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '13px',
                outline: 'none'
              }}
            />
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
              Nenhum cliente encontrado.
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
          <div style={{ maxWidth: '900px', margin: '0 auto' }}>
            {/* Contact Details Header */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', marginBottom: '24px' }}>
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
            </div>

            {/* Conversation History Timeline */}
            <h3 style={{ fontSize: '18px', fontWeight: '600', marginBottom: '16px', color: 'var(--text-main)' }}>
              Linha do Tempo de Atendimentos ({contactHistory.length})
            </h3>

            {loadingHistory ? (
              <p style={{ color: 'var(--text-muted)' }}>Carregando histórico do cliente...</p>
            ) : contactHistory.length === 0 ? (
              <p style={{ color: 'var(--text-muted)' }}>Nenhum histórico de conversa registrado para este cliente.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {contactHistory.map(conv => (
                  <div key={conv.id} className="glass-panel" style={{ padding: '20px', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-color)' }}>
                    {/* Conversation Info Header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '12px', borderBottom: '1px solid var(--border-color)', marginBottom: '14px' }}>
                      <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
                        <span className={`badge badge-${conv.status}`}>
                          {conv.status.replace('_', ' ')}
                        </span>
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Building size={14} /> Dpto: <strong>{conv.whatsapp_number?.nome_departamento || 'Geral'}</strong>
                        </span>
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Calendar size={14} /> {new Date(conv.criado_em).toLocaleDateString('pt-BR')} às {new Date(conv.criado_em).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {conv.messages.length} mensagem{conv.messages.length !== 1 ? 'ns' : ''}
                      </span>
                    </div>

                    {/* Messages Transcript inside Conversation */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '250px', overflowY: 'auto', paddingRight: '4px' }}>
                      {conv.messages.map(msg => (
                        <div
                          key={msg.id}
                          style={{
                            padding: '8px 12px',
                            borderRadius: 'var(--radius-md)',
                            backgroundColor: msg.remetente === 'cliente' ? '#1c283e' : 'rgba(0, 230, 153, 0.12)',
                            alignSelf: msg.remetente === 'cliente' ? 'flex-start' : 'flex-end',
                            maxWidth: '80%',
                            fontSize: '13px'
                          }}
                        >
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '2px', display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                            <span>{msg.remetente === 'cliente' ? 'Cliente' : msg.remetente === 'ia' ? 'IA Concierge' : 'Atendente'}</span>
                            <span>{new Date(msg.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}</span>
                          </div>
                          <div>{msg.conteudo}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
