import React, { useEffect, useState } from 'react';
import { LogOut } from 'lucide-react';
import { apiFetch } from './services/api';
import { techApiFetch } from './services/techApi';
import { OsPhotoQuickUploadModal } from './components/TechBoard';
import { FotoLauncherLogin } from './pages/FotoLauncherLogin';

// App standalone (/foto-os) pedido pelo usuário em 05/10/2026: em vez de abrir o sistema inteiro
// pra tirar uma foto de O.S., instala só esse atalho na tela inicial - abre, pergunta a O.S., e já
// manda a foto. Aceita login de técnico OU atendente/admin (cada um grava sua própria sessão -
// tech_token / token - exatamente como os apps completos já fazem, então reaproveita sem conflito
// se o mesmo navegador também tiver os outros dois PWAs instalados).
export const FotoLauncherApp: React.FC = () => {
  const [status, setStatus] = useState<'checking' | 'authed' | 'anon'>('checking');

  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    if (link) link.setAttribute('href', '/foto-manifest.json');
    document.title = 'OminiChannel Foto O.S.';
  }, []);

  const checkAuth = async () => {
    const techToken = localStorage.getItem('tech_token');
    const adminToken = localStorage.getItem('token');
    if (techToken) {
      try {
        await techApiFetch('/me');
        setStatus('authed');
        return;
      } catch {
        localStorage.removeItem('tech_token');
      }
    }
    if (adminToken) {
      try {
        await apiFetch('/auth/me');
        setStatus('authed');
        return;
      } catch {
        localStorage.removeItem('token');
      }
    }
    setStatus('anon');
  };

  useEffect(() => { checkAuth(); }, []);

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('tech_token');
    setStatus('anon');
  };

  if (status === 'checking') {
    return (
      <div style={{
        height: '100dvh', width: '100%', backgroundColor: 'var(--bg-primary)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--accent-primary)', fontFamily: 'var(--font-heading)', fontSize: '16px'
      }}>
        Carregando...
      </div>
    );
  }

  if (status === 'anon') {
    return <FotoLauncherLogin onLoginSuccess={checkAuth} />;
  }

  // onClose do modal reseta só a busca/seleção (ver OsPhotoQuickUploadModal) - não tem "pra onde
  // fechar" aqui, já que essa página É o app inteiro. O botão de sair fica flutuando por cima, com
  // z-index maior que o do modal (30000), pra sempre estar acessível.
  return (
    <div style={{ height: '100dvh', width: '100%', backgroundColor: 'var(--bg-primary)' }}>
      <button
        onClick={handleLogout}
        title="Sair"
        style={{
          position: 'fixed', top: '14px', left: '14px', zIndex: 30001,
          width: '34px', height: '34px', borderRadius: '8px', cursor: 'pointer',
          background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)',
          border: '1px solid var(--border-color, rgba(255,255,255,0.14))',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <LogOut size={16} />
      </button>
      <OsPhotoQuickUploadModal onClose={() => { /* sem "fechar" aqui - a página inteira é isto */ }} />
    </div>
  );
};

export default FotoLauncherApp;
