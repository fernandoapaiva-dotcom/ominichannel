import React, { useState } from 'react';
import { Wrench, Phone, KeyRound } from 'lucide-react';

interface TechnicianLoginProps {
  onLoginSuccess: () => void;
}

export const TechnicianLogin: React.FC<TechnicianLoginProps> = ({ onLoginSuccess }) => {
  const [telefone, setTelefone] = useState('');
  const [pin, setPin] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');
    setLoading(true);
    try {
      const res = await fetch('/api/v1/technician-portal/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ telefone: telefone.trim(), pin: pin.trim() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Telefone ou PIN inválido.');
      }
      const data = await res.json();
      localStorage.setItem('tech_token', data.access_token);
      onLoginSuccess();
    } catch (err: any) {
      setErrorMsg(err.message || 'Erro ao entrar.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', width: '100vw', backgroundColor: 'var(--bg-primary)',
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
          <Wrench size={34} />
        </div>

        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: 700, marginBottom: '6px', textAlign: 'center' }}>
          Portal do Técnico
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '26px', textAlign: 'center' }}>
          Entre com seu telefone e seu PIN de acesso
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
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Telefone (com DDD)</label>
            <div style={{ position: 'relative' }}>
              <Phone size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
              <input
                type="tel"
                inputMode="tel"
                required
                autoFocus
                placeholder="Ex: 61999998888"
                value={telefone}
                onChange={(e) => setTelefone(e.target.value)}
                style={{
                  width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)',
                  fontSize: '16px', outline: 'none', boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>PIN</label>
            <div style={{ position: 'relative' }}>
              <KeyRound size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
              <input
                type="password"
                inputMode="numeric"
                required
                maxLength={6}
                placeholder="••••"
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
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
            {loading ? 'Entrando...' : 'Entrar'}
          </button>
        </form>

        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '20px', textAlign: 'center' }}>
          Não tem um PIN ainda? Fale com o administrador da loja.
        </p>
      </div>
    </div>
  );
};
