import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft, Download, FileText, Monitor, RefreshCw, X, Clock,
  Inbox, Search, CheckCircle2, XCircle, Wrench, Package, PackageCheck, AlertTriangle, Trash2,
  Camera, Image as ImageIcon, Loader2, ChevronLeft, ChevronRight,
  type LucideIcon,
} from 'lucide-react';
import { apiFetch, apiUpload } from '../services/api';
import { techApiFetch, techApiUpload } from '../services/techApi';
import { User } from '../types';

/**
 * Quadro de técnicos: uma linha por técnico, uma coluna por estágio da O.S. (dados do Softsystem, enviados pelo
 * vigia da loja). Todos os usuários veem o quadro e o modo TV; o detalhe/auditoria por técnico é só do admin.
 * As finalizadas não aparecem aqui (são muitas): ficam para a auditoria no detalhe do técnico.
 */

export interface BoardCard {
  codos: number;
  empresa: string;
  cliente?: string | null;
  equipamento?: string | null;
  tecnico2?: string | null;
  data_entrada?: string | null;
  ultimo_evento_em?: string | null;
  dias_no_estagio?: number | null;
  dias_desde_entrada?: number | null;
  tipo_os?: string | null;
}

// Status que o Portal do Técnico deixa o próprio técnico mudar direto pelo cartão (ver
// TECHNICIAN_ALLOWED_STATUSES no backend) - só passado como prop quando faz sentido (aba "Minhas
// O.S.", nunca no quadro administrativo nem no "Quadro Geral").
export const TECH_STATUS_OPTIONS: { key: number; short: string }[] = [
  { key: 6, short: 'Retirada' },
  { key: 13, short: 'S/ Defeito' },
  { key: 11, short: 'S/ Conserto' },
];
export type ChangeStatusFn = (codos: number, empresa: string, status: number, label: string, obs?: string) => void;
export interface BoardCell { count: number; cards: BoardCard[] }
export interface BoardTech { name: string; total_open: number; cells: Record<string, BoardCell> }
export interface BoardData {
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
  tipo_os?: string | null; finalizada_em?: string | null; aberta: boolean; paga: boolean; venda_codigo?: number | null;
  efetivada_motivo?: string | null; timeline: TimelineItem[];
}
interface DetailData {
  name: string;
  summary: { abertas_agora: number; entradas_no_periodo: number; finalizadas_no_periodo: number; trabalhou_no_periodo: number; efetivadas_no_periodo: number };
  orders: DetailOrder[];
  truncated: boolean;
}
interface OsPecaItem { descricao: string; quantidade?: number | null; preco?: number | null }
interface OsFotoItem {
  id: number; file_url: string; mimetype: string; uploaded_by?: string | null; criado_em: string;
  gdrive_status: string; whatsapp_status: string; softsystem_status: string;
}
interface OsOrderDetail {
  codos: number; empresa: string; cliente?: string | null; equipamento?: string | null;
  tecnico?: string | null; tecnico2?: string | null; data_entrada?: string | null;
  tipo_os?: string | null; situacao: string; stage: string;
  valor_total?: number | null; forma_pagamento?: string | null;
  historico: (TimelineItem & { obs?: string | null })[];
  pecas: OsPecaItem[];
  fotos: OsFotoItem[];
}

const EMPRESAS: { key: string; label: string }[] = [
  { key: '', label: 'Todas' },
  { key: 'servweld', label: 'Servweld' },
  { key: 'centrooeste', label: 'Centro-Oeste' },
];
const EMPRESA_LABEL: Record<string, string> = { servweld: 'Servweld', centrooeste: 'Centro-Oeste' };

// Cor de cada coluna (barra do topo do cartão): do início do fluxo até a retirada
const STAGE_COLORS: Record<string, string> = {
  entrada: '#60a5fa', avaliacao: '#a78bfa', orcamento: '#f59e0b', aprovado: '#34d399', nao_aprovado: '#ef4444',
  execucao: '#00e699', peca: '#f97316', retirada: '#22d3ee', sem_reparo: '#94a3b8', descarte: '#fb7185', finalizada: '#64748b',
};

// Um ícone por estágio - deixa os chips de filtro (lista do celular/Portal do Técnico) reconhecíveis de
// relance, não só por cor.
const STAGE_ICONS: Record<string, LucideIcon> = {
  entrada: Inbox, avaliacao: Search, orcamento: FileText, aprovado: CheckCircle2, nao_aprovado: XCircle,
  execucao: Wrench, peca: Package, retirada: PackageCheck, sem_reparo: AlertTriangle, descarte: Trash2,
};

// Tipo de O.S. (natureza): cor e sigla para identificar de relance no cartão - paleta separada da cor de
// estágio (que já usa a borda esquerda do cartão), então o selo do tipo fica num tom quente/frio diferente.
const TIPO_OS_STYLE: Record<string, { color: string; short: string }> = {
  'Orçamento': { color: '#38bdf8', short: 'ORÇ' },
  'Garantia de Fábrica': { color: '#c084fc', short: 'G.FÁB' },
  'Garantia de Loja': { color: '#facc15', short: 'G.LOJA' },
  'Visita Técnica': { color: '#4ade80', short: 'VISITA' },
  'Equipamento de Locação': { color: '#f472b6', short: 'LOCAÇÃO' },
};
const tipoOsStyle = (tipo?: string | null) => (tipo && TIPO_OS_STYLE[tipo]) || { color: '#64748b', short: tipo || '?' };

const TipoOsBadge: React.FC<{ tipo?: string | null; scale?: number }> = ({ tipo, scale = 1 }) => {
  if (!tipo) return null;
  const st = tipoOsStyle(tipo);
  return (
    <span
      title={tipo}
      style={{
        display: 'inline-block', padding: `${1 * scale}px ${5 * scale}px`, borderRadius: '4px',
        fontSize: `${9 * scale}px`, fontWeight: 800, lineHeight: 1.5, letterSpacing: '0.2px',
        background: `${st.color}26`, color: st.color, whiteSpace: 'nowrap',
        overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%', minWidth: 0,
      }}
    >{st.short}</span>
  );
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
  const [stageFilter, setStageFilter] = useState<string>('');

  // Modo TV: carrossel passando por um técnico de cada vez (em vez da grade estática, onde os técnicos
  // de baixo ficavam escondidos - ninguém rola a tela sozinho de longe). CAROUSEL_MS por técnico.
  const CAROUSEL_MS = 60000;
  const [carouselIndex, setCarouselIndex] = useState(0);
  const techCount = board?.technicians.length || 0;
  const activeIndex = techCount > 0 ? ((carouselIndex % techCount) + techCount) % techCount : 0;
  useEffect(() => {
    if (!tvMode || techCount <= 1) return;
    const t = window.setTimeout(() => setCarouselIndex(i => i + 1), CAROUSEL_MS);
    return () => window.clearTimeout(t);
  }, [tvMode, carouselIndex, techCount]);
  useEffect(() => { setCarouselIndex(0); }, [empresa, tvMode]);
  useEffect(() => {
    if (!tvMode) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') setCarouselIndex(i => i + 1);
      if (e.key === 'ArrowLeft') setCarouselIndex(i => i - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tvMode]);

  // Tela estreita (celular/tablet retrato): 8 colunas não cabem de jeito nenhum, então vira uma
  // lista vertical por técnico em vez da grade. Já deitado (paisagem), mostra a mesma grade do
  // desktop (rolável por toque) - só o retrato vira lista. O modo TV é sempre um telão largo.
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

  // Zoom manual pro celular (retrato ou paisagem): a tela é pequena e tem muita informação, então o
  // técnico/atendente ajusta o tamanho como quiser. Mesmo mecanismo de "scale" que o Modo TV já usa.
  const [mobileZoom, setMobileZoom] = useState<number>(() => {
    try {
      const v = parseFloat(localStorage.getItem('omni_board_mobile_zoom') || '1');
      return isFinite(v) && v > 0 ? v : 1;
    } catch { return 1; }
  });
  const setZoom = (next: number) => {
    const clamped = Math.max(0.8, Math.min(1.6, Math.round(next * 100) / 100));
    setMobileZoom(clamped);
    try { localStorage.setItem('omni_board_mobile_zoom', String(clamped)); } catch {}
  };

  // "+N O.S." de uma célula do quadro: abre com a lista completa (sem o limite de cartões por célula)
  const [cellModal, setCellModal] = useState<{ tecnico: string; label: string; stage: string } | null>(null);

  // Relatório em PDF (só admin)
  const [reportOpen, setReportOpen] = useState(false);

  // Busca por número da O.S., cliente ou equipamento (pedido do usuário, 29/09/2026) - substitui o
  // quadro normal enquanto tem texto digitado, igual o Portal do Técnico (TechnicianPortal.tsx).
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResultCard[]>([]);
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    const q = searchQuery.trim();
    if (!q) { setSearchResults([]); return; }
    setSearching(true);
    const handle = window.setTimeout(() => {
      const qs = new URLSearchParams({ q });
      if (empresa) qs.set('empresa', empresa);
      apiFetch(`/os-board/search?${qs.toString()}`)
        .then(data => setSearchResults(data.results || []))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false));
    }, 350);
    return () => window.clearTimeout(handle);
  }, [searchQuery, empresa]);

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (empresa) qs.set('empresa', empresa);
      // No modo TV busca bem mais que cabe na tela de uma vez: o carrossel gira as páginas de cada
      // célula sozinho (ver TvCarousel), então precisa ter tudo em mãos pra isso funcionar sem
      // depender de mais uma chamada à API a cada página.
      qs.set('cards_per_cell', tvMode ? '60' : '6');
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

  const scale = tvMode ? 1.1 : (isNarrow ? mobileZoom : 1);
  const fs = (px: number) => `${Math.round(px * scale * 10) / 10}px`;

  const stages = board?.stages || [];
  // Retrato vira lista vertical (MobileBoard); paisagem já usa a mesma grade do desktop (rolável por
  // toque nos dois eixos, ver BoardGrid) - só o Modo TV nunca cai aqui.
  const useMobileLayout = isNarrow && !tvMode && !isLandscape;
  const showZoomControls = isNarrow && !tvMode;

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

        {!tvMode && <SearchBar query={searchQuery} onQueryChange={setSearchQuery} />}

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
            {/* A lista simples (sem números financeiros) qualquer atendente pode gerar - só o
                relatório completo com KPIs/financeiro/ranking é exclusivo de admin (ver ReportPanel). */}
            <button onClick={() => setReportOpen(true)} style={{ ...iconBtn, width: 'auto', padding: '0 12px', gap: '6px', display: 'flex', alignItems: 'center', fontSize: '12px', fontWeight: 700 }}>
              <FileText size={15} /> {isAdmin ? 'Relatórios' : 'Lista de O.S.'}
            </button>
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

      {/* Modo TV: nome do técnico em destaque - é a informação que quem está de longe, na oficina, precisa achar primeiro */}
      {tvMode && board && techCount > 0 && (
        <div style={{ textAlign: 'center', margin: '2px 0 14px', flexShrink: 0 }}>
          <div style={{ fontSize: fs(46), fontWeight: 900, color: 'var(--accent-primary)', letterSpacing: '0.5px', lineHeight: 1.1 }}>
            {titleCase(board.technicians[activeIndex].name)}
          </div>
          <div style={{ fontSize: fs(14), color: 'var(--text-muted)', fontWeight: 700, marginTop: '4px' }}>
            Técnico {activeIndex + 1} de {techCount} · {board.technicians[activeIndex].total_open} O.S. em aberto
          </div>
        </div>
      )}

      {showZoomControls && (
        <div style={{ position: 'fixed', right: '14px', bottom: '14px', zIndex: 50, display: 'flex', flexDirection: 'column', gap: '6px', background: 'var(--bg-secondary, rgba(20,24,32,0.92))', border: '1px solid var(--border-color, rgba(255,255,255,0.14))', borderRadius: '10px', padding: '4px', boxShadow: '0 4px 14px rgba(0,0,0,0.35)' }}>
          <button onClick={() => setZoom(mobileZoom + 0.15)} title="Aumentar zoom" style={{ ...iconBtn, width: '36px', height: '36px', fontSize: '16px', fontWeight: 800 }}>+</button>
          <button onClick={() => setZoom(mobileZoom - 0.15)} title="Diminuir zoom" style={{ ...iconBtn, width: '36px', height: '36px', fontSize: '16px', fontWeight: 800 }}>−</button>
        </div>
      )}

      {/* Quadro: carrossel (TV), busca, lista por técnico (tela estreita) ou grade (desktop) */}
      {!tvMode && searchQuery.trim() ? (
        <SearchResultsList results={searchResults} loading={searching} showEmpresa={!empresa} showTecnico />
      ) : tvMode ? (
        <TvCarousel
          board={board}
          loading={loading}
          activeIndex={activeIndex}
          carouselMs={CAROUSEL_MS}
          carouselKey={carouselIndex}
          onGoTo={setCarouselIndex}
          scale={scale}
          fs={fs}
          onOpenCell={(tecnico, stage, label) => setCellModal({ tecnico, stage, label })}
        />
      ) : useMobileLayout ? (
        <MobileBoard
          board={board}
          loading={loading}
          stageFilter={stageFilter}
          setStageFilter={setStageFilter}
          isAdmin={isAdmin}
          onOpenTech={setDetailTech}
          showEmpresa={!empresa}
          onOpenCell={(tecnico, stage, label) => setCellModal({ tecnico, stage, label })}
        />
      ) : (
        <BoardGrid
          board={board}
          loading={loading}
          scale={scale}
          isAdmin={isAdmin}
          onOpenTech={setDetailTech}
          showEmpresa={!empresa}
          onOpenCell={(tecnico, stage, label) => setCellModal({ tecnico, stage, label })}
        />
      )}
      {!tvMode && !isAdmin && (
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '8px' }}>
          Finalizadas e O.S. já efetivadas não aparecem no quadro. O detalhe por técnico é exclusivo de administradores.
        </div>
      )}

      {cellModal && (
        <CellModal
          tecnico={cellModal.tecnico}
          stage={cellModal.stage}
          label={cellModal.label}
          empresa={empresa}
          showEmpresa={!empresa}
          onClose={() => setCellModal(null)}
        />
      )}

      {reportOpen && (
        <ReportPanel stages={stages} defaultEmpresa={empresa} isAdmin={isAdmin} onClose={() => setReportOpen(false)} />
      )}
    </div>
  );
};

// --------------------------------------------------------------------------- grade (desktop / celular deitado / Portal do Técnico)

// Mesma grade do quadro administrativo (uma linha por técnico, uma coluna por estágio, cabeçalho colorido
// por STAGE_COLORS) - extraída pra ser reaproveitada também no Portal do Técnico (TechnicianPortal.tsx)
// em telas largas, em vez de reimplementar o visual do quadro principal.
export const BoardGrid: React.FC<{
  board: BoardData | null; loading: boolean; scale?: number; isAdmin: boolean;
  onOpenTech?: (name: string) => void; onOpenCell: (tecnico: string, stage: string, label: string) => void;
  showEmpresa: boolean; onChangeStatus?: ChangeStatusFn;
}> = ({ board, loading, scale = 1, isAdmin, onOpenTech, onOpenCell, showEmpresa, onChangeStatus }) => {
  const fs = (px: number) => `${Math.round(px * scale * 10) / 10}px`;
  const stages = board?.stages || [];
  const stagesCount = Math.max(stages.length, 1);
  // Colunas fixas ocupando 100% da largura disponível (grid com container de largura definida - sem isso,
  // nomes longos de cliente em uma só linha inflam a largura "natural" das colunas bem além do necessário).
  const techColWidth = Math.round(100 * scale);
  const minStageCol = Math.round(82 * scale);
  const gridCols = `${techColWidth}px repeat(${stagesCount}, minmax(${minStageCol}px, 1fr))`;
  const clickable = isAdmin && !!onOpenTech;

  return (
    <div style={{ flex: 1, overflow: 'auto', WebkitOverflowScrolling: 'touch', touchAction: 'pan-x pan-y', overscrollBehavior: 'contain', border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', background: 'var(--bg-secondary, rgba(255,255,255,0.02))' }}>
      <div style={{ width: '100%', display: 'grid', gridTemplateColumns: gridCols }}>
        {/* linha de títulos */}
        <div style={{ ...headCell(scale), position: 'sticky', left: 0, top: 0, zIndex: 3 }}>Técnico</div>
        {stages.map(st => (
          <div
            key={st.key} title={st.label}
            style={{
              ...headCell(scale), position: 'sticky', top: 0, zIndex: 2, borderTop: `3px solid ${STAGE_COLORS[st.key] || '#64748b'}`,
              flexDirection: 'column', alignItems: 'flex-start', justifyContent: 'center', gap: '2px',
              whiteSpace: 'normal', overflow: 'visible', textOverflow: 'clip',
            }}
          >
            <span style={{ lineHeight: 1.15, wordBreak: 'break-word' }}>{st.label}</span>
            <span style={{ color: STAGE_COLORS[st.key] || 'var(--text-muted)', fontSize: `${11 * scale}px` }}>{board?.totals?.[st.key] ?? 0}</span>
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
              onClick={() => { if (clickable) onOpenTech!(tech.name); }}
              title={clickable ? 'Ver detalhes e auditoria deste técnico' : undefined}
              style={{
                position: 'sticky', left: 0, zIndex: 1, padding: `${7 * scale}px ${9 * scale}px`,
                background: 'var(--bg-primary, #0b1220)', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                borderRight: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                cursor: clickable ? 'pointer' : 'default', minWidth: 0,
              }}
            >
              <div style={{ fontSize: fs(12.5), fontWeight: 800, color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={titleCase(tech.name)}>{titleCase(tech.name)}</div>
              <div style={{ fontSize: fs(10), color: 'var(--text-muted)', marginTop: '1px' }}>{tech.total_open} em aberto</div>
            </div>
            {stages.map(st => {
              const cell = tech.cells[st.key] || { count: 0, cards: [] };
              return (
                <div key={st.key} style={{ padding: `${4 * scale}px`, borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRight: '1px solid var(--border-color, rgba(255,255,255,0.05))', display: 'flex', flexDirection: 'column', gap: `${3 * scale}px`, minHeight: `${44 * scale}px`, minWidth: 0 }}>
                  {cell.cards.map(card => <OsCard key={`${card.empresa}-${card.codos}`} card={card} color={STAGE_COLORS[st.key]} scale={scale} showEmpresa={showEmpresa} onChangeStatus={onChangeStatus} />)}
                  {cell.count > cell.cards.length && (
                    <button
                      onClick={() => onOpenCell(tech.name, st.key, st.label)}
                      style={{ fontSize: fs(11), fontWeight: 700, color: 'var(--accent-primary)', textAlign: 'center', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.25)', borderRadius: '6px', padding: '3px 0', cursor: 'pointer' }}
                    >+{cell.count - cell.cards.length} O.S.</button>
                  )}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

const CellModal: React.FC<{ tecnico: string; stage: string; label: string; empresa: string; showEmpresa: boolean; onClose: () => void }> = ({ tecnico, stage, label, empresa, showEmpresa, onClose }) => {
  const [cards, setCards] = useState<BoardCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const qs = new URLSearchParams({ tecnico, stage });
        if (empresa) qs.set('empresa', empresa);
        const data = await apiFetch(`/os-board/cell?${qs.toString()}`);
        if (!cancelled) setCards(data.cards || []);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Não foi possível carregar a lista.');
      }
    })();
    return () => { cancelled = true; };
  }, [tecnico, stage, empresa]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 30000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '560px', maxHeight: '82vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', borderRadius: '12px', overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>{titleCase(tecnico)}</div>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>{label} · {cards ? cards.length : '…'} O.S.</div>
          </div>
          <button onClick={onClose} style={iconBtn}><X size={16} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {error && <div style={{ color: '#f87171', fontSize: '13px' }}>{error}</div>}
          {!error && cards === null && <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '20px' }}>Carregando…</div>}
          {cards && cards.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '20px' }}>Nenhuma O.S. nesta célula.</div>}
          {cards && cards.map(card => (
            <MobileOsRow key={`${card.empresa}-${card.codos}`} card={card} stageLabel={label} color={STAGE_COLORS[stage]} showEmpresa={showEmpresa} showStage={false} />
          ))}
        </div>
      </div>
    </div>
  );
};

// --------------------------------------------------------------------------- detalhe da O.S. (histórico + peças)

const formatMoney = (v?: number | null) => (typeof v === 'number' ? v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) : null);

const formatDateTime = (iso?: string | null) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
};

// Mesmo detalhe, dois back-ends (admin vs Portal do Técnico) - os dois módulos compartilham estes
// componentes de cartão, então precisa descobrir qual chamar (ver technician_portal.order_detail /
// os_board._order_detail, que devolvem o mesmo formato).
//
// Achado em produção, 02/10/2026: clicar numa O.S. no Portal do Técnico dava "sessão expirada" e
// voltava pro login do admin. Duas causas, uma atrás da outra:
// 1ª tentativa, incompleta: decidia o back-end pelo pathname da URL, que não é confiável (SPA de
//    tela única, o caminho nem sempre bate com '/tecnico' no momento do clique).
// 2ª causa, a de verdade: mesmo escolhendo a URL certa, o Portal do Técnico usa um cliente HTTP
//    PRÓPRIO (techApiFetch, services/techApi.ts) com uma chave de sessão separada (localStorage
//    'tech_token', não 'token') e seu próprio redirecionamento de sessão expirada (pra /tecnico,
//    não /login) - de propósito, pra um técnico e um atendente poderem estar logados ao mesmo
//    tempo no mesmo navegador/celular sem um derrubar a sessão do outro (ver o comentário em
//    techApi.ts). Chamar apiFetch (do admin) sempre ia falhar pro técnico nessa tela, não importa
//    a URL - precisa trocar o cliente HTTP inteiro, não só o prefixo.
const fetchOsDetail = (codos: number) => {
  const isTechnician = !!localStorage.getItem('tech_token');
  return isTechnician ? techApiFetch(`/order/${codos}`) : apiFetch(`/os-board/order/${codos}`);
};

// Mesma escolha de cliente HTTP do fetchOsDetail acima - admin e técnico sobem a foto pra
// endpoints espelhados (os_board.upload_order_photo / technician_portal.technician_upload_order_photo).
// sendToCustomer=false: documento interno (ex.: NF de compra que o cliente apresenta pra acionar
// garantia de fábrica - pedido do usuário em 05/10/2026) - sobe pro Drive e anexa no Softsystem
// igual, só não dispara pro WhatsApp do cliente (ele já tem o original, não faz sentido devolver).
const uploadOsPhoto = (codos: number, formData: FormData, sendToCustomer: boolean) => {
  formData.append('send_to_customer', sendToCustomer ? 'true' : 'false');
  const isTechnician = !!localStorage.getItem('tech_token');
  return isTechnician ? techApiUpload(`/order/${codos}/photos`, formData) : apiUpload(`/os-board/order/${codos}/photos`, formData);
};

// Checkbox compartilhado pelos dois pontos de upload (OsDetailModal e OsPhotoQuickUploadModal) -
// reseta sozinho pro padrão (enviar) depois de cada envio, pra não esquecer marcado sem querer e
// pular o envio de uma foto que devia ir pro cliente.
// Visualizador de foto em tela cheia, dentro da própria página (pedido do usuário em 05/10/2026:
// clicar numa foto abria aba nova do navegador, perdendo o contexto da O.S.) - com setas pra
// passar pra próxima/anterior sem fechar. Só participa da navegação quem é imagem de verdade;
// documentos (PDF, etc.) continuam abrindo em aba nova ao clicar, já que não faz sentido "ampliar"
// um PDF dentro desse visualizador.
const PhotoLightbox: React.FC<{ photos: OsFotoItem[]; index: number; onClose: () => void; onIndexChange: (i: number) => void }> = ({ photos, index, onClose, onIndexChange }) => {
  const photo = photos[index];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' && photos.length > 1) onIndexChange((index + 1) % photos.length);
      else if (e.key === 'ArrowLeft' && photos.length > 1) onIndexChange((index - 1 + photos.length) % photos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, photos.length, onClose, onIndexChange]);

  if (!photo) return null;

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 40000, background: 'rgba(0,0,0,0.92)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <button
        onClick={onClose}
        style={{ position: 'absolute', top: '16px', right: '16px', width: '38px', height: '38px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.08)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
      ><X size={18} /></button>

      {photos.length > 1 && (
        <button
          onClick={e => { e.stopPropagation(); onIndexChange((index - 1 + photos.length) % photos.length); }}
          style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', width: '42px', height: '42px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.08)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
        ><ChevronLeft size={22} /></button>
      )}

      <img
        src={photo.file_url} alt="Foto da O.S." onClick={e => e.stopPropagation()}
        style={{ maxWidth: '92vw', maxHeight: '84vh', objectFit: 'contain', borderRadius: '8px', boxShadow: '0 10px 40px rgba(0,0,0,0.5)' }}
      />

      {photos.length > 1 && (
        <button
          onClick={e => { e.stopPropagation(); onIndexChange((index + 1) % photos.length); }}
          style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', width: '42px', height: '42px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.08)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
        ><ChevronRight size={22} /></button>
      )}

      {photos.length > 1 && (
        <div style={{ position: 'absolute', bottom: '18px', left: '50%', transform: 'translateX(-50%)', fontSize: '12.5px', fontWeight: 700, color: 'rgba(255,255,255,0.85)', background: 'rgba(255,255,255,0.1)', padding: '4px 12px', borderRadius: '999px' }}>
          {index + 1} / {photos.length}
        </div>
      )}
    </div>
  );
};

const InternalDocToggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void }> = ({ checked, onChange }) => (
  <label style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '11.5px', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px 0' }}>
    <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} style={{ marginTop: '2px', flexShrink: 0 }} />
    <span>Documento interno (ex.: NF de compra pra garantia de fábrica) — não enviar ao cliente, só anexar no Drive/Softsystem</span>
  </label>
);

const OsDetailModal: React.FC<{ codos: number; onClose: () => void }> = ({ codos, onClose }) => {
  const [data, setData] = useState<OsOrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [internalDoc, setInternalDoc] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const result = await fetchOsDetail(codos);
        if (!cancelled) setData(result);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Não foi possível carregar o detalhe da O.S.');
      }
    })();
    return () => { cancelled = true; };
  }, [codos]);

  const handlePhotoSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (cameraInputRef.current) cameraInputRef.current.value = '';
    if (!file) return;
    setPhotoError(null);
    setUploadingPhoto(true);
    const sendToCustomer = !internalDoc;
    try {
      const formData = new FormData();
      formData.append('file', file);
      const newPhoto = await uploadOsPhoto(codos, formData, sendToCustomer);
      setData(prev => prev ? { ...prev, fotos: [newPhoto, ...prev.fotos] } : prev);
    } catch (err: any) {
      setPhotoError(err?.message || 'Não foi possível enviar a foto.');
    } finally {
      setUploadingPhoto(false);
      setInternalDoc(false);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 30000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '520px', maxHeight: '82vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', borderRadius: '12px', overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>O.S. #{codos}</div>
            {data && <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>{data.cliente || '—'} · {data.equipamento || 'Sem equipamento'}</div>}
          </div>
          <button onClick={onClose} style={iconBtn}><X size={16} /></button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {error && <div style={{ color: '#f87171', fontSize: '13px' }}>{error}</div>}
          {!error && !data && <div style={{ color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center', padding: '20px' }}>Carregando…</div>}

          {data && (
            <>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {data.tipo_os && <TipoOsBadge tipo={data.tipo_os} />}
                <span style={{ fontSize: '11px', fontWeight: 700, padding: '3px 9px', borderRadius: '999px', background: `${STAGE_COLORS[data.stage] || '#64748b'}22`, color: STAGE_COLORS[data.stage] || '#94a3b8', border: `1px solid ${STAGE_COLORS[data.stage] || '#64748b'}55` }}>
                  {data.situacao}
                </span>
                {(data.tecnico || data.tecnico2) && (
                  <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)' }}>
                    {[data.tecnico, data.tecnico2].filter(Boolean).join(' + ')}
                  </span>
                )}
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                  <Clock size={14} /> Histórico
                </div>
                {data.historico.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Sem eventos registrados ainda.</div>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  {data.historico.map((h, i) => (
                    <div key={i} style={{ display: 'flex', gap: '10px', padding: '6px 0', borderBottom: i < data.historico.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none' }}>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', flexShrink: 0, minWidth: '82px' }}>{formatDateTime(h.data)}</div>
                      <div style={{ fontSize: '12.5px', color: 'var(--text-main)', fontWeight: 600 }}>
                        {h.evento}
                        {h.obs && h.obs !== 'N/A' && <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', fontWeight: 400, marginTop: '2px' }}>{h.obs}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                  <Package size={14} /> Peças
                </div>
                {data.pecas.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nenhuma peça lançada nesta O.S.</div>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  {data.pecas.map((p, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', padding: '6px 0', borderBottom: i < data.pecas.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none' }}>
                      <div style={{ fontSize: '12.5px', color: 'var(--text-main)', fontWeight: 600 }}>
                        {p.quantidade ? `${p.quantidade}x ` : ''}{p.descricao}
                      </div>
                      {formatMoney(p.preco) && <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>{formatMoney(p.preco)}</div>}
                    </div>
                  ))}
                </div>
                {data.valor_total != null && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.1)', fontSize: '13px', fontWeight: 800 }}>
                    <span style={{ color: 'var(--text-main)' }}>Total</span>
                    <span style={{ color: 'var(--accent-primary, #00e699)' }}>{formatMoney(data.valor_total)}</span>
                  </div>
                )}
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                    <ImageIcon size={14} /> Fotos
                  </div>
                  <button
                    onClick={() => cameraInputRef.current?.click()}
                    disabled={uploadingPhoto}
                    style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '8px', padding: '6px 10px', cursor: uploadingPhoto ? 'default' : 'pointer', opacity: uploadingPhoto ? 0.6 : 1 }}
                  >
                    {uploadingPhoto ? <Loader2 size={14} className="animate-spin" /> : <Camera size={14} />}
                    {uploadingPhoto ? 'Enviando…' : 'Tirar foto'}
                  </button>
                  <input
                    ref={cameraInputRef} type="file" accept="image/*" capture="environment"
                    onChange={handlePhotoSelected} style={{ display: 'none' }}
                  />
                </div>
                <InternalDocToggle checked={internalDoc} onChange={setInternalDoc} />
                {photoError && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '8px' }}>{photoError}</div>}
                {data.fotos.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nenhuma foto tirada ainda nesta O.S.</div>}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))', gap: '8px' }}>
                  {data.fotos.map(f => {
                    const isImage = f.mimetype.startsWith('image/');
                    const imageFotos = data.fotos.filter(x => x.mimetype.startsWith('image/'));
                    const imgIdx = isImage ? imageFotos.findIndex(x => x.id === f.id) : -1;
                    return (
                      <button
                        key={f.id}
                        onClick={() => isImage ? setLightboxIndex(imgIdx) : window.open(f.file_url, '_blank', 'noopener,noreferrer')}
                        style={{ display: 'block', position: 'relative', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.1)', aspectRatio: '1', background: 'rgba(255,255,255,0.03)', padding: 0, cursor: 'pointer' }}
                      >
                        {isImage ? (
                          <img src={f.file_url} alt="Foto da O.S." style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                        ) : (
                          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FileText size={22} color="var(--text-muted)" /></div>
                        )}
                        <div style={{ position: 'absolute', bottom: '3px', right: '3px', display: 'flex', gap: '2px' }} title={`Drive: ${f.gdrive_status} · WhatsApp: ${f.whatsapp_status} · Softsystem: ${f.softsystem_status}`}>
                          {[f.gdrive_status, f.whatsapp_status, f.softsystem_status].map((s, i) => (
                            <span key={i} style={{ width: '6px', height: '6px', borderRadius: '50%', background: s === 'done' ? '#34d399' : s === 'failed' ? '#ef4444' : (s === 'sem_telefone' || s === 'nao_enviar') ? '#94a3b8' : '#f59e0b', boxShadow: '0 0 0 1px rgba(0,0,0,0.4)' }} />
                          ))}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      {lightboxIndex !== null && data && (
        <PhotoLightbox
          photos={data.fotos.filter(f => f.mimetype.startsWith('image/'))}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onIndexChange={setLightboxIndex}
        />
      )}
    </div>
  );
};

// --------------------------------------------------------------------------- relatório em PDF (admin)

const REPORT_STATUS_OPTIONS = [
  { key: 'todas', label: 'Todas' },
  { key: 'abertas', label: 'Em aberto' },
  { key: 'finalizadas', label: 'Finalizadas' },
  { key: 'efetivadas', label: 'Efetivadas (venda/pagamento)' },
];

const ReportPanel: React.FC<{ stages: { key: string; label: string }[]; defaultEmpresa: string; isAdmin: boolean; onClose: () => void }> = ({ stages, defaultEmpresa, isAdmin, onClose }) => {
  const [empresa, setEmpresa] = useState(defaultEmpresa);
  const [tecnico, setTecnico] = useState('todos');
  const [tecnicos, setTecnicos] = useState<string[]>([]);
  const [evento, setEvento] = useState('todos');
  const [status, setStatus] = useState('todas');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState(toInputDate(new Date()));
  const [incluirLista, setIncluirLista] = useState(true);
  // completo = relatório de gestão (KPIs, financeiro, ranking), só admin; lista = só as O.S. do
  // filtro, sem números de acompanhamento - pra imprimir/entregar pro técnico, qualquer atendente
  // pode gerar. Quem não é admin nem vê a opção completo (o backend também bloqueia).
  const [modo, setModo] = useState<'completo' | 'lista'>(isAdmin ? 'completo' : 'lista');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const qs = new URLSearchParams();
        if (empresa) qs.set('empresa', empresa);
        const data = await apiFetch(`/os-board/technicians?${qs.toString()}`);
        if (!cancelled) setTecnicos(data || []);
      } catch { /* lista de técnicos é só conveniência do filtro - falha aqui não impede gerar o relatório */ }
    })();
    return () => { cancelled = true; };
  }, [empresa]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const gerarPdf = async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ tecnico, evento, status, incluir_lista: String(incluirLista), modo });
      if (empresa) qs.set('empresa', empresa);
      if (start) qs.set('start', `${start}T00:00:00`);
      if (end) qs.set('end', `${end}T23:59:59`);
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/v1/os-board/report.pdf?${qs.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Não foi possível gerar o relatório (HTTP ${response.status}).`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível gerar o relatório.');
    } finally {
      setLoading(false);
    }
  };

  const input: React.CSSProperties = {
    padding: '7px 9px', borderRadius: '8px', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)',
    border: '1px solid var(--border-color, rgba(255,255,255,0.12))', fontSize: '12.5px', width: '100%',
  };
  const label: React.CSSProperties = { fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px', display: 'block' };

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 30000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '480px', maxHeight: '88vh', overflowY: 'auto', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', borderRadius: '12px' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>Relatório em PDF</div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
              {modo === 'lista' ? 'Só a lista de O.S. do filtro, pra entregar' : 'Produtividade, financeiro e forma de pagamento'}
            </div>
          </div>
          <button onClick={onClose} style={iconBtn}><X size={16} /></button>
        </div>

        <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {isAdmin ? (
            <div>
              <span style={label}>Tipo de PDF</span>
              <div style={{ display: 'flex', gap: '8px' }}>
                {([
                  { key: 'completo', title: 'Relatório completo', desc: 'KPIs, financeiro, ranking' },
                  { key: 'lista', title: 'Lista simples', desc: 'só as O.S., pra entregar' },
                ] as const).map(opt => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setModo(opt.key)}
                    style={{
                      flex: 1, textAlign: 'left', padding: '8px 10px', borderRadius: '9px', cursor: 'pointer',
                      background: modo === opt.key ? 'rgba(0, 230, 153, 0.14)' : 'var(--bg-secondary, rgba(255,255,255,0.04))',
                      border: modo === opt.key ? '1px solid rgba(0, 230, 153, 0.45)' : '1px solid var(--border-color, rgba(255,255,255,0.12))',
                    }}
                  >
                    <div style={{ fontSize: '12px', fontWeight: 700, color: modo === opt.key ? 'var(--accent-primary)' : 'var(--text-main)' }}>{opt.title}</div>
                    <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{opt.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            // Atendente só tem a lista simples - o relatório completo (financeiro/ranking) é
            // exclusivo de admin, então nem faz sentido mostrar a escolha.
            <div style={{ padding: '8px 10px', borderRadius: '9px', background: 'rgba(0, 230, 153, 0.08)', border: '1px solid rgba(0, 230, 153, 0.25)', fontSize: '11.5px', color: 'var(--text-muted)' }}>
              Lista simples de O.S. (sem dados financeiros) - pra ver, imprimir ou entregar pro técnico.
            </div>
          )}

          <div>
            <span style={label}>Empresa</span>
            <select id="report-empresa" value={empresa} onChange={e => { setEmpresa(e.target.value); setTecnico('todos'); }} style={input}>
              <option value="">Todas</option>
              <option value="servweld">Servweld</option>
              <option value="centrooeste">Centro-Oeste</option>
            </select>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <div style={{ flex: 1 }}>
              <span style={label}>Técnico</span>
              <select id="report-tecnico" value={tecnico} onChange={e => setTecnico(e.target.value)} style={input}>
                <option value="todos">Todos os técnicos</option>
                {tecnicos.map(t => <option key={t} value={t}>{titleCase(t)}</option>)}
                <option value="SEM TÉCNICO">Sem técnico</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <span style={label}>Evento</span>
              <select id="report-evento" value={evento} onChange={e => setEvento(e.target.value)} style={input}>
                <option value="todos">Todos os eventos</option>
                {stages.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
                <option value="finalizada">Finalizada</option>
              </select>
            </div>
          </div>

          <div>
            <span style={label}>Status</span>
            <select id="report-status" value={status} onChange={e => setStatus(e.target.value)} style={input}>
              {REPORT_STATUS_OPTIONS.map(o => <option key={o.key} value={o.key}>{o.label}</option>)}
            </select>
          </div>

          <div style={{ display: 'flex', gap: '10px' }}>
            <div style={{ flex: 1 }}>
              <span style={label}>Entrada de</span>
              <input id="report-start" type="date" value={start} onChange={e => setStart(e.target.value)} style={input} />
            </div>
            <div style={{ flex: 1 }}>
              <span style={label}>até</span>
              <input id="report-end" type="date" value={end} onChange={e => setEnd(e.target.value)} style={input} />
            </div>
          </div>

          {modo === 'completo' && (
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12.5px', color: 'var(--text-main)', cursor: 'pointer' }}>
              <input type="checkbox" checked={incluirLista} onChange={e => setIncluirLista(e.target.checked)} />
              Incluir lista detalhada de O.S. no fim do PDF
            </label>
          )}

          {error && <div style={{ padding: '8px 10px', borderRadius: '8px', background: 'rgba(239,68,68,0.12)', color: '#f87171', fontSize: '12px' }}>{error}</div>}

          <button
            onClick={gerarPdf}
            disabled={loading}
            style={{
              marginTop: '4px', padding: '10px', borderRadius: '9px', background: 'var(--accent-primary, #00e699)', color: '#04140f',
              fontWeight: 800, fontSize: '13px', border: 'none', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.7 : 1,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            }}
          >
            <FileText size={15} /> {loading ? 'Gerando…' : 'Gerar PDF'}
          </button>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', textAlign: 'center' }}>
            O valor de cada O.S. é a soma dos itens lançados no Softsystem - referência para acompanhamento, não substitui o fechamento contábil oficial.
          </div>
        </div>
      </div>
    </div>
  );
};

// --------------------------------------------------------------------------- lista (tela estreita / celular)

export const MobileBoard: React.FC<{
  board: BoardData | null; loading: boolean; stageFilter: string; setStageFilter: (k: string) => void;
  isAdmin: boolean; onOpenTech: (name: string) => void; showEmpresa: boolean;
  onOpenCell: (tecnico: string, stage: string, label: string) => void; onChangeStatus?: ChangeStatusFn;
}> = ({ board, loading, stageFilter, setStageFilter, isAdmin, onOpenTech, showEmpresa, onOpenCell, onChangeStatus }) => {
  const stages = board?.stages || [];
  const stageKeys = stageFilter ? [stageFilter] : stages.map(s => s.key);

  const rows = (board?.technicians || [])
    .map(tech => {
      const items = stageKeys.flatMap(sk => (tech.cells[sk]?.cards || []).map(c => ({ card: c, stageKey: sk })));
      const shown = stageKeys.reduce((sum, sk) => sum + (tech.cells[sk]?.count || 0), 0);
      return { tech, items, shown };
    })
    .filter(r => r.shown > 0);

  return (
    // Mesma estrutura de UM nível só que já funciona na grade (BoardGrid): um único container com
    // overflow:auto, cabeçalho fixo por DENTRO dele via position:sticky - não um wrapper flex extra
    // por fora com o cabeçalho como irmão. Testado em produção: com dois níveis de flex-column (esse
    // wrapper + o container de scroll) a lista não rolava no celular; achatado num nível só, como a
    // grade, resolve.
    <div style={{ flex: 1, overflow: 'auto', WebkitOverflowScrolling: 'touch', touchAction: 'pan-y', overscrollBehavior: 'contain' }}>
      {/* filtro de estágio: como 8 colunas não cabem lado a lado, escolhe-se uma por vez (ou "Todos") */}
      <div style={{ position: 'sticky', top: 0, zIndex: 2, background: 'var(--bg-primary)', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px', padding: '2px 0 8px' }}>
        <StageChip label="Todos" count={board?.total_open ?? 0} active={!stageFilter} onClick={() => setStageFilter('')} />
        {stages.map(st => (
          <StageChip key={st.key} label={st.label} count={board?.totals?.[st.key] ?? 0} color={STAGE_COLORS[st.key]} Icon={STAGE_ICONS[st.key]} active={stageFilter === st.key} onClick={() => setStageFilter(st.key)} />
        ))}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {board && rows.length === 0 && !loading && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>Nenhuma O.S. neste filtro.</div>
        )}
        {rows.map(({ tech, items, shown }) => (
          <div key={tech.name} style={{ border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', overflow: 'hidden', background: 'var(--bg-secondary, rgba(255,255,255,0.02))' }}>
            <div
              onClick={() => { if (isAdmin) onOpenTech(tech.name); }}
              style={{ padding: '10px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-primary, #0b1220)', cursor: isAdmin ? 'pointer' : 'default' }}
            >
              <span style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-main)' }}>{titleCase(tech.name)}</span>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 700 }}>{shown} {stageFilter ? 'nesse estágio' : 'em aberto'}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {items.map(({ card, stageKey }) => (
                <MobileOsRow key={`${card.empresa}-${card.codos}`} card={card} stageLabel={stages.find(s => s.key === stageKey)?.label || stageKey} color={STAGE_COLORS[stageKey]} showEmpresa={showEmpresa} showStage={!stageFilter} onChangeStatus={onChangeStatus} />
              ))}
              {shown > items.length && (
                stageFilter ? (
                  <button
                    onClick={() => onOpenCell(tech.name, stageFilter, stages.find(s => s.key === stageFilter)?.label || stageFilter)}
                    style={{ padding: '8px 12px', fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary)', background: 'rgba(0,230,153,0.08)', border: 'none', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.06))', textAlign: 'center', cursor: 'pointer' }}
                  >Ver todas as {shown} O.S.</button>
                ) : (
                  <div style={{ padding: '8px 12px', fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textAlign: 'center' }}>+{shown - items.length} O.S. (filtre por um estágio pra ver todas)</div>
                )
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const StageChip: React.FC<{ label: string; count: number; active: boolean; onClick: () => void; color?: string; Icon?: LucideIcon }> = ({ label, count, active, onClick, color, Icon }) => {
  // Cor do estágio sempre aparece (não só quando selecionado) - senão os chips ficam todos cinzas e
  // iguais, difícil de bater o olho e achar "Não aprovado" ou "Entrada" rapidamente na lista do
  // celular. Grade de 2 colunas com largura igual (em vez de "pill" que quebra linha torto,
  // pedido do usuário 29/09/2026): texto à esquerda, contador à direita, tudo alinhado.
  const c = color || 'var(--accent-primary)';
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '6px', width: '100%', boxSizing: 'border-box',
        padding: '7px 10px', borderRadius: '8px', minWidth: 0,
        fontSize: '12px', fontWeight: 700, cursor: 'pointer',
        background: active ? `${c}2E` : `${c}14`,
        color: active ? c : 'var(--text-main)',
        border: `1.5px solid ${active ? c : `${c}55`}`,
      }}
    >
      {Icon && <Icon size={13} color={c} style={{ flexShrink: 0 }} />}
      <span style={{ flex: 1, minWidth: 0, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ flexShrink: 0, color: c, fontWeight: 800 }}>{count}</span>
    </button>
  );
};

const MobileOsRow: React.FC<{ card: BoardCard; stageLabel: string; color?: string; showEmpresa: boolean; showStage: boolean; onChangeStatus?: ChangeStatusFn }> = ({ card, stageLabel, color, showEmpresa, showStage, onChangeStatus }) => {
  const dias = card.dias_no_estagio ?? 0;
  const aging = dias >= 15 ? '#ef4444' : dias >= 7 ? '#f59e0b' : null;
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  return (
    <div
      onClick={() => setShowDetail(true)}
      style={{ position: 'relative', padding: '9px 12px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.06))', borderLeft: `3px solid ${aging || color || '#64748b'}`, display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0, cursor: 'pointer' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 800, color: 'var(--text-main)', overflow: 'hidden', minWidth: 0 }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>#{card.codos} {card.cliente ? '· ' + titleCase(card.cliente) : ''}</span>
        <span style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
          <TipoOsBadge tipo={card.tipo_os} />
          <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{fmtDate(card.data_entrada)}</span>
          {onChangeStatus && (
            <button
              ref={btnRef}
              onClick={(e) => { e.stopPropagation(); setAnchorRect(btnRef.current!.getBoundingClientRect()); }}
              title="Mudar status"
              style={{ width: '34px', height: '34px', padding: 0, borderRadius: '7px', border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '18px', lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
            >⋮</button>
          )}
        </span>
      </div>
      {anchorRect && onChangeStatus && (
        <StatusMenu
          anchorRect={anchorRect}
          onClose={() => setAnchorRect(null)}
          onPick={(status, label, obs) => { setAnchorRect(null); onChangeStatus(card.codos, card.empresa, status, label, obs); }}
        />
      )}
      {card.equipamento && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{card.equipamento}</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', fontSize: '11px', marginTop: '2px', flexWrap: 'wrap' }}>
        <span style={{ color: aging || 'var(--text-muted)', fontWeight: aging ? 800 : 500 }}>{dias === 0 ? 'hoje no estágio' : `${dias}d no estágio`}</span>
        <span style={{ display: 'flex', gap: '8px', color: 'var(--text-muted)' }}>
          {showStage && <span style={{ color: color || 'var(--text-muted)', fontWeight: 700 }}>{stageLabel}</span>}
          {showEmpresa && <span>{EMPRESA_LABEL[card.empresa] || card.empresa}</span>}
        </span>
      </div>
      {showDetail && <OsDetailModal codos={card.codos} onClose={() => setShowDetail(false)} />}
    </div>
  );
};

// --------------------------------------------------------------------------- busca (quadro administrativo + Portal do Técnico)

export interface SearchResultCard extends BoardCard {
  tecnico?: string;
  stage_label?: string;
}

// Caixa de busca por O.S., cliente ou equipamento - mesmo componente usado no quadro administrativo
// (TechBoard) e no Portal do Técnico (TechnicianPortal.tsx), cada um passando sua própria função de
// busca (endpoints diferentes: /os-board/search vs /technician-portal/search).
export const SearchBar: React.FC<{ query: string; onQueryChange: (q: string) => void; placeholder?: string }> = ({ query, onQueryChange, placeholder }) => (
  <div style={{ position: 'relative', flex: '1 1 220px', minWidth: '140px', maxWidth: '360px' }}>
    <Search size={14} color="var(--text-muted)" style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
    <input
      value={query}
      onChange={e => onQueryChange(e.target.value)}
      placeholder={placeholder || 'Buscar O.S., cliente ou equipamento...'}
      style={{
        width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 30px', fontSize: '12.5px', fontWeight: 600,
        borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.14))',
        background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)',
      }}
    />
    {query && (
      <button
        onClick={() => onQueryChange('')}
        title="Limpar busca"
        style={{ position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)', width: '20px', height: '20px', borderRadius: '5px', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      ><X size={13} /></button>
    )}
  </div>
);

// Lista de resultados (achatada, sem agrupar por técnico/estágio - mostra os dois como legenda no
// cartão) - reaproveita MobileOsRow pra ficar visualmente igual ao resto do quadro.
export const SearchResultsList: React.FC<{ results: SearchResultCard[]; loading: boolean; showEmpresa: boolean; showTecnico: boolean; onChangeStatus?: ChangeStatusFn }> = ({ results, loading, showEmpresa, showTecnico, onChangeStatus }) => {
  if (loading) {
    return <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Buscando…</div>;
  }
  if (results.length === 0) {
    return <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhuma O.S. em aberto encontrada com esse termo.</div>;
  }
  return (
    <div style={{ flex: 1, overflow: 'auto', WebkitOverflowScrolling: 'touch', touchAction: 'pan-y', overscrollBehavior: 'contain' }}>
      <div style={{ border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', overflow: 'hidden', background: 'var(--bg-secondary, rgba(255,255,255,0.02))' }}>
        {results.map(card => (
          <div key={`${card.empresa}-${card.codos}`}>
            {showTecnico && (
              <div style={{ padding: '6px 12px 0', fontSize: '10.5px', fontWeight: 700, color: 'var(--text-muted)' }}>{titleCase(card.tecnico || '')}</div>
            )}
            <MobileOsRow card={card} stageLabel={card.stage_label || ''} color={STAGE_COLORS[(card as any).stage] } showEmpresa={showEmpresa} showStage onChangeStatus={onChangeStatus} />
          </div>
        ))}
      </div>
    </div>
  );
};

// --------------------------------------------------------------------------- envio rápido de foto/arquivo de O.S.

// Atalho pedido pelo usuário em 05/10/2026: antes só dava pra tirar foto depois de abrir o detalhe
// de uma O.S. específica no quadro. Esse modal fica disponível direto na barra lateral (ver Sidebar
// "Fotos de O.S."), sem precisar achar o cartão da O.S. primeiro - digita o número (ou nome/
// equipamento), confirma qual é, e manda quantas fotos/arquivos quiser de uma vez (câmera ou
// escolhendo vários arquivos do computador/celular). Cada arquivo sobe e aparece com seu próprio
// status assim que termina - nunca espera os outros pra mostrar progresso.
interface QuickUploadFileState {
  key: string; file: File; status: 'uploading' | 'done' | 'error'; error?: string; result?: OsFotoItem;
}

export const OsPhotoQuickUploadModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResultCard[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<SearchResultCard | null>(null);
  const [files, setFiles] = useState<QuickUploadFileState[]>([]);
  const [internalDoc, setInternalDoc] = useState(false);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const filePickerRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!query.trim() || selected) { setResults([]); return; }
    let cancelled = false;
    setSearching(true);
    const handle = setTimeout(async () => {
      try {
        const qs = new URLSearchParams({ q: query.trim() });
        const isTechnician = !!localStorage.getItem('tech_token');
        const data = isTechnician
          ? await techApiFetch(`/search?${qs.toString()}`)
          : await apiFetch(`/os-board/search?${qs.toString()}`);
        if (!cancelled) setResults(data.results || []);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 350);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [query, selected]);

  const uploadOne = async (key: string, file: File, codos: number, sendToCustomer: boolean) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await uploadOsPhoto(codos, formData, sendToCustomer);
      setFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'done', result } : f));
    } catch (err: any) {
      setFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'error', error: err?.message || 'Falha ao enviar' } : f));
    }
  };

  const addFiles = (fileList: FileList | null) => {
    if (!fileList || !fileList.length || !selected) return;
    const codos = selected.codos;
    const sendToCustomer = !internalDoc;
    const toAdd = Array.from(fileList).map((file, i) => ({
      key: `${Date.now()}_${i}_${file.name}`, file, status: 'uploading' as const,
    }));
    setFiles(prev => [...toAdd, ...prev]);
    toAdd.forEach(item => uploadOne(item.key, item.file, codos, sendToCustomer));
    setInternalDoc(false);
  };

  // Depois que termina de subir, ficava sem nenhum "pronto!" claro (pedido do usuário em
  // 05/10/2026: "fica meio vago e nao sabemos se deu certo") - esse resumo só aparece quando
  // TODOS os arquivos da fila já terminaram (sucesso ou falha), nunca enquanto algum ainda sobe.
  const doneCount = files.filter(f => f.status === 'done').length;
  const errorCount = files.filter(f => f.status === 'error').length;
  const allSettled = files.length > 0 && files.every(f => f.status !== 'uploading');

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 30000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '480px', maxHeight: '82vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', borderRadius: '12px', overflow: 'hidden' }}>
        <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-main)' }}>Enviar foto/arquivo de uma O.S.</div>
          <button onClick={onClose} style={iconBtn}><X size={16} /></button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {!selected && (
            <>
              <div>
                <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '6px' }}>Número da O.S., nome do cliente ou equipamento</div>
                <SearchBar query={query} onQueryChange={setQuery} placeholder="Ex.: 33160" />
              </div>
              {query.trim() && (
                searching ? (
                  <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Buscando…</div>
                ) : results.length === 0 ? (
                  <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhuma O.S. em aberto encontrada com esse termo.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {results.map(card => (
                      <button
                        key={`${card.empresa}-${card.codos}`}
                        onClick={() => { setSelected(card); setQuery(''); setResults([]); }}
                        style={{ textAlign: 'left', padding: '10px 12px', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', background: 'var(--bg-secondary, rgba(255,255,255,0.03))', cursor: 'pointer' }}
                      >
                        <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--text-main)' }}>
                          #{card.codos} · {card.cliente ? titleCase(card.cliente) : 'Cliente não identificado'}
                        </div>
                        <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                          {card.equipamento || 'Sem equipamento'} · {EMPRESA_LABEL[card.empresa] || card.empresa}
                        </div>
                      </button>
                    ))}
                  </div>
                )
              )}
            </>
          )}

          {selected && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderRadius: '8px', background: 'rgba(0,230,153,0.08)', border: '1px solid rgba(0,230,153,0.25)' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--text-main)' }}>
                    O.S. #{selected.codos} · {selected.cliente ? titleCase(selected.cliente) : 'Cliente não identificado'}
                  </div>
                  <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    {selected.equipamento || 'Sem equipamento'} · {EMPRESA_LABEL[selected.empresa] || selected.empresa}
                  </div>
                </div>
                <button
                  onClick={() => { setSelected(null); setFiles([]); }}
                  style={{ fontSize: '11.5px', fontWeight: 700, color: 'var(--text-muted)', background: 'transparent', border: '1px solid var(--border-color, rgba(255,255,255,0.16))', borderRadius: '6px', padding: '5px 9px', cursor: 'pointer', flexShrink: 0 }}
                >Trocar</button>
              </div>

              <InternalDocToggle checked={internalDoc} onChange={setInternalDoc} />
              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => cameraInputRef.current?.click()}
                  style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '12.5px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '8px', padding: '10px', cursor: 'pointer' }}
                >
                  <Camera size={15} /> Tirar foto
                </button>
                <button
                  onClick={() => filePickerRef.current?.click()}
                  style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '12.5px', fontWeight: 700, color: 'var(--text-main)', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', border: '1px solid var(--border-color, rgba(255,255,255,0.16))', borderRadius: '8px', padding: '10px', cursor: 'pointer' }}
                >
                  <ImageIcon size={15} /> Escolher arquivos
                </button>
              </div>
              <input
                ref={cameraInputRef} type="file" accept="image/*" capture="environment"
                onChange={e => { addFiles(e.target.files); if (cameraInputRef.current) cameraInputRef.current.value = ''; }}
                style={{ display: 'none' }}
              />
              <input
                ref={filePickerRef} type="file" accept="image/*,application/pdf" multiple
                onChange={e => { addFiles(e.target.files); if (filePickerRef.current) filePickerRef.current.value = ''; }}
                style={{ display: 'none' }}
              />

              {files.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {files.map(f => (
                    <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 10px', borderRadius: '8px', background: 'var(--bg-secondary, rgba(255,255,255,0.03))', border: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
                      {f.status === 'uploading' && <Loader2 size={15} className="animate-spin" color="var(--text-muted)" />}
                      {f.status === 'done' && <CheckCircle2 size={15} color="#34d399" />}
                      {f.status === 'error' && <XCircle size={15} color="#ef4444" />}
                      <div style={{ flex: 1, minWidth: 0, fontSize: '12px', fontWeight: 600, color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {f.file.name}
                      </div>
                      <div style={{ fontSize: '11px', color: f.status === 'error' ? '#f87171' : 'var(--text-muted)', flexShrink: 0 }}>
                        {f.status === 'uploading' ? 'Enviando…' : f.status === 'done' ? (f.result?.whatsapp_status === 'nao_enviar' ? 'Salvo (não enviado ao cliente)' : 'Enviado') : (f.error || 'Falhou')}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {allSettled && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '14px', borderRadius: '10px', textAlign: 'center', background: errorCount === 0 ? 'rgba(52,211,153,0.1)' : 'rgba(239,68,68,0.08)', border: `1px solid ${errorCount === 0 ? 'rgba(52,211,153,0.3)' : 'rgba(239,68,68,0.25)'}` }}>
                  {errorCount === 0 ? (
                    <>
                      <CheckCircle2 size={28} color="#34d399" style={{ margin: '0 auto' }} />
                      <div style={{ fontSize: '13.5px', fontWeight: 800, color: 'var(--text-main)' }}>
                        Pronto! {doneCount === 1 ? '1 arquivo enviado' : `${doneCount} arquivos enviados`} na O.S. #{selected.codos}.
                      </div>
                    </>
                  ) : (
                    <>
                      <XCircle size={28} color="#ef4444" style={{ margin: '0 auto' }} />
                      <div style={{ fontSize: '13.5px', fontWeight: 800, color: 'var(--text-main)' }}>
                        {doneCount > 0 ? `${doneCount} enviado(s), mas ${errorCount} falhou(aram).` : `Falha ao enviar ${errorCount === 1 ? 'o arquivo' : 'os arquivos'}.`} Tenta de novo?
                      </div>
                    </>
                  )}
                  <button
                    onClick={() => { setSelected(null); setFiles([]); }}
                    style={{ alignSelf: 'center', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: 700, color: '#04140d', background: 'var(--accent-primary, #00e699)', border: 'none', borderRadius: '8px', padding: '10px 18px', cursor: 'pointer' }}
                  >
                    Concluir
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

const iconBtn: React.CSSProperties = {
  width: '34px', height: '34px', borderRadius: 'var(--radius-md, 8px)', cursor: 'pointer',
  background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const headCell = (scale: number): React.CSSProperties => ({
  padding: `${6 * scale}px ${7 * scale}px`, fontSize: `${9.5 * scale}px`, fontWeight: 800, textTransform: 'uppercase',
  letterSpacing: '0.2px', color: 'var(--text-main)', background: 'var(--bg-primary, #0b1220)',
  borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.12))', display: 'flex', alignItems: 'center',
  overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
});

const OsCard: React.FC<{ card: BoardCard; color?: string; scale: number; showEmpresa: boolean; onChangeStatus?: ChangeStatusFn }> = ({ card, color, scale, showEmpresa, onChangeStatus }) => {
  const dias = card.dias_no_estagio ?? 0;
  // parada há muito tempo no mesmo estágio: chama atenção
  const aging = dias >= 15 ? '#ef4444' : dias >= 7 ? '#f59e0b' : null;
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  return (
    <div
      onClick={() => setShowDetail(true)}
      title="Ver histórico e peças desta O.S."
      style={{
        position: 'relative', borderRadius: '6px', padding: `${4 * scale}px ${6 * scale}px`, background: 'rgba(255,255,255,0.04)',
        borderLeft: `3px solid ${aging || color || '#64748b'}`, minWidth: 0, overflow: 'visible', cursor: 'pointer',
      }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '4px', fontSize: `${10.5 * scale}px`, fontWeight: 800, color: 'var(--text-main)', overflow: 'hidden', minWidth: 0 }}>
        <span style={{ flexShrink: 0 }}>#{card.codos}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px', overflow: 'hidden', minWidth: 0 }}>
          <TipoOsBadge tipo={card.tipo_os} scale={scale} />
          {onChangeStatus && (
            <button
              ref={btnRef}
              onClick={(e) => { e.stopPropagation(); setAnchorRect(btnRef.current!.getBoundingClientRect()); }}
              title="Mudar status"
              style={{ width: `${Math.max(16 * scale, 28)}px`, height: `${Math.max(16 * scale, 28)}px`, flexShrink: 0, padding: 0, borderRadius: '6px', border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', cursor: 'pointer', fontSize: `${Math.max(10 * scale, 15)}px`, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >⋮</button>
          )}
        </span>
      </div>
      <div style={{ fontSize: `${9.5 * scale}px`, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={card.cliente || ''}>
        {card.cliente ? titleCase(card.cliente) : '—'}
      </div>
      {card.equipamento && (
        <div style={{ fontSize: `${9 * scale}px`, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={card.equipamento}>
          {card.equipamento}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '4px', fontSize: `${8.5 * scale}px`, marginTop: '2px' }}>
        <span style={{ color: aging || 'var(--text-muted)', fontWeight: aging ? 800 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{dias === 0 ? 'hoje' : `${dias}d`}</span>
        <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>{fmtDate(card.data_entrada)}{showEmpresa ? ` · ${(EMPRESA_LABEL[card.empresa] || card.empresa).slice(0, 4)}` : ''}</span>
      </div>
      {anchorRect && onChangeStatus && (
        <StatusMenu
          anchorRect={anchorRect}
          onClose={() => setAnchorRect(null)}
          onPick={(status, label, obs) => { setAnchorRect(null); onChangeStatus(card.codos, card.empresa, status, label, obs); }}
        />
      )}
      {showDetail && <OsDetailModal codos={card.codos} onClose={() => setShowDetail(false)} />}
    </div>
  );
};

// Menuzinho flutuante com os 3 status que o técnico pode definir - usado tanto no cartão da grade
// (OsCard) quanto na linha da lista (MobileOsRow).
const STATUS_LABELS: Record<number, string> = { 6: 'Aguardando retirada', 11: 'Sem conserto', 13: 'Sem defeito' };

// Flutua via portal direto no <body>, posicionado em 'fixed' pelas coordenadas reais do botão que
// abriu - nunca fica preso/cortado por nenhum contêiner com overflow:hidden no meio do caminho
// (já tentei "furar" isso ajustando overflow container por container - achado em produção,
// 29/09/2026, que sempre sobrava algum nível intermediário cortando o menu; só resolveu de vez
// saindo inteiramente da árvore de recorte).
// Confirmado em produção (30/09/2026): dentro do app instalado pelo Google Play (TWA), window.prompt
// E window.confirm não disparam diálogo nenhum - o clique simplesmente não faz nada visível (o app
// fica esperando uma resposta de UI nativa que esse ambiente não sabe mostrar). Por isso o menu
// inteiro (escolher status, perguntar o motivo do "sem conserto", confirmar) é resolvido só com UI
// própria dentro do mesmo portal, nunca com diálogo nativo do navegador.
const StatusMenu: React.FC<{ anchorRect: DOMRect; onClose: () => void; onPick: (status: number, label: string, obs?: string) => void }> = ({ anchorRect, onClose, onPick }) => {
  const [step, setStep] = useState<'menu' | 'motivo' | 'confirm'>('menu');
  const [pendingKey, setPendingKey] = useState<number | null>(null);
  const [obsText, setObsText] = useState('');

  useEffect(() => {
    if (step !== 'menu') return; // com o textarea/confirmação aberta, clique fora não deve fechar sozinho
    const onDocClick = () => onClose();
    // "capture" pra fechar antes de qualquer outro onClick da página processar o clique de fora
    document.addEventListener('click', onDocClick, true);
    return () => document.removeEventListener('click', onDocClick, true);
  }, [onClose, step]);

  const choose = (key: number) => {
    setPendingKey(key);
    // "Sem conserto" é o único cujo texto ao cliente muda com o motivo (ver
    // AutomationService.sem_conserto_motivo, no backend) - pergunta antes de confirmar. Opcional:
    // sem motivo, vai a mensagem padrão, sem detalhe.
    setStep(key === 11 ? 'motivo' : 'confirm');
  };

  const confirm = () => {
    if (pendingKey == null) return;
    onPick(pendingKey, STATUS_LABELS[pendingKey], pendingKey === 11 ? (obsText.trim() || undefined) : undefined);
  };

  const menuWidth = step === 'menu' ? 170 : 220;
  const spaceBelow = window.innerHeight - anchorRect.bottom;
  const openUpward = spaceBelow < 220 && anchorRect.top > 220;
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.max(8, Math.min(anchorRect.right - menuWidth, window.innerWidth - menuWidth - 8)),
    ...(openUpward ? { bottom: window.innerHeight - anchorRect.top + 4 } : { top: anchorRect.bottom + 4 }),
    zIndex: 9999, background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.18))',
    borderRadius: '8px', boxShadow: '0 6px 18px rgba(0,0,0,0.4)', overflow: 'hidden', width: `${menuWidth}px`,
  };

  const btnStyle: React.CSSProperties = { display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: '12.5px', fontWeight: 700, color: 'var(--text-main)', background: 'transparent', border: 'none', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))', cursor: 'pointer' };
  const cancelStyle: React.CSSProperties = { display: 'block', width: '100%', textAlign: 'center', padding: '8px', fontSize: '11px', color: 'var(--text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' };

  let body: React.ReactNode;
  if (step === 'menu') {
    body = (
      <>
        {TECH_STATUS_OPTIONS.map(opt => (
          <button key={opt.key} onClick={() => choose(opt.key)} style={btnStyle}>{STATUS_LABELS[opt.key]}</button>
        ))}
        <button onClick={onClose} style={cancelStyle}>Cancelar</button>
      </>
    );
  } else if (step === 'motivo') {
    body = (
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '11.5px', fontWeight: 700, color: 'var(--text-main)' }}>Motivo (opcional)</div>
        <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Aparece resumido na mensagem pro cliente.</div>
        <textarea
          autoFocus
          value={obsText}
          onChange={e => setObsText(e.target.value)}
          rows={3}
          style={{ width: '100%', boxSizing: 'border-box', resize: 'none', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12.5px', padding: '6px 8px', fontFamily: 'inherit' }}
        />
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={() => setStep('menu')} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>Voltar</button>
          <button onClick={() => setStep('confirm')} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '11.5px', fontWeight: 800, cursor: 'pointer' }}>Continuar</button>
        </div>
      </div>
    );
  } else {
    body = (
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>
          Marcar como "{pendingKey != null ? STATUS_LABELS[pendingKey] : ''}"?
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={() => setStep(pendingKey === 11 ? 'motivo' : 'menu')} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>Voltar</button>
          <button onClick={confirm} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '11.5px', fontWeight: 800, cursor: 'pointer' }}>Confirmar</button>
        </div>
      </div>
    );
  }

  return createPortal(
    <div onClick={e => e.stopPropagation()} style={style}>
      {body}
    </div>,
    document.body
  );
};

// --------------------------------------------------------------------------- carrossel (modo TV)

const TvCarousel: React.FC<{
  board: BoardData | null; loading: boolean; activeIndex: number; carouselMs: number; carouselKey: number;
  onGoTo: (i: number) => void; scale: number; fs: (px: number) => string;
  onOpenCell: (tecnico: string, stage: string, label: string) => void;
}> = ({ board, loading, activeIndex, carouselMs, carouselKey, onGoTo, scale, fs, onOpenCell }) => {
  const stages = board?.stages || [];
  const tech = board?.technicians[activeIndex];

  // Uma célula pode ter mais O.S. do que cabe na tela de uma vez (ex.: "Entrada" com 26) - em vez de
  // esconder o resto atrás de um botão que ninguém vai clicar de longe, o conteúdo da célula vira
  // páginas de PAGE_SIZE cartões, trocando sozinho a cada PAGE_ROTATE_MS, então dentro do tempo em
  // que o técnico fica na tela dá pra ver TODAS as O.S. daquele estágio, não só as primeiras.
  const PAGE_SIZE = 6;
  const PAGE_ROTATE_MS = 4500;
  const [subTick, setSubTick] = useState(0);
  useEffect(() => { setSubTick(0); }, [carouselKey]);
  useEffect(() => {
    const t = window.setInterval(() => setSubTick(s => s + 1), PAGE_ROTATE_MS);
    return () => window.clearInterval(t);
  }, []);

  if (!board || board.technicians.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: fs(16) }}>
        {loading ? 'Carregando…' : 'Nenhuma O.S. em aberto neste filtro.'}
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', background: 'var(--bg-secondary, rgba(255,255,255,0.02))', overflow: 'hidden' }}>
      {/* Barra de progresso até trocar de técnico - reinicia a animação a cada slide (key) */}
      <div style={{ height: '3px', background: 'rgba(255,255,255,0.06)', flexShrink: 0 }}>
        <div key={carouselKey} style={{ height: '100%', background: 'var(--accent-primary)', animation: `tvCarouselProgress ${carouselMs}ms linear forwards` }} />
      </div>
      <style>{'@keyframes tvCarouselProgress { from { width: 0% } to { width: 100% } }'}</style>

      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: `repeat(${Math.max(stages.length, 1)}, 1fr)`, overflow: 'hidden' }}>
        {stages.map(st => {
          const cell = tech?.cells[st.key] || { count: 0, cards: [] };
          const totalPages = Math.max(1, Math.ceil(cell.cards.length / PAGE_SIZE));
          const page = subTick % totalPages;
          const visibleCards = cell.cards.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
          return (
            <div key={st.key} style={{ display: 'flex', flexDirection: 'column', minWidth: 0, borderRight: '1px solid var(--border-color, rgba(255,255,255,0.06))' }}>
              <div
                title={st.label}
                style={{
                  padding: `${9 * scale}px ${8 * scale}px`, borderTop: `3px solid ${STAGE_COLORS[st.key] || '#64748b'}`,
                  borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.12))', background: 'var(--bg-primary, #0b1220)',
                  flexShrink: 0, minHeight: `${64 * scale}px`, display: 'flex', flexDirection: 'column', justifyContent: 'center',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '4px' }}>
                  <div style={{ fontSize: fs(11), fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.2px', color: 'var(--text-main)', lineHeight: 1.2 }}>{st.label}</div>
                  {totalPages > 1 && <div style={{ fontSize: fs(9), fontWeight: 700, color: 'var(--text-muted)', flexShrink: 0 }}>{page + 1}/{totalPages}</div>}
                </div>
                <div style={{ fontSize: fs(13), fontWeight: 800, color: STAGE_COLORS[st.key] || 'var(--text-muted)', marginTop: '2px' }}>{cell.count}</div>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: `${6 * scale}px`, display: 'flex', flexDirection: 'column', gap: `${5 * scale}px` }}>
                {visibleCards.map(card => <OsCard key={`${card.empresa}-${card.codos}`} card={card} color={STAGE_COLORS[st.key]} scale={scale} showEmpresa />)}
                {cell.count > cell.cards.length && tech && (
                  <button
                    onClick={() => onOpenCell(tech.name, st.key, st.label)}
                    style={{ fontSize: fs(11), fontWeight: 700, color: 'var(--accent-primary)', textAlign: 'center', padding: '4px 0', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.25)', borderRadius: '6px', cursor: 'pointer' }}
                  >+{cell.count - cell.cards.length} O.S.</button>
                )}
              </div>
              {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'center', gap: '3px', padding: `${4 * scale}px 0 ${6 * scale}px` }}>
                  {Array.from({ length: totalPages }).map((_, i) => (
                    <span key={i} style={{
                      width: i === page ? '12px' : '5px', height: '5px', borderRadius: '3px', transition: 'width 0.3s',
                      background: i === page ? (STAGE_COLORS[st.key] || 'var(--accent-primary)') : 'rgba(255,255,255,0.15)',
                    }} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Pontos de navegação - um por técnico, clicável para pular direto e reiniciar a contagem */}
      <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap', padding: `${8 * scale}px ${10 * scale}px`, borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))', flexShrink: 0, background: 'var(--bg-primary, #0b1220)' }}>
        {board.technicians.map((t, i) => (
          <button
            key={t.name}
            onClick={() => onGoTo(i)}
            title={`${titleCase(t.name)} (${t.total_open} em aberto)`}
            style={{
              padding: i === activeIndex ? '4px 10px' : '4px 8px', borderRadius: '999px', fontSize: fs(10), fontWeight: 700, cursor: 'pointer',
              background: i === activeIndex ? 'rgba(0,230,153,0.18)' : 'transparent',
              color: i === activeIndex ? 'var(--accent-primary)' : 'var(--text-muted)',
              border: `1px solid ${i === activeIndex ? 'rgba(0,230,153,0.4)' : 'var(--border-color, rgba(255,255,255,0.1))'}`,
            }}
          >{i === activeIndex ? titleCase(t.name) : i + 1}</button>
        ))}
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
  { key: 'efetivadas', label: 'Efetivadas (venda/pagamento)' },
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
    const lines = [['O.S.', 'Empresa', 'Tipo de O.S.', 'Cliente', 'Equipamento', 'Técnico', 'Técnico 2', 'Entrada', 'Situação', 'Finalizada em', 'Efetivada', 'Venda', 'Linha do tempo']
      .map(q).join(';')];
    for (const o of data.orders) {
      lines.push([
        o.codos, EMPRESA_LABEL[o.empresa] || o.empresa, o.tipo_os, o.cliente, o.equipamento, o.tecnico, o.tecnico2,
        fmtDateTime(o.data_entrada), o.situacao, fmtDateTime(o.finalizada_em), o.efetivada_motivo ? 'sim' : 'não',
        o.venda_codigo ? `#${o.venda_codigo}` : '',
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
          {tile('Efetivadas no período', data.summary.efetivadas_no_periodo, '#64748b')}
        </div>
      )}

      <div style={{ border: '1px solid var(--border-color, rgba(255,255,255,0.08))', borderRadius: '10px', overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '760px' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              {['O.S.', 'Tipo', 'Cliente / Equipamento', 'Entrada', 'Situação', 'Finalizada', 'Linha do tempo'].map(h => (
                <th key={h} style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.12))' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Carregando…</td></tr>}
            {!loading && data && data.orders.length === 0 && (
              <tr><td colSpan={7} style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Nenhuma O.S. neste filtro.</td></tr>
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
                    <td style={{ padding: '9px 12px' }}><TipoOsBadge tipo={o.tipo_os} /></td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>
                      {o.cliente ? titleCase(o.cliente) : '—'}
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{o.equipamento || ''}</div>
                    </td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>{fmtDateTime(o.data_entrada)}</td>
                    <td style={{ padding: '9px 12px' }}>
                      <span style={{ padding: '2px 8px', borderRadius: '999px', fontSize: '11px', fontWeight: 700, background: `${STAGE_COLORS[o.stage] || '#64748b'}26`, color: STAGE_COLORS[o.stage] || 'var(--text-muted)' }}>{o.situacao}</span>
                      {o.efetivada_motivo && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>{o.efetivada_motivo}</div>}
                    </td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-main)' }}>{fmtDateTime(o.finalizada_em)}</td>
                    <td style={{ padding: '9px 12px', color: 'var(--text-muted)' }}>{o.timeline.length} evento(s) {open ? '▲' : '▼'}</td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={7} style={{ padding: '6px 12px 14px 40px', background: 'rgba(255,255,255,0.02)' }}>
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
