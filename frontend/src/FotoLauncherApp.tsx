import React, { useEffect, useState } from 'react';
import { LogOut, Wrench, Package } from 'lucide-react';
import { apiFetch } from './services/api';
import { techApiFetch } from './services/techApi';
import { OsPhotoQuickUploadModal } from './components/TechBoard';
import { FotoLauncherLogin } from './pages/FotoLauncherLogin';
import { FotoProdutoApp } from './components/FotoProdutoApp';

// App standalone (/foto-os) pedido pelo usuário em 05/10/2026: em vez de abrir o sistema inteiro
// pra tirar uma foto de O.S., instala só esse atalho na tela inicial - abre, pergunta a O.S., e já
// manda a foto. Aceita login de técnico OU atendente/admin (cada um grava sua própria sessão -
// tech_token / token - exatamente como os apps completos já fazem, então reaproveita sem conflito
// se o mesmo navegador também tiver os outros dois PWAs instalados).
export const FotoLauncherApp: React.FC = () => {
  const [status, setStatus] = useState<'checking' | 'authed' | 'anon'>('checking');
  // 15/10/2026: além das fotos de O.S., aba para fotografar os PRODUTOS que chegam (foto de venda com IA)
  const [aba, setAba] = useState<'os' | 'produto'>(() => (localStorage.getItem('foto_app_aba') === 'produto' ? 'produto' : 'os'));
  useEffect(() => { try { localStorage.setItem('foto_app_aba', aba); } catch { /* ok */ } }, [aba]);

  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    if (link) link.setAttribute('href', '/foto-manifest.json');
    document.title = 'OminiChannel Foto';
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

  // Barra fixa no topo (acima do modal de O.S., que usa z-index 30000): sair + as duas abas.
  const abaBtn = (id: 'os' | 'produto', rotulo: string, icone: React.ReactNode) => (
    <button onClick={() => setAba(id)} style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '10px 6px',
      borderRadius: '10px', border: 'none', fontWeight: 700, fontSize: '13.5px', cursor: 'pointer',
      background: aba === id ? 'var(--accent-primary)' : 'rgba(255,255,255,0.06)', color: aba === id ? '#04130d' : 'var(--text-muted)',
    }}>{icone}{rotulo}</button>
  );
  return (
    <div style={{ height: '100dvh', width: '100%', backgroundColor: 'var(--bg-primary)', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 30001, display: 'flex', gap: '8px', alignItems: 'center',
        padding: '10px 12px', background: 'var(--bg-primary)', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.14))',
      }}>
        <button onClick={handleLogout} title="Sair" style={{
          width: '38px', height: '38px', flexShrink: 0, borderRadius: '10px', cursor: 'pointer', background: 'rgba(255,255,255,0.06)',
          color: 'var(--text-muted)', border: '1px solid var(--border-color, rgba(255,255,255,0.14))', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}><LogOut size={16} /></button>
        {abaBtn('os', 'Fotos de O.S.', <Wrench size={15} />)}
        {abaBtn('produto', 'Fotos de Produto', <Package size={15} />)}
      </div>
      {aba === 'os' ? (
        // onClose do modal reseta só a busca/seleção (ver OsPhotoQuickUploadModal) - não tem "pra onde fechar"
        <OsPhotoQuickUploadModal onClose={() => { /* sem "fechar" aqui - a página inteira é isto */ }} />
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', paddingTop: '60px' }}>
          <FotoProdutoApp />
        </div>
      )}
    </div>
  );
};

export default FotoLauncherApp;
