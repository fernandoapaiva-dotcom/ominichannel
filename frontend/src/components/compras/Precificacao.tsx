import React, { useState } from 'react';
import { Globe, Save, Lock, ExternalLink, AlertTriangle } from 'lucide-react';
import { api, brl, pct, Concorrente, Entrada, ItemNota, Parcela } from './comprasApi';
import { Aviso, Botao, Chip, card, input } from './ui';
import { ParcelasEditor } from './ParcelasEditor';
import { CadastroProdutoModal } from './CadastroProdutoModal';
import { FotoProduto, useFotosProdutos } from './FotoProduto';

interface Props {
  entrada: Entrada;
  onAtualizada: () => void;
}

const CORES_COMPOSICAO: Record<string, [string, string]> = {
  custo_mercadoria: ['Custo da mercadoria', '#64748b'],
  impostos_venda: ['Impostos na venda', '#ef4444'],
  custo_fixo: ['Custo fixo da loja', '#f59e0b'],
  despesas_variaveis: ['Despesas variáveis', '#a855f7'],
  lucro: ['Lucro', '#22c55e'],
};

// Mesmo markup divisor do backend (compras_custo_service) - só para prévia ao digitar
function deducoesSemMargem(it: ItemNota) {
  return (it.impostos_saida_pct || 0) + ((it as any).custo_fixo_pct || 0) + ((it as any).despesas_variaveis_pct || 0);
}
function precoPorMargem(it: ItemNota, margem: number) {
  const d = deducoesSemMargem(it) + margem;
  const custo = it.custo_unitario_real || 0;
  return d < 95 && custo > 0 ? Math.round((custo / (1 - d / 100)) * 100) / 100 : 0;
}
function margemPorPreco(it: ItemNota, preco: number) {
  const custo = it.custo_unitario_real || 0;
  return preco > 0 ? (1 - custo / preco) * 100 - deducoesSemMargem(it) : 0;
}

const BarraComposicao: React.FC<{ comp: Record<string, number>; preco: number }> = ({ comp, preco }) => (
  <div>
    <div style={{ display: 'flex', height: '10px', borderRadius: '5px', overflow: 'hidden', background: 'var(--bg-primary)' }}>
      {Object.entries(CORES_COMPOSICAO).map(([k, [rotulo, cor]]) => {
        const v = Math.max(comp[k] || 0, 0);
        return <div key={k} title={`${rotulo}: ${brl(comp[k])}`} style={{ width: `${(v / preco) * 100}%`, background: cor }} />;
      })}
    </div>
    <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '4px', fontSize: '11px', color: 'var(--text-muted)' }}>
      {Object.entries(CORES_COMPOSICAO).map(([k, [rotulo, cor]]) => (
        <span key={k}><span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '2px', background: cor, marginRight: '3px' }} />{rotulo} {brl(comp[k])}</span>
      ))}
    </div>
  </div>
);

export const Precificacao: React.FC<Props> = ({ entrada, onAtualizada }) => {
  const [itens, setItens] = useState<ItemNota[]>(entrada.itens);
  const [parcelas, setParcelas] = useState<Parcela[]>(entrada.parcelas);
  const [parcelasCte, setParcelasCte] = useState<Parcela[]>(entrada.parcelas_cte);
  const [salvando, setSalvando] = useState(false);
  const [pesquisando, setPesquisando] = useState<number | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: 'ok' | 'erro' | 'alerta'; texto: string } | null>(null);
  const [cadastroItem, setCadastroItem] = useState<ItemNota | null>(null);
  const [versaoFotos, setVersaoFotos] = useState(0);
  const fotos = useFotosProdutos(entrada.empresa, entrada.itens.map((i) => i.softsystem_prod_codigo), versaoFotos);
  const somenteLeitura = !['contada', 'aguardando_contagem', 'contagem_divergente'].includes(entrada.status);
  // depois do lançamento o preço de venda ainda pode ser ajustado - vai direto para o Softsystem
  const lancada = entrada.status === 'enviada_softsystem'
    || (entrada.status === 'fechada' && entrada.softsystem_modo === 'teste' && (entrada.eventos || []).some((ev) => ev.acao === 'lancamento_teste'));
  const precoEditavel = !somenteLeitura || lancada;
  const [atualizandoPreco, setAtualizandoPreco] = useState(false);
  const atualizarPrecoSoftsystem = async () => {
    setAtualizandoPreco(true);
    try {
      const r = await api<any>(`/entradas/${entrada.id}/preco-softsystem`, {
        method: 'PUT', body: { itens: itens.map((i) => ({ item_id: i.id, preco_venda_final: i.preco_venda_final, margem_lucro_pct: i.margem_lucro_pct })) },
      });
      setMensagem({ tipo: 'ok', texto: r.mensagem });
      onAtualizada();
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    } finally {
      setAtualizandoPreco(false);
    }
  };

  const atualizarItem = (id: number, mud: Partial<ItemNota>) => setItens(itens.map((i) => (i.id === id ? { ...i, ...mud } : i)));

  const salvar = async (): Promise<boolean> => {
    setSalvando(true);
    try {
      const r = await api<{ calculo: { itens: ItemNota[] } }>(`/entradas/${entrada.id}/precificacao`, {
        method: 'PUT',
        body: {
          itens: itens.map((i) => ({
            item_id: i.id, margem_lucro_pct: i.margem_lucro_pct, preco_venda_final: i.preco_venda_final,
            preco_mercado_min: i.preco_mercado_min, preco_mercado_med: i.preco_mercado_med, preco_mercado_max: i.preco_mercado_max,
            preco_mercado_resumo: i.preco_mercado_resumo, concorrentes: i.concorrentes,
          })),
          parcelas, parcelas_cte: parcelasCte,
        },
      });
      setItens(itens.map((i) => {
        const c = r.calculo.itens.find((x: any) => x.item_id === i.id);
        return c ? { ...i, ...c, id: i.id } : i;
      }));
      return true;
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
      return false;
    } finally {
      setSalvando(false);
    }
  };

  const pesquisarMercado = async (it: ItemNota) => {
    setPesquisando(it.id!);
    try {
      const r = await api<{ benchmark: { min: number; med: number; max: number; concorrentes: Concorrente[]; resumo: string } }>('/buscar-preco-mercado', {
        body: { descricao: it.softsystem_descricao || it.descricao_fornecedor, ean: it.ean, ncm: it.ncm },
      });
      const b = r.benchmark;
      atualizarItem(it.id!, {
        preco_mercado_min: b.min, preco_mercado_med: b.med, preco_mercado_max: b.max,
        preco_mercado_resumo: b.resumo, concorrentes: b.concorrentes,
      });
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    } finally {
      setPesquisando(null);
    }
  };

  const fechar = async () => {
    if (!(await salvar())) return;
    if (!confirm('Fechar a entrada? Depois disso preços e vencimentos ficam travados.')) return;
    try {
      const r = await api<any>(`/entradas/${entrada.id}/fechar`, { method: 'POST' });
      const lanc = r.lancamento;
      const txtLanc = lanc ? ` ${lanc.mensagem}` : '';
      setMensagem({
        tipo: lanc && !lanc.lancado && lanc.modo !== 'desligado' ? 'erro' : 'ok',
        texto: `Entrada fechada.${txtLanc}${r.clientes_notificados ? ` ${r.clientes_notificados} cliente(s) do balcão avisados no WhatsApp.` : ''}`,
      });
      onAtualizada();
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  const totalVenda = itens.reduce((a, i) => a + (i.preco_venda_final || 0) * (i.qtd_contada ?? i.quantidade), 0);
  const totalLucro = itens.reduce((a, i) => a + ((i.composicao_preco?.lucro || 0) * (i.qtd_contada ?? i.quantidade)), 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {mensagem && <Aviso tipo={mensagem.tipo} onFechar={() => setMensagem(null)}>{mensagem.texto}</Aviso>}
      {entrada.status !== 'contada' && !somenteLeitura && (
        <Aviso tipo="info">Você pode ir ajustando os preços já, mas a entrada só fecha depois da contagem física.</Aviso>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px' }}>
        <div style={{ ...card, padding: '12px' }}><div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Venda prevista do lote</div><div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-main)' }}>{brl(totalVenda)}</div></div>
        <div style={{ ...card, padding: '12px' }}><div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Lucro previsto</div><div style={{ fontSize: '18px', fontWeight: 700, color: '#22c55e' }}>{brl(totalLucro)}</div></div>
        <div style={{ ...card, padding: '12px' }}><div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Custo do lote</div><div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-main)' }}>{brl(itens.reduce((a, i) => a + (i.custo_unitario_real || 0) * (i.qtd_contada ?? i.quantidade), 0))}</div></div>
      </div>

      {itens.map((it) => {
        const preco = it.preco_venda_final || 0;
        const margemReal = margemPorPreco(it, preco);
        const minima = (it as any).margem_minima_pct ?? 10;
        return (
          <div key={it.id} style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
              <FotoProduto foto={it.softsystem_prod_codigo ? fotos[String(it.softsystem_prod_codigo)] : undefined}
                codproduto={it.softsystem_prod_codigo} descricao={it.softsystem_descricao || it.descricao_fornecedor} onTrocada={() => setVersaoFotos((v) => v + 1)} />
              <div>
                <div style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                  {it.softsystem_descricao || it.descricao_fornecedor}
                  {!it.softsystem_prod_codigo && (() => {
                    const cad = (it as any).cadastro_novo;
                    return (
                      <>
                        {' '}<Chip cor={cad?.confirmado ? '#22c55e' : '#ef4444'}>{cad?.confirmado ? 'produto novo · cadastro confirmado' : 'produto novo · falta confirmar o cadastro'}</Chip>
                        {!['enviada_softsystem', 'cancelada'].includes(entrada.status) && (
                          <Botao variante={cad?.confirmado ? 'fantasma' : 'primario'} style={{ padding: '3px 10px', fontSize: '12px', marginLeft: '6px' }}
                            onClick={() => setCadastroItem(it)}>
                            Cadastro do produto novo
                          </Botao>
                        )}
                      </>
                    );
                  })()}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {it.softsystem_prod_codigo && `#${it.softsystem_prod_codigo} · `}NCM {it.ncm} · {it.qtd_contada ?? it.quantidade} {it.unidade}
                  {it.tem_st && ' · com ST'} · preço atual no Softsystem {brl(it.softsystem_preco_venda)}
                </div>
              </div>
              </div>
              <div style={{ textAlign: 'right', fontSize: '12px', color: 'var(--text-muted)' }}>
                Custo real <strong style={{ color: 'var(--text-main)', fontSize: '15px' }}>{brl(it.custo_unitario_real)}</strong>
                <div>impostos na venda {pct(it.impostos_saida_pct)} · fixo {pct((it as any).custo_fixo_pct)} · variáveis {pct((it as any).despesas_variaveis_pct)}</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Margem de lucro (%)
                <input type="number" step="0.5" disabled={!precoEditavel} style={{ ...input, width: '110px', display: 'block', marginTop: '4px' }}
                  value={it.margem_lucro_pct ?? ''}
                  onChange={(e) => {
                    const m = parseFloat(e.target.value) || 0;
                    atualizarItem(it.id!, { margem_lucro_pct: m, preco_venda_final: precoPorMargem(it, m) });
                  }} />
              </label>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Preço de venda (R$)
                <input type="number" step="0.01" disabled={!precoEditavel} style={{ ...input, width: '130px', display: 'block', marginTop: '4px', fontWeight: 700 }}
                  value={preco || ''}
                  onChange={(e) => atualizarItem(it.id!, { preco_venda_final: parseFloat(e.target.value) || 0 })} />
              </label>
              <div style={{ fontSize: '12px', color: margemReal < minima ? '#f87171' : 'var(--text-muted)', paddingBottom: '8px' }}>
                Margem real {pct(margemReal)} · markup {it.custo_unitario_real ? (preco / it.custo_unitario_real).toFixed(2) : '—'}x
              </div>
              {precoEditavel && (
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', paddingBottom: '4px' }}>
                  {(it.opcoes_margem || []).map((o) => (
                    <button key={o.rotulo} onClick={() => atualizarItem(it.id!, { preco_venda_final: o.preco, margem_lucro_pct: Math.round(o.margem_pct * 10) / 10 })}
                      title={o.abaixo_da_minima ? 'Abaixo da margem mínima da loja' : ''}
                      style={{
                        ...input, width: 'auto', cursor: 'pointer', fontSize: '12px', padding: '5px 9px',
                        borderColor: o.abaixo_da_minima ? '#f59e0b' : 'var(--border-color)',
                      }}>
                      {o.rotulo}: <strong>{brl(o.preco)}</strong> ({pct(o.margem_pct)})
                    </button>
                  ))}
                </div>
              )}
            </div>

            {it.composicao_preco && preco > 0 && <BarraComposicao comp={it.composicao_preco} preco={preco} />}

            {(it.alertas || []).map((a, i) => (
              <div key={i} style={{ fontSize: '12px', color: '#f59e0b', display: 'flex', gap: '4px', alignItems: 'center' }}><AlertTriangle size={12} />{a}</div>
            ))}

            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {it.concorrentes?.length
                    ? <>Mercado: mín {brl(it.preco_mercado_min)} · mediana <strong>{brl(it.preco_mercado_med)}</strong> · máx {brl(it.preco_mercado_max)}</>
                    : it.preco_mercado_resumo || 'Concorrentes ainda não pesquisados.'}
                </span>
                {!somenteLeitura && (
                  <Botao variante="secundario" icone={<Globe size={13} />} onClick={() => pesquisarMercado(it)} disabled={pesquisando === it.id} style={{ fontSize: '12px', padding: '5px 10px' }}>
                    {pesquisando === it.id ? 'Pesquisando no Google...' : 'Ver concorrentes'}
                  </Botao>
                )}
              </div>
              {!!it.concorrentes?.length && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '6px' }}>
                  {it.concorrentes.map((c, i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-main)' }}>
                      <span>
                        {c.url ? <a href={c.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-primary)' }}>{c.loja} <ExternalLink size={10} /></a> : c.loja}
                        {c.observacao && <span style={{ color: 'var(--text-muted)' }}> · {c.observacao}</span>}
                      </span>
                      <span>
                        <strong>{brl(c.preco)}</strong>
                        {preco > 0 && <span style={{ color: c.preco < preco ? '#f87171' : '#22c55e', marginLeft: '6px' }}>{c.preco < preco ? 'mais barato' : 'mais caro'}</span>}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '14px' }}>
        <div style={card}>
          <ParcelasEditor titulo="Vencimentos do fornecedor" parcelas={parcelas} valorEsperado={entrada.valor_total_nota}
            dataBase={entrada.data_emissao?.slice(0, 10)} onChange={setParcelas} somenteLeitura={somenteLeitura} />
        </div>
        {(entrada.valor_frete_cte || 0) > 0 && (
          <div style={card}>
            <ParcelasEditor titulo="Vencimento do frete (transportadora)" parcelas={parcelasCte} valorEsperado={entrada.valor_frete_cte || 0}
              dataBase={entrada.data_emissao?.slice(0, 10)} onChange={setParcelasCte} somenteLeitura={somenteLeitura} />
          </div>
        )}
      </div>

      {!somenteLeitura && (
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <Botao variante="secundario" icone={<Save size={14} />} disabled={salvando}
            onClick={async () => { if (await salvar()) setMensagem({ tipo: 'ok', texto: 'Precificação salva.' }); }}>
            Salvar
          </Botao>
          <Botao icone={<Lock size={14} />} onClick={fechar} disabled={salvando || entrada.status !== 'contada'}
            title={entrada.status !== 'contada' ? 'Conclua a contagem física primeiro' : ''}>
            Fechar entrada
          </Botao>
        </div>
      )}
      {lancada && (
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>Nota já lançada: o preço novo vai direto para o cadastro do produto no Softsystem.</span>
          <Botao icone={<Save size={14} />} onClick={atualizarPrecoSoftsystem} disabled={atualizandoPreco}>
            {atualizandoPreco ? 'Gravando no Softsystem...' : 'Atualizar preço no Softsystem'}
          </Botao>
        </div>
      )}
      {cadastroItem && (
        <CadastroProdutoModal entradaId={entrada.id} empresa={entrada.empresa} item={cadastroItem as any}
          onFechar={() => setCadastroItem(null)} onSalvo={onAtualizada} />
      )}
    </div>
  );
};
