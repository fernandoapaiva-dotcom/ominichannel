import React, { useEffect, useState } from 'react';
import { techApiFetch } from './services/techApi';
import { TechnicianLogin } from './pages/TechnicianLogin';
import { TechnicianChangePin } from './pages/TechnicianChangePin';
import { TechnicianPortal } from './pages/TechnicianPortal';

interface TechnicianMe {
  id: number;
  nome: string;
  cargo?: string | null;
  departamento?: string | null;
  must_change_pin: boolean;
}

export const TechnicianPortalApp: React.FC = () => {
  const [me, setMe] = useState<TechnicianMe | null>(null);
  const [loading, setLoading] = useState(true);

  // Troca o manifesto da aba principal pelo do técnico (nome, ícone e start_url próprios) - sem
  // isso, instalar/gerar o app (TWA/"Adicionar à tela inicial") a partir de /tecnico pegava o
  // manifesto do sistema administrativo, com o start_url errado.
  useEffect(() => {
    const link = document.querySelector('link[rel="manifest"]');
    if (link) link.setAttribute('href', '/tecnico-manifest.json');
    document.title = 'OminiChannel Técnico';
  }, []);

  const checkAuth = async () => {
    const token = localStorage.getItem('tech_token');
    if (!token) {
      setLoading(false);
      setMe(null);
      return;
    }
    try {
      const data = await techApiFetch('/me');
      setMe(data);
    } catch {
      localStorage.removeItem('tech_token');
      setMe(null);
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

  if (!me) {
    // Depois do login, reconsulta /me (em vez de só marcar "logado") pra já saber se esse PIN é
    // provisório (must_change_pin) e decidir a próxima tela certa.
    return <TechnicianLogin onLoginSuccess={checkAuth} />;
  }

  if (me.must_change_pin) {
    return <TechnicianChangePin onChanged={checkAuth} nome={me.nome} />;
  }

  return <TechnicianPortal onLogout={() => setMe(null)} />;
};

export default TechnicianPortalApp;
