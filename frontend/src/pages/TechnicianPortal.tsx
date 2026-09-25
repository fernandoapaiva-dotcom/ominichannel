import React, { useCallback, useEffect, useState } from 'react';
import { LogOut, RefreshCw, User as UserIcon } from 'lucide-react';
import { techApiFetch } from '../services/techApi';
import { MobileBoard, BoardGrid, BoardData } from '../components/TechBoard';

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

  // Igual ao quadro administrativo (TechBoard.tsx): tela estreita em retrato vira lista; deitada ou
  // desktop usa a mesma grade com cabeçalho colorido por estágio, ocupando 100% da largura disponível.
  const [isNarrow, setIsNarrow] = useState<boolean>(() => typeof window !== 'undefined' && window.innerWidth < 860);
  const [isLandscape, setIsLandscape] = useState<boolean>(() => typeof window !== 'undefined' && window.innerWidth > window.innerHeight);
  useEffect(() => {
    const onResize = () => {
      setIsNarrow(window.innerWidth < 860);
      setIsLandscape(window.innerWidth > window.innerHeight);
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);
  const useMobileLayout = isNarrow && !isLandscape;

  const [zoom, setZoomState] = useState<number>(() => {
    try {
      const v = parseFloat(localStorage.getItem('omni_tech_portal_zoom') || '1');
      return isFinite(v) && v > 0 ? v : 1;
    } catch { return 1; }
  });
  const setZoom = (next: number) => {
    const clamped = Math.max(0.8, Math.min(1.6, Math.round(next * 100) / 100));
    setZoomState(clamped);
    try { localStorage.setItem('omni_tech_portal_zoom', String(clamped)); } catch {}
  };

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
    // Confirmado em produção: em paisagem (BoardGrid, container flex:'1 1 0%'+minHeight:0+overflow:
    // hidden por fora e overflow:auto por dentro) o toque rola normal nesse aparelho - então o mesmo
    // padrão (região interna com overflow, não a página inteira) também é usado no retrato agora, em
    // vez do scroll nativo da página que não deu certo.
    <div style={{ height: '100dvh', width: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)', boxSizing: 'border-box', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', padding: '14px 16px 10px', flexShrink: 0 }}>
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

      <div style={{ display: 'flex', gap: '6px', padding: '0 16px 10px', flexShrink: 0 }}>
        <button
          onClick={() => setTab('meus')}
          style={{ flex: 1, padding: '9px', fontSize: '13px', fontWeight: 700, borderRadius: '8px', cursor: 'pointer', background: tab === 'meus' ? 'rgba(0,230,153,0.16)' : 'transparent', color: tab === 'meus' ? 'var(--accent-primary)' : 'var(--text-muted)', border: `1px solid ${tab === 'meus' ? 'rgba(0,230,153,0.4)' : 'var(--border-color, rgba(255,255,255,0.12))'}` }}
        >Minhas O.S.</button>
        <button
          onClick={() => setTab('geral')}
          style={{ flex: 1, padding: '9px', fontSize: '13px', fontWeight: 700, borderRadius: '8px', cursor: 'pointer', background: tab === 'geral' ? 'rgba(0,230,153,0.16)' : 'transparent', color: tab === 'geral' ? 'var(--accent-primary)' : 'var(--text-muted)', border: `1px solid ${tab === 'geral' ? 'rgba(0,230,153,0.4)' : 'var(--border-color, rgba(255,255,255,0.12))'}` }}
        >Quadro Geral</button>
      </div>

      <div style={{ display: 'flex', gap: '4px', padding: '0 16px 10px', flexShrink: 0 }}>
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
        <div style={{ margin: '0 16px 10px', padding: '10px 14px', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontSize: '13px', flexShrink: 0 }}>{error}</div>
      )}

      {!useMobileLayout && (
        <div style={{ position: 'fixed', right: '14px', bottom: '14px', zIndex: 50, display: 'flex', flexDirection: 'column', gap: '6px', background: 'var(--bg-secondary, rgba(20,24,32,0.92))', border: '1px solid var(--border-color, rgba(255,255,255,0.14))', borderRadius: '10px', padding: '4px', boxShadow: '0 4px 14px rgba(0,0,0,0.35)' }}>
          <button onClick={() => setZoom(zoom + 0.15)} title="Aumentar zoom" style={{ width: '36px', height: '36px', fontSize: '16px', fontWeight: 800, borderRadius: 'var(--radius-md, 8px)', cursor: 'pointer', background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))' }}>+</button>
          <button onClick={() => setZoom(zoom - 0.15)} title="Diminuir zoom" style={{ width: '36px', height: '36px', fontSize: '16px', fontWeight: 800, borderRadius: 'var(--radius-md, 8px)', cursor: 'pointer', background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))' }}>−</button>
        </div>
      )}

      <div style={{ flex: '1 1 0%', minHeight: 0, minWidth: 0, padding: '0 16px 16px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {useMobileLayout ? (
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
        ) : (
          <BoardGrid
            board={board}
            loading={loading}
            scale={zoom}
            isAdmin={false}
            showEmpresa={!empresa}
            onOpenCell={() => {}}
          />
        )}
      </div>
    </div>
  );
};
