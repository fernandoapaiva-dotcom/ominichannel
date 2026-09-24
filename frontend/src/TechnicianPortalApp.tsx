import React, { useEffect, useState } from 'react';
import { techApiFetch } from './services/techApi';
import { TechnicianLogin } from './pages/TechnicianLogin';
import { TechnicianPortal } from './pages/TechnicianPortal';

export const TechnicianPortalApp: React.FC = () => {
  const [authed, setAuthed] = useState(false);
  const [loading, setLoading] = useState(true);

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
        height: '100vh', width: '100vw', backgroundColor: 'var(--bg-primary)',
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
