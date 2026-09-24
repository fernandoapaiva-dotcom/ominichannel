import React, { useEffect, useState } from 'react';
import { techApiFetch } from './services/techApi';
import { TechnicianLogin } from './pages/TechnicianLogin';
import { TechnicianPortal } from './pages/TechnicianPortal';

export const TechnicianPortalApp: React.FC = () => {
  const [authed, setAuthed] = useState(false);
  const [loading, setLoading] = useState(true);

  // index.css trava html/body/#root em overflow:hidden !important no celular (o app administrativo
  // depende disso pra controlar o próprio scroll internamente) - !important sempre vence estilo
  // inline via JS, então a única forma de liberar o scroll da página aqui é por uma classe CSS com
  // especificidade maior (ver a regra "tech-portal-scroll" em index.css). Aplicada durante toda a
  // vida do Portal do Técnico (login + quadro), removida ao sair pro app administrativo não ser afetado.
  useEffect(() => {
    document.documentElement.classList.add('tech-portal-scroll');
    document.body.classList.add('tech-portal-scroll');
    document.getElementById('root')?.classList.add('tech-portal-scroll');
    return () => {
      document.documentElement.classList.remove('tech-portal-scroll');
      document.body.classList.remove('tech-portal-scroll');
      document.getElementById('root')?.classList.remove('tech-portal-scroll');
    };
  }, []);

  const checkAuth = async () => {
    const token = localStorage.getItem('tech_token');
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      await techApiFetch('/me');
      setAuthed(true);
    } catch {
      localStorage.removeItem('tech_token');
      setAuthed(false);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { checkAuth(); }, []);

  if (loading) {
    return (
      <div style={{
        height: '100dvh', width: '100%', backgroundColor: 'var(--bg-primary)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--accent-primary)', fontFamily: 'var(--font-heading)', fontSize: '16px'
      }}>
        Carregando Portal do Técnico...
      </div>
    );
  }

  if (!authed) {
    return <TechnicianLogin onLoginSuccess={() => setAuthed(true)} />;
  }

  return <TechnicianPortal onLogout={() => setAuthed(false)} />;
};

export default TechnicianPortalApp;
