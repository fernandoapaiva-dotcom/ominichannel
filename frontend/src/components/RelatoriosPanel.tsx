import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, BarChart3, FileText, Loader2, RefreshCw, Search, CheckCircle2, XCircle, Eye, MessageCircle } from 'lucide-react';
import { User } from '../types';
import { apiFetch } from '../services/api';

/**
 * Módulo Relatórios - pedido do usuário em 14/10/2026. Por enquanto um relatório: avisos e
 * cobranças por WhatsApp das O.S. em "Aguardando aprovação" e "Aguardando retirada" (backend:
 * app/api/v1/relatorios.py + app/services/os_envio_report_service.py), na tela e em PDF.
 * Diário (padrão: hoje, só a hora) ou por período (agrupado por data); busca por cliente mostra
 * quantas vezes ele foi cobrado em cada etapa (visão "Por cliente").
 */

interface EnvioRow {
  id: number; data: string; data_hora: string; codos: number; empresa: string | null; cliente: string;
  contato: string | null; telefone: string | null; tecnico: string | null; equipamento: string | null;
  valor_total: number | null; etapa: 'orcamento' | 'retirada'; etapa_label: string; tipo: string; tipo_label: string;
  tentativa: number | null; status: string; status_label: string; sucesso: boolean; respondeu: boolean; resultado: string;
}
interface ClienteRow {
  cliente: string; contato: string | null; telefone: string | null; os: number[];
  orcamento_envios: number; orcamento_cobrancas: number; retirada_envios: number; retirada_cobrancas: number;
  descarte: number; falhas: number; respondidas: number; ultimo_envio: string | null; total: number;
}
interface Resumo {
  total: number; orcamento: number; retirada: number; cobrancas: number; envios: number; sucesso: number; falhas: number;
  entregues: number; lidas: number; respondidas: number; os_distintas: number; clientes_distintos: number; valor_aguardando_aprovacao: number;
}
interface CoberturaResumo {
  etapa: 'orcamento' | 'retirada'; label: string; total: number; avisadas: number; no_periodo: number; sem_mensagem: number;
  atrasadas: number; falhas: number; sem_telefone: number; na_interno: number; mensagens: number;
}
interface CoberturaItem {
  codos: number; empresa: string; cliente: string; contato: string | null; telefone: string | null; tecnico: string | null;
  valor_total: number | null; etapa: 'orcamento' | 'retirada'; etapa_label: string; entrou_em: string | null;
  dias_no_status: number | null; dias_restantes: number | null; mensagens: number; mensagens_periodo: number;
  ultimo_envio: string | null; ultimo_status: string | null; proxima_cobranca: string | null;
  situacao: 'atrasada' | 'falhou' | 'sem_telefone' | 'na_interno' | 'aguardando_1a' | 'em_dia'; situacao_label: string;
}
interface ReportData {
  resumo: Resumo; rows: EnvioRow[]; por_cliente: ClienteRow[];
  cobertura: { agora: string; resumo: CoberturaResumo[]; itens: CoberturaItem[] };
}

const SITUACAO_COLOR: Record<CoberturaItem['situacao'], string> = {
  atrasada: '#ef4444', falhou: '#ef4444', sem_telefone: '#f59e0b', na_interno: '#94a3b8', aguardando_1a: '#38bdf8', em_dia: '#22c55e',
};
const PROBLEMAS = new Set(['atrasada', 'falhou', 'sem_telefone']);

type Preset = 'hoje' | 'ontem' | '7d' | '30d' | 'mes' | 'tudo' | 'custom';

const PRESETS: { key: Preset; label: string }[] = [
  { key: 'hoje', label: 'Hoje' }, { key: 'ontem', label: 'Ontem' }, { key: '7d', label: '7 dias' },
  { key: '30d', label: '30 dias' }, { key: 'mes', label: 'Este mês' }, { key: 'tudo', label: 'Tudo' },
  { key: 'custom', label: 'Período…' },
];

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const presetRange = (p: Preset): [string, string] => {
  const hoje = new Date();
  const dias = (n: number) => { const d = new Date(hoje); d.setDate(d.getDate() - n); return d; };
  switch (p) {
    case 'hoje': return [ymd(hoje), ymd(hoje)];
    case 'ontem': return [ymd(dias(1)), ymd(dias(1))];
    case '7d': return [ymd(dias(6)), ymd(hoje)];
    case '30d': return [ymd(dias(29)), ymd(hoje)];
    case 'mes': return [ymd(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ymd(hoje)];
    default: return ['', ''];
  }
};

const money = (v?: number | null) => (typeof v === 'number' ? v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }) : '—');
const fmtDia = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
const fmtHora = (iso: string) => iso.slice(11, 16);
const fmtDataHora = (iso?: string | null) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)} ${iso.slice(11, 16)}` : '—');

const STATUS_COLOR: Record<string, string> = { read: '#22c55e', delivered: '#38bdf8', sent: '#94a3b8' };
const RESULTADO_COLOR = (r: string) =>
  r.startsWith('Aprovado') || r.startsWith('Retirado') ? '#22c55e' : r === 'Recusado' || r.startsWith('Desmanche') ? '#f87171' : '#f59e0b';

const Badge: React.FC<{ color: string; children: React.ReactNode; title?: string }> = ({ color, children, title }) => (
  <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '999px', color, background: `${color}1F`, border: `1px solid ${color}55`, whiteSpace: 'nowrap' }}>
    {children}
  </span>
);

const Kpi: React.FC<{ label: string; value: React.ReactNode; hint?: string; color?: string }> = ({ label, value, hint, color }) => (
  <div style={{ flex: '1 1 140px', minWidth: '130px', background: 'var(--bg-card, var(--bg-secondary))', border: '1px solid var(--border-color)', borderRadius: '10px', padding: '12px 14px' }}>
    <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{label}</div>
    <div style={{ fontSize: '22px', fontWeight: 800, color: color || 'var(--text-main)', marginTop: '4px' }}>{value}</div>
    {hint && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{hint}</div>}
  </div>
);

export const RelatoriosPanel: React.FC<{ user: User; onBack: () => void }> = ({ onBack }) => {
  const [preset, setPreset] = useState<Preset>('hoje');
  const [[inicio, fim], setRange] = useState<[string, string]>(presetRange('hoje'));
  const [etapa, setEtapa] = useState('');
  const [empresa, setEmpresa] = useState('');
  const [cliente, setCliente] = useState('');
  const [clienteBusca, setClienteBusca] = useState('');
  const [visao, setVisao] = useState<'envios' | 'clientes' | 'conferencia'>('envios');
  const [soProblemas, setSoProblemas] = useState(false);
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // busca por cliente com um respiro, pra não consultar a cada tecla
  useEffect(() => {
    const t = window.setTimeout(() => setClienteBusca(cliente.trim()), 400);
    return () => window.clearTimeout(t);
  }, [cliente]);

  // buscou um cliente: a visão "Por cliente" é a que responde "quantas vezes ele foi cobrado"
  useEffect(() => { if (clienteBusca) setVisao('clientes'); }, [clienteBusca]);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    if (inicio) p.set('inicio', inicio);
    if (fim) p.set('fim', fim);
    if (etapa) p.set('etapa', etapa);
    if (empresa) p.set('empresa', empresa);
    if (clienteBusca) p.set('cliente', clienteBusca);
    return p;
  }, [inicio, fim, etapa, empresa, clienteBusca]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await apiFetch(`/relatorios/cobrancas-os?${qs.toString()}`));
    } catch (err: any) {
      setError(err?.message || 'Não foi possível carregar o relatório.');
    } finally {
      setLoading(false);
    }
  }, [qs]);

  useEffect(() => { load(); }, [load]);

  const choosePreset = (p: Preset) => {
    setPreset(p);
    if (p !== 'custom') setRange(presetRange(p));
  };

  const gerarPdf = async () => {
    setPdfLoading(true);
    setError(null);
    try {
      const p = new URLSearchParams(qs);
      p.set('visao', visao);
      const token = localStorage.getItem('token');
      const response = await fetch(`/api/v1/relatorios/cobrancas-os/pdf?${p.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Não foi possível gerar o PDF (HTTP ${response.status}).`);
      }
      const url = URL.createObjectURL(await response.blob());
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err: any) {
      setError(err?.message || 'Não foi possível gerar o PDF.');
    } finally {
      setPdfLoading(false);
    }
  };

  const umDia = !!inicio && inicio === fim;

  // por período: agrupa por dia (mais recente primeiro), com subtotal de cada dia
  const porDia = useMemo(() => {
    const groups: { dia: string; rows: EnvioRow[] }[] = [];
    for (const r of data?.rows || []) {
      const last = groups[groups.length - 1];
      if (last && last.dia === r.data) last.rows.push(r);
      else groups.push({ dia: r.data, rows: [r] });
    }
    return groups;
  }, [data]);

  const input: React.CSSProperties = {
    padding: '8px 10px', borderRadius: '8px', background: 'var(--bg-secondary, rgba(255,255,255,0.04))', color: 'var(--text-main)',
    border: '1px solid var(--border-color, rgba(255,255,255,0.12))', fontSize: '13px', fontFamily: 'inherit', boxSizing: 'border-box',
  };
  const chip = (active: boolean): React.CSSProperties => ({
    padding: '7px 12px', borderRadius: '999px', fontSize: '12.5px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap',
    background: active ? 'rgba(0,230,153,0.16)' : 'transparent', color: active ? 'var(--accent-primary)' : 'var(--text-muted)',
    border: `1px solid ${active ? 'rgba(0,230,153,0.45)' : 'var(--border-color, rgba(255,255,255,0.12))'}`,
  });
  const th: React.CSSProperties = { textAlign: 'left', padding: '9px 10px', fontSize: '11px', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.3px', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap', background: 'var(--bg-primary)', position: 'sticky', top: 0, zIndex: 1 };
  const td: React.CSSProperties = { padding: '9px 10px', fontSize: '13px', color: 'var(--text-main)', borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.06))', verticalAlign: 'top' };

  const r = data?.resumo;
  const pct = (n: number) => (r && r.total ? `${Math.round((100 * n) / r.total)}%` : '0%');

  const envioRow = (x: EnvioRow) => (
    <tr key={x.id}>
      <td style={{ ...td, whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{fmtHora(x.data_hora)}</td>
      <td style={{ ...td, fontWeight: 800, whiteSpace: 'nowrap' }}>#{x.codos}</td>
      <td style={{ ...td, minWidth: '200px' }}>
        <div style={{ fontWeight: 700 }}>{x.cliente}</div>
        <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{[x.contato, x.telefone].filter(Boolean).join(' · ')}</div>
      </td>
      <td style={td}><Badge color={x.etapa === 'orcamento' ? '#f59e0b' : '#a78bfa'}>{x.etapa_label}</Badge></td>
      <td style={{ ...td, whiteSpace: 'nowrap' }}>{x.tipo_label}{x.tentativa ? <span style={{ color: 'var(--text-muted)' }}> · {x.tentativa}ª</span> : null}</td>
      <td style={td}>
        {x.sucesso
          ? <Badge color={STATUS_COLOR[x.status] || '#94a3b8'}>{x.status === 'read' ? <Eye size={11} /> : <CheckCircle2 size={11} />}{x.status_label}</Badge>
          : <Badge color="#ef4444"><XCircle size={11} />{x.status_label}</Badge>}
      </td>
      <td style={{ ...td, whiteSpace: 'nowrap' }}>{x.respondeu ? <Badge color="#22c55e"><MessageCircle size={11} />Sim</Badge> : <span style={{ color: 'var(--text-muted)' }}>Não</span>}</td>
      <td style={td}><span style={{ color: RESULTADO_COLOR(x.resultado), fontWeight: 700, fontSize: '12.5px' }}>{x.resultado}</span></td>
      <td style={{ ...td, whiteSpace: 'nowrap' }}>{money(x.valor_total)}</td>
      <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{x.tecnico || '—'}</td>
    </tr>
  );

  return (
    <div style={{ flex: 1, minWidth: 0, height: '100%', overflowY: 'auto', background: 'var(--bg-primary)', boxSizing: 'border-box', padding: '20px 16px 32px' }}>
      <div style={{ maxWidth: '1280px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <button onClick={onBack} title="Voltar" style={{ width: '34px', height: '34px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
            <ArrowLeft size={16} />
          </button>
          <div style={{ flex: 1, minWidth: '200px' }}>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: '20px', fontWeight: 800, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <BarChart3 size={20} /> Relatórios
            </div>
            <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>Avisos e cobranças de O.S. pelo WhatsApp · Aguardando aprovação e Aguardando retirada</div>
          </div>
          <button onClick={load} disabled={loading} title="Atualizar" style={{ ...chip(false), display: 'flex', alignItems: 'center', gap: '6px' }}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Atualizar
          </button>
          <button onClick={gerarPdf} disabled={pdfLoading || !data} style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px', borderRadius: '8px', border: 'none', background: 'var(--accent-primary)', color: '#04140d', fontSize: '13px', fontWeight: 800, cursor: 'pointer', opacity: pdfLoading ? 0.7 : 1 }}>
            {pdfLoading ? <Loader2 size={14} className="animate-spin" /> : <FileText size={14} />} Gerar PDF
          </button>
        </div>

        {/* filtros */}
        <div style={{ background: 'var(--bg-card, var(--bg-secondary))', border: '1px solid var(--border-color)', borderRadius: '12px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
            {PRESETS.map(p => <button key={p.key} onClick={() => choosePreset(p.key)} style={chip(preset === p.key)}>{p.label}</button>)}
            {preset === 'custom' && (
              <span style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                <input type="date" value={inicio} onChange={e => setRange([e.target.value, fim])} style={input} />
                <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>até</span>
                <input type="date" value={fim} onChange={e => setRange([inicio, e.target.value])} style={input} />
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <div style={{ position: 'relative', flex: '2 1 260px' }}>
              <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input value={cliente} onChange={e => setCliente(e.target.value)} placeholder="Buscar cliente (razão social, contato, telefone ou nº da O.S.)" style={{ ...input, width: '100%', paddingLeft: '30px' }} />
            </div>
            <select value={etapa} onChange={e => setEtapa(e.target.value)} style={{ ...input, flex: '1 1 180px' }}>
              <option value="">Aprovação e retirada</option>
              <option value="orcamento">Aguardando aprovação</option>
              <option value="retirada">Aguardando retirada</option>
            </select>
            <select value={empresa} onChange={e => setEmpresa(e.target.value)} style={{ ...input, flex: '1 1 150px' }}>
              <option value="">Todas as lojas</option>
              <option value="servweld">Servweld</option>
              <option value="centrooeste">Centro-Oeste</option>
            </select>
          </div>
        </div>

        {error && <div style={{ color: '#f87171', fontSize: '13px' }}>{error}</div>}

        {data?.cobertura && (
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            {data.cobertura.resumo.map(c => {
              const cor = c.etapa === 'orcamento' ? '#f59e0b' : '#a78bfa';
              const problemas = c.atrasadas + c.falhas + c.sem_telefone;
              const pctAv = c.total ? Math.round((100 * c.avisadas) / c.total) : 0;
              return (
                <button key={c.etapa} onClick={() => { setVisao('conferencia'); setEtapa(c.etapa); }} title="Ver a conferência dessas O.S."
                  style={{ flex: '1 1 300px', textAlign: 'left', cursor: 'pointer', background: 'var(--bg-card, var(--bg-secondary))', border: `1px solid ${cor}55`, borderRadius: '12px', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px', fontFamily: 'inherit' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '12px', fontWeight: 800, color: cor, textTransform: 'uppercase', letterSpacing: '0.4px' }}>{c.label} · agora</span>
                    {problemas > 0
                      ? <Badge color="#ef4444"><XCircle size={11} />{problemas} precisa(m) de atenção</Badge>
                      : <Badge color="#22c55e"><CheckCircle2 size={11} />Tudo certo</Badge>}
                  </div>
                  <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div><div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-main)', lineHeight: 1 }}>{c.total}</div><div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>O.S. no status</div></div>
                    <div><div style={{ fontSize: '28px', fontWeight: 800, color: '#22c55e', lineHeight: 1 }}>{c.avisadas}</div><div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>receberam mensagem ({pctAv}%)</div></div>
                    <div><div style={{ fontSize: '28px', fontWeight: 800, color: 'var(--text-main)', lineHeight: 1 }}>{c.no_periodo}</div><div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>com envio no período</div></div>
                  </div>
                  <div style={{ height: '6px', borderRadius: '999px', background: 'rgba(148,163,184,0.18)', overflow: 'hidden' }}>
                    <div style={{ width: `${pctAv}%`, height: '100%', background: '#22c55e' }} />
                  </div>
                  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', fontSize: '11.5px', color: 'var(--text-muted)' }}>
                    <span>{c.mensagens} mensagens</span>
                    <span style={{ color: c.atrasadas ? '#f87171' : undefined, fontWeight: c.atrasadas ? 800 : 400 }}>{c.atrasadas} atrasada(s)</span>
                    <span style={{ color: c.falhas ? '#f87171' : undefined, fontWeight: c.falhas ? 800 : 400 }}>{c.falhas} com falha</span>
                    <span style={{ color: c.sem_telefone ? '#f59e0b' : undefined, fontWeight: c.sem_telefone ? 800 : 400 }}>{c.sem_telefone} sem telefone</span>
                    {c.etapa === 'orcamento' && <span>{c.na_interno} interno (N/A)</span>}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {r && (
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <Kpi label="Envios" value={r.total} hint={`${r.os_distintas} O.S. · ${r.clientes_distintos} cliente(s)`} />
            <Kpi label="Aguard. aprovação" value={r.orcamento} color="#f59e0b" />
            <Kpi label="Aguard. retirada" value={r.retirada} color="#a78bfa" />
            <Kpi label="Sucesso no envio" value={pct(r.sucesso)} hint={`${r.sucesso} ok · ${r.falhas} falha(s)`} color={r.falhas ? '#f59e0b' : '#22c55e'} />
            <Kpi label="Lidas" value={pct(r.lidas)} hint={`${r.lidas} de ${r.total}`} />
            <Kpi label="Responderam" value={pct(r.respondidas)} hint="até 3 dias depois" />
            <Kpi label="Valor aguard. aprovação" value={money(r.valor_aguardando_aprovacao)} hint="O.S. ainda sem resposta" />
          </div>
        )}

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button onClick={() => setVisao('envios')} style={chip(visao === 'envios')}>Envios</button>
          <button onClick={() => setVisao('clientes')} style={chip(visao === 'clientes')}>Por cliente</button>
          <button onClick={() => setVisao('conferencia')} style={chip(visao === 'conferencia')}>Conferência por status</button>
          {visao === 'conferencia' && (
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-muted)', marginLeft: '8px', cursor: 'pointer' }}>
              <input type="checkbox" checked={soProblemas} onChange={e => setSoProblemas(e.target.checked)} /> Só o que precisa de atenção
            </label>
          )}
          {loading && <Loader2 size={14} className="animate-spin" style={{ color: 'var(--text-muted)', marginLeft: '6px' }} />}
        </div>

        <div style={{ background: 'var(--bg-card, var(--bg-secondary))', border: '1px solid var(--border-color)', borderRadius: '12px', overflow: 'auto', maxHeight: '70vh' }}>
          {visao === 'conferencia' ? (
            (() => {
              const itens = (data?.cobertura.itens || []).filter(x => !soProblemas || PROBLEMAS.has(x.situacao));
              if (!itens.length) return <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>{soProblemas ? 'Nenhuma O.S. com problema na cobrança.' : 'Nenhuma O.S. nesse status agora.'}</div>;
              return (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      <th style={th}>Cobrança</th><th style={th}>O.S.</th><th style={th}>Cliente</th><th style={th}>Status</th>
                      <th style={th}>No status há</th><th style={th}>Mensagens</th><th style={th}>Última mensagem</th><th style={th}>Próxima cobrança</th>
                      <th style={th}>Valor</th><th style={th}>Técnico</th>
                    </tr>
                  </thead>
                  <tbody>
                    {itens.map(x => (
                      <tr key={`${x.empresa}-${x.codos}-${x.etapa}`}>
                        <td style={td}><Badge color={SITUACAO_COLOR[x.situacao]}>{x.situacao_label}</Badge></td>
                        <td style={{ ...td, fontWeight: 800, whiteSpace: 'nowrap' }}>#{x.codos}</td>
                        <td style={{ ...td, minWidth: '200px' }}>
                          <div style={{ fontWeight: 700 }}>{x.cliente}</div>
                          <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{[x.contato, x.telefone].filter(Boolean).join(' · ') || 'sem telefone'}</div>
                        </td>
                        <td style={td}><Badge color={x.etapa === 'orcamento' ? '#f59e0b' : '#a78bfa'}>{x.etapa_label}</Badge></td>
                        <td style={{ ...td, whiteSpace: 'nowrap' }}>
                          {x.dias_no_status ?? '—'} dia(s)
                          {x.dias_restantes != null && <div style={{ fontSize: '11.5px', color: x.dias_restantes <= 15 ? '#f87171' : 'var(--text-muted)' }}>restam {x.dias_restantes} p/ descarte</div>}
                        </td>
                        <td style={{ ...td, fontWeight: 800 }}>{x.mensagens}{x.mensagens_periodo !== x.mensagens && <span style={{ fontWeight: 400, color: 'var(--text-muted)', fontSize: '11.5px' }}> ({x.mensagens_periodo} no período)</span>}</td>
                        <td style={{ ...td, whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{x.ultimo_envio ? <>{fmtDataHora(x.ultimo_envio)}<div style={{ fontSize: '11.5px', color: x.ultimo_status === 'Falhou' ? '#f87171' : undefined }}>{x.ultimo_status}</div></> : 'nenhuma'}</td>
                        <td style={{ ...td, whiteSpace: 'nowrap', color: x.situacao === 'atrasada' ? '#f87171' : 'var(--text-muted)', fontWeight: x.situacao === 'atrasada' ? 800 : 400 }}>{fmtDataHora(x.proxima_cobranca)}</td>
                        <td style={{ ...td, whiteSpace: 'nowrap' }}>{money(x.valor_total)}</td>
                        <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{x.tecnico || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              );
            })()
          ) : data && data.rows.length === 0 ? (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Nenhum aviso ou cobrança enviado com esses filtros.</div>
          ) : visao === 'envios' ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Hora</th><th style={th}>O.S.</th><th style={th}>Cliente</th><th style={th}>Etapa</th>
                  <th style={th}>Tipo</th><th style={th}>WhatsApp</th><th style={th}>Respondeu</th><th style={th}>Situação atual</th>
                  <th style={th}>Valor</th><th style={th}>Técnico</th>
                </tr>
              </thead>
              <tbody>
                {umDia ? (data?.rows || []).map(envioRow) : porDia.map(g => (
                  <React.Fragment key={g.dia}>
                    <tr>
                      <td colSpan={10} style={{ ...td, background: 'rgba(0,230,153,0.06)', fontSize: '12px', fontWeight: 800, color: 'var(--accent-primary)', textTransform: 'capitalize' }}>
                        {fmtDia(g.dia)}
                        <span style={{ color: 'var(--text-muted)', fontWeight: 600, textTransform: 'none', marginLeft: '10px' }}>
                          {g.rows.length} envio(s) · {g.rows.filter(x => !x.sucesso).length} falha(s)
                        </span>
                      </td>
                    </tr>
                    {g.rows.map(envioRow)}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Cliente</th><th style={th}>O.S.</th>
                  <th style={th} title="Avisos iniciais / cobranças de aprovação">Aprovação (env. / cobr.)</th>
                  <th style={th} title="Avisos iniciais / cobranças de retirada">Retirada (env. / cobr.)</th>
                  <th style={th}>Descarte</th><th style={th}>Falhas</th><th style={th}>Respondeu</th><th style={th}>Último envio</th><th style={th}>Total</th>
                </tr>
              </thead>
              <tbody>
                {(data?.por_cliente || []).map(c => (
                  <tr key={c.cliente}>
                    <td style={{ ...td, minWidth: '220px' }}>
                      <div style={{ fontWeight: 700 }}>{c.cliente}</div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{[c.contato, c.telefone].filter(Boolean).join(' · ')}</div>
                    </td>
                    <td style={td}>{c.os.map(n => `#${n}`).join(', ')}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>{c.orcamento_envios} / <b style={{ color: '#f59e0b' }}>{c.orcamento_cobrancas}</b></td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>{c.retirada_envios} / <b style={{ color: '#a78bfa' }}>{c.retirada_cobrancas}</b></td>
                    <td style={td}>{c.descarte || '—'}</td>
                    <td style={{ ...td, color: c.falhas ? '#f87171' : 'var(--text-muted)', fontWeight: c.falhas ? 800 : 400 }}>{c.falhas}</td>
                    <td style={td}>{c.respondidas}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>{fmtDataHora(c.ultimo_envio)}</td>
                    <td style={{ ...td, fontWeight: 800 }}>{c.total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
          Envio = aviso inicial (orçamento pronto / disponível para retirada). Cobrança = lembrete automático de 2 em 2 dias, com o número da tentativa.
          Status do WhatsApp atualiza sozinho (enviada → entregue → lida). Histórico disponível desde 22/09/2026.
          {' '}Conferência: O.S. que estão no status agora (sem pagamento/venda lançados), com as mensagens desde que entraram nele.
          "Atrasada" = já passou um expediente inteiro (dia útil, até 18h) depois da data da cobrança sem ela sair.
        </div>
      </div>
    </div>
  );
};
