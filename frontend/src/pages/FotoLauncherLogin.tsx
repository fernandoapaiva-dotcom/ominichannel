import React, { useState } from 'react';
import { Camera, Wrench, UserRound, Phone, KeyRound, Lock } from 'lucide-react';

interface FotoLauncherLoginProps {
  onLoginSuccess: () => void;
}

// Login combinado do Lancador de Foto: tanto tecnico (telefone+PIN) quanto atendente/admin
// (usuario+senha) usam esse mesmo atalho, entao precisa aceitar as duas sessoes - cada aba
// chama o endpoint de login certo e grava a chave certa no localStorage (tech_token ou token),
// exatamente como TechnicianLogin.tsx / Login.tsx ja fazem separados.
export const FotoLauncherLogin: React.FC<FotoLauncherLoginProps> = ({ onLoginSuccess }) => {
  const [tab, setTab] = useState<'tecnico' | 'atendente'>('tecnico');
  const [telefone, setTelefone] = useState('');
  const [pin, setPin] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmitTecnico = async (e: React.FormEvent) => {
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

  const handleSubmitAtendente = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');
    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username.trim());
      formData.append('password', password.trim());
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || 'Usuário ou senha incorretos');
      }
      const data = await res.json();
      localStorage.setItem('token', data.access_token);
      onLoginSuccess();
    } catch (err: any) {
      setErrorMsg(err.message || 'Erro ao realizar login.');
    } finally {
      setLoading(false);
    }
  };

  const tabBtn = (key: 'tecnico' | 'atendente', label: string, Icon: typeof Wrench) => (
    <button
      type="button"
      onClick={() => { setTab(key); setErrorMsg(''); }}
      style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
        padding: '10px', borderRadius: '8px', border: tab === key ? '1px solid rgba(0,230,153,0.4)' : '1px solid transparent',
        background: tab === key ? 'rgba(0,230,153,0.12)' : 'transparent',
        color: tab === key ? 'var(--accent-primary)' : 'var(--text-muted)',
        fontSize: '13px', fontWeight: 700, cursor: 'pointer',
      }}
    >
      <Icon size={15} /> {label}
    </button>
  );

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
          <Camera size={34} />
        </div>

        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: 700, marginBottom: '6px', textAlign: 'center' }}>
          Foto de O.S.
        </h1>
        <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px', textAlign: 'center' }}>
          Registre fotos/arquivos de uma O.S. direto, sem abrir o sistema inteiro
        </p>

        <div style={{ display: 'flex', gap: '6px', width: '100%', marginBottom: '20px' }}>
          {tabBtn('tecnico', 'Técnico', Wrench)}
          {tabBtn('atendente', 'Atendente', UserRound)}
        </div>

        {errorMsg && (
          <div style={{
            width: '100%', padding: '10px 14px', backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 'var(--radius-md)', color: '#f87171',
            fontSize: '13px', marginBottom: '16px', textAlign: 'center', boxSizing: 'border-box'
          }}>
            {errorMsg}
          </div>
        )}

        {tab === 'tecnico' ? (
          <form onSubmit={handleSubmitTecnico} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Telefone (com DDD)</label>
              <div style={{ position: 'relative' }}>
                <Phone size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
                <input
                  type="tel" inputMode="tel" required autoFocus placeholder="Ex: 61999998888"
                  value={telefone} onChange={(e) => setTelefone(e.target.value)}
                  style={{ width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '16px', outline: 'none', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>PIN</label>
              <div style={{ position: 'relative' }}>
                <KeyRound size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
                <input
                  type="password" inputMode="numeric" required maxLength={6} placeholder="••••"
                  value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  style={{ width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '16px', outline: 'none', letterSpacing: '4px', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <button type="submit" className="btn-primary" disabled={loading} style={{ width: '100%', justifyContent: 'center', marginTop: '8px', padding: '14px', fontSize: '15px' }}>
              {loading ? 'Entrando...' : 'Entrar'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleSubmitAtendente} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Login</label>
              <div style={{ position: 'relative' }}>
                <UserRound size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
                <input
                  type="text" required autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="Ex: admin ou atendente1"
                  value={username} onChange={(e) => setUsername(e.target.value)}
                  style={{ width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '16px', outline: 'none', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>Senha</label>
              <div style={{ position: 'relative' }}>
                <Lock size={16} style={{ position: 'absolute', left: '12px', top: '14px', color: 'var(--text-muted)' }} />
                <input
                  type="password" required autoCapitalize="none" autoCorrect="off" spellCheck={false} placeholder="••••••••"
                  value={password} onChange={(e) => setPassword(e.target.value)}
                  style={{ width: '100%', padding: '13px 12px 13px 38px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '16px', outline: 'none', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <button type="submit" className="btn-primary" disabled={loading} style={{ width: '100%', justifyContent: 'center', marginTop: '8px', padding: '14px', fontSize: '15px' }}>
              {loading ? 'Entrando...' : 'Entrar'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};
