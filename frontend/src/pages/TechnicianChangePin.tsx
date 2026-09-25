import React, { useState } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { techApiFetch } from '../services/techApi';

interface TechnicianChangePinProps {
  onChanged: () => void;
  nome?: string;
}

export const TechnicianChangePin: React.FC<TechnicianChangePinProps> = ({ onChanged, nome }) => {
  const [newPin, setNewPin] = useState('');
  const [confirmPin, setConfirmPin] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');

    if (!/^\d{4,6}$/.test(newPin)) {
      setErrorMsg('O PIN deve ter de 4 a 6 dígitos numéricos.');
      return;
    }
    if (newPin !== confirmPin) {
      setErrorMsg('Os dois PINs não são iguais.');
      return;
    }

    setLoading(true);
    try {
      await techApiFetch('/change-pin', {
        method: 'POST',
        body: JSON.stringify({ new_pin: newPin }),
      });
      onChanged();
    } catch (err: any) {
      setErrorMsg(err.message || 'Erro ao trocar o PIN.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      height: '100dvh', width: '100%', backgroundColor: 'var(--bg-primary)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px', boxSizing: 'border-box',
      backgroundImage: 'radial-gradient(circle at 50% 30%, rgba(0, 230, 153, 0.08) 0%, transparent 60%)'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%', maxWidth: '380px', padding: '32px 28px', borderRadius: 'var(--radius-lg)',
        display: 'flex', flexDirection: 'column', alignItems: 'center'
      }}>
        <div style={{
          width: '64px', height: '64px', borderRadius: 'var(--radius-md)', background: 'var(--accent-gradient)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 'var(--accent-glow)',
          color: '#051a12', marginBottom: '16px'
        }}>
          <ShieldCheck size={34} />
        </div>

        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: 700, marginBottom: '6px', textAlign: 'center' }}>
          Crie seu PIN
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '26px', textAlign: 'center' }}>
          {nome ? `Olá, ${nome}! ` : ''}Esse é seu primeiro acesso - troque o PIN provisório por um só seu antes de continuar.
        </p>

        {errorMsg && (
          <div style={{
            width: '100%', padding: '10px 14px', backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 'var(--radius-md)', color: '#f87171',
            fontSize: '13px', marginBottom: '16px', textAlign: 'center', boxSizing: 'border-box'
          }}>
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Novo PIN (4 a 6 dígitos)</label>
            <div style={{ position: 'relative' }}>
              <KeyRound size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
              <input
                type="password"
                inputMode="numeric"
                required
                autoFocus
                maxLength={6}
                placeholder="••••"
                value={newPin}
                onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ''))}
                style={{
                  width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)',
                  fontSize: '16px', outline: 'none', letterSpacing: '4px', boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Confirme o novo PIN</label>
            <div style={{ position: 'relative' }}>
              <KeyRound size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
              <input
                type="password"
                inputMode="numeric"
                required
                maxLength={6}
                placeholder="••••"
                value={confirmPin}
                onChange={(e) => setConfirmPin(e.target.value.replace(/\D/g, ''))}
                style={{
                  width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)',
                  fontSize: '16px', outline: 'none', letterSpacing: '4px', boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          <button
            type="submit"
            className="btn-primary"
            disabled={loading}
            style={{ width: '100%', justifyContent: 'center', marginTop: '8px', padding: '14px', fontSize: '15px' }}
          >
            {loading ? 'Salvando...' : 'Salvar e continuar'}
          </button>
        </form>

        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '20px', textAlign: 'center' }}>
          Guarde bem esse PIN - se esquecer, peça pro administrador da loja resetar.
        </p>
      </div>
    </div>
  );
};
