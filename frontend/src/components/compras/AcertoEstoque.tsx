import React, { useEffect, useRef, useState } from 'react';
import { Search, Trash2, Save, MapPin, History, Loader2 } from 'lucide-react';
import { api, brl, dataBR, Empresa, NOME_LOJA } from './comprasApi';
import { Aviso, Botao, Campo, card, input, td, th } from './ui';

/**
 * Acerto de estoque (inventário) - pedido do usuário em 15/10/2026: o estoque do Softsystem não
 * bate com o físico (ex.: eletrodo 913 com 105 no sistema e 32 na prateleira). Busca/bipa o
 * produto, digita a quantidade que tem de verdade e grava no Softsystem um Ajuste de Estoque
 * (entrada da sobra / saída da falta) igual ao da tela dele - backend: compras.py /estoque/acerto.
 * A diferença é recalculada no servidor contra o estoque do momento (não contra o número da tela).
 */

interface ProdutoBusca {
  codigo: number; cod_original: string; cod_barras: string; descricao: string; unidade: string;
  estoque: number; preco_venda: number; custo_medio: number; localizacao?: string | null;
}
interface Linha extends ProdutoBusca { fisica: string }
interface Acerto {
  codajuste: number; data: string | null; operador: string; pecas_entrada: number; pecas_saida: number;
  valor_entrada: number; valor_saida: number; obs: string; fechado: boolean;
}

const num = (s: string) => (s.trim() === '' ? NaN : Number(s.replace(',', '.')));
const fmt = (v: number) => v.toLocaleString('pt-BR', { maximumFractionDigits: 3 });

export const AcertoEstoque: React.FC<{ empresa: Empresa; isAdmin: boolean }> = ({ empresa, isAdmin }) => {
  const [termo, setTermo] = useState('');
  const [resultados, setResultados] = useState<ProdutoBusca[]>([]);
  const [buscando, setBuscando] = useState(false);
  const [linhas, setLinhas] = useState<Linha[]>([]);
  const [motivo, setMotivo] = useState('');
  const [gravando, setGravando] = useState(false);
  const [msg, setMsg] = useState<{ tipo: 'ok' | 'erro' | 'alerta'; texto: string } | null>(null);
  const [acertos, setAcertos] = useState<Acerto[]>([]);
  const [modo, setModo] = useState<string>('');
  const buscaRef = useRef<HTMLInputElement>(null);

  const carregarHistorico = async () => {
    try {
      const r = await api<{ acertos: Acerto[]; modo: string }>(`/estoque/acertos?empresa=${empresa}`);
      setAcertos(r.acertos);
      setModo(r.modo);
    } catch { /* histórico é secundário */ }
  };

  useEffect(() => { setLinhas([]); setResultados([]); setMsg(null); carregarHistorico(); /* eslint-disable-next-line */ }, [empresa]);

  const adicionar = async (p: ProdutoBusca) => {
    setResultados([]);
    setTermo('');
    if (linhas.some((l) => l.codigo === p.codigo)) { buscaRef.current?.focus(); return; }
    let completo = p;
    try {
      const r = await api<{ produto: ProdutoBusca }>(`/estoque/produto/${p.codigo}?empresa=${empresa}`);
      completo = r.produto;
    } catch { /* usa o da busca */ }
    setLinhas((ls) => [...ls, { ...completo, fisica: '' }]);
    buscaRef.current?.focus();
  };

  const buscar = async () => {
    const t = termo.trim();
    if (!t) return;
    setBuscando(true);
    setMsg(null);
    try {
      const r = await api<{ produtos: ProdutoBusca[] }>(`/softsystem/buscar-produto?empresa=${empresa}&termo=${encodeURIComponent(t)}&limite=15`);
      // código de barras / código exato bipado: entra direto na lista
      if (r.produtos.length === 1) adicionar(r.produtos[0]);
      else setResultados(r.produtos);
      if (!r.produtos.length) setMsg({ tipo: 'alerta', texto: `Nenhum produto encontrado para "${t}".` });
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    } finally {
      setBuscando(false);
    }
  };

  const validas = linhas.filter((l) => !Number.isNaN(num(l.fisica)) && num(l.fisica) >= 0);
  const comDiferenca = validas.filter((l) => Math.abs(num(l.fisica) - l.estoque) > 0.0001);
  const valorSaida = comDiferenca.reduce((a, l) => a + Math.max(0, l.estoque - num(l.fisica)) * (l.custo_medio || 0), 0);
  const valorEntrada = comDiferenca.reduce((a, l) => a + Math.max(0, num(l.fisica) - l.estoque) * (l.custo_medio || 0), 0);

  const gravar = async () => {
    if (!comDiferenca.length) { setMsg({ tipo: 'alerta', texto: 'Nenhum produto com diferença entre o físico e o sistema.' }); return; }
    if (motivo.trim().length < 3) { setMsg({ tipo: 'alerta', texto: 'Informe o motivo do acerto (fica gravado no Softsystem).' }); return; }
    const resumo = comDiferenca.map((l) => `#${l.codigo}: ${fmt(l.estoque)} → ${fmt(num(l.fisica))}`).join('\n');
    if (!confirm(`${modo === 'teste' ? '[TESTE - cópia] ' : ''}Gravar o acerto de estoque no Softsystem (${NOME_LOJA[empresa]})?\n\n${resumo}\n\nSaída: ${brl(valorSaida)} · Entrada: ${brl(valorEntrada)}`)) return;
    setGravando(true);
    setMsg(null);
    try {
      const r = await api<any>('/estoque/acerto', {
        body: { empresa, motivo: motivo.trim(), itens: validas.map((l) => ({ codproduto: l.codigo, quantidade_fisica: num(l.fisica) })) },
      });
      setMsg({ tipo: 'ok', texto: r.mensagem });
      setLinhas([]);
      setMotivo('');
      carregarHistorico();
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    } finally {
      setGravando(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div>
          <div style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-main)' }}>Acerto de estoque · {NOME_LOJA[empresa]}</div>
          <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
            Bipe ou busque o produto, conte o que tem na prateleira e digite a quantidade física. O sistema grava no Softsystem um
            Ajuste de Estoque com a diferença (saída do que falta, entrada do que sobra), com o seu nome e o motivo.
          </div>
        </div>
        {modo === 'teste' && <Aviso tipo="info">Modo TESTE: os acertos vão para a cópia do Softsystem, não para o de verdade.</Aviso>}
        {modo === 'desligado' && <Aviso tipo="alerta">A gravação no Softsystem ainda não foi liberada neste servidor.</Aviso>}
        {!isAdmin && <Aviso tipo="alerta">Somente administradores gravam acertos de estoque. Você pode montar a lista para conferência.</Aviso>}

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: '1 1 320px' }}>
            <Search size={15} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              ref={buscaRef}
              value={termo}
              onChange={(e) => setTermo(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') buscar(); }}
              placeholder="Código de barras, código, código original ou descrição - Enter para buscar"
              style={{ ...input, width: '100%', paddingLeft: '32px' }}
              autoFocus
            />
          </div>
          <Botao icone={buscando ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} onClick={buscar} disabled={buscando}>Buscar</Botao>
        </div>

        {resultados.length > 0 && (
          <div style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
            {resultados.map((p) => (
              <button key={p.codigo} onClick={() => adicionar(p)}
                style={{ display: 'flex', width: '100%', justifyContent: 'space-between', gap: '10px', padding: '9px 12px', background: 'transparent', border: 'none', borderBottom: '1px solid var(--border-color)', cursor: 'pointer', textAlign: 'left', color: 'var(--text-main)', fontSize: '13px' }}>
                <span><strong>#{p.codigo}</strong> {p.descricao} <span style={{ color: 'var(--text-muted)' }}>({p.cod_original})</span></span>
                <span style={{ color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>sistema: {fmt(p.estoque)} {p.unidade}</span>
              </button>
            ))}
          </div>
        )}

        {msg && <Aviso tipo={msg.tipo === 'ok' ? 'ok' : msg.tipo === 'erro' ? 'erro' : 'alerta'} onFechar={() => setMsg(null)}>{msg.texto}</Aviso>}

        {linhas.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Produto</th><th style={th}>Localização</th><th style={{ ...th, textAlign: 'right' }}>No sistema</th>
                  <th style={{ ...th, textAlign: 'right' }}>Físico (contado)</th><th style={{ ...th, textAlign: 'right' }}>Diferença</th>
                  <th style={{ ...th, textAlign: 'right' }}>Valor (custo)</th><th style={th}></th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((l, i) => {
                  const f = num(l.fisica);
                  const dif = Number.isNaN(f) ? null : f - l.estoque;
                  const cor = dif === null || Math.abs(dif) < 0.0001 ? 'var(--text-muted)' : dif < 0 ? '#f87171' : '#22c55e';
                  return (
                    <tr key={l.codigo}>
                      <td style={td}>
                        <div style={{ fontWeight: 600 }}>#{l.codigo} {l.descricao}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{l.cod_original}{l.cod_barras ? ` · EAN ${l.cod_barras}` : ''}</div>
                      </td>
                      <td style={{ ...td, whiteSpace: 'nowrap', color: l.localizacao ? '#38bdf8' : 'var(--text-muted)' }}>
                        <MapPin size={12} style={{ verticalAlign: '-2px' }} /> {l.localizacao || '—'}
                      </td>
                      <td style={{ ...td, textAlign: 'right', whiteSpace: 'nowrap' }}>{fmt(l.estoque)} {l.unidade}</td>
                      <td style={{ ...td, textAlign: 'right' }}>
                        <input value={l.fisica} inputMode="decimal" placeholder="0"
                          onChange={(e) => setLinhas((ls) => ls.map((x, j) => (j === i ? { ...x, fisica: e.target.value } : x)))}
                          style={{ ...input, width: '110px', textAlign: 'right', fontSize: '16px', fontWeight: 700 }} />
                      </td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 800, color: cor, whiteSpace: 'nowrap' }}>
                        {dif === null ? '—' : `${dif > 0 ? '+' : ''}${fmt(dif)}`}
                      </td>
                      <td style={{ ...td, textAlign: 'right', color: cor, whiteSpace: 'nowrap' }}>
                        {dif === null ? '—' : brl(Math.abs(dif) * (l.custo_medio || 0))}
                      </td>
                      <td style={td}>
                        <Botao variante="fantasma" icone={<Trash2 size={13} />} onClick={() => setLinhas((ls) => ls.filter((_, j) => j !== i))} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {linhas.length > 0 && (
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <Campo rotulo="Motivo do acerto (obrigatório)" style={{ flex: '1 1 320px' }}>
              <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ex.: inventário da prateleira P.S D 03 / mercadoria repassada sem nota"
                style={{ ...input, width: '100%' }} />
            </Campo>
            <div style={{ fontSize: '12.5px', color: 'var(--text-muted)', paddingBottom: '8px' }}>
              {comDiferenca.length} produto(s) com diferença · saída <strong style={{ color: '#f87171' }}>{brl(valorSaida)}</strong> · entrada <strong style={{ color: '#22c55e' }}>{brl(valorEntrada)}</strong>
            </div>
            <Botao icone={gravando ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} onClick={gravar}
              disabled={gravando || !isAdmin || modo === 'desligado' || !comDiferenca.length}>
              {gravando ? 'Gravando no Softsystem...' : modo === 'teste' ? 'Gravar na cópia de teste' : 'Gravar acerto no Softsystem'}
            </Botao>
          </div>
        )}
      </div>

      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 700, color: 'var(--text-main)', marginBottom: '10px' }}>
          <History size={15} /> Últimos ajustes de estoque no Softsystem {modo === 'teste' ? '(produção)' : ''}
        </div>
        {acertos.length === 0 ? (
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhum ajuste encontrado.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr><th style={th}>Nº</th><th style={th}>Data</th><th style={th}>Operador</th><th style={{ ...th, textAlign: 'right' }}>Entrada</th><th style={{ ...th, textAlign: 'right' }}>Saída</th><th style={th}>Obs.</th></tr>
              </thead>
              <tbody>
                {acertos.map((a) => (
                  <tr key={a.codajuste}>
                    <td style={{ ...td, fontWeight: 700 }}>{a.codajuste}{!a.fechado && <span style={{ color: '#f59e0b', fontSize: '11px' }}> (aberto)</span>}</td>
                    <td style={td}>{dataBR(a.data)}</td>
                    <td style={td}>{a.operador}</td>
                    <td style={{ ...td, textAlign: 'right', color: '#22c55e' }}>{a.pecas_entrada ? `${fmt(a.pecas_entrada)} pç · ${brl(a.valor_entrada)}` : '—'}</td>
                    <td style={{ ...td, textAlign: 'right', color: '#f87171' }}>{a.pecas_saida ? `${fmt(a.pecas_saida)} pç · ${brl(a.valor_saida)}` : '—'}</td>
                    <td style={{ ...td, fontSize: '12px', color: 'var(--text-muted)' }}>{a.obs || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
