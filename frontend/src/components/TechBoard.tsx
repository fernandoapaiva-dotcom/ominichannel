import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Download, Monitor, RefreshCw, X } from 'lucide-react';
import { apiFetch } from '../services/api';
import { User } from '../types';

/**
 * Quadro de técnicos: uma linha por técnico, uma coluna por estágio da O.S. (dados do Softsystem, enviados pelo
 * vigia da loja). Todos os usuários veem o quadro e o modo TV; o detalhe/auditoria por técnico é só do admin.
 * As finalizadas não aparecem aqui (são muitas): ficam para a auditoria no detalhe do técnico.
 */

interface BoardCard {
  codos: number;
  empresa: string;
  cliente?: string | null;
  equipamento?: string | null;
  tecnico2?: string | null;
  data_entrada?: string | null;
  ultimo_evento_em?: string | null;
  dias_no_estagio?: number | null;
  dias_desde_entrada?: number | null;
}
interface BoardCell { count: number; cards: BoardCard[] }
interface BoardTech { name: string; total_open: number; cells: Record<string, BoardCell> }
interface BoardData {
  stages: { key: string; label: string }[];
  technicians: BoardTech[];
  totals: Record<string, number>;
  total_open: number;
  generated_at: string;
}
interface TimelineItem { evento: string; cod: number; data: string }
interface DetailOrder {
  codos: number; empresa: string; cliente?: string | null; equipamento?: string | null;
  tecnico?: string | null; tecnico2?: string | null; data_entrada?: string | null; situacao: string; stage: string;
  finalizada_em?: string | null; aberta: boolean; paga: boolean; timeline: TimelineItem[];
}
interface DetailData {
  name: string;
  summary: { abertas_agora: number; entradas_no_periodo: number; finalizadas_no_periodo: number; trabalhou_no_periodo: number };
  orders: DetailOrder[];
  truncated: boolean;
}

const EMPRESAS: { key: string; label: string }[] = [
  { key: '', label: 'Todas' },
  { key: 'servweld', label: 'Servweld' },
  { key: 'centrooeste', label: 'Centro-Oeste' },
];
const EMPRESA_LABEL: Record<string, string> = { servweld: 'Servweld', centrooeste: 'Centro-Oeste' };

// Cor de cada coluna (barra do topo do cartão): do início do fluxo até a retirada
const STAGE_COLORS: Record<string, string> = {
  entrada: '#60a5fa', avaliacao: '#a78bfa', orcamento: '#f59e0b', aprovado: '#34d399',
  execucao: '#00e699', peca: '#f97316', retirada: '#22d3ee', sem_reparo: '#94a3b8', finalizada: '#64748b',
};

const fmtDate = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
};
const fmtDateTime = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '—' : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
};
const titleCase = (s: string) => s.toLowerCase().replace(/(^|\s)\S/g, c => c.toUpperCase());
const toInputDate = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

interface Props {
  user: User;
  onBack?: () => void;
}

export const TechBoard: React.FC<Props> = ({ user, onBack }) => {
  const isAdmin = user.role === 'admin';
  const [empresa, setEmpresa] = useState<string>('');
  const [board, setBoard] = useState<BoardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tvMode, setTvMode] = useState<boolean>(() => {
    try { return localStorage.getItem('omni_board_tv') === '1'; } catch { return false; }
  });
  const [now, setNow] = useState(new Date());
  const [detailTech, setDetailTech] = useState<string | null>(null);
  const reloadTimer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (empresa) qs.set('empresa', empresa);
      qs.set('cards_per_cell', tvMode ? '8' : '6');
      const data = await apiFetch(`/os-board/board?${qs.toString()}`);
      setBoard(data);
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível carregar o quadro.');
    } finally {
      setLoading(false);
    }
  }, [empresa, tvMode]);

  useEffect(() => { setLoading(true); load(); }, [load]);

  // Atualiza sozinho: aviso em tempo real do servidor (WebSocket do Dashboard) + releitura periódica de segurança
  useEffect(() => {
    const onUpdate = () => {
      if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
      reloadTimer.current = window.setTimeout(load, 800);
    };
    window.addEventListener('os-board-update', onUpdate);
    const interval = window.setInterval(load, tvMode ? 30000 : 60000);
    return () => {
      window.removeEventListener('os-board-update', onUpdate);
      window.clearInterval(interval);
      if (reloadTimer.current) window.clearTimeout(reloadTimer.current);
    };
  }, [load, tvMode]);

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const enterTv = () => {
    setTvMode(true);
    try { localStorage.setItem('omni_board_tv', '1'); } catch {}
    try { document.documentElement.requestFullscreen?.(); } catch {}
  };
  const exitTv = () => {
    setTvMode(false);
    try { localStorage.removeItem('omni_board_tv'); } catch {}
    try { if (document.fullscreenElement) document.exitFullscreen?.(); } catch {}
  };
  useEffect(() => {
    if (!tvMode) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') exitTv(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tvMode]);

  if (detailTech && isAdmin) {
    return <TechDetail name={detailTech} empresa={empresa} onBack={() => setDetailTech(null)} />;
  }

  const scale = tvMode ? 1.35 : 1;
  const fs = (px: number) => `${Math.round(px * scale * 10) / 10}px`;

  const stages = board?.stages || [];
  const gridCols = `${tvMode ? 200 : 150}px repeat(${Math.max(stages.length, 1)}, minmax(${tvMode ? 190 : 150}px, 1fr))`;

  const wrapperStyle: React.CSSProperties = tvMode
    ? { position: 'fixed', inset: 0, zIndex: 20000, background: 'var(--bg-primary, #0b1220)', display: 'flex', flexDirection: 'column', padding: '14px 18px', overflow: 'hidden' }
    : { flex: 1, display: 'flex', flexDirection: 'column', padding: '16px 20px', overflow: 'hidden', minWidth: 0, height: '100%', background: 'var(--bg-primary)' };

  return (
    <div style={wrapperStyle}>
      {/* Cabeçalho */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap', marginBottom: '12px' }}>
        {!tvMode && onBack && (
          <button onClick={onBack} title="Voltar" style={iconBtn}><ArrowLeft size={16} /></button>
        )}
        <div>
          <div style={{ fontSize: fs(20), fontWeight: 800, color: 'var(--text-main)', letterSpacing: '0.2px' }}>Quadro de Técnicos</div>
          <div style={{ fontSize: fs(12), color: 'var(--text-muted)' }}>
            {board ? `${board.total_open} O.S. em aberto` : 'Carregando…'}
            {board && ` · atualizado ${new Date(board.generated_at).toLocaleTimeString('pt-BR')}`}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '4px', marginLeft: '8px' }}>
          {EMPRESAS.map(e => (
            <button
              key={e.key || 'todas'}
              onClick={() => setEmpresa(e.key)}
              style={{
                padding: tvMode ? '8px 16px' : '6px 12px', fontSize: fs(12), fontWeight: 700, cursor: 'pointer',
                borderRadius: 'var(--radius-md, 8px)',
                background: empresa === e.key ? 'rgba(0,230,153,0.16)' : 'transparent',
                color: empresa === e.key ? 'var(--accent-primary)' : 'var(--text-muted)',
                border: empresa === e.key ? '1px solid rgba(0,230,153,0.4)' : '1px solid var(--border-color, rgba(255,255,255,0.12))',
              }}
            >{e.label}</button>
          ))}
        </div>

        <div style={{ flex: 1 }} />
        {tvMode && (
          <div style={{ fontSize: fs(26), fontWeight: 800, color: 'var(--text-main)', fontVariantNumeric: 'tabular-nums' }}>
            {now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
            <span style={{ fontSize: fs(12), color: 'var(--text-muted)', fontWeight: 600, marginLeft: '10px' }}>
              {now.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })}
            </span>
          </div>
        )}
        {!tvMode && (
          <>
            <button onClick={() => { setLoading(true); load(); }} title="Atualizar agora" style={iconBtn}><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>
            <button onClick={enterTv} style={{ ...iconBtn, width: 'auto', padding: '0 12px', gap: '6px', display: 'flex', alignItems: 'center', fontSize: '12px', fontWeight: 700 }}>
              <Monitor size={15} /> Modo TV
            </button>
          </>
        )}
        {tvMode && (
          <button onClick={exitTv} title="Sair do modo TV (Esc)" style={iconBtn}><X size={16} /></button>
        )}
      </div>

      {error && (
        <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontSize: fs(13), marginBottom: '10px' }}>{error}</div>
      )}

      {/* Quadro */}
      <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', background: 'var(--bg-secondary, rgba(255,255,255,0.02))' }}>
        <div style={{ minWidth: 'max-content', display: 'grid', gridTemplateColumns: gridCols }}>
          {/* linha de títulos */}
          <div style={{ ...headCell(scale), position: 'sticky', left: 0, top: 0, zIndex: 3 }}>Técnico</div>
          {stages.map(st => (
            <div key={st.key} style={{ ...headCell(scale), position: 'sticky', top: 0, zIndex: 2, borderTop: `3px solid ${STAGE_COLORS[st.key] || '#64748b'}` }}>
              <span>{st.label}</span>
              <span style={{ marginLeft: '8px', color: STAGE_COLORS[st.key] || 'var(--text-muted)' }}>{board?.totals?.[st.key] ?? 0}</span>
            </div>
          ))}

          {board && board.technicians.length === 0 && !loading && (
            <div style={{ gridColumn: `1 / span ${stages.length + 1}`, padding: '40px', textAlign: 'center', color: 'var(--text-muted)', fontSize: fs(14) }}>
              Nenhuma O.S. em aberto neste filtro.
            </div>
          )}

          {(board?.technicians || []).map(tech => (
            <React.Fragment key={tech.name}>
              <div
                onClick={() => { if (isAdmin && !tvMode) setDetailTech(tech.name); }}
                title={isAdmin && !tvMode ? 'Ver detalhes e auditoria deste técnico' : undefined}
                style={{
                  position: 'sticky', left: 0, zIndex: 1, padding: `${10 * scale}px ${12 * scale}px`,
                  background: 'var(--bg-primary, #0b1220)', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                  borderRight: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                  cursor: isAdmin && !tvMode ? 'pointer' : 'default',
                }}
              >
                <div style={{ fontSize: fs(15), fontWeight: 800, color: 'var(--text-main)' }}>{titleCase(tech.name)}</div>
                <div style={{ fontSize: fs(12), color: 'var(--text-muted)', marginTop: '2px' }}>{tech.total_open} em aberto</div>
              </div>
              {stages.map(st => {
                const cell = tech.cells[st.key] || { count: 0, cards: [] };
                return (
                  <div key={st.key} style={{ padding: `${8 * scale}px`, borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRight: '1px solid var(--border-color, rgba(255,255,255,0.05))', display: 'flex', flexDirection: 'column', gap: `${6 * scale}px`, minHeight: `${64 * scale}px` }}>
                    {cell.cards.map(card => <OsCard key={`${card.empresa}-${card.codos}`} card={card} color={STAGE_COLORS[st.key]} scale={scale} showEmpresa={!empresa} />)}
                    {cell.count > cell.cards.length && (
                      <div style={{ fontSize: fs(11), fontWeight: 700, color: 'var(--text-muted)', textAlign: 'center' }}>+{cell.count - cell.cards.length} O.S.</div>
                    )}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>
      {!tvMode && !isAdmin && (
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
          Finalizadas e O.S. já efetivadas não aparecem no quadro. O detalhe por técnico é exclusivo de administradores.
        </div>
      )}
    </div>
  );
};

const iconBtn: React.CSSProperties = {
  width: '34px', height: '34px', borderRadius: 'var(--radius-md, 8px)', cursor: 'pointer',
  background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const headCell = (scale: number): React.CSSProperties => ({
  padding: `${10 * scale}px ${12 * scale}px`, fontSize: `${12 * scale}px`, fontWeight: 800, textTransform: 'uppercase',
  letterSpacing: '0.6px', color: 'var(--text-main)', background: 'var(--bg-primary, #0b1220)',
  borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.12))', display: 'flex', alignItems: 'center',
});

const OsCard: React.FC<{ card: BoardCard; color?: string; scale: number; showEmpresa: boolean }> = ({ card, color, scale, showEmpresa }) => {
  const dias = card.dias_no_estagio ?? 0;
  // parada há muito tempo no mesmo estágio: chama atenção
  const aging = dias >= 15 ? '#ef4444' : dias >= 7 ? '#f59e0b' : null;
  return (
    <div style={{
      borderRadius: '8px', padding: `${6 * scale}px ${8 * scale}px`, background: 'rgba(255,255,255,0.04)',
      borderLeft: `3px solid ${aging || color || '#64748b'}`, minWidth: 0,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px', fontSize: `${12 * scale}px`, fontWeight: 800, color: 'var(--text-main)' }}>
        <span>#{card.codos}</span>
        <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{fmtDate(card.data_entrada)}</span>
      </div>
      <div style={{ fontSize: `${11 * scale}px`, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={card.cliente || ''}>
        {card.cliente ? titleCase(card.cliente) : '—'}
      </div>
      {card.equipamento && (
        <div style={{ fontSize: `${10.5 * scale}px`, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={card.equipamento}>
          {card.equipamento}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px', fontSize: `${10 * scale}px`, marginTop: '2px' }}>
        <span style={{ color: aging || 'var(--text-muted)', fontWeight: aging ? 800 : 500 }}>{dias === 0 ? 'hoje' : `${dias}d no estágio`}</span>
        {showEmpresa && <span style={{ color: 'var(--text-muted)' }}>{EMPRESA_LABEL[card.empresa] || card.empresa}</span>}
      </div>
    </div>
  );
};

// --------------------------------------------------------------------------- detalhe / auditoria (admin)

const STATUS_OPTIONS = [
  { key: 'trabalhou', label: 'Trabalhou no período' },
  { key: 'entrada', label: 'Entradas no período' },
  { key: 'finalizadas', label: 'Finalizadas no período' },
  { key: 'abertas', label: 'Em aberto agora' },
  { key: 'todas', label: 'Todas' },
];

const TechDetail: React.FC<{ name: string; empresa: string; onBack: () => void }> = ({ name, empresa: empresaInit, onBack }) => {
  const [empresa, setEmpresa] = useState(empresaInit);
  const [status, setStatus] = useState('trabalhou');
  const [start, setStart] = useState(toInputDate(new Date(Date.now() - 30 * 86400000)));
  const [end, setEnd] = useState(toInputDate(new Date()));
  const [data, setData] = useState<DetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ name, status, start: `${start}T00:00:00`, end: `${end}T23:59:59` });
      if (empresa) qs.set('empresa', empresa);
      setData(await apiFetch(`/os-board/technician?${qs.toString()}`));
      setError(null);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível carregar o detalhe.');
    } finally {
      setLoading(false);
    }
  }, [name, status, start, end, empresa]);
  useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    if (!data) return;
    const q = (v: any) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [['O.S.', 'Empresa', 'Cliente', 'Equipamento', 'Técnico', 'Técnico 2', 'Entrada', 'Situação', 'Finalizada em', 'Efetivada', 'Linha do tempo']
      .map(q).join(';')];
    for (const o of data.orders) {
      lines.push([
        o.codos, EMPRESA_LABEL[o.empresa] || o.empresa, o.cliente, o.equipamento, o.tecnico, o.tecnico2,
        fmtDateTime(o.data_entrada), o.situacao, fmtDateTime(o.finalizada_em), o.paga ? 'sim' : 'não',
        o.timeline.map(t => `${t.evento} ${fmtDateTime(t.data)}`).join(' > '),
      ].map(q).join(';'));
    }
    const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `auditoria-${name.toLowerCase()}-${start}-a-${end}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const tile = (label: string, value: number | string, color: string) => (
    <div style={{ flex: '1 1 150px', padding: '12px 14px', borderRadius: '10px', background: 'rgba(255,255,255,0.04)', borderTop: `3px solid ${color}` }}>
      <div style={{ fontSize: '24px', fontWeight: 800, color: 'var(--text-main)' }}>{value}</div>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600 }}>{label}</div>
    </div>
  );

  const input: React.CSSProperties = {
    padding: '6px 8px', borderRadius: '8px', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)',
    border: '1px solid var(--border-color, rgba(255,255,255,0.12))', fontSize: '12px',
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '16px 20px', overflow: 'auto', minWidth: 0, height: '100%', background: 'var(--bg-primary)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '14px', flexWrap: 'wrap' }}>
        <button onClick={onBack} title="Voltar ao quadro" style={iconBtn}><ArrowLeft size={16} /></button>
        <div>
          <div style={{ fontSize: '20px', fontWeight: 800, color: 'var(--text-main)' }}>{titleCase(name)}</div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Detalhe e auditoria das O.S. do técnico</div>
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={exportCsv} disabled={!data || data.orders.length === 0} style={{ ...iconBtn, width: 'auto', padding: '0 12px', gap: '6px', fontSize: '12px', fontWeight: 700 }}>
          <Download size={14} /> Exportar CSV
        </button>
      </div>

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '14px' }}>
        <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>De <input type="date" id="tech-start" value={start} onChange={e => setStart(e.target.value)} style={input} /></label>
        <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>até <input type="date" id="tech-end" value={end} onChange={e => setEnd(e.target.value)} style={input} /></label>
        <select id="tech-status" value={status} onChange={e => setStatus(e.target.value)} style={input}>
          {STATUS_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
        <select id="tech-empresa" value={empresa} onChange={e => setEmpresa(e.target.value)} style={input}>
          {EMPRESAS.map(e => <option key={e.key || 'todas'} value={e.key}>{e.label}</option>)}
        </select>
      </div>

      {error && <div style={{ padding: '10px 14px', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontSize: '13px', marginBottom: '10px' }}>{error}</div>}

      {data && (
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '14px' }}>
          {tile('Em aberto agora', data.summary.abertas_agora, '#f59e0b')}
          {tile('Entradas no período', data.summary.entradas_no_periodo, '#60a5fa')}
          {tile('Finalizadas no período', data.summary.finalizadas_no_periodo, '#34d399')}
          {tile('Trabalhou no período', data.summary.trabalhou_no_periodo, '#a78bfa')}
        </div>
      )}

      <div style={{ border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '760px' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              {['O.S.', 'Cliente / Equipamento', 'Entrada', 'Situação', 'Finalizada', 'Linha do tempo'].map(h => (
                <th key={h} style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.12))' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Carregando…</td></tr>}
            {!loading && data && data.orders.length === 0 && (
              <tr><td colSpan={6} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Nenhuma O.S. neste filtro.</td></tr>
            )}
            {!loading && data?.orders.map(o => {
              const key = `${o.empresa}-${o.codos}`;
              const open = expanded.has(key);
              return (
                <React.Fragment key={key}>
                  <tr
                    onClick={() => setExpanded(prev => { const n = new Set(prev); if (n.has(key)) n.delete(key); else n.add(key); return n; })}
                    style={{ cursor: 'pointer', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.06))' }}
                  >
                    <td style={{ padding: '9px 12px', fontWeight: 800, color: 'var(--text-main)' }}>
                      #{o.codos}<div style={{ fontSize: '10px', fontWeight: 500, color: 'var(--text-muted)' }}>{EMPRESA_LABEL[o.empresa] || o.empresa}</div>
                    </td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>
                      {o.cliente ? titleCase(o.cliente) : '—'}
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{o.equipamento || ''}</div>
                    </td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>{fmtDateTime(o.data_entrada)}</td>
                    <td style={{ padding: '9px 12px' }}>
                      <span style={{ padding: '2px 8px', borderRadius: '999px', fontSize: '11px', fontWeight: 700, background: `${STAGE_COLORS[o.stage] || '#64748b'}26`, color: STAGE_COLORS[o.stage] || 'var(--text-muted)' }}>{o.situacao}</span>
                      {o.paga && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>efetivada</div>}
                    </td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>{fmtDateTime(o.finalizada_em)}</td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-muted)' }}>{o.timeline.length} evento(s) {open ? '▲' : '▼'}</td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={6} style={{ padding: '6px 12px 14px 40px', background: 'rgba(255,255,255,0.02)' }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                          {o.timeline.map((t, i) => (
                            <span key={i} style={{ padding: '4px 10px', borderRadius: '8px', background: 'rgba(255,255,255,0.05)', fontSize: '11px', color: 'var(--text-main)' }}>
                              <b>{t.evento}</b> <span style={{ color: 'var(--text-muted)' }}>{fmtDateTime(t.data)}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {data?.truncated && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>Mostrando as 300 O.S. mais recentes; reduza o período para ver as demais.</div>}
    </div>
  );
};
