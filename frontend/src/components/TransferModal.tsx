import React, { useState, useEffect } from 'react';
import { X, ArrowRightLeft, Sparkles, Building, User as UserIcon } from 'lucide-react';
import { User, Conversation, WhatsAppNumber } from '../types';
import { apiFetch } from '../services/api';

interface TransferModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: Conversation | null;
  onTransferSuccess: () => void;
}

export const TransferModal: React.FC<TransferModalProps> = ({
  isOpen,
  onClose,
  conversation,
  onTransferSuccess
}) => {
  const [users, setUsers] = useState<User[]>([]);
  const [departments, setDepartments] = useState<WhatsAppNumber[]>([]);
  const [selectedDeptId, setSelectedDeptId] = useState<string>('');
  const [selectedUserId, setSelectedUserId] = useState<string>('');
  const [motivo, setMotivo] = useState('');
  const [gerarResumoIa, setGerarResumoIa] = useState(true);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      Promise.all([
        apiFetch('/users/'),
        apiFetch('/whatsapp-numbers/')
      ])
        .then(([userData, deptData]) => {
          setUsers(userData);
          setDepartments(deptData);
          if (conversation?.whatsapp_number_id) {
            setSelectedDeptId(conversation.whatsapp_number_id.toString());
          }
        })
        .catch((err) => console.error(err));
    }
  }, [isOpen, conversation]);

  if (!isOpen || !conversation) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      setLoading(true);
      await apiFetch(`/conversations/${conversation.id}/transfer`, {
        method: 'POST',
        body: JSON.stringify({
          para_whatsapp_number_id: selectedDeptId ? parseInt(selectedDeptId) : null,
          para_user_id: selectedUserId ? parseInt(selectedUserId) : null,
          motivo: motivo.trim() || 'Transferência de atendimento',
          gerar_resumo_ia: gerarResumoIa
        })
      });
      onTransferSuccess();
      onClose();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Erro ao transferir');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    }}>
      <div className="glass-panel" style={{
        width: '480px',
        padding: '24px',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        border: '1px solid var(--border-color)'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ fontFamily: 'var(--font-heading)', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-main)' }}>
            <ArrowRightLeft size={20} style={{ color: 'var(--accent-primary)' }} /> Transferir Atendimento
          </h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Target Department / Sector Selection */}
          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-main)', marginBottom: '6px', fontWeight: '600' }}>
              <Building size={15} style={{ color: 'var(--accent-primary)' }} /> Setor / Departamento Destino:
            </label>
            <select
              value={selectedDeptId}
              onChange={(e) => setSelectedDeptId(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '14px',
                outline: 'none'
              }}
            >
              <option value="">Manter departamento atual</option>
              {departments.map((dept) => (
                <option key={dept.id} value={dept.id}>
                  📁 {dept.nome_departamento} ({dept.numero})
                </option>
              ))}
            </select>
          </div>

          {/* Target User / Attendant Selection */}
          <div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-main)', marginBottom: '6px', fontWeight: '600' }}>
              <UserIcon size={15} style={{ color: 'var(--accent-primary)' }} /> Atendente Específico (Opcional):
            </label>
            <select
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '14px',
                outline: 'none'
              }}
            >
              <option value="">Fila do Setor (Sem atendente específico)</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  👤 {u.nome} ({u.role})
                </option>
              ))}
            </select>
          </div>

          {/* AI Summary Checkbox Card */}
          <div style={{
            padding: '12px',
            backgroundColor: 'rgba(168, 85, 247, 0.08)',
            border: '1px solid rgba(168, 85, 247, 0.25)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px'
          }}>
            <input
              type="checkbox"
              id="gerarResumoIa"
              checked={gerarResumoIa}
              onChange={(e) => setGerarResumoIa(e.target.checked)}
              style={{ marginTop: '3px', width: '16px', height: '16px', accentColor: '#c084fc', cursor: 'pointer' }}
            />
            <label htmlFor="gerarResumoIa" style={{ cursor: 'pointer', fontSize: '12px', color: 'var(--text-main)', lineHeight: '1.4' }}>
              <strong style={{ color: '#c084fc', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Sparkles size={14} /> Resumo Automático da Conversa via IA Gemini
              </strong>
              A IA analisará todo o histórico da conversa e criará um resumo executivo com os principais pontos para o novo atendente estar 100% ciente.
            </label>
          </div>

          {/* Motivo Input */}
          <div>
            <label style={{ display: 'block', fontSize: '13px', color: 'var(--text-muted)', marginBottom: '6px' }}>
              Motivo ou Instrução da Transferência:
            </label>
            <textarea
              rows={2}
              placeholder="Ex: Cliente deseja agendar visita técnica presencial..."
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '13px',
                outline: 'none',
                resize: 'none'
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '4px' }}>
            <button type="button" onClick={onClose} className="btn-secondary" disabled={loading}>
              Cancelar
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={loading}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>🤖 Analisando Histórico & Transferindo...</>
              ) : (
                <><ArrowRightLeft size={16} /> Confirmar Transferência</>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
