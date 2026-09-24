import React, { useCallback, useEffect, useState } from 'react';
import { LogOut, RefreshCw, User as UserIcon } from 'lucide-react';
import { techApiFetch } from '../services/techApi';
import { MobileBoard, BoardData } from '../components/TechBoard';

interface TechnicianMe {
  id: number;
  nome: string;
  cargo?: string | null;
  departamento?: string | null;
}

interface TechnicianPortalProps {
  onLogout: () => void;
}

const EMPRESAS: { key: string; label: string }[] = [
  { key: '', label: 'Todas' },
  { key: 'servweld', label: 'Servweld' },
  { key: 'centrooeste', label: 'Centro-Oeste' },
];

export const TechnicianPortal: React.FC<TechnicianPortalProps> = ({ onLogout }) => {
  const [me, setMe] = useState<TechnicianMe | null>(null);
  const [tab, setTab] = useState<'geral' | 'meus'>('meus');
  const [empresa, setEmpresa] = useState('');
  const [board, setBoard] = useState<BoardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState('');

  useEffect(() => {
    techApiFetch('/me').then(setMe).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (empresa) qs.set('empresa', empresa);
      const endpoint = tab === 'meus' ? '/my-orders' : '/board';
      const data = await techApiFetch(`${endpoint}?${qs.toString()}`);
      setBoard(data);
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível carregar o quadro.');
    } finally {
      setLoading(false);
    }
  }, [tab, empresa]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  useEffect(() => {
    const interval = window.setInterval(load, 60000);
    return () => window.clearInterval(interval);
  }, [load]);
  useEffect(() => { setStageFilter(''); }, [tab]);

  const handleLogout = () => {
    localStorage.removeItem('tech_token');
    onLogout();
  };

  return (
    <div style={{ height: '100vh', width: '100vw', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', padding: '14px 16px 10px' }}>
        <div style={{ width: '34px', height: '34px', borderRadius: '50%', background: 'rgba(0,230,153,0.16)', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <UserIcon size={17} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {me?.nome || 'Técnico'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{me?.cargo || 'Portal do Técnico'}</div>
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={() => { setLoading(true); load(); }} title="Atualizar" style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
        <button onClick={handleLogout} title="Sair" style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
          <LogOut size={14} />
        </button>
      </div>

      <div style={{ display: 'flex', gap: '6px', padding: '0 16px 10px' }}>
        <button
          onClick={() => setTab('meus')}
          style={{ flex: 1, padding: '9px', fontSize: '13px', fontWeight: 700, borderRadius: '8px', cursor: 'pointer', background: tab === 'meus' ? 'rgba(0,230,153,0.16)' : 'transparent', color: tab === 'meus' ? 'var(--accent-primary)' : 'var(--text-muted)', border: `1px solid ${tab === 'meus' ? 'rgba(0,230,153,0.4)' : 'var(--border-color, rgba(255,255,255,0.12))'}` }}
        >Minhas O.S.</button>
        <button
          onClick={() => setTab('geral')}
          style={{ flex: 1, padding: '9px', fontSize: '13px', fontWeight: 700, borderRadius: '8px', cursor: 'pointer', background: tab === 'geral' ? 'rgba(0,230,153,0.16)' : 'transparent', color: tab === 'geral' ? 'var(--accent-primary)' : 'var(--text-muted)', border: `1px solid ${tab === 'geral' ? 'rgba(0,230,153,0.4)' : 'var(--border-color, rgba(255,255,255,0.12))'}` }}
        >Quadro Geral</button>
      </div>

      <div style={{ display: 'flex', gap: '4px', padding: '0 16px 10px' }}>
        {EMPRESAS.map(e => (
          <button
            key={e.key || 'todas'}
            onClick={() => setEmpresa(e.key)}
            style={{
              padding: '6px 12px', fontSize: '12px', fontWeight: 700, cursor: 'pointer', borderRadius: '8px',
              background: empresa === e.key ? 'rgba(59,130,246,0.16)' : 'transparent',
              color: empresa === e.key ? '#60a5fa' : 'var(--text-muted)',
              border: `1px solid ${empresa === e.key ? 'rgba(59,130,246,0.4)' : 'var(--border-color, rgba(255,255,255,0.12))'}`,
            }}
          >{e.label}</button>
        ))}
      </div>

      {error && (
        <div style={{ margin: '0 16px 10px', padding: '10px 14px', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontSize: '13px' }}>{error}</div>
      )}

      <div style={{ flex: 1, minHeight: 0, padding: '0 16px 16px', display: 'flex' }}>
        <MobileBoard
          board={board}
          loading={loading}
          stageFilter={stageFilter}
          setStageFilter={setStageFilter}
          isAdmin={false}
          onOpenTech={() => {}}
          showEmpresa={!empresa}
          onOpenCell={() => {}}
        />
      </div>
    </div>
  );
};
