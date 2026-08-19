import React, { useState, useEffect } from 'react';
import { X, Search, User, Phone, Check } from 'lucide-react';
import { apiFetch } from '../services/api';

interface ContactPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectContact: (contact: { nome: string; telefone: string }) => void;
}

export const ContactPickerModal: React.FC<ContactPickerModalProps> = ({
  isOpen,
  onClose,
  onSelectContact
}) => {
  const [search, setSearch] = useState('');
  const [contacts, setContacts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      apiFetch('/contacts/')
        .then(data => setContacts(data || []))
        .catch(err => console.error('Error loading contacts for picker:', err))
        .finally(() => setLoading(false));
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const filteredContacts = contacts.filter(c => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (c.nome && c.nome.toLowerCase().includes(q)) || (c.telefone && c.telefone.includes(q));
  });

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 2000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '440px',
        borderRadius: 'var(--radius-lg)',
        backgroundColor: '#0b0f19',
        border: '1px solid var(--border-color)',
        overflow: 'hidden',
        boxShadow: '0 24px 48px rgba(0,0,0,0.6)'
      }}>
        {/* Header Estilo WhatsApp Contatos */}
        <div style={{
          padding: '16px 20px',
          backgroundColor: '#111827',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justify: 'space-between',
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(14, 165, 233, 0.15)',
              color: '#0ea5e9',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <User size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#fff' }}>Contatos (Agenda da Empresa)</h3>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{contacts.length} contatos disponíveis</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Search Bar */}
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', backgroundColor: '#111827' }}>
          <div style={{ position: 'relative' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '10px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Pesquisar contatos..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '8px 12px 8px 36px',
                backgroundColor: '#1e293b',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: '#fff',
                fontSize: '13px'
              }}
            />
          </div>
        </div>

        {/* Contacts List */}
        <div style={{ maxHeight: '320px', overflowY: 'auto' }}>
          {loading ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              Carregando contatos...
            </div>
          ) : filteredContacts.length === 0 ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              Nenhum contato encontrado.
            </div>
          ) : (
            filteredContacts.map(c => (
              <div
                key={c.id}
                onClick={() => {
                  onSelectContact({ nome: c.nome || 'Contato', telefone: c.telefone });
                  onClose();
                }}
                style={{
                  padding: '12px 20px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  transition: 'background 0.2s'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{
                    width: '38px',
                    height: '38px',
                    borderRadius: '50%',
                    backgroundColor: 'rgba(14, 165, 233, 0.2)',
                    color: '#0ea5e9',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: '700',
                    fontSize: '14px'
                  }}>
                    {(c.nome || c.telefone).charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: '600', color: '#fff' }}>
                      {c.nome || 'Contato sem nome'}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      📞 {c.telefone}
                    </div>
                  </div>
                </div>
                <span style={{ fontSize: '11px', color: '#0ea5e9', fontWeight: '700' }}>Compartilhar ➔</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
