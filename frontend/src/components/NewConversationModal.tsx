import React, { useState, useEffect } from 'react';
import { X, Send, Phone, Building, User, MessageSquare, Search } from 'lucide-react';
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
  const [phone, setPhone] = useState('');
  const [contactName, setContactName] = useState('');
  const [initialMessage, setInitialMessage] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [contacts, setContacts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      // Load existing tenant contacts for quick selection
      apiFetch('/contacts/')
        .then(data => setContacts(data || []))
        .catch(err => console.error('Error fetching contacts for modal:', err));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredContacts = contacts.filter(c => {
    if (!searchQuery.trim()) return false;
    const q = searchQuery.toLowerCase();
    const nameMatch = c.nome && c.nome.toLowerCase().includes(q);
    const phoneMatch = c.telefone && c.telefone.includes(q);
    return nameMatch || phoneMatch;
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWnId) {
      alert('Por favor, selecione um departamento / número de WhatsApp.');
      return;
    }

    const cleanPhone = phone.replace(/\D/g, '');
    if (!cleanPhone || cleanPhone.length < 8) {
      alert('Por favor, informe um número de telefone válido.');
      return;
    }

    try {
      setLoading(true);
      const conv = await apiFetch('/conversations/start', {
        method: 'POST',
        body: JSON.stringify({
          whatsapp_number_id: selectedWnId,
          telefone: cleanPhone,
          nome: contactName.trim() || undefined,
          mensagem_inicial: initialMessage.trim() || undefined
        })
      });

      onConversationCreated(conv);
      onClose();
      setPhone('');
      setContactName('');
      setInitialMessage('');
    } catch (err: any) {
      alert(err.message || 'Erro ao iniciar nova conversa.');
    } finally {
      setLoading(false);
    }
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
      zIndex: 1000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '480px',
        borderRadius: 'var(--radius-lg)',
        padding: '28px',
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        boxShadow: '0 20px 40px rgba(0, 0, 0, 0.4)'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <MessageSquare size={20} />
            </div>
            <h3 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-main)' }}>
              Nova Conversa
            </h3>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'transparent', color: 'var(--text-muted)', border: 'none', cursor: 'pointer' }}
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', display: 'block' }}>
              Departamento / Número de Envio
            </label>
            <select
              value={selectedWnId || (whatsappNumbers[0]?.id || 0)}
              onChange={(e) => setSelectedWnId(Number(e.target.value))}
              style={{
                width: '100%',
                padding: '10px 12px',
                backgroundColor: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '14px'
              }}
            >
              {whatsappNumbers.map(wn => (
                <option key={wn.id} value={wn.id}>
                  {wn.nome_departamento} ({wn.numero})
                </option>
              ))}
            </select>
          </div>

          {/* Quick Contact Search / Autocomplete */}
          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>🔍 Buscar em Contatos Cadastrados</span>
              {contacts.length > 0 && <span style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '600' }}>{contacts.length} contato(s) na agenda</span>}
            </label>
            <div style={{ position: 'relative' }}>
              <Search size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="Digite o nome ou telefone do cliente..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px 10px 38px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '14px'
                }}
              />
            </div>

            {/* Filtered Search Suggestions Dropdown */}
            {filteredContacts.length > 0 && searchQuery.trim() !== '' && (
              <div style={{
                maxHeight: '160px',
                overflowY: 'auto',
                backgroundColor: 'var(--bg-primary)',
                border: '1px solid var(--accent-primary)',
                borderRadius: 'var(--radius-md)',
                marginTop: '6px',
                display: 'flex',
                flexDirection: 'column',
                boxShadow: '0 8px 16px rgba(0,0,0,0.5)',
                zIndex: 10
              }}>
                {filteredContacts.map(c => (
                  <div
                    key={c.id}
                    onClick={() => {
                      setPhone(c.telefone);
                      setContactName(c.nome || '');
                      setSearchQuery('');
                    }}
                    style={{
                      padding: '10px 12px',
                      borderBottom: '1px solid var(--border-color)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      backgroundColor: 'rgba(0, 230, 153, 0.05)'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <div style={{
                        width: '28px',
                        height: '28px',
                        borderRadius: '50%',
                        backgroundColor: 'rgba(0, 230, 153, 0.2)',
                        color: 'var(--accent-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontWeight: '700',
                        fontSize: '12px'
                      }}>
                        {(c.nome || c.telefone).charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>
                          {c.nome || 'Contato sem nome'}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          📞 {c.telefone}
                        </div>
                      </div>
                    </div>
                    <span style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '700' }}>Selecionar ➔</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', display: 'block' }}>
              Número do Destinatário (com DDD e DDI 55)
            </label>
            <div style={{ position: 'relative' }}>
              <Phone size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                required
                placeholder="Ex: 5511999998888"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px 10px 38px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '14px'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', display: 'block' }}>
              Nome do Contato (Opcional)
            </label>
            <div style={{ position: 'relative' }}>
              <User size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="Ex: Maria Silva"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px 10px 38px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '14px'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', display: 'block' }}>
              Mensagem Inicial (Opcional)
            </label>
            <textarea
              rows={3}
              placeholder="Digite uma mensagem inicial para ser enviada..."
              value={initialMessage}
              onChange={(e) => setInitialMessage(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 12px',
                backgroundColor: 'var(--bg-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '14px',
                resize: 'none'
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '12px' }}>
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
            >
              Cancelar
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={loading}
            >
              <Send size={16} /> {loading ? 'Iniciando...' : 'Iniciar Conversa'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
