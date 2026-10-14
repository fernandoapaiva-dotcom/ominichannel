import React, { useEffect, useState } from 'react';
import { Activity, AlertTriangle, BarChart3, Cpu, DollarSign, Plus, RefreshCw, Save, Trash2, TrendingUp } from 'lucide-react';
import { apiFetch } from '../services/api';

// Painel Admin > Consumo de IA - lê o que o observador de tokens do backend grava (ia_consumo_service.py).
// Separa o TREINO (gasto único: catálogo das vistas explodidas, OCR) do USO do dia a dia.

interface Totais { chamadas: number; erros: number; tok_entrada: number; tok_saida: number; tok_pensamento: number; custo_brl: number }
interface Funcao extends Totais { nome: string; grupo: string; tipo: 'treino' | 'recorrente'; custo_medio_brl: number; tokens_medio: number }
interface Resumo {
  cotacao_dolar: number;
  orcamento_mensal_brl: number;
  observando_desde: string | null;
  hoje: Totais;
  mes: Totais;
  mes_recorrente: Totais;
  mes_treino: Totais;
  media_recorrente_dia_brl: number;
  projecao_mes_brl: number;
  projecao_recorrente_mes_brl: number;
  por_dia: { dia: string; recorrente: Totais; treino: Totais }[];
  por_funcao: Funcao[];
  por_modelo: (Totais & { modelo: string })[];
  ultimos_erros: { quando: string; funcao: string; modelo: string; erro: string }[];
}
interface Precos { cotacao_dolar: number; orcamento_mensal_brl: number; modelos: Record<string, { entrada: number; saida: number }> }

const COR_REC = 'var(--accent-primary)';
const COR_TREINO = '#f5a524';

const brl = (v: number) => {
  const casas = v !== 0 && Math.abs(v) < 1 ? 3 : 2;
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: casas, maximumFractionDigits: casas });
};
const tokens = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} mi`;
  if (n >= 1_000) return `${(n / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;
  return String(Math.round(n));
};
const totalTok = (t: Totais) => t.tok_entrada + t.tok_saida + t.tok_pensamento;
const dataBR = (iso: string) => new Date(iso.endsWith('Z') ? iso : `${iso}Z`).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

const card: React.CSSProperties = {
  backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-lg)', padding: '16px 18px',
};
const th: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', fontSize: '11px', color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap', borderBottom: '1px solid var(--border-color)' };
const td: React.CSSProperties = { padding: '8px 10px', fontSize: '13px', color: 'var(--text-main)', borderBottom: '1px solid var(--border-color)', whiteSpace: 'nowrap' };
const input: React.CSSProperties = { padding: '6px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)', color: 'var(--text-main)', fontSize: '13px', width: '100%', boxSizing: 'border-box' };

const Card: React.FC<{ titulo: string; valor: string; sub?: React.ReactNode; icone: React.ReactNode }> = ({ titulo, valor, sub, icone }) => (
  <div style={card}>
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '12px', fontWeight: 600 }}>{icone}{titulo}</div>
    <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text-main)', margin: '6px 0 4px' }}>{valor}</div>
    {sub && <div style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.5 }}>{sub}</div>}
  </div>
);

export const IAConsumoPanel: React.FC = () => {
  const [dias, setDias] = useState(30);
  const [dados, setDados] = useState<Resumo | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [precos, setPrecos] = useState<Precos | null>(null);
  const [mostrarPrecos, setMostrarPrecos] = useState(false);
  const [recalcular, setRecalcular] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [msgPrecos, setMsgPrecos] = useState<string | null>(null);

  const carregar = async (d = dias) => {
    setCarregando(true);
    setErro(null);
    try {
      setDados(await apiFetch(`/settings/ia-consumo/resumo?dias=${d}`));
    } catch (e: any) {
      setErro(e.message || 'Falha ao carregar o consumo');
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => { carregar(dias); }, [dias]);

  const abrirPrecos = async () => {
    setMostrarPrecos(v => !v);
    setMsgPrecos(null);
    if (!precos) {
      try { setPrecos(await apiFetch('/settings/ia-consumo/precos')); } catch (e: any) { setMsgPrecos(e.message); }
    }
  };

  const salvarPrecos = async () => {
    if (!precos) return;
    setSalvando(true);
    setMsgPrecos(null);
    try {
      setPrecos(await apiFetch(`/settings/ia-consumo/precos?recalcular=${recalcular}`, { method: 'POST', body: JSON.stringify(precos) }));
      setMsgPrecos(recalcular ? 'Salvo - custo de todo o histórico recalculado.' : 'Salvo - vale para as próximas chamadas.');
      setRecalcular(false);
      carregar();
    } catch (e: any) {
      setMsgPrecos(e.message || 'Falha ao salvar');
    } finally {
      setSalvando(false);
    }
  };

  const mudaModelo = (nome: string, campo: 'entrada' | 'saida', valor: string) =>
    setPrecos(p => p && { ...p, modelos: { ...p.modelos, [nome]: { ...p.modelos[nome], [campo]: Number(valor) } } });
  const renomeiaModelo = (antigo: string, novo: string) =>
    setPrecos(p => {
      if (!p || !novo || novo === antigo || p.modelos[novo]) return p;
      const modelos: Precos['modelos'] = {};
      Object.entries(p.modelos).forEach(([k, v]) => { modelos[k === antigo ? novo : k] = v; });
      return { ...p, modelos };
    });
  const removeModelo = (nome: string) =>
    setPrecos(p => { if (!p) return p; const { [nome]: _, ...resto } = p.modelos; return { ...p, modelos: resto }; });

  if (!dados) {
    return (
      <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
        {erro ? <p style={{ color: '#ef4444' }}>{erro}</p> : <><RefreshCw size={28} className="animate-spin" style={{ margin: '0 auto 12px', color: 'var(--accent-primary)' }} /><p>Carregando consumo de IA...</p></>}
      </div>
    );
  }

  const maxDia = Math.max(0.0001, ...dados.por_dia.map(d => d.recorrente.custo_brl + d.treino.custo_brl));
  const totalFuncoes = dados.por_funcao.reduce((s, f) => s + f.custo_brl, 0) || 1;
  const orc = dados.orcamento_mensal_brl;
  const pctOrc = orc > 0 ? Math.min(100, (dados.mes.custo_brl / orc) * 100) : 0;
  const pensamentoMes = dados.mes.tok_pensamento;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Cabeçalho */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h3 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-main)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Cpu size={20} color="var(--accent-primary)" /> Consumo de IA (tokens e custo)
          </h3>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
            Cada chamada ao Gemini é registrada: de onde veio, quantos tokens usou e quanto custou.
            {dados.observando_desde ? ` Observando desde ${dataBR(dados.observando_desde)}.` : ' Ainda não houve nenhuma chamada desde que o observador foi ligado.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {[7, 30, 90].map(d => (
            <button key={d} type="button" className={dias === d ? 'btn-primary' : 'btn-secondary'} onClick={() => setDias(d)} style={{ padding: '6px 12px', fontSize: '12px' }}>
              {d} dias
            </button>
          ))}
          <button type="button" className="btn-secondary" onClick={() => carregar()} disabled={carregando} style={{ padding: '6px 10px' }} title="Atualizar">
            <RefreshCw size={14} className={carregando ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '12px' }}>
        <Card titulo="Hoje" icone={<Activity size={14} />} valor={brl(dados.hoje.custo_brl)}
          sub={<>{tokens(totalTok(dados.hoje))} tokens · {dados.hoje.chamadas} chamada(s){dados.hoje.erros > 0 && <span style={{ color: '#ef4444' }}> · {dados.hoje.erros} erro(s)</span>}</>} />
        <Card titulo="Mês até agora" icone={<DollarSign size={14} />} valor={brl(dados.mes.custo_brl)}
          sub={<>
            <span style={{ color: COR_REC }}>■</span> Uso do dia a dia {brl(dados.mes_recorrente.custo_brl)}<br />
            <span style={{ color: COR_TREINO }}>■</span> Treino (gasto único) {brl(dados.mes_treino.custo_brl)}
          </>} />
        <Card titulo="Projeção do mês" icone={<TrendingUp size={14} />} valor={brl(dados.projecao_mes_brl)}
          sub={orc > 0 ? (
            <>
              <div style={{ height: '6px', borderRadius: '3px', backgroundColor: 'var(--bg-primary)', overflow: 'hidden', margin: '4px 0' }}>
                <div style={{ width: `${pctOrc}%`, height: '100%', backgroundColor: pctOrc >= 80 ? '#ef4444' : COR_REC }} />
              </div>
              {pctOrc.toFixed(0)}% do orçamento de {brl(orc)}{dados.projecao_mes_brl > orc && <span style={{ color: '#ef4444' }}> · projeção passa do orçamento</span>}
            </>
          ) : 'Treino já gasto + uso do dia a dia na média dos dias passados'} />
        <Card titulo="Uso do dia a dia" icone={<BarChart3 size={14} />} valor={`${brl(dados.projecao_recorrente_mes_brl)}/mês`}
          sub={<>média de {brl(dados.media_recorrente_dia_brl)} por dia - é o custo que fica depois que o treino acabar</>} />
      </div>

      {/* Por dia */}
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
          <strong style={{ fontSize: '14px', color: 'var(--text-main)' }}>Gasto por dia</strong>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            <span style={{ color: COR_REC }}>■</span> dia a dia &nbsp; <span style={{ color: COR_TREINO }}>■</span> treino
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: dados.por_dia.length > 40 ? '1px' : '3px', height: '140px' }}>
          {dados.por_dia.map(d => {
            const rec = d.recorrente.custo_brl, tr = d.treino.custo_brl;
            const dia = d.dia.slice(8, 10) + '/' + d.dia.slice(5, 7);
            return (
              <div key={d.dia} title={`${dia}: ${brl(rec + tr)} (dia a dia ${brl(rec)} · treino ${brl(tr)}) · ${tokens(totalTok(d.recorrente) + totalTok(d.treino))} tokens`}
                style={{ flex: '1 1 0', minWidth: '2px', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
                <div style={{ height: `${(tr / maxDia) * 100}%`, backgroundColor: COR_TREINO, borderRadius: '2px 2px 0 0' }} />
                <div style={{ height: `${(rec / maxDia) * 100}%`, backgroundColor: COR_REC, borderRadius: tr > 0 ? 0 : '2px 2px 0 0', minHeight: rec > 0 ? '2px' : 0 }} />
              </div>
            );
          })}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>
          <span>{dados.por_dia[0] && dados.por_dia[0].dia.split('-').reverse().slice(0, 2).join('/')}</span>
          <span>maior dia: {brl(maxDia)}</span>
          <span>hoje</span>
        </div>
      </div>

      {/* Onde mais gasta */}
      <div style={card}>
        <strong style={{ fontSize: '14px', color: 'var(--text-main)' }}>Onde mais gasta (últimos {dias} dias)</strong>
        {dados.por_funcao.length === 0 ? (
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhuma chamada à IA no período.</p>
        ) : (
          <div style={{ overflowX: 'auto', marginTop: '10px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Função</th><th style={th}>Grupo</th><th style={th}>Chamadas</th>
                  <th style={th}>Tokens / uso</th><th style={th}>Custo / uso</th><th style={th}>Total</th><th style={{ ...th, minWidth: '110px' }}>Parte do gasto</th>
                </tr>
              </thead>
              <tbody>
                {dados.por_funcao.map(f => {
                  const pct = (f.custo_brl / totalFuncoes) * 100;
                  const cor = f.tipo === 'treino' ? COR_TREINO : COR_REC;
                  return (
                    <tr key={f.nome + f.grupo}>
                      <td style={{ ...td, fontWeight: 600 }}>{f.nome}</td>
                      <td style={{ ...td, color: 'var(--text-muted)' }}>
                        {f.grupo}{f.tipo === 'treino' && <span style={{ marginLeft: '6px', fontSize: '10px', padding: '1px 6px', borderRadius: '8px', backgroundColor: 'rgba(245,165,36,0.15)', color: COR_TREINO }}>único</span>}
                      </td>
                      <td style={td}>{f.chamadas}{f.erros > 0 && <span style={{ color: '#ef4444' }}> ({f.erros} erro{f.erros > 1 ? 's' : ''})</span>}</td>
                      <td style={td}>{tokens(f.tokens_medio)}</td>
                      <td style={td}>{brl(f.custo_medio_brl)}</td>
                      <td style={{ ...td, fontWeight: 700 }}>{brl(f.custo_brl)}</td>
                      <td style={td}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <div style={{ flex: 1, height: '6px', borderRadius: '3px', backgroundColor: 'var(--bg-primary)', overflow: 'hidden' }}>
                            <div style={{ width: `${pct}%`, height: '100%', backgroundColor: cor }} />
                          </div>
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)', width: '34px', textAlign: 'right' }}>{pct.toFixed(0)}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {pensamentoMes > 0 && (
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '10px 0 0' }}>
            No mês, {tokens(pensamentoMes)} tokens foram de "raciocínio" da IA (cobrado como saída) - {((pensamentoMes / Math.max(1, totalTok(dados.mes))) * 100).toFixed(0)}% do total.
          </p>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '12px' }}>
        {/* Por modelo */}
        <div style={card}>
          <strong style={{ fontSize: '14px', color: 'var(--text-main)' }}>Por modelo</strong>
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '10px' }}>
            <thead><tr><th style={th}>Modelo</th><th style={th}>Chamadas</th><th style={th}>Tokens</th><th style={th}>Custo</th></tr></thead>
            <tbody>
              {dados.por_modelo.map(m => (
                <tr key={m.modelo}>
                  <td style={td}>{m.modelo}</td><td style={td}>{m.chamadas}</td><td style={td}>{tokens(totalTok(m))}</td><td style={td}>{brl(m.custo_brl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Erros */}
        <div style={card}>
          <strong style={{ fontSize: '14px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <AlertTriangle size={14} color="#ef4444" /> Últimos erros da IA
          </strong>
          {dados.ultimos_erros.length === 0 ? (
            <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhum erro registrado.</p>
          ) : (
            <div style={{ maxHeight: '220px', overflowY: 'auto', marginTop: '8px' }}>
              {dados.ultimos_erros.map((e, i) => (
                <div key={i} style={{ fontSize: '12px', padding: '6px 0', borderBottom: '1px solid var(--border-color)' }}>
                  <div style={{ color: 'var(--text-main)' }}><strong>{dataBR(e.quando)}</strong> · {e.funcao} · {e.modelo}</div>
                  <div style={{ color: /402|RESOURCE_EXHAUSTED|quota/i.test(e.erro) ? '#ef4444' : 'var(--text-muted)', wordBreak: 'break-word' }}>
                    {/402|RESOURCE_EXHAUSTED/i.test(e.erro) ? 'Crédito da IA esgotado - recarregar no Google AI Studio. ' : ''}{e.erro}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Tabela de preços */}
      <div style={card}>
        <button type="button" className="btn-secondary" onClick={abrirPrecos} style={{ fontSize: '13px' }}>
          <DollarSign size={14} /> {mostrarPrecos ? 'Fechar tabela de preços' : 'Tabela de preços, cotação e orçamento'}
        </button>
        {mostrarPrecos && precos && (
          <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
              Preço em US$ por 1 milhão de tokens (conferir em ai.google.dev/pricing). O "raciocínio" é cobrado pelo preço de saída.
              O valor exato da fatura é o do painel de Billing do Google AI Studio.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px' }}>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Cotação do dólar (R$)
                <input style={input} type="number" step="0.01" value={precos.cotacao_dolar} onChange={e => setPrecos({ ...precos, cotacao_dolar: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Orçamento mensal (R$, 0 = sem)
                <input style={input} type="number" step="1" value={precos.orcamento_mensal_brl} onChange={e => setPrecos({ ...precos, orcamento_mensal_brl: Number(e.target.value) })} />
              </label>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr><th style={th}>Modelo</th><th style={th}>Entrada (US$/1M)</th><th style={th}>Saída (US$/1M)</th><th style={th}></th></tr></thead>
                <tbody>
                  {Object.entries(precos.modelos).map(([nome, p]) => (
                    <tr key={nome}>
                      <td style={td}>
                        {nome === 'padrao' ? <span title="usado para modelos que não estão na lista">padrão (outros modelos)</span>
                          : <input style={input} defaultValue={nome} onBlur={e => renomeiaModelo(nome, e.target.value.trim())} />}
                      </td>
                      <td style={td}><input style={input} type="number" step="0.01" value={p.entrada} onChange={e => mudaModelo(nome, 'entrada', e.target.value)} /></td>
                      <td style={td}><input style={input} type="number" step="0.01" value={p.saida} onChange={e => mudaModelo(nome, 'saida', e.target.value)} /></td>
                      <td style={td}>{nome !== 'padrao' && <button type="button" className="btn-secondary" onClick={() => removeModelo(nome)} style={{ padding: '4px 8px' }}><Trash2 size={13} /></button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="button" className="btn-secondary" style={{ fontSize: '12px' }}
                onClick={() => { let n = 'novo-modelo'; let i = 2; while (precos.modelos[n]) n = `novo-modelo-${i++}`; setPrecos({ ...precos, modelos: { ...precos.modelos, [n]: { entrada: 0, saida: 0 } } }); }}>
                <Plus size={13} /> Modelo
              </button>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <input type="checkbox" checked={recalcular} onChange={e => setRecalcular(e.target.checked)} />
                aplicar também ao que já foi gasto (recalcular o histórico)
              </label>
              <button type="button" className="btn-primary" onClick={salvarPrecos} disabled={salvando} style={{ fontSize: '13px', marginLeft: 'auto' }}>
                <Save size={14} /> {salvando ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </div>
        )}
        {msgPrecos && <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '10px 0 0' }}>{msgPrecos}</p>}
      </div>
    </div>
  );
};
