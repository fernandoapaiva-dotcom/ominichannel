import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeft, Download, FileText, Monitor, RefreshCw, X, Clock,
  Inbox, Search, CheckCircle2, XCircle, Wrench, Package, PackageCheck, AlertTriangle, Trash2,
  Camera, Image as ImageIcon, Loader2, ChevronLeft, ChevronRight, Video, Paperclip, Sparkles, Bell, Menu,
  BarChart3, ZoomIn, ZoomOut, Maximize2, MessageSquare, Eye, EyeOff,
  type LucideIcon,
} from 'lucide-react';
import { TechDashboard } from './TechDashboard';
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
  // pendência interna aberta (alerta "!") - ver OsInteractionsSection
  pendencia?: { mensagem: string; autor: string; criado_em: string } | null;
}

// Status que o Portal do Técnico deixa o próprio técnico mudar direto pelo cartão (ver
// TECHNICIAN_ALLOWED_STATUSES no backend) - só passado como prop quando faz sentido (aba "Minhas
// O.S.", nunca no quadro administrativo nem no "Quadro Geral").
export const TECH_STATUS_OPTIONS: { key: number; short: string }[] = [
  { key: 4, short: 'Execução' },
  { key: 8, short: 'Aguard. Peça' },
  { key: 6, short: 'Retirada' },
  { key: 13, short: 'S/ Defeito' },
  { key: 11, short: 'S/ Conserto' },
  { key: 7, short: 'Finalizada' },
];

// Transições permitidas pelo app, por CHAVE de estágio atual (mesma chave usada nas células do
// quadro - ver BoardData.stages/BOARD_STAGES no backend) - expandido em 07/10/2026, mesmo mapa
// do backend (technician_portal.TECHNICIAN_ALLOWED_TRANSITIONS), só que indexado por chave de
// string em vez de código numérico porque é isso que já está disponível em cada card renderizado
// (sem precisar saber se "sem_reparo" é código 11 ou 13 - as duas vão pro mesmo lugar: Finalizada).
// "Retirada" (6) também aparece antes da aprovação (entrada/avaliação/orçamento/não aprovado) -
// pedido do usuário em 14/10/2026: aí o backend não muda o status, reenvia o orçamento pro
// cliente e devolve status "needs_approval" pro app mostrar o aviso (ver TechnicianPortal.tsx).
const STAGE_KEY_ALLOWED_TRANSITIONS: Record<string, number[]> = {
  entrada: [11, 13, 6],
  avaliacao: [11, 13, 6],
  orcamento: [6],
  nao_aprovado: [6],
  aprovado: [4, 8, 6],
  peca: [4, 6],
  execucao: [6],
  sem_reparo: [7, 6],
  descarte: [7],
};
// Garantia (de loja ou de fábrica) vai pra "Aguardando retirada" de qualquer estágio em aberto, sem
// aprovação do cliente - pedido do usuário em 14/10/2026 (backend: technician_portal._retirada_livre).
const isGarantia = (tipoOs?: string | null) => tipoOs === 'Garantia de Loja' || tipoOs === 'Garantia de Fábrica';
const allowedStatusKeys = (stageKey: string, tipoOs?: string | null): number[] => {
  const base = STAGE_KEY_ALLOWED_TRANSITIONS[stageKey] || [];
  if (isGarantia(tipoOs) && !base.includes(6) && stageKey !== 'retirada' && stageKey !== 'finalizada') return [...base, 6];
  return base;
};

// Admin na plataforma: todos os status liberados (menu "⋮" do cartão e botões dentro da O.S.).
// Só o TechBoard do escritório provê true - Portal do Técnico e demais usuários ficam no padrão.
const StatusPermContext = React.createContext<{ podeTudo: boolean }>({ podeTudo: false });

export type ChangeStatusFn = (codos: number, empresa: string, status: number, label: string, obs?: string) => void;
export interface BoardCell { count: number; cards: BoardCard[] }
export interface BoardTech { name: string; total_open: number; cells: Record<string, BoardCell> }
export interface BoardData {
  stages: { key: string; label: string }[];
  technicians: BoardTech[];
  totals: Record<string, number>;
  total_open: number;
  generated_at: string;
  leaderboard?: { tecnico: string; finalizadas: number }[];
  leaderboard_month_label?: string;
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
  tipo_os?: string | null; situacao: string; situacao_evento?: number | null; stage: string;
  pode_mudar_qualquer_status?: boolean;
  valor_total?: number | null; forma_pagamento?: string | null; tecnico_nota?: string | null;
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
// Alerta "!" no cartão quando a O.S. tem pendência interna aberta (ex.: "parei, placa sem
// estoque") - some sozinho quando alguém resolve pela seção Interações da O.S.
const PendenciaBadge: React.FC<{ pendencia?: BoardCard['pendencia']; size?: number }> = ({ pendencia, size = 18 }) => {
  if (!pendencia) return null;
  return (
    <span
      title={`Pendência: ${pendencia.mensagem} (${pendencia.autor})`}
      style={{ width: `${size}px`, height: `${size}px`, borderRadius: '50%', background: '#ef4444', color: '#fff', fontWeight: 900, fontSize: `${Math.round(size * 0.7)}px`, lineHeight: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 0 0 2px rgba(239,68,68,0.25)' }}
    >!</span>
  );
};

export const titleCase = (s: string) => s.toLowerCase().replace(/(^|\s)\S/g, c => c.toUpperCase());

// Cor fixa por técnico (sempre a mesma pro mesmo nome, determinístico) - pedido do usuário em
// 07/10/2026: "tudo amarelo fica ruim, cada um com uma cor percebe melhor" no letreiro de
// observações. Paleta escolhida pra ter bom contraste em fundo escuro.
const TECHNICIAN_COLORS = ['#fde047', '#60a5fa', '#34d399', '#f472b6', '#a78bfa', '#fb923c', '#22d3ee', '#4ade80', '#fca5a5', '#38bdf8'];
export const colorForTechnician = (name: string): string => {
  const norm = (name || '').trim().toUpperCase();
  let hash = 0;
  for (let i = 0; i < norm.length; i++) hash = (hash * 31 + norm.charCodeAt(i)) >>> 0;
  return TECHNICIAN_COLORS[hash % TECHNICIAN_COLORS.length];
};
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
  // Mudança de status pelo "⋮" dos cartões do quadro do escritório (pedido do usuário em
  // 14/10/2026) - admin com todos os status (StatusPermContext), demais com a regra do estágio.
  const [statusNotice, setStatusNotice] = useState<{ kind: 'ok' | 'aviso' | 'erro'; title?: string; text: string } | null>(null);
  useEffect(() => {
    if (!statusNotice || statusNotice.kind === 'aviso') return;
    const t = window.setTimeout(() => setStatusNotice(null), 5000);
    return () => window.clearTimeout(t);
  }, [statusNotice]);
  const handleChangeStatus: ChangeStatusFn = async (codos, _empresa, status, _label, obs) => {
    try {
      const res = await apiFetch(`/os-board/order/${codos}/status`, { method: 'POST', body: JSON.stringify({ status, obs }) });
      if (res?.status === 'needs_approval') setStatusNotice({ kind: 'aviso', title: res.title, text: res.message });
      else setStatusNotice({ kind: 'ok', text: res?.message || 'Status atualizado.' });
      window.dispatchEvent(new CustomEvent('os-board-update'));
    } catch (err: any) {
      setStatusNotice({ kind: 'erro', text: err?.message || 'Não foi possível mudar o status.' });
    }
  };

  // Modo TV: carrossel passando por um técnico de cada vez (em vez da grade estática, onde os técnicos
  // de baixo ficavam escondidos - ninguém rola a tela sozinho de longe). CAROUSEL_MS por técnico.
  // Um slide a mais no final do giro é o Painel do Fluxo (gráficos + ranking do mês) - pedido do
  // usuário em 08/10/2026 ("aplica no modo TV também pra aparecer").
  const CAROUSEL_MS = 60000;
  const [carouselIndex, setCarouselIndex] = useState(0);
  const techCount = board?.technicians.length || 0;
  const totalSlides = techCount + 1;
  const rawSlideIndex = techCount > 0 ? ((carouselIndex % totalSlides) + totalSlides) % totalSlides : 0;
  const isDashboardSlide = techCount > 0 && rawSlideIndex === techCount;
  const activeIndex = isDashboardSlide ? 0 : rawSlideIndex;
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

  // Painel do Fluxo (gráficos + ranking "funcionário do mês") - pedido do usuário em 08/10/2026.
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [leaderboard, setLeaderboard] = useState<{ tecnico: string; finalizadas: number }[]>([]);
  const [leaderboardMonth, setLeaderboardMonth] = useState('');

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
      // Ranking do mês - busca junto (payload leve) pra já estar pronto quando o Modo TV girar
      // pro slide do painel, sem precisar esperar mais uma chamada na hora.
      const dashQs = new URLSearchParams();
      if (empresa) dashQs.set('empresa', empresa);
      apiFetch(`/os-board/dashboard?${dashQs.toString()}`)
        .then(d => { setLeaderboard(d.leaderboard || []); setLeaderboardMonth(d.leaderboard_month_label || ''); })
        .catch(() => {});
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
    <StatusPermContext.Provider value={{ podeTudo: isAdmin }}>
    <div style={wrapperStyle}>
      <NotesTicker />
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
            <button onClick={() => setDashboardOpen(true)} style={{ ...iconBtn, width: 'auto', padding: '0 12px', gap: '6px', display: 'flex', alignItems: 'center', fontSize: '12px', fontWeight: 700 }}>
              <BarChart3 size={15} /> Painel
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
      {tvMode && board && techCount > 0 && !isDashboardSlide && (
        <div style={{ textAlign: 'center', margin: '2px 0 14px', flexShrink: 0 }}>
          <div style={{ fontSize: fs(46), fontWeight: 900, color: 'var(--accent-primary)', letterSpacing: '0.5px', lineHeight: 1.1 }}>
            {titleCase(board.technicians[activeIndex].name)}
          </div>
          <div style={{ fontSize: fs(14), color: 'var(--text-muted)', fontWeight: 700, marginTop: '4px' }}>
            Técnico {activeIndex + 1} de {techCount} · {board.technicians[activeIndex].total_open} O.S. em aberto
          </div>
        </div>
      )}

      {tvMode && board && isDashboardSlide && (
        <div style={{ textAlign: 'center', margin: '2px 0 14px', flexShrink: 0 }}>
          <div style={{ fontSize: fs(34), fontWeight: 900, color: 'var(--accent-primary)', letterSpacing: '0.5px', lineHeight: 1.1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
            <BarChart3 size={34} /> Painel do Fluxo
          </div>
          <div style={{ fontSize: fs(14), color: 'var(--text-muted)', fontWeight: 700, marginTop: '4px' }}>
            Status das O.S. e destaque do mês
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
        <SearchResultsList results={searchResults} loading={searching} showEmpresa={!empresa} showTecnico onChangeStatus={handleChangeStatus} />
      ) : tvMode && isDashboardSlide && board ? (
        <TechDashboard board={{ ...board, leaderboard, leaderboard_month_label: leaderboardMonth }} tvMode />
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
          onChangeStatus={handleChangeStatus}
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
          onChangeStatus={handleChangeStatus}
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
          onChangeStatus={handleChangeStatus}
        />
      )}

      {statusNotice && (
        <div style={{ position: 'fixed', left: '50%', bottom: '24px', transform: 'translateX(-50%)', zIndex: 10000, width: 'min(440px, calc(100% - 32px))', padding: '12px 14px', borderRadius: '10px', background: 'var(--bg-primary, #0b1220)', border: `1px solid ${statusNotice.kind === 'ok' ? 'rgba(34,197,94,0.5)' : statusNotice.kind === 'aviso' ? 'rgba(245,158,11,0.6)' : 'rgba(248,113,113,0.6)'}`, boxShadow: '0 8px 24px rgba(0,0,0,0.45)', display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
          <div style={{ flex: 1, fontSize: '12.5px', lineHeight: 1.45, color: 'var(--text-main)' }}>
            {statusNotice.title && <div style={{ fontWeight: 800, color: '#f59e0b', marginBottom: '2px' }}>{statusNotice.title}</div>}
            <span style={{ fontWeight: statusNotice.title ? 400 : 700, color: statusNotice.kind === 'erro' ? '#f87171' : statusNotice.kind === 'ok' ? '#22c55e' : 'var(--text-main)' }}>{statusNotice.text}</span>
          </div>
          <button onClick={() => setStatusNotice(null)} style={{ ...iconBtn, width: '26px', height: '26px', flexShrink: 0 }}><X size={14} /></button>
        </div>
      )}

      {reportOpen && (
        <ReportPanel stages={stages} defaultEmpresa={empresa} isAdmin={isAdmin} onClose={() => setReportOpen(false)} />
      )}

      {dashboardOpen && board && (
        <div onClick={() => setDashboardOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 30000, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}>
          <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '980px', maxHeight: '88vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.12))', borderRadius: '12px', padding: '16px 18px' }}>
            <TechDashboard board={{ ...board, leaderboard, leaderboard_month_label: leaderboardMonth }} onClose={() => setDashboardOpen(false)} />
          </div>
        </div>
      )}
    </div>
    </StatusPermContext.Provider>
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
                  {cell.cards.map(card => <OsCard key={`${card.empresa}-${card.codos}`} card={card} stageKey={st.key} color={STAGE_COLORS[st.key]} scale={scale} showEmpresa={showEmpresa} onChangeStatus={onChangeStatus} />)}
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

const CellModal: React.FC<{ tecnico: string; stage: string; label: string; empresa: string; showEmpresa: boolean; onClose: () => void; onChangeStatus?: ChangeStatusFn }> = ({ tecnico, stage, label, empresa, showEmpresa, onClose, onChangeStatus }) => {
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
            <MobileOsRow key={`${card.empresa}-${card.codos}`} card={card} stageLabel={label} stageKey={stage} color={STAGE_COLORS[stage]} showEmpresa={showEmpresa} showStage={false} onChangeStatus={onChangeStatus} />
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
// Quem está usando a tela sai do APP aberto (ver main.tsx), não de existir um tech_token salvo -
// achado em 13/10/2026: o dono entrou no Portal do Técnico nesse mesmo navegador (pra testar o
// Copiloto), o tech_token ficou guardado, e o Quadro administrativo passou a se comportar como
// técnico - escondia a seção "Relatório pro Cliente" (rascunho da IA + "Gerar com IA") e chamava
// os endpoints do técnico. Admin e técnico logados juntos no mesmo navegador é cenário previsto
// (ver techApi.ts), então o token sozinho nunca diz em qual dos dois apps a pessoa está.
// /foto-os aceita os dois logins e prefere o do técnico (FotoLauncherApp.checkAuth) - lá o token
// continua sendo o critério certo.
const isTechnicianSession = (): boolean => {
  const path = window.location.pathname;
  if (path.startsWith('/tecnico')) return true;
  if (path.startsWith('/foto-os')) return !!localStorage.getItem('tech_token');
  return false;
};

const fetchOsDetail = (codos: number) => {
  const isTechnician = isTechnicianSession();
  return isTechnician ? techApiFetch(`/order/${codos}`) : apiFetch(`/os-board/order/${codos}`);
};

// Mesma escolha de cliente HTTP do fetchOsDetail acima - admin e técnico sobem a foto pra
// endpoints espelhados (os_board.upload_order_photo / technician_portal.technician_upload_order_photo).
// sendToCustomer=false: documento interno (ex.: NF de compra que o cliente apresenta pra acionar
// garantia de fábrica - pedido do usuário em 05/10/2026) - sobe pro Drive e anexa no Softsystem
// igual, só não dispara pro WhatsApp do cliente (ele já tem o original, não faz sentido devolver).
const uploadOsPhoto = (codos: number, formData: FormData, sendToCustomer: boolean) => {
  formData.append('send_to_customer', sendToCustomer ? 'true' : 'false');
  const isTechnician = isTechnicianSession();
  return isTechnician ? techApiUpload(`/order/${codos}/photos`, formData) : apiUpload(`/os-board/order/${codos}/photos`, formData);
};

// Laudo técnico (vai pro campo Observação do Softsystem) + mensagem pro cliente (vai no PDF),
// gerados pela IA a partir do que já está lançado na O.S. (peças/mão de obra + nota do técnico) -
// ver backend/app/services/os_report_service.py. getOsReport busca um rascunho já pronto (gerado
// sozinho pela varredura automática); draftOsReport gera/regenera do zero; rejectOsReport reprova
// com um motivo e pede nova versão; sendOsReport aprova e manda de verdade (PDF pro cliente +
// grava no Softsystem).
const getOsReport = (codos: number) => {
  const isTechnician = isTechnicianSession();
  return isTechnician ? techApiFetch(`/order/${codos}/report`) : apiFetch(`/os-board/order/${codos}/report`);
};

// Último relatório já enviado (só no quadro administrativo - a seção de relatório não aparece
// pro técnico): libera o "Reenviar com valores atualizados" quando o preço foi renegociado.
const getOsLastSentReport = (codos: number): Promise<{ enviado_em: string; aprovado_por: string | null; valor_total: number | null }> =>
  apiFetch(`/os-board/order/${codos}/last-sent-report`);

const draftOsReport = (codos: number) => {
  const isTechnician = isTechnicianSession();
  return isTechnician ? techApiFetch(`/order/${codos}/draft-report`, { method: 'POST' }) : apiFetch(`/os-board/order/${codos}/draft-report`, { method: 'POST' });
};

const rejectOsReport = (codos: number, reason: string) => {
  const isTechnician = isTechnicianSession();
  const body = JSON.stringify({ reason });
  return isTechnician ? techApiFetch(`/order/${codos}/reject-report`, { method: 'POST', body }) : apiFetch(`/os-board/order/${codos}/reject-report`, { method: 'POST', body });
};

const sendOsReport = (codos: number, internalNote: string, customerMessage: string) => {
  const isTechnician = isTechnicianSession();
  const body = JSON.stringify({ internal_note: internalNote, customer_message: customerMessage });
  return isTechnician ? techApiFetch(`/order/${codos}/send-report`, { method: 'POST', body }) : apiFetch(`/os-board/order/${codos}/send-report`, { method: 'POST', body });
};

// Checkbox compartilhado pelos dois pontos de upload (OsDetailModal e OsPhotoQuickUploadModal) -
// reseta sozinho pro padrão (enviar) depois de cada envio, pra não esquecer marcado sem querer e
// pular o envio de uma foto que devia ir pro cliente.
// Visualizador de foto em tela cheia, dentro da própria página (pedido do usuário em 05/10/2026:
// clicar numa foto abria aba nova do navegador, perdendo o contexto da O.S.) - com setas pra
// passar pra próxima/anterior sem fechar. Só participa da navegação quem é imagem de verdade;
// documentos (PDF, etc.) continuam abrindo em aba nova ao clicar, já que não faz sentido "ampliar"
// um PDF dentro desse visualizador.
// Zoom na foto (pedido do usuário em 13/10/2026: "nas fotos no módulo do técnico a gente não consegue
// dar zoom"). As páginas bloqueiam o zoom do navegador de propósito (user-scalable=no no viewport,
// pro sistema se comportar como app no celular) - então o zoom é feito aqui dentro do visualizador:
// pinça com 2 dedos / toque duplo no celular, rodinha / clique duplo no computador, arrastar pra
// mover a foto ampliada, e botões +/−/ajustar. Setas e troca de foto só valem com a foto em 100%.
const ZOOM_MIN = 1;
const ZOOM_MAX = 6;
const ZOOM_DOUBLE_TAP = 2.5;
const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

const PhotoLightbox: React.FC<{ photos: OsFotoItem[]; index: number; onClose: () => void; onIndexChange: (i: number) => void }> = ({ photos, index, onClose, onIndexChange }) => {
  const photo = photos[index];
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [gesturing, setGesturing] = useState(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ startDist: number; startZoom: number; startPan: { x: number; y: number }; startPoint: { x: number; y: number } } | null>(null);
  const movedRef = useRef(false);
  const lastTapRef = useRef(0);
  const zoomed = zoom > 1.01;

  const resetZoom = useCallback(() => { setZoom(1); setPan({ x: 0, y: 0 }); }, []);
  useEffect(() => { resetZoom(); }, [index, resetZoom]);

  const applyZoom = useCallback((next: number) => {
    const z = clampZoom(next);
    setZoom(z);
    if (z <= 1.01) setPan({ x: 0, y: 0 });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { if (zoomed) resetZoom(); else onClose(); }
      else if (e.key === '+' || e.key === '=') applyZoom(zoom * 1.4);
      else if (e.key === '-') applyZoom(zoom / 1.4);
      else if (zoomed) return;
      else if (e.key === 'ArrowRight' && photos.length > 1) onIndexChange((index + 1) % photos.length);
      else if (e.key === 'ArrowLeft' && photos.length > 1) onIndexChange((index - 1 + photos.length) % photos.length);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index, photos.length, onClose, onIndexChange, zoom, zoomed, resetZoom, applyZoom]);

  const dist = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    movedRef.current = false;
    const pts = Array.from(pointers.current.values());
    gesture.current = {
      startDist: pts.length >= 2 ? dist(pts[0], pts[1]) : 0,
      startZoom: zoom,
      startPan: pan,
      startPoint: { x: e.clientX, y: e.clientY },
    };
    setGesturing(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = Array.from(pointers.current.values());
    const g = gesture.current;
    if (pts.length >= 2) {
      if (!g.startDist) { g.startDist = dist(pts[0], pts[1]); g.startZoom = zoom; return; }
      movedRef.current = true;
      applyZoom(g.startZoom * (dist(pts[0], pts[1]) / g.startDist));
    } else if (zoomed) {
      const dx = e.clientX - g.startPoint.x;
      const dy = e.clientY - g.startPoint.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) movedRef.current = true;
      setPan({ x: g.startPan.x + dx, y: g.startPan.y + dy });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    const pts = Array.from(pointers.current.values());
    // Sobrou 1 dedo depois da pinça: recomeça o arraste a partir dele, sem a foto "pular"
    gesture.current = pts.length ? { startDist: 0, startZoom: zoom, startPan: pan, startPoint: pts[0] } : null;
    if (!pts.length) setGesturing(false);
    if (e.pointerType === 'touch' && !movedRef.current && pts.length === 0) {
      const now = Date.now();
      if (now - lastTapRef.current < 300) {
        if (zoomed) resetZoom(); else applyZoom(ZOOM_DOUBLE_TAP);
        lastTapRef.current = 0;
      } else lastTapRef.current = now;
    }
  };

  const onWheel = (e: React.WheelEvent) => {
    e.stopPropagation();
    applyZoom(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
  };

  if (!photo) return null;

  const btn: React.CSSProperties = { width: '38px', height: '38px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.08)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' };
  const navBtn: React.CSSProperties = { position: 'absolute', top: '50%', transform: 'translateY(-50%)', width: '42px', height: '42px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.08)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', zIndex: 2 };

  return (
    <div
      // Um arraste que termina fora da foto gera "click" no fundo - não pode fechar o visualizador
      onClick={() => { if (movedRef.current) { movedRef.current = false; return; } onClose(); }}
      style={{ position: 'fixed', inset: 0, zIndex: 40000, background: 'rgba(0,0,0,0.92)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}
    >
      <div onClick={e => e.stopPropagation()} style={{ position: 'absolute', top: '16px', right: '16px', display: 'flex', gap: '8px', zIndex: 2 }}>
        <button title="Diminuir zoom" onClick={() => applyZoom(zoom / 1.4)} disabled={!zoomed} style={{ ...btn, opacity: zoomed ? 1 : 0.4 }}><ZoomOut size={18} /></button>
        <button title="Aumentar zoom" onClick={() => applyZoom(zoom * 1.4)} disabled={zoom >= ZOOM_MAX} style={{ ...btn, opacity: zoom >= ZOOM_MAX ? 0.4 : 1 }}><ZoomIn size={18} /></button>
        {zoomed && <button title="Ajustar à tela" onClick={resetZoom} style={btn}><Maximize2 size={17} /></button>}
        <button title="Fechar" onClick={onClose} style={btn}><X size={18} /></button>
      </div>

      {photos.length > 1 && !zoomed && (
        <button onClick={e => { e.stopPropagation(); onIndexChange((index - 1 + photos.length) % photos.length); }} style={{ ...navBtn, left: '12px' }}>
          <ChevronLeft size={22} />
        </button>
      )}

      <img
        src={photo.file_url} alt="Foto da O.S." draggable={false}
        onClick={e => e.stopPropagation()}
        onDoubleClick={e => { e.stopPropagation(); if (zoomed) resetZoom(); else applyZoom(ZOOM_DOUBLE_TAP); }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
        style={{
          maxWidth: '92vw', maxHeight: '84vh', objectFit: 'contain', borderRadius: zoomed ? 0 : '8px', boxShadow: '0 10px 40px rgba(0,0,0,0.5)',
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transition: gesturing ? 'none' : 'transform 0.12s ease-out',
          touchAction: 'none', userSelect: 'none', cursor: zoomed ? 'grab' : 'zoom-in',
        }}
      />

      {photos.length > 1 && !zoomed && (
        <button onClick={e => { e.stopPropagation(); onIndexChange((index + 1) % photos.length); }} style={{ ...navBtn, right: '12px' }}>
          <ChevronRight size={22} />
        </button>
      )}

      <div style={{ position: 'absolute', bottom: '18px', left: '50%', transform: 'translateX(-50%)', fontSize: '12.5px', fontWeight: 700, color: 'rgba(255,255,255,0.85)', background: 'rgba(255,255,255,0.1)', padding: '4px 12px', borderRadius: '999px', whiteSpace: 'nowrap', pointerEvents: 'none' }}>
        {zoomed
          ? `${Math.round(zoom * 100)}% · arraste para mover`
          : `${photos.length > 1 ? `${index + 1} / ${photos.length} · ` : ''}pinça ou toque duplo para ampliar`}
      </div>
    </div>
  );
};

// Cada bloco do detalhe da O.S. (Histórico, Peças, Observações, Fotos...) ganha um fundo
// intercalado entre a cor primária (verde) e secundária (azul) do app - pedido do usuário em
// 07/10/2026: "para ele ver melhor as coisas... intercalando para ele saber quando acaba uma e
// inicia a outra". Só decide a cor; quem decide QUAL variante cada bloco leva é a sequência de
// chamadas a nextSectionVariant() em OsDetailModal (pulando os blocos escondidos pro técnico, pra
// alternância continuar certa mesmo com seções condicionais no meio).
const SECTION_TINT = {
  primary: { background: 'rgba(0,230,153,0.045)', border: 'rgba(0,230,153,0.16)' },
  secondary: { background: 'rgba(96,165,250,0.05)', border: 'rgba(96,165,250,0.18)' },
};
const Section: React.FC<{ variant: 'primary' | 'secondary'; children: React.ReactNode }> = ({ variant, children }) => (
  <div style={{ background: SECTION_TINT[variant].background, border: `1px solid ${SECTION_TINT[variant].border}`, borderRadius: '10px', padding: '12px 14px' }}>
    {children}
  </div>
);

const InternalDocToggle: React.FC<{ checked: boolean; onChange: (v: boolean) => void }> = ({ checked, onChange }) => (
  <label style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '11.5px', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px 0' }}>
    <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} style={{ marginTop: '2px', flexShrink: 0 }} />
    <span>Documento interno (ex.: NF de compra pra garantia de fábrica) — não enviar ao cliente, só anexar no Drive/Softsystem</span>
  </label>
);

// --------------------------------------------------------------------------- botões de status dentro da O.S.

// Pedido do usuário em 14/10/2026: os botões de mudar status (antes só no "⋮" do cartão, no Portal
// do Técnico) também dentro da O.S., na plataforma. Admin: todos os status liberados, sem travas
// (backend: os_board.change_order_status -> technician_portal.ADMIN_STATUS_OPTIONS). Demais
// usuários e técnicos: só os que a regra do estágio atual permite (STAGE_KEY_ALLOWED_TRANSITIONS);
// os outros aparecem apagados.
const OS_STATUS_BUTTONS: { code: number; label: string; stage: string }[] = [
  { code: 2, label: 'Avaliação', stage: 'avaliacao' },
  { code: 3, label: 'Orçamento enviado', stage: 'orcamento' },
  { code: 15, label: 'Aprovado', stage: 'aprovado' },
  { code: 16, label: 'Não aprovado', stage: 'nao_aprovado' },
  { code: 4, label: 'Execução', stage: 'execucao' },
  { code: 8, label: 'Aguardando peça', stage: 'peca' },
  { code: 6, label: 'Aguardando retirada', stage: 'retirada' },
  { code: 11, label: 'Sem conserto', stage: 'sem_reparo' },
  { code: 13, label: 'Sem defeito', stage: 'sem_reparo' },
  { code: 12, label: 'Não autorizada', stage: 'nao_aprovado' },
  { code: 14, label: 'Descarte', stage: 'descarte' },
  { code: 7, label: 'Finalizada', stage: 'finalizada' },
];
const STATUS_SO_QUADRO = new Set([15, 16, 14]); // não existem como evento no Softsystem
const STATUS_ADMIN_ONLY = new Set([2, 3, 15, 16, 12, 14]); // técnico nunca escolhe esses

const OsStatusButtons: React.FC<{
  codos: number; stage: string; tipoOs?: string | null; situacaoEvento: number | null | undefined; podeTudo: boolean; isTechnician: boolean;
  onChanged: () => void;
}> = ({ codos, stage, tipoOs, situacaoEvento, podeTudo, isTechnician, onChanged }) => {
  const [pending, setPending] = useState<number | null>(null);
  const [obs, setObs] = useState('');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ kind: 'ok' | 'aviso' | 'erro'; title?: string; text: string } | null>(null);

  const allowed = allowedStatusKeys(stage, tipoOs);
  const visiveis = OS_STATUS_BUTTONS.filter(b => podeTudo || !STATUS_ADMIN_ONLY.has(b.code));
  const enabled = (code: number) => code !== situacaoEvento && (podeTudo || allowed.includes(code));
  const obsRequired = !podeTudo && !isGarantia(tipoOs) && stage === 'aprovado' && pending === 6;
  const pendingBtn = OS_STATUS_BUTTONS.find(b => b.code === pending);

  const confirmar = async () => {
    if (pending == null || sending) return;
    if (obsRequired && !obs.trim()) return;
    setSending(true);
    setResult(null);
    try {
      const body = JSON.stringify(isTechnician ? { codos, status: pending, obs: obs.trim() || undefined } : { status: pending, obs: obs.trim() || undefined });
      const res = isTechnician
        ? await techApiFetch('/os/status', { method: 'POST', body })
        : await apiFetch(`/os-board/order/${codos}/status`, { method: 'POST', body });
      if (res?.status === 'needs_approval') {
        setResult({ kind: 'aviso', title: res.title, text: res.message });
      } else {
        setResult({ kind: 'ok', text: res?.message || 'Status atualizado.' });
        onChanged();
        window.dispatchEvent(new CustomEvent('os-board-update'));
      }
      setPending(null);
      setObs('');
    } catch (err: any) {
      setResult({ kind: 'erro', text: err?.message || 'Não foi possível mudar o status.' });
    } finally {
      setSending(false);
    }
  };

  const resultColor = result?.kind === 'ok' ? '#22c55e' : result?.kind === 'aviso' ? '#f59e0b' : '#f87171';

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
          <RefreshCw size={14} /> Mudar status
        </div>
        {podeTudo && <span style={{ fontSize: '10.5px', fontWeight: 700, color: 'var(--text-muted)' }}>Admin · todos liberados</span>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(128px, 1fr))', gap: '6px' }}>
        {visiveis.map(b => {
          // cinza da coluna "finalizada" parece botão desligado - clareia só aqui
          const c = b.code === 7 ? '#cbd5e1' : (STAGE_COLORS[b.stage] || '#94a3b8');
          const atual = b.code === situacaoEvento;
          const on = enabled(b.code);
          const sel = pending === b.code;
          return (
            <button
              key={b.code}
              disabled={!on || sending}
              onClick={() => { setPending(sel ? null : b.code); setResult(null); setObs(''); }}
              title={atual ? 'Status atual' : on ? `Mudar para ${b.label}` : 'Não disponível a partir do status atual'}
              style={{
                padding: '9px 8px', borderRadius: '8px', fontSize: '12px', fontWeight: 700, lineHeight: 1.2, textAlign: 'center',
                cursor: on && !sending ? 'pointer' : 'default', fontFamily: 'inherit',
                color: atual ? '#04140d' : on ? c : 'var(--text-muted)',
                background: atual ? c : sel ? `${c}33` : on ? `${c}12` : 'transparent',
                border: `1.5px solid ${atual || sel ? c : on ? `${c}66` : 'rgba(148,163,184,0.18)'}`,
                opacity: on || atual ? 1 : 0.45,
              }}
            >
              {b.label}{atual ? ' · atual' : ''}
            </button>
          );
        })}
      </div>

      {pendingBtn && (
        <div style={{ marginTop: '10px', padding: '10px', borderRadius: '8px', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', border: '1px solid var(--border-color, rgba(255,255,255,0.14))', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--text-main)' }}>Mudar para "{pendingBtn.label}"?</div>
          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
            {STATUS_SO_QUADRO.has(pendingBtn.code)
              ? 'Esse status não existe no Softsystem: muda só no quadro (igual quando o cliente responde SIM/NÃO no WhatsApp).'
              : 'Grava o evento no Softsystem com o seu nome. Se esse status tiver mensagem automática, o cliente recebe no WhatsApp.'}
          </div>
          {!STATUS_SO_QUADRO.has(pendingBtn.code) && (
            <textarea
              value={obs}
              onChange={e => setObs(e.target.value)}
              rows={2}
              placeholder={pendingBtn.code === 11 ? 'Motivo (vai na mensagem ao cliente)' : obsRequired ? 'Obrigatório: o que foi feito (pulando a Execução)' : 'Observação (opcional)'}
              style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', borderRadius: '6px', border: `1px solid ${obsRequired && !obs.trim() ? 'rgba(248,113,113,0.5)' : 'var(--border-color, rgba(255,255,255,0.18))'}`, background: 'var(--bg-primary)', color: 'var(--text-main)', fontSize: '12.5px', padding: '7px 9px', fontFamily: 'inherit' }}
            />
          )}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button onClick={() => { setPending(null); setObs(''); }} disabled={sending} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '12px', fontWeight: 700, cursor: 'pointer' }}>
              Cancelar
            </button>
            <button onClick={confirmar} disabled={sending || (obsRequired && !obs.trim())} style={{ flex: 1.4, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px', borderRadius: '6px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '12px', fontWeight: 800, cursor: sending ? 'default' : 'pointer', opacity: sending || (obsRequired && !obs.trim()) ? 0.6 : 1 }}>
              {sending && <Loader2 size={13} className="animate-spin" />} Confirmar
            </button>
          </div>
        </div>
      )}

      {result && (
        <div style={{ marginTop: '10px', padding: '9px 11px', borderRadius: '8px', fontSize: '12.5px', lineHeight: 1.45, color: 'var(--text-main)', background: `${resultColor}14`, border: `1px solid ${resultColor}55` }}>
          {result.title && <div style={{ fontWeight: 800, color: resultColor, marginBottom: '2px' }}>{result.title}</div>}
          <span style={{ color: result.title ? 'var(--text-main)' : resultColor, fontWeight: result.title ? 400 : 700 }}>{result.text}</span>
        </div>
      )}
    </div>
  );
};

// --------------------------------------------------------------------------- interações internas da O.S.

// Pedido do usuário em 14/10/2026, no estilo do "Interagir na Ordem de Serviço" do Telecontrol:
// técnico e escritório conversam dentro da O.S. com histórico. "Pendência" acende o alerta (!) no
// cartão do quadro até alguém resolver; "Observação" é só registro (ex.: "cotação enviada pra
// fábrica, aguardando retorno"). Leitura confirmada = alguém do outro lado abriu a O.S. depois.
interface OsInteractionItem {
  id: number; tipo: 'observacao' | 'pendencia' | 'resolucao'; mensagem: string; autor: string;
  autor_tipo: 'admin' | 'tecnico'; criado_em: string; lido_em: string | null; lido_por: string | null;
  resolved_at: string | null; resolved_by: string | null;
}

const INTERACTION_TIPO: Record<OsInteractionItem['tipo'], { label: string; color: string }> = {
  observacao: { label: 'Observação', color: '#94a3b8' },
  pendencia: { label: 'Pendência', color: '#ef4444' },
  resolucao: { label: 'Resolvido', color: '#22c55e' },
};

const OsInteractionsSection: React.FC<{ codos: number; isTechnician: boolean }> = ({ codos, isTechnician }) => {
  const [items, setItems] = useState<OsInteractionItem[] | null>(null);
  const [text, setText] = useState('');
  const [sending, setSending] = useState<OsInteractionItem['tipo'] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const call = useCallback((opts?: RequestInit) => {
    const path = `/order/${codos}/interactions`;
    return isTechnician ? techApiFetch(path, opts) : apiFetch(`/os-board${path}`, opts);
  }, [codos, isTechnician]);

  const load = useCallback(async () => {
    try {
      setItems((await call()) || []);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível carregar as interações.');
      setItems([]);
    }
  }, [call]);

  useEffect(() => { load(); }, [load]);

  const openPendencias = (items || []).filter(i => i.tipo === 'pendencia' && !i.resolved_at);
  const lastOpen = openPendencias[openPendencias.length - 1];
  const mySide = isTechnician ? 'tecnico' : 'admin';

  const submit = async (tipo: OsInteractionItem['tipo']) => {
    if (sending) return;
    if (tipo !== 'resolucao' && !text.trim()) return;
    setSending(tipo);
    setError(null);
    try {
      await call({ method: 'POST', body: JSON.stringify({ tipo, mensagem: text.trim() }) });
      setText('');
      await load();
      // acende/apaga o "!" no quadro sem esperar o WebSocket
      window.dispatchEvent(new CustomEvent('os-board-update'));
    } catch (err: any) {
      setError(err?.message || 'Não foi possível registrar a interação.');
    } finally {
      setSending(null);
    }
  };

  const btn = (color: string, filled = false, enabled = true): React.CSSProperties => ({
    flex: 1, minWidth: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px 6px', borderRadius: '6px',
    fontSize: '11.5px', fontWeight: 800, cursor: enabled ? 'pointer' : 'default', border: `1px solid ${color}55`,
    background: filled ? color : `${color}14`, color: filled ? '#04140d' : color, opacity: enabled ? 1 : 0.5,
  });

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
        <MessageSquare size={14} /> Interações internas
        {lastOpen && <PendenciaBadge pendencia={lastOpen} size={16} />}
      </div>

      {openPendencias.length > 0 && (
        <div style={{ padding: '8px 10px', borderRadius: '8px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.35)', marginBottom: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {openPendencias.map(p => (
            <div key={p.id} style={{ fontSize: '12px', color: '#fca5a5' }}>
              <AlertTriangle size={12} style={{ verticalAlign: '-2px', marginRight: '4px' }} />
              <b>{p.mensagem}</b> <span style={{ color: 'var(--text-muted)' }}>— {titleCase(p.autor)}, {formatDateTime(p.criado_em)}</span>
            </div>
          ))}
        </div>
      )}

      {error && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '8px' }}>{error}</div>}
      {items === null && <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Carregando…</div>}
      {items && items.length === 0 && (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Nenhuma interação nesta O.S. ainda.</div>
      )}
      {items && items.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', marginBottom: '10px' }}>
          {items.map((it, idx) => {
            const t = INTERACTION_TIPO[it.tipo] || INTERACTION_TIPO.observacao;
            const mine = it.autor_tipo === mySide;
            return (
              <div key={it.id} style={{ display: 'flex', gap: '10px', padding: '7px 0', borderBottom: idx < items.length - 1 ? '1px solid rgba(255,255,255,0.06)' : 'none' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', flexShrink: 0, minWidth: '82px' }}>{formatDateTime(it.criado_em)}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', fontSize: '11.5px', fontWeight: 700, color: 'var(--text-main)' }}>
                    {titleCase(it.autor)}
                    <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)' }}>{it.autor_tipo === 'tecnico' ? 'Técnico' : 'Escritório'}</span>
                    <span style={{ fontSize: '10px', fontWeight: 800, padding: '1px 7px', borderRadius: '999px', color: t.color, background: `${t.color}1F`, border: `1px solid ${t.color}55` }}>
                      {it.tipo === 'pendencia' && it.resolved_at ? 'Pendência (resolvida)' : t.label}
                    </span>
                  </div>
                  <div style={{ fontSize: '12.5px', color: 'var(--text-main)', marginTop: '2px', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{it.mensagem}</div>
                  {mine && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '10.5px', marginTop: '3px', color: it.lido_em ? '#22c55e' : '#f59e0b' }}>
                      {it.lido_em ? <Eye size={12} /> : <EyeOff size={12} />}
                      {it.lido_em ? `Lido por ${titleCase(it.lido_por || '')} em ${formatDateTime(it.lido_em)}` : 'Leitura não confirmada'}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        rows={2}
        placeholder={openPendencias.length > 0 ? 'Ex: a placa chegou, pode seguir' : 'Ex: parei, a placa não tem em estoque / cotação enviada pra fábrica'}
        style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12.5px', padding: '8px 10px', fontFamily: 'inherit', lineHeight: 1.5, marginBottom: '6px' }}
      />
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
        <button onClick={() => submit('observacao')} disabled={!!sending || !text.trim()} style={btn('#94a3b8', false, !!text.trim())}
          title="Só fica registrado no histórico da O.S., sem alerta">
          {sending === 'observacao' && <Loader2 size={13} className="animate-spin" />} Registrar observação
        </button>
        <button onClick={() => submit('pendencia')} disabled={!!sending || !text.trim()} style={btn('#ef4444', false, !!text.trim())}
          title="Acende o alerta (!) no quadro até alguém resolver">
          {sending === 'pendencia' ? <Loader2 size={13} className="animate-spin" /> : <AlertTriangle size={13} />} Abrir pendência
        </button>
        {openPendencias.length > 0 && (
          <button onClick={() => submit('resolucao')} disabled={!!sending} style={btn('#22c55e', true)}
            title="Fecha a(s) pendência(s) aberta(s) - o texto acima (opcional) fica como resposta">
            {sending === 'resolucao' ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />} Resolver pendência
          </button>
        )}
      </div>
    </div>
  );
};

const OsDetailModal: React.FC<{ codos: number; onClose: () => void }> = ({ codos, onClose }) => {
  const [data, setData] = useState<OsOrderDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mediaFiles, setMediaFiles] = useState<QuickUploadFileState[]>([]);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [internalDoc, setInternalDoc] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const cameraPhotoRef = useRef<HTMLInputElement>(null);
  const cameraVideoRef = useRef<HTMLInputElement>(null);
  const filePickerRef = useRef<HTMLInputElement>(null);
  const sendingRef = useRef(false);
  const [internalNote, setInternalNote] = useState<string | null>(null);
  const [customerMessage, setCustomerMessage] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportSending, setReportSending] = useState(false);
  const [reportRejecting, setReportRejecting] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportSent, setReportSent] = useState(false);
  const [lastSent, setLastSent] = useState<{ enviado_em: string; aprovado_por: string | null } | null>(null);
  const [showRejectInput, setShowRejectInput] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [techNotes, setTechNotes] = useState<{ id: number; mensagem: string; tecnico: string; criado_por: string; criado_em: string }[]>([]);
  const [newNoteText, setNewNoteText] = useState('');
  const [addingNote, setAddingNote] = useState(false);
  const [noteError, setNoteError] = useState<string | null>(null);
  const [resolvingNoteId, setResolvingNoteId] = useState<number | null>(null);
  const isTechnicianUser = isTechnicianSession();

  const loadTechNotes = async () => {
    try {
      const res = await (isTechnicianUser ? techApiFetch(`/order/${codos}/notes`) : apiFetch(`/os-board/order/${codos}/notes`));
      setTechNotes(res || []);
    } catch {
      // silencioso - não é crítico pra abrir a O.S.
    }
  };

  const handleAddNote = async () => {
    if (!newNoteText.trim() || addingNote) return;
    setAddingNote(true);
    setNoteError(null);
    try {
      const body = JSON.stringify({ mensagem: newNoteText.trim() });
      await apiFetch(`/os-board/order/${codos}/notes`, { method: 'POST', body });
      setNewNoteText('');
      await loadTechNotes();
    } catch (err: any) {
      setNoteError(err?.message || 'Não foi possível adicionar a observação.');
    } finally {
      setAddingNote(false);
    }
  };

  const handleResolveNote = async (noteId: number) => {
    if (resolvingNoteId) return;
    setResolvingNoteId(noteId);
    try {
      await apiFetch(`/os-board/notes/${noteId}/resolve`, { method: 'POST' });
      await loadTechNotes();
    } catch (err: any) {
      setNoteError(err?.message || 'Não foi possível marcar como resolvido.');
    } finally {
      setResolvingNoteId(null);
    }
  };

  const handleDraftReport = async () => {
    setReportError(null);
    setReportLoading(true);
    try {
      const res = await draftOsReport(codos);
      setInternalNote(res.internal_note);
      setCustomerMessage(res.customer_message);
      setReportSent(false);
      setShowRejectInput(false);
    } catch (err: any) {
      setReportError(err?.message || 'Não foi possível gerar o rascunho.');
    } finally {
      setReportLoading(false);
    }
  };

  const handleRejectReport = async () => {
    if (!rejectReason.trim()) return;
    setReportError(null);
    setReportRejecting(true);
    try {
      const res = await rejectOsReport(codos, rejectReason.trim());
      setInternalNote(res.internal_note);
      setCustomerMessage(res.customer_message);
      setRejectReason('');
      setShowRejectInput(false);
    } catch (err: any) {
      setReportError(err?.message || 'Não foi possível reprovar e gerar nova versão.');
    } finally {
      setReportRejecting(false);
    }
  };

  const handleSendReport = async () => {
    // Trava síncrona (useRef, não o estado reportSending) contra clique duplo - achado em
    // produção em 07/10/2026 (O.S. #1966 mandou o PDF 2x pro cliente): como a aprovação agora
    // responde rápido (segundo plano, não trava mais a tela esperando o WhatsApp), um duplo
    // clique rápido passava antes do React re-renderizar o botão desabilitado (setState é
    // assíncrono/batched - não bloqueia a chamada seguinte na mesma "volta" do event loop).
    if (!internalNote || !customerMessage || sendingRef.current) return;
    sendingRef.current = true;
    setReportError(null);
    setReportSending(true);
    try {
      await sendOsReport(codos, internalNote, customerMessage);
      setReportSent(true);
    } catch (err: any) {
      setReportError(err?.message || 'Não foi possível enviar o relatório.');
    } finally {
      setReportSending(false);
      sendingRef.current = false;
    }
  };

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
    loadTechNotes();
    return () => { cancelled = true; };
  }, [codos]);

  // Se a varredura automática já gerou um rascunho pra essa O.S., mostra ele direto - sem
  // precisar clicar em "Gerar com IA" (pedido do usuário: fluxo rápido, revisar e aprovar/
  // reprovar assim que abre a O.S.).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getOsReport(codos);
        if (!cancelled && res) {
          setInternalNote(res.internal_note);
          setCustomerMessage(res.customer_message);
        }
      } catch {
        // Sem rascunho pendente - normal, mantém o botão manual "Gerar com IA".
      }
      if (isTechnicianUser) return;
      try {
        const sent = await getOsLastSentReport(codos);
        if (!cancelled && sent) setLastSent(sent);
      } catch {
        // Nunca enviado - sem opção de reenvio.
      }
    })();
    return () => { cancelled = true; };
  }, [codos]);

  // Foto/vídeo/arquivo (pedido do usuário em 07/10/2026: ele via só "Tirar foto" aqui e achou que a
  // função de mandar multimídia pro cliente, já implementada antes, tinha sumido - na verdade só
  // faltava deixar visível/completo igual ao menuzinho de status, ver StatusMenu) - cada item sobe
  // em paralelo e aparece com o próprio status, sem esperar os outros terminarem.
  const uploadMediaOne = async (key: string, file: File, sendToCustomer: boolean) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await uploadOsPhoto(codos, formData, sendToCustomer);
      setMediaFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'done', result } : f));
      setData(prev => prev ? { ...prev, fotos: [result, ...prev.fotos] } : prev);
    } catch (err: any) {
      setMediaFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'error', error: err?.message || 'Falha ao enviar' } : f));
    }
  };

  const addMediaFiles = (fileList: FileList | null) => {
    if (!fileList || !fileList.length) return;
    setPhotoError(null);
    const sendToCustomer = !internalDoc;
    const toAdd = Array.from(fileList).map((file, i) => ({
      key: `${Date.now()}_${i}_${file.name}`, file, status: 'uploading' as const,
    }));
    setMediaFiles(prev => [...toAdd, ...prev]);
    toAdd.forEach(item => uploadMediaOne(item.key, item.file, sendToCustomer));
    setInternalDoc(false);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Zera a cada render e só avança quando a seção realmente aparece na tela (o "&&" de uma seção
  // escondida pro técnico nunca chama isso) - garante que a alternância primária/secundária seja
  // sempre contínua nos blocos visíveis, não importa quais ficam de fora pra cada tipo de usuário.
  let sectionCount = 0;
  const nextSectionVariant = (): 'primary' | 'secondary' => (sectionCount++ % 2 === 0 ? 'primary' : 'secondary');

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

              <Section variant={nextSectionVariant()}>
                <OsStatusButtons
                  codos={codos}
                  stage={data.stage}
                  tipoOs={data.tipo_os}
                  situacaoEvento={data.situacao_evento}
                  podeTudo={!isTechnicianUser && !!data.pode_mudar_qualquer_status}
                  isTechnician={isTechnicianUser}
                  onChanged={() => { fetchOsDetail(codos).then(setData).catch(() => {}); }}
                />
              </Section>

              <Section variant={nextSectionVariant()}>
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
              </Section>

              <Section variant={nextSectionVariant()}>
                <OsInteractionsSection codos={codos} isTechnician={isTechnicianUser} />
              </Section>

              <Section variant={nextSectionVariant()}>
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
              </Section>

              {/* Pedido do usuário em 07/10/2026: essa seção "lota e confunde" o técnico - fica só
                  pro admin revisar/aprovar o laudo (mesma modal, aberta a partir do Quadro
                  administrativo); o técnico só lança peça/observação, que já alimentam a IA. */}
              {!isTechnicianUser && (
              <Section variant={nextSectionVariant()}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                    <Sparkles size={14} /> Relatório pro Cliente
                  </div>
                  {!internalNote && (() => {
                    // Botão só fica ativo se já tem algo lançado pra IA trabalhar em cima (peça ou
                    // nota do técnico no campo Observação) - pedido do usuário em 07/10/2026: numa
                    // O.S. recém-aberta ("Entrada", nada lançado ainda) o botão ativo era só
                    // "sujeira" na tela, convite a gerar relatório vazio/sem sentido.
                    const fed = data.pecas.length > 0 || !!(data.tecnico_nota && data.tecnico_nota.trim());
                    const disabled = reportLoading || !fed;
                    return (
                      <button
                        onClick={handleDraftReport}
                        disabled={disabled}
                        title={fed ? undefined : 'Lance uma peça ou a observação do técnico na O.S. antes de gerar o relatório.'}
                        style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: fed ? 'var(--accent-primary, #00e699)' : 'var(--text-muted)', background: fed ? 'rgba(0,230,153,0.1)' : 'rgba(148,163,184,0.08)', border: `1px solid ${fed ? 'rgba(0,230,153,0.3)' : 'rgba(148,163,184,0.2)'}`, borderRadius: '8px', padding: '6px 10px', cursor: disabled ? 'default' : 'pointer', opacity: reportLoading ? 0.6 : 1 }}
                      >
                        {reportLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                        {reportLoading ? 'Gerando…' : lastSent ? 'Reenviar com valores atualizados' : 'Gerar com IA'}
                      </button>
                    );
                  })()}
                </div>
                {reportError && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '8px' }}>{reportError}</div>}
                {!internalNote && !reportLoading && !reportError && lastSent && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px', color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-primary, #00e699)', fontWeight: 700 }}>
                      <CheckCircle2 size={14} /> Enviado ao cliente em {new Date(lastSent.enviado_em).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })}{lastSent.aprovado_por ? ` por ${lastSent.aprovado_por}` : ''}
                    </div>
                    <div>Renegociou o preço? Atualize as peças/valores na O.S. no Softsystem e clique em "Reenviar com valores atualizados" - a IA monta uma nova versão pra você revisar antes de ir pro cliente (o PDF sai marcado como orçamento atualizado).</div>
                  </div>
                )}
                {!internalNote && !reportLoading && !reportError && !lastSent && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {(data.pecas.length > 0 || !!(data.tecnico_nota && data.tecnico_nota.trim()))
                      ? 'A IA monta o laudo técnico e o diagnóstico/orçamento a partir das peças lançadas - você revisa, edita e aprova (ou reprova com um motivo) antes de qualquer coisa ir pro cliente ou pro Softsystem.'
                      : 'Lance uma peça ou escreva a observação do técnico na O.S. (campo Observação, no Softsystem) pra liberar o relatório.'}
                  </div>
                )}
                {internalNote && customerMessage && !reportSent && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <div>
                      <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>Laudo técnico (vai pro Softsystem)</div>
                      <textarea
                        value={internalNote}
                        onChange={e => setInternalNote(e.target.value)}
                        rows={4}
                        style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12.5px', padding: '8px 10px', fontFamily: 'inherit', lineHeight: 1.5 }}
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>Mensagem pro cliente (vai no PDF)</div>
                      <textarea
                        value={customerMessage}
                        onChange={e => setCustomerMessage(e.target.value)}
                        rows={7}
                        style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', borderRadius: '8px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12.5px', padding: '8px 10px', fontFamily: 'inherit', lineHeight: 1.5 }}
                      />
                    </div>
                    {showRejectInput && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', padding: '8px', borderRadius: '8px', background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.25)' }}>
                        <input
                          value={rejectReason}
                          onChange={e => setRejectReason(e.target.value)}
                          placeholder="Por que não está bom? (a IA reelabora com isso)"
                          style={{ width: '100%', boxSizing: 'border-box', borderRadius: '6px', border: '1px solid rgba(248,113,113,0.3)', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12px', padding: '7px 9px', fontFamily: 'inherit' }}
                        />
                        <div style={{ display: 'flex', gap: '6px' }}>
                          <button onClick={() => { setShowRejectInput(false); setRejectReason(''); }} disabled={reportRejecting} style={{ flex: 1, padding: '7px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11px', fontWeight: 700, cursor: 'pointer' }}>
                            Cancelar
                          </button>
                          <button onClick={handleRejectReport} disabled={reportRejecting || !rejectReason.trim()} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '7px', borderRadius: '6px', border: 'none', background: '#f87171', color: '#2b0a0a', fontSize: '11px', fontWeight: 800, cursor: reportRejecting ? 'default' : 'pointer', opacity: reportRejecting ? 0.7 : 1 }}>
                            {reportRejecting ? <Loader2 size={13} className="animate-spin" /> : null}
                            {reportRejecting ? 'Reelaborando…' : 'Confirmar reprovação'}
                          </button>
                        </div>
                      </div>
                    )}
                    {!showRejectInput && (
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button onClick={handleDraftReport} disabled={reportLoading} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>
                          Gerar de novo
                        </button>
                        <button onClick={() => setShowRejectInput(true)} disabled={reportSending} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid rgba(248,113,113,0.3)', background: 'transparent', color: '#f87171', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>
                          Reprovar
                        </button>
                        <button onClick={handleSendReport} disabled={reportSending || !internalNote.trim() || !customerMessage.trim()} style={{ flex: 1.3, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px', borderRadius: '6px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '11.5px', fontWeight: 800, cursor: reportSending ? 'default' : 'pointer', opacity: reportSending ? 0.7 : 1 }}>
                          {reportSending ? <Loader2 size={13} className="animate-spin" /> : null}
                          {reportSending ? 'Enviando…' : lastSent ? 'Aprovar e reenviar pro cliente' : 'Aprovar e enviar pro cliente'}
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {reportSent && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--accent-primary, #00e699)', fontWeight: 700, padding: '8px', background: 'rgba(0,230,153,0.08)', borderRadius: '8px' }}>
                    <CheckCircle2 size={14} /> Aprovado! Enviando pro cliente e gravando no Softsystem em segundo plano - pode fechar e seguir pra próxima O.S.
                  </div>
                )}
              </Section>
              )}

              <Section variant={nextSectionVariant()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                  <Bell size={14} /> Observações pro Técnico
                </div>
                {noteError && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '8px' }}>{noteError}</div>}
                {techNotes.length === 0 && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>Nenhuma observação pendente nesta O.S.</div>
                )}
                {techNotes.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '8px' }}>
                    {techNotes.map(n => (
                      <div key={n.id} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px', padding: '8px 10px', borderRadius: '8px', background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.25)' }}>
                        <div style={{ fontSize: '12.5px', color: 'var(--text-main)' }}>
                          {n.mensagem}
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                            {n.criado_por} · {new Date(n.criado_em).toLocaleDateString('pt-BR')}
                          </div>
                        </div>
                        {!isTechnicianUser && (
                          <button
                            onClick={() => handleResolveNote(n.id)}
                            disabled={resolvingNoteId === n.id}
                            style={{ flexShrink: 0, fontSize: '11px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'transparent', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '6px', padding: '4px 8px', cursor: resolvingNoteId === n.id ? 'default' : 'pointer', whiteSpace: 'nowrap' }}
                          >
                            {resolvingNoteId === n.id ? '...' : 'Resolvido'}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {!isTechnicianUser && (
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <input
                      value={newNoteText}
                      onChange={e => setNewNoteText(e.target.value)}
                      placeholder="Ex: a peça chegou"
                      style={{ flex: 1, boxSizing: 'border-box', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12px', padding: '7px 9px', fontFamily: 'inherit' }}
                      onKeyDown={e => { if (e.key === 'Enter') handleAddNote(); }}
                    />
                    <button
                      onClick={handleAddNote}
                      disabled={addingNote || !newNoteText.trim()}
                      style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '6px', padding: '0 12px', cursor: addingNote ? 'default' : 'pointer', opacity: addingNote ? 0.6 : 1 }}
                    >
                      {addingNote ? <Loader2 size={13} className="animate-spin" /> : 'Adicionar'}
                    </button>
                  </div>
                )}
              </Section>

              <Section variant={nextSectionVariant()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>
                  <ImageIcon size={14} /> Fotos e Vídeos
                </div>
                {/* Pedido do usuário em 07/10/2026: ele não via mais onde mandar foto/vídeo direto
                    pro cliente (já existia, só estava "escondido" atrás de um único botão de
                    câmera) - agora os 3 botões (igual ao menuzinho de status) deixam explícito que
                    dá pra mandar foto, vídeo ou qualquer arquivo, e o aviso abaixo deixa claro que
                    isso já vai pro WhatsApp do cliente, a não ser que marque como documento interno. */}
                <div style={{ display: 'flex', gap: '6px', marginBottom: '8px' }}>
                  <button
                    onClick={() => cameraPhotoRef.current?.click()}
                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '8px', padding: '8px 6px', cursor: 'pointer' }}
                  ><Camera size={14} /> Foto</button>
                  <button
                    onClick={() => cameraVideoRef.current?.click()}
                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: 'var(--accent-primary, #00e699)', background: 'rgba(0,230,153,0.1)', border: '1px solid rgba(0,230,153,0.3)', borderRadius: '8px', padding: '8px 6px', cursor: 'pointer' }}
                  ><Video size={14} /> Vídeo</button>
                  <button
                    onClick={() => filePickerRef.current?.click()}
                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: 'var(--text-main)', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', border: '1px solid var(--border-color, rgba(255,255,255,0.16))', borderRadius: '8px', padding: '8px 6px', cursor: 'pointer' }}
                  ><Paperclip size={14} /> Arquivo</button>
                  <input ref={cameraPhotoRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); if (cameraPhotoRef.current) cameraPhotoRef.current.value = ''; }} />
                  <input ref={cameraVideoRef} type="file" accept="video/*" capture="environment" style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); if (cameraVideoRef.current) cameraVideoRef.current.value = ''; }} />
                  {/* accept só com image/video (sem application/pdf): é o que faz o Chrome/Android abrir a
                      galeria de fotos direto, sem o menu "Escolha uma ação" (Câmera/Câmera Filmadora/
                      Arquivos) - misturar um tipo não-mídia nesse accept é o que derruba pro seletor
                      genérico antigo. Pedido do usuário em 07/10/2026 ("não ficou legal" aquele menu). */}
                  <input ref={filePickerRef} type="file" accept="image/*,video/*" multiple style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); if (filePickerRef.current) filePickerRef.current.value = ''; }} />
                </div>
                <div style={{ fontSize: '11px', color: internalDoc ? 'var(--text-muted)' : 'var(--accent-primary, #00e699)', fontWeight: 600, marginBottom: '6px' }}>
                  {internalDoc ? '🔒 Vai ficar só no Drive/Softsystem, não vai pro cliente.' : '📤 Isso vai direto pro WhatsApp do cliente.'}
                </div>
                <InternalDocToggle checked={internalDoc} onChange={setInternalDoc} />
                {mediaFiles.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', margin: '6px 0' }}>
                    {mediaFiles.map(f => (
                      <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
                        {f.status === 'uploading' && <Loader2 size={12} className="animate-spin" />}
                        {f.status === 'done' && <span style={{ color: 'var(--accent-primary)' }}>✓</span>}
                        {f.status === 'error' && <span style={{ color: '#ef4444' }}>✗</span>}
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.file.name}</span>
                      </div>
                    ))}
                  </div>
                )}
                {photoError && <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '8px' }}>{photoError}</div>}
                {data.fotos.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nenhuma foto ou vídeo ainda nesta O.S.</div>}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(84px, 1fr))', gap: '8px' }}>
                  {data.fotos.map(f => {
                    const isImage = f.mimetype.startsWith('image/');
                    const isVideo = f.mimetype.startsWith('video/');
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
                          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{isVideo ? <Video size={22} color="var(--text-muted)" /> : <FileText size={22} color="var(--text-muted)" />}</div>
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
              </Section>
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
  // Pedido do usuário em 07/10/2026: a grade de 11 chips de estágio tomava a tela quase inteira,
  // sobrando só uma fresta pra ver as O.S. de verdade - "ficou horrível, super apertado". Agora
  // fica recolhido por padrão (só uma barra com o filtro atual) e só abre a grade cheia quando o
  // técnico toca nela; escolher um estágio já fecha sozinho, pra sobrar tela pra lista.
  const [filtersOpen, setFiltersOpen] = useState(false);
  const activeLabel = stageFilter ? (stages.find(s => s.key === stageFilter)?.label || stageFilter) : 'Todos';
  const activeCount = stageFilter ? (board?.totals?.[stageFilter] ?? 0) : (board?.total_open ?? 0);
  const activeColor = stageFilter ? (STAGE_COLORS[stageFilter] || 'var(--accent-primary)') : 'var(--accent-primary)';

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
      {/* filtro de estágio recolhível: fechado por padrão (só a barra com o filtro atual), abre a
          grade de chips por cima da lista quando tocado, e fecha sozinho ao escolher um estágio -
          pedido do usuário em 07/10/2026 ("campo de visão minúsculo" -> depois "super apertado"
          com a grade cheia sempre aberta tomando a tela toda). */}
      <div style={{ position: 'sticky', top: 0, zIndex: 3, background: 'var(--bg-primary)', padding: '2px 0 10px' }}>
        <button
          onClick={() => setFiltersOpen(v => !v)}
          style={{
            display: 'flex', alignItems: 'center', gap: '10px', width: '100%', boxSizing: 'border-box',
            padding: '11px 14px', borderRadius: '10px', cursor: 'pointer',
            background: `${activeColor}1F`, border: `1.5px solid ${activeColor}55`,
          }}
        >
          <Menu size={18} color={activeColor} style={{ flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, textAlign: 'left', fontSize: '14px', fontWeight: 800, color: activeColor, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {activeLabel} <span style={{ fontWeight: 700, opacity: 0.85 }}>({activeCount})</span>
          </span>
          <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', flexShrink: 0 }}>{filtersOpen ? 'Fechar ▲' : 'Filtrar ▾'}</span>
        </button>
        {filtersOpen && (
          <div style={{ marginTop: '8px', padding: '10px', borderRadius: '12px', background: 'var(--bg-secondary, #0f1824)', border: '1px solid var(--border-color, rgba(255,255,255,0.1))', boxShadow: '0 8px 24px rgba(0,0,0,0.35)', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
            <StageChip label="Todos" count={board?.total_open ?? 0} active={!stageFilter} onClick={() => { setStageFilter(''); setFiltersOpen(false); }} />
            {stages.map(st => (
              <StageChip key={st.key} label={st.label} count={board?.totals?.[st.key] ?? 0} color={STAGE_COLORS[st.key]} Icon={STAGE_ICONS[st.key]} active={stageFilter === st.key} onClick={() => { setStageFilter(st.key); setFiltersOpen(false); }} />
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
        {board && rows.length === 0 && !loading && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '14px' }}>Nenhuma O.S. neste filtro.</div>
        )}
        {rows.map(({ tech, items, shown }) => {
          // Cada técnico com sua cor fixa (mesma do letreiro de avisos) - pedido do usuário em
          // 07/10/2026: "você nem consegue distinguir quando muda de um técnico pra outro" - a barra
          // grossa colorida + cabeçalho maior deixa a troca de técnico óbvia rolando a lista.
          const techColor = colorForTechnician(tech.name);
          return (
          <div key={tech.name} style={{ border: `1px solid ${techColor}40`, borderRadius: '12px', overflow: 'hidden', background: 'var(--bg-secondary, rgba(255,255,255,0.02))' }}>
            <div
              onClick={() => { if (isAdmin) onOpenTech(tech.name); }}
              style={{ padding: '14px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', background: `${techColor}1F`, borderLeft: `5px solid ${techColor}`, cursor: isAdmin ? 'pointer' : 'default' }}
            >
              <span style={{ fontSize: '17px', fontWeight: 800, color: techColor, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 }}>{titleCase(tech.name)}</span>
              <span style={{ flexShrink: 0, fontSize: '12.5px', color: 'var(--text-main)', fontWeight: 800, background: 'rgba(255,255,255,0.08)', padding: '4px 10px', borderRadius: '999px' }}>{shown} {stageFilter ? 'nesse estágio' : 'em aberto'}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {items.map(({ card, stageKey }) => (
                <MobileOsRow key={`${card.empresa}-${card.codos}`} card={card} stageLabel={stages.find(s => s.key === stageKey)?.label || stageKey} stageKey={stageKey} color={STAGE_COLORS[stageKey]} showEmpresa={showEmpresa} showStage={!stageFilter} onChangeStatus={onChangeStatus} />
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
          );
        })}
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
        display: 'flex', alignItems: 'center', gap: '8px', width: '100%', boxSizing: 'border-box',
        minHeight: '46px', padding: '9px 12px', borderRadius: '10px', minWidth: 0,
        fontSize: '13.5px', fontWeight: 700, cursor: 'pointer',
        background: active ? `${c}2E` : `${c}14`,
        color: active ? c : 'var(--text-main)',
        border: `1.5px solid ${active ? c : `${c}55`}`,
      }}
    >
      {Icon && <Icon size={15} color={c} style={{ flexShrink: 0 }} />}
      <span style={{ flex: 1, minWidth: 0, textAlign: 'left', lineHeight: 1.2, wordBreak: 'break-word' }}>{label}</span>
      <span style={{ flexShrink: 0, color: c, fontWeight: 800, fontSize: '15px' }}>{count}</span>
    </button>
  );
};

const MobileOsRow: React.FC<{ card: BoardCard; stageLabel: string; stageKey: string; color?: string; showEmpresa: boolean; showStage: boolean; onChangeStatus?: ChangeStatusFn }> = ({ card, stageLabel, stageKey, color, showEmpresa, showStage, onChangeStatus }) => {
  const dias = card.dias_no_estagio ?? 0;
  const aging = dias >= 15 ? '#ef4444' : dias >= 7 ? '#f59e0b' : null;
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  return (
    <div
      onClick={() => setShowDetail(true)}
      style={{ position: 'relative', padding: '13px 14px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.06))', borderLeft: `4px solid ${aging || color || '#64748b'}`, display: 'flex', flexDirection: 'column', gap: '5px', minWidth: 0, cursor: 'pointer' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px', minWidth: 0 }}>
        <span style={{ fontSize: '14.5px', fontWeight: 800, color: 'var(--text-main)', lineHeight: 1.3, minWidth: 0, wordBreak: 'break-word' }}>#{card.codos} {card.cliente ? '· ' + titleCase(card.cliente) : ''}</span>
        <span style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '7px' }}>
          <PendenciaBadge pendencia={card.pendencia} size={20} />
          <TipoOsBadge tipo={card.tipo_os} />
          {onChangeStatus && (
            <button
              ref={btnRef}
              onClick={(e) => { e.stopPropagation(); setAnchorRect(btnRef.current!.getBoundingClientRect()); }}
              title="Mudar status"
              style={{ width: '38px', height: '38px', padding: 0, borderRadius: '8px', border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '20px', lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}
            >⋮</button>
          )}
        </span>
      </div>
      {anchorRect && onChangeStatus && (
        <StatusMenu
          anchorRect={anchorRect}
          codos={card.codos}
          stageKey={stageKey}
          tipoOs={card.tipo_os}
          onClose={() => setAnchorRect(null)}
          onPick={(status, label, obs) => { setAnchorRect(null); onChangeStatus(card.codos, card.empresa, status, label, obs); }}
        />
      )}
      {card.equipamento && <div style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.3 }}>{card.equipamento}</div>}
      {card.pendencia && <div style={{ fontSize: '12px', color: '#f87171', fontWeight: 700, lineHeight: 1.3 }}>Pendência: {card.pendencia.mensagem}</div>}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', fontSize: '12px', marginTop: '2px', flexWrap: 'wrap' }}>
        <span style={{ color: aging || 'var(--text-muted)', fontWeight: aging ? 800 : 600 }}>{dias === 0 ? 'hoje no estágio' : `${dias}d no estágio`}</span>
        <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{fmtDate(card.data_entrada)}</span>
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
            <MobileOsRow card={card} stageLabel={card.stage_label || ''} stageKey={(card as any).stage || ''} color={STAGE_COLORS[(card as any).stage] } showEmpresa={showEmpresa} showStage onChangeStatus={onChangeStatus} />
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
        const isTechnician = isTechnicianSession();
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

const OsCard: React.FC<{ card: BoardCard; stageKey: string; color?: string; scale: number; showEmpresa: boolean; onChangeStatus?: ChangeStatusFn }> = ({ card, stageKey, color, scale, showEmpresa, onChangeStatus }) => {
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
          <PendenciaBadge pendencia={card.pendencia} size={Math.max(Math.round(13 * scale), 14)} />
          <TipoOsBadge tipo={card.tipo_os} scale={scale} />
          {onChangeStatus && (
            <button
              ref={btnRef}
              onClick={(e) => { e.stopPropagation(); setAnchorRect(btnRef.current!.getBoundingClientRect()); }}
              title="Mudar status"
              // escritório (mouse): botão menor pra não espremer a etiqueta do tipo; técnico (dedo): 28px
              style={{ width: `${Math.max(16 * scale, isTechnicianSession() ? 28 : 20)}px`, height: `${Math.max(16 * scale, isTechnicianSession() ? 28 : 20)}px`, flexShrink: 0, padding: 0, borderRadius: '6px', border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', cursor: 'pointer', fontSize: `${Math.max(10 * scale, isTechnicianSession() ? 15 : 13)}px`, lineHeight: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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
          codos={card.codos}
          stageKey={stageKey}
          tipoOs={card.tipo_os}
          onClose={() => setAnchorRect(null)}
          onPick={(status, label, obs) => { setAnchorRect(null); onChangeStatus(card.codos, card.empresa, status, label, obs); }}
        />
      )}
      {showDetail && <OsDetailModal codos={card.codos} onClose={() => setShowDetail(false)} />}
    </div>
  );
};

// Menuzinho flutuante com os status disponíveis (varia por estágio - ver
// STAGE_KEY_ALLOWED_TRANSITIONS) - usado tanto no cartão da grade
// (OsCard) quanto na linha da lista (MobileOsRow).
const STATUS_LABELS: Record<number, string> = {
  2: 'Avaliação', 3: 'Orçamento enviado', 15: 'Orçamento aprovado', 16: 'Não aprovado',
  4: 'Execução', 6: 'Aguardando retirada', 7: 'Finalizada', 8: 'Aguardando peça',
  11: 'Sem conserto', 12: 'Não autorizada', 13: 'Sem defeito', 14: 'Descarte',
};

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
const StatusMenu: React.FC<{ anchorRect: DOMRect; codos: number; stageKey: string; tipoOs?: string | null; onClose: () => void; onPick: (status: number, label: string, obs?: string) => void }> = ({ anchorRect, codos, stageKey, tipoOs, onClose, onPick }) => {
  const [step, setStep] = useState<'menu' | 'motivo' | 'confirm'>('menu');
  const [pendingKey, setPendingKey] = useState<number | null>(null);
  const [obsText, setObsText] = useState('');
  const { podeTudo } = React.useContext(StatusPermContext);
  const allowedKeys = allowedStatusKeys(stageKey, tipoOs);
  const availableOptions = podeTudo
    ? OS_STATUS_BUTTONS.filter(b => b.stage !== stageKey || b.code === 13 || b.code === 11).map(b => ({ key: b.code, short: b.label }))
    : TECH_STATUS_OPTIONS.filter(opt => allowedKeys.includes(opt.key));
  // Pulando direto de "Aprovado" pra "Aguardando retirada" (sem passar pela Execução), a
  // observação vira obrigatória - pedido do usuário em 07/10/2026: precisa explicar o que foi
  // feito, já que não existe outro registro desse caminho mais curto.
  const obsRequired = !podeTudo && !isGarantia(tipoOs) && stageKey === 'aprovado' && pendingKey === 6;
  // Anexo de foto/vídeo ao mudar status (pedido do usuário em 07/10/2026): fica registrado nos
  // arquivos da O.S. no Softsystem e vai pro cliente, mesmo pipeline do upload rápido já existente
  // (uploadOsPhoto -> handle_os_photo_upload: Drive + WhatsApp + Softsystem, em paralelo).
  const [mediaFiles, setMediaFiles] = useState<QuickUploadFileState[]>([]);
  const midiaCameraPhotoRef = useRef<HTMLInputElement>(null);
  const midiaCameraVideoRef = useRef<HTMLInputElement>(null);
  const midiaFilePickerRef = useRef<HTMLInputElement>(null);

  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (step !== 'menu') return; // com o textarea/confirmação aberta, clique fora não deve fechar sozinho
    // BUG encontrado em produção em 07/10/2026 (técnico relatou "cliquei em todos os botões e
    // nenhum funcionou"): esse listener fica no document em fase de CAPTURA, que roda ANTES do
    // evento chegar no alvo - ou seja, roda antes até do próprio onClick do botão de opção lá
    // dentro do menu. Sem checar se o clique foi DENTRO do menu, ele fechava (onClose) a cada
    // toque em QUALQUER botão da própria lista, inclusive os de status - o stopPropagation() no
    // wrapper do menu não adianta nada aqui porque é fase de bolha (bubble), e a fase de captura
    // no document já rodou antes disso. Com o containment check abaixo, só fecha quando o clique
    // realmente aconteceu fora do menu.
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('click', onDocClick, true);
    return () => document.removeEventListener('click', onDocClick, true);
  }, [onClose, step]);

  const choose = (key: number) => {
    setPendingKey(key);
    // "Sem conserto" pergunta o motivo (opcional - vira o {motivo} da mensagem ao cliente, ver
    // AutomationService.sem_conserto_motivo). "Aprovado" -> "Aguardando retirada" (pulando a
    // Execução) também pergunta, mas aqui é OBRIGATÓRIO (ver obsRequired acima).
    const needsObsStep = key === 11 || (!podeTudo && !isGarantia(tipoOs) && stageKey === 'aprovado' && key === 6);
    setStep(needsObsStep ? 'motivo' : 'confirm');
  };

  const uploadMediaOne = async (key: string, file: File) => {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await uploadOsPhoto(codos, formData, true);
      setMediaFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'done', result } : f));
    } catch (err: any) {
      setMediaFiles(prev => prev.map(f => f.key === key ? { ...f, status: 'error', error: err?.message || 'Falha ao enviar' } : f));
    }
  };

  const addMediaFiles = (fileList: FileList | null) => {
    if (!fileList || !fileList.length) return;
    const toAdd = Array.from(fileList).map((file, i) => ({
      key: `${Date.now()}_${i}_${file.name}`, file, status: 'uploading' as const,
    }));
    setMediaFiles(prev => [...prev, ...toAdd]);
    toAdd.forEach(item => uploadMediaOne(item.key, item.file));
  };

  const confirm = () => {
    if (pendingKey == null) return;
    if (obsRequired && !obsText.trim()) return;
    const sendsObs = pendingKey === 11 || obsRequired;
    onPick(pendingKey, STATUS_LABELS[pendingKey], sendsObs ? (obsText.trim() || undefined) : undefined);
  };

  const menuWidth = step === 'menu' ? 170 : 240;
  const spaceBelow = window.innerHeight - anchorRect.bottom;
  const openUpward = spaceBelow < 220 && anchorRect.top > 220;
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.max(8, Math.min(anchorRect.right - menuWidth, window.innerWidth - menuWidth - 8)),
    ...(openUpward ? { bottom: window.innerHeight - anchorRect.top + 4 } : { top: anchorRect.bottom + 4 }),
    zIndex: 9999, background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color, rgba(255,255,255,0.18))',
    borderRadius: '8px', boxShadow: '0 6px 18px rgba(0,0,0,0.4)', overflowX: 'hidden', overflowY: 'auto', width: `${menuWidth}px`,
    maxHeight: `${Math.max(200, (openUpward ? anchorRect.top : window.innerHeight - anchorRect.bottom) - 16)}px`,
  };

  const btnStyle: React.CSSProperties = { display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: '12.5px', fontWeight: 700, color: 'var(--text-main)', background: 'transparent', border: 'none', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.08))', cursor: 'pointer' };
  const cancelStyle: React.CSSProperties = { display: 'block', width: '100%', textAlign: 'center', padding: '8px', fontSize: '11px', color: 'var(--text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' };

  let body: React.ReactNode;
  if (step === 'menu') {
    body = (
      <>
        {availableOptions.map(opt => (
          <button key={opt.key} onClick={() => choose(opt.key)} style={btnStyle}>{STATUS_LABELS[opt.key]}</button>
        ))}
        <button onClick={onClose} style={cancelStyle}>Cancelar</button>
      </>
    );
  } else if (step === 'motivo') {
    body = (
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '11.5px', fontWeight: 700, color: 'var(--text-main)' }}>Motivo {obsRequired ? '(obrigatório)' : '(opcional)'}</div>
        <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>
          {obsRequired ? 'Explique o que foi feito - vai pro registro interno da O.S.' : 'Aparece resumido na mensagem pro cliente.'}
        </div>
        <textarea
          autoFocus
          value={obsText}
          onChange={e => setObsText(e.target.value)}
          rows={3}
          style={{ width: '100%', boxSizing: 'border-box', resize: 'none', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)', fontSize: '12.5px', padding: '6px 8px', fontFamily: 'inherit' }}
        />
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={() => setStep('menu')} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>Voltar</button>
          <button
            onClick={() => { if (!obsRequired || obsText.trim()) setStep('confirm'); }}
            disabled={obsRequired && !obsText.trim()}
            style={{ flex: 1, padding: '8px', borderRadius: '6px', border: 'none', background: (obsRequired && !obsText.trim()) ? 'var(--border-color, rgba(255,255,255,0.18))' : 'var(--accent-primary)', color: (obsRequired && !obsText.trim()) ? 'var(--text-muted)' : '#04140d', fontSize: '11.5px', fontWeight: 800, cursor: (obsRequired && !obsText.trim()) ? 'not-allowed' : 'pointer' }}
          >Continuar</button>
        </div>
      </div>
    );
  } else {
    // Confirmação + anexo de mídia na MESMA tela (pedido do usuário em 07/10/2026: a etapa
    // separada só pra "pular" deixava o fluxo lento pra quem não quer anexar nada) - os botões de
    // foto/vídeo ficam compactos ao lado do "Confirmar", nunca bloqueando quem só quer confirmar.
    const btnMini: React.CSSProperties = { flex: 1, padding: '6px 4px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'rgba(255,255,255,0.04)', color: 'var(--text-main)', fontSize: '10px', fontWeight: 700, cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' };
    body = (
      <div style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-main)' }}>
          Marcar como "{pendingKey != null ? STATUS_LABELS[pendingKey] : ''}"?
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={() => midiaCameraPhotoRef.current?.click()} style={btnMini}><Camera size={14} />Foto</button>
          <button onClick={() => midiaCameraVideoRef.current?.click()} style={btnMini}><Video size={14} />Vídeo</button>
          <button onClick={() => midiaFilePickerRef.current?.click()} style={btnMini}><Paperclip size={14} />Arquivo</button>
        </div>
        <input ref={midiaCameraPhotoRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); e.target.value = ''; }} />
        <input ref={midiaCameraVideoRef} type="file" accept="video/*" capture="environment" style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); e.target.value = ''; }} />
        <input ref={midiaFilePickerRef} type="file" accept="image/*,video/*" multiple style={{ display: 'none' }} onChange={e => { addMediaFiles(e.target.files); e.target.value = ''; }} />
        {mediaFiles.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '80px', overflowY: 'auto' }}>
            {mediaFiles.map(f => (
              <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: 'var(--text-muted)' }}>
                {f.status === 'uploading' && <Loader2 size={12} className="animate-spin" />}
                {f.status === 'done' && <span style={{ color: 'var(--accent-primary)' }}>✓</span>}
                {f.status === 'error' && <span style={{ color: '#ef4444' }}>✗</span>}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.file.name}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={() => setStep((pendingKey === 11 || obsRequired) ? 'motivo' : 'menu')} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid var(--border-color, rgba(255,255,255,0.18))', background: 'transparent', color: 'var(--text-muted)', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer' }}>Voltar</button>
          <button onClick={confirm} style={{ flex: 1, padding: '8px', borderRadius: '6px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '11.5px', fontWeight: 800, cursor: 'pointer' }}>Confirmar</button>
        </div>
      </div>
    );
  }

  return createPortal(
    <div ref={menuRef} onClick={e => e.stopPropagation()} style={style}>
      {body}
    </div>,
    document.body
  );
};

// --------------------------------------------------------------------------- letreiro de observações

interface TickerNote {
  id: number;
  codos: number;
  tecnico: string;
  mensagem: string;
  criado_em: string;
}

// Barra fixa no rodapé do Quadro Geral com as observações ativas deixadas pros técnicos (ex.: "a
// peça chegou") - pedido do usuário em 07/10/2026, estilo "breaking news" de telejornal, sempre
// visível (oculta sozinha quando não há nada pendente). Atualiza na hora via o mesmo WebSocket que
// já avisa o resto do quadro (TECH_NOTE_UPDATE -> evento 'tech-note-update', ver Dashboard.tsx),
// com uma releitura periódica de segurança.
const NotesTicker: React.FC = () => {
  const [notes, setNotes] = useState<TickerNote[]>([]);

  const load = useCallback(() => {
    apiFetch('/os-board/notes/ticker').then(data => setNotes(data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const onUpdate = () => load();
    window.addEventListener('tech-note-update', onUpdate);
    const interval = window.setInterval(load, 60000);
    return () => {
      window.removeEventListener('tech-note-update', onUpdate);
      window.clearInterval(interval);
    };
  }, [load]);

  if (notes.length === 0) return null;

  const totalChars = notes.reduce((sum, n) => sum + n.mensagem.length + n.tecnico.length + 25, 0);
  const duration = Math.max(20, Math.round(totalChars * 0.13));

  const renderItems = (keyPrefix: string) => notes.map(n => (
    <span key={`${keyPrefix}-${n.id}`} style={{ paddingRight: '36px' }}>
      <b style={{ color: colorForTechnician(n.tecnico) }}>{titleCase(n.tecnico)}</b>
      {' — '}
      <span style={{ color: 'var(--text-muted, #94a3b8)', fontWeight: 700 }}>O.S. #{n.codos}:</span>
      {' '}{n.mensagem}
      <span style={{ color: 'var(--text-muted, #94a3b8)', fontWeight: 400 }}> ({new Date(n.criado_em).toLocaleDateString('pt-BR')})</span>
      <span style={{ color: 'var(--text-muted, #94a3b8)' }}>     •</span>
    </span>
  ));

  return (
    <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 20001, height: '34px', background: 'rgba(15,23,42,0.97)', borderTop: '1px solid rgba(250,204,21,0.4)', display: 'flex', alignItems: 'center', overflow: 'hidden' }}>
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'center', gap: '6px', padding: '0 12px', height: '100%', background: '#b91c1c', color: '#fff', fontSize: '11px', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        <Bell size={12} /> Avisos
      </div>
      <div style={{ flex: 1, overflow: 'hidden', whiteSpace: 'nowrap', position: 'relative', height: '100%' }}>
        <div
          className="animate-ticker"
          style={{ display: 'inline-block', whiteSpace: 'nowrap', fontSize: '12.5px', fontWeight: 600, color: '#e2e8f0', lineHeight: '34px', animationDuration: `${duration}s` }}
        >
          <span style={{ paddingRight: '70px' }}>{renderItems('a')}</span>
          <span style={{ paddingRight: '70px' }}>{renderItems('b')}</span>
        </div>
      </div>
    </div>
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
                {visibleCards.map(card => <OsCard key={`${card.empresa}-${card.codos}`} card={card} stageKey={st.key} color={STAGE_COLORS[st.key]} scale={scale} showEmpresa />)}
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
