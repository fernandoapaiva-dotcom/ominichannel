import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Key, Truck, Search, Upload, Link2, AlertTriangle, CheckCircle, ShieldCheck, Plus, Trash2, Copy, ClipboardList, Loader2 } from 'lucide-react';
import {
  api, brl, dataBR, formatarChave, Calculo, Cte, DespesaExtra, Empresa, ItemNota, NOME_LOJA, Parcela, ResultadoBusca, SoftsystemProduto,
} from './comprasApi';
import { Aviso, Botao, Campo, Chip, card, input, td, th } from './ui';
import { ProdutoVinculoModal } from './ProdutoVinculoModal';
import { ParcelasEditor } from './ParcelasEditor';
import { FotoProduto, useFotosProdutos } from './FotoProduto';

interface Props {
  empresaPadrao: Empresa;
  onSalva: (entradaId: number) => void;
  onAbrirExistente: (entradaId: number) => void;
}

const somarDias = (iso: string, dias: number) => {
  const d = new Date(`${(iso || new Date().toISOString()).slice(0, 10)}T12:00:00`);
  d.setDate(d.getDate() + dias);
  return d.toISOString().slice(0, 10);
};

export const NovaEntrada: React.FC<Props> = ({ empresaPadrao, onSalva, onAbrirExistente }) => {
  // Chave guardada no navegador até a entrada ser salva (pedido do usuário em 14/10/2026): recarregar
  // ou fechar a página sem querer não obriga a digitar/bipar os 44 dígitos de novo.
  const CHAVE_SALVA = 'compras_nova_entrada_chave';
  const [chaveNfe, setChaveNfeState] = useState<string>(() => {
    try { return localStorage.getItem(CHAVE_SALVA) || ''; } catch { return ''; }
  });
  const setChaveNfe = (v: string) => {
    setChaveNfeState(v);
    try { if (v) localStorage.setItem(CHAVE_SALVA, v); else localStorage.removeItem(CHAVE_SALVA); } catch { /* sem storage: só não guarda */ }
  };
  const [temCte, setTemCte] = useState(false);
  const [chaveCte, setChaveCte] = useState('');
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<ResultadoBusca | null>(null);
  const [manifestando, setManifestando] = useState(false);
  const [msgManifestacao, setMsgManifestacao] = useState<string | null>(null);

  const [empresa, setEmpresa] = useState<Empresa>(empresaPadrao);
  const [itens, setItens] = useState<ItemNota[]>([]);
  const [resumo, setResumo] = useState<Record<string, number>>({});
  const [cte, setCte] = useState<Cte | null>(null);
  const [parcelas, setParcelas] = useState<Parcela[]>([]);
  const [parcelasCte, setParcelasCte] = useState<Parcela[]>([]);
  const [despesas, setDespesas] = useState<DespesaExtra[]>([]);
  const [novaDesp, setNovaDesp] = useState({ descricao: '', valor: '' });
  const [tipoRateio, setTipoRateio] = useState<'valor' | 'quantidade'>('valor');
  const [vinculoIdx, setVinculoIdx] = useState<number | null>(null);
  const [salvando, setSalvando] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  const nota = resultado?.nota;
  const chaveLimpa = chaveNfe.replace(/\D/g, '');

  const aplicarResultado = (r: ResultadoBusca) => {
    setResultado(r);
    if (r.status !== 'ok' || !r.nota || !r.calculo) return;
    setEmpresa((r.empresa || r.nota.empresa_destino) as Empresa);
    setItens(r.calculo.itens);
    setResumo(r.calculo.resumo);
    setParcelas(r.parcelas || []);
    const c = r.cte || null;
    setCte(c);
    setParcelasCte(r.parcelas_cte?.length ? r.parcelas_cte : c?.carregado && c.frete_da_loja && c.valor_frete_total
      ? [{ numero: '001', vencimento: somarDias(r.nota.data_emissao, 30), valor: c.valor_frete_total, origem: 'condicao' }]
      : []);
  };

  const buscar = async (silencioso = false) => {
    if (!silencioso) {
      setErro(null);
      setMsgManifestacao(null);
      setBuscando(true);
    }
    try {
      const r = await api<ResultadoBusca>('/nota/buscar', {
        body: { chave_nfe: chaveLimpa, chave_cte: temCte ? chaveCte.replace(/\D/g, '') : null, empresa: empresaPadrao },
      });
      aplicarResultado(r);
    } catch (e: any) {
      if (!silencioso) setErro(e.message);
    } finally {
      if (!silencioso) setBuscando(false);
    }
  };

  // Ciência registrada automaticamente e a SEFAZ ainda liberando o XML (pedido do usuário em
  // 14/10/2026: "preciso que seja imediato"): o backend continua tentando sozinho; a tela só pergunta
  // de novo de tempos em tempos (sem gastar consulta na SEFAZ) e abre a nota assim que ela chegar.
  const buscarRef = useRef(buscar);
  buscarRef.current = buscar;
  const aguardando = resultado?.status === 'aguardando_xml';
  useEffect(() => {
    if (!aguardando) return;
    const t = window.setInterval(() => buscarRef.current(true), 6000);
    return () => window.clearInterval(t);
  }, [aguardando, chaveLimpa]);

  const importarXml = async (file: File) => {
    setErro(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const r = await api<any>('/parse-xml', { form });
      if (r.tipo === 'CTE') {
        if (!nota) {
          setErro('Esse arquivo é um CT-e. Importe primeiro a NF-e e depois o CT-e da transportadora.');
          return;
        }
        const c: Cte = { ...r.cte, carregado: true, frete_da_loja: r.cte.empresa_tomadora === empresa };
        setCte(c);
        setParcelasCte(!c.frete_da_loja ? [] : r.parcelas_cte?.length ? r.parcelas_cte
          : [{ numero: '001', vencimento: somarDias(nota.data_emissao, 30), valor: c.valor_frete_total || 0, origem: 'condicao' }]);
        await recalcular({ cteNovo: c });
      } else {
        aplicarResultado(r);
        setChaveNfe(r.nota.chave_acesso);
      }
    } catch (e: any) {
      setErro(e.message);
    }
  };

  // ciencia: até 10 dias da emissão; confirmacao: depois disso (a SEFAZ recusa a Ciência com 596) -
  // declara oficialmente que a mercadoria foi recebida, o que é o caso de quem está dando a entrada
  const manifestar = async (tipo: 'ciencia' | 'confirmacao' = 'ciencia') => {
    if (!resultado?.empresa) return;
    const pergunta = tipo === 'confirmacao'
      ? 'Registrar a CONFIRMAÇÃO DA OPERAÇÃO na SEFAZ em nome da loja?\n\nÉ o evento oficial que diz que a mercadoria desta nota foi RECEBIDA. Só confirme se ela chegou.'
      : 'Registrar a Ciência da Operação na SEFAZ em nome da loja? (evento oficial: não aceita nem recusa a nota, só libera o XML)';
    if (!confirm(pergunta)) return;
    setManifestando(true);
    setErro(null);
    try {
      const r = await api<any>('/nota/manifestar-ciencia', { body: { chave: chaveLimpa, empresa: resultado.empresa, tipo } });
      setMsgManifestacao(r.mensagem);
      buscar();
    } catch (e: any) {
      if (tipo === 'ciencia' && /10 dias/.test(e.message)) {
        setResultado({ ...resultado, status: 'precisa_confirmacao', mensagem: e.message });
      } else {
        setErro(e.message);
      }
    } finally {
      setManifestando(false);
    }
  };

  const recalcular = async (o: { itensNovos?: ItemNota[]; cteNovo?: Cte | null; despesasNovas?: DespesaExtra[]; rateio?: 'valor' | 'quantidade' } = {}) => {
    if (!nota) return;
    const c = o.cteNovo !== undefined ? o.cteNovo : cte;
    try {
      const r = await api<Calculo>('/calcular', {
        body: {
          empresa,
          itens: o.itensNovos || itens,
          totais: nota.totais,
          frete_cte: c?.frete_da_loja ? c.valor_frete_total || 0 : 0,
          icms_cte: c?.frete_da_loja ? c.icms?.v_icms || 0 : 0,
          despesas_extras: o.despesasNovas || despesas,
          tipo_rateio: o.rateio || tipoRateio,
        },
      });
      setItens(r.itens);
      setResumo(r.resumo);
    } catch (e: any) {
      setErro(e.message);
    }
  };

  const escolherProduto = (p: SoftsystemProduto, modo: 'vincular' | 'modelo') => {
    if (vinculoIdx === null) return;
    const novos = itens.map((it, i) => {
      if (i !== vinculoIdx) return it;
      if (modo === 'vincular') {
        return {
          ...it, softsystem_status: 'vinculado' as const, vinculo_metodo: 'manual', produto_modelo_codigo: null, produto_modelo_descricao: null,
          softsystem_prod_codigo: String(p.codigo), softsystem_descricao: p.descricao, softsystem_grupo: p.grupo,
          softsystem_subgrupo: p.subgrupo, softsystem_unidade: p.unidade, softsystem_estoque: p.estoque,
          softsystem_preco_venda: p.preco_venda, softsystem_custo_medio: p.custo_medio, softsystem_ncm: p.ncm,
          alerta_ncm_diferente: !!(p.ncm && it.ncm && p.ncm !== it.ncm),
        };
      }
      return {
        ...it, softsystem_status: 'novo' as const, vinculo_metodo: 'similar', softsystem_prod_codigo: null,
        softsystem_descricao: null, produto_modelo_codigo: String(p.codigo), produto_modelo_descricao: p.descricao,
        softsystem_grupo: p.grupo, softsystem_subgrupo: p.subgrupo, softsystem_preco_venda: undefined, softsystem_custo_medio: undefined,
      };
    });
    setVinculoIdx(null);
    setItens(novos);
    recalcular({ itensNovos: novos });
  };

  const alterarFator = (idx: number, valor: number) => {
    setItens(itens.map((it, i) => (i === idx ? { ...it, fator_conversao: valor > 0 ? valor : 1 } : it)));
  };

  const adicionarDespesa = () => {
    const valor = parseFloat(novaDesp.valor.replace(',', '.')) || 0;
    if (!novaDesp.descricao.trim() || valor <= 0) return;
    const novas = [...despesas, { id: String(Date.now()), descricao: novaDesp.descricao.trim(), valor }];
    setDespesas(novas);
    setNovaDesp({ descricao: '', valor: '' });
    recalcular({ despesasNovas: novas });
  };

  const [versaoFotos, setVersaoFotos] = useState(0);
  const fotos = useFotosProdutos(empresa, itens.map((i) => i.softsystem_prod_codigo || i.produto_modelo_codigo), versaoFotos);
  const pendentes = useMemo(() => itens.filter((i) => !i.softsystem_prod_codigo && !i.produto_modelo_codigo), [itens]);

  const salvar = async () => {
    if (!nota || !resultado) return;
    setSalvando(true);
    setErro(null);
    try {
      const r = await api<{ entrada_id: number }>('/entradas', {
        body: {
          empresa, origem_xml: resultado.origem, nota: { ...nota, itens: undefined }, cte,
          itens: itens.map((i) => ({ ...i, fator_conversao: i.fator_conversao || 1 })),
          despesas_extras: despesas, tipo_rateio: tipoRateio, parcelas, parcelas_cte: parcelasCte,
        },
      });
      try { localStorage.removeItem(CHAVE_SALVA); } catch { /* ok */ }
      onSalva(r.entrada_id);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setSalvando(false);
    }
  };

  // ------------------------------------------------------------------ etapa 1: chaves
  if (!nota) {
    return (
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '760px' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: '17px', color: 'var(--text-main)' }}>Nova entrada de mercadoria</h3>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
            Digite ou bipe a chave de acesso da NF-e. O sistema busca a nota na pasta do Softsystem ou na SEFAZ,
            vincula os produtos e calcula impostos, custo e vencimentos.
          </p>
        </div>

        <Campo rotulo="Chave de acesso da NF-e (44 dígitos)">
          <div style={{ display: 'flex', gap: '8px' }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <Key size={14} style={{ position: 'absolute', left: '10px', top: '11px', color: 'var(--text-muted)' }} />
              <input
                autoFocus
                style={{ ...input, paddingLeft: '30px', fontFamily: 'monospace', fontSize: '14px', letterSpacing: '0.5px' }}
                value={formatarChave(chaveNfe)}
                onChange={(e) => setChaveNfe(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && chaveLimpa.length === 44 && buscar()}
                placeholder="0000 0000 0000 0000 0000 0000 0000 0000 0000 0000 0000"
              />
            </div>
          </div>
          <span style={{ fontSize: '11px', color: chaveLimpa.length === 44 ? '#22c55e' : 'var(--text-muted)' }}>{chaveLimpa.length}/44 dígitos</span>
        </Campo>

        <label style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '13px', color: 'var(--text-main)', cursor: 'pointer' }}>
          <input type="checkbox" checked={temCte} onChange={(e) => setTemCte(e.target.checked)} />
          <Truck size={15} /> Veio com CT-e de transportadora (frete pago pela loja)
        </label>
        {temCte && (
          <Campo rotulo="Chave de acesso do CT-e" dica="O valor do frete e o crédito de ICMS do CT-e entram no custo dos itens.">
            <input
              style={{ ...input, fontFamily: 'monospace', fontSize: '14px' }}
              value={formatarChave(chaveCte)}
              onChange={(e) => setChaveCte(e.target.value)}
              placeholder="Chave do CT-e"
            />
          </Campo>
        )}

        {erro && <Aviso tipo="erro">{erro}</Aviso>}

        {resultado?.status === 'ja_importada' && resultado.entrada_id && (
          <Aviso tipo="info">
            {resultado.mensagem}{' '}
            <Botao variante="secundario" onClick={() => onAbrirExistente(resultado.entrada_id!)} style={{ marginLeft: '8px' }}>Abrir entrada</Botao>
          </Aviso>
        )}
        {resultado?.status === 'nao_encontrado' && <Aviso tipo="alerta">{resultado.mensagem}</Aviso>}
        {resultado?.status === 'aguardando_xml' && (
          <Aviso tipo="info">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, marginBottom: '4px' }}>
              <Loader2 size={15} className="animate-spin" /> Baixando o XML completo da SEFAZ...
            </div>
            <div style={{ fontSize: '12.5px' }}>{resultado.mensagem}</div>
            {resultado.resumo && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
                {resultado.resumo.emitente_nome} · {brl(resultado.resumo.valor_total)} · emitida em {dataBR(resultado.resumo.data_emissao)}
              </div>
            )}
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)', marginTop: '6px' }}>
              Pode deixar esta tela aberta - a nota abre sozinha. Se tiver o arquivo XML em mãos, também pode importar agora.
            </div>
          </Aviso>
        )}
        {resultado?.status === 'precisa_ciencia' && (
          <Aviso tipo="alerta">
            <div style={{ marginBottom: '6px' }}>{resultado.mensagem}</div>
            {resultado.resumo && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                {resultado.resumo.emitente_nome} · {brl(resultado.resumo.valor_total)} · emitida em {dataBR(resultado.resumo.data_emissao)}
              </div>
            )}
            {msgManifestacao ? <strong>{msgManifestacao}</strong> : (
              <Botao icone={<ShieldCheck size={14} />} onClick={() => manifestar('ciencia')} disabled={manifestando}>
                {manifestando ? 'Enviando à SEFAZ...' : 'Registrar Ciência da Operação'}
              </Botao>
            )}
          </Aviso>
        )}
        {resultado?.status === 'precisa_confirmacao' && (
          <Aviso tipo="alerta">
            <div style={{ marginBottom: '6px' }}>{resultado.mensagem}</div>
            {resultado.resumo && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                {resultado.resumo.emitente_nome} · {brl(resultado.resumo.valor_total)} · emitida em {dataBR(resultado.resumo.data_emissao)}
              </div>
            )}
            {msgManifestacao ? <strong>{msgManifestacao}</strong> : (
              <Botao icone={<ShieldCheck size={14} />} onClick={() => manifestar('confirmacao')} disabled={manifestando}>
                {manifestando ? 'Enviando à SEFAZ...' : 'Confirmar a Operação (a mercadoria chegou)'}
              </Botao>
            )}
          </Aviso>
        )}

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <Botao icone={<Search size={15} />} onClick={() => buscar()} disabled={chaveLimpa.length !== 44 || buscando}>
            {buscando ? 'Buscando a nota...' : 'Buscar nota'}
          </Botao>
          <Botao variante="secundario" icone={<Upload size={15} />} onClick={() => uploadRef.current?.click()}>
            Importar arquivo XML
          </Botao>
          <input ref={uploadRef} type="file" accept=".xml" hidden onChange={(e) => e.target.files?.[0] && importarXml(e.target.files[0])} />
        </div>
      </div>
    );
  }

  // ------------------------------------------------------------------ etapa 2: conferir a nota
  const t = nota.totais;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
            NF-e {nota.numero_nf} · série {nota.serie} · {dataBR(nota.data_emissao)} · {NOME_LOJA[empresa]}
          </div>
          <h3 style={{ margin: '4px 0', fontSize: '18px', color: 'var(--text-main)' }}>{nota.fornecedor.razao_social}</h3>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            CNPJ {nota.fornecedor.cnpj} · {nota.fornecedor.uf}
            {nota.fornecedor.crt === '1' && <> · <Chip cor="#a855f7">fornecedor do Simples</Chip></>}
            {' · '}XML: {resultado?.origem === 'sefaz' ? 'baixado da SEFAZ' : resultado?.origem === 'upload' ? 'arquivo importado' : 'pasta do Softsystem'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Total da nota</div>
          <div style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-main)' }}>{brl(t.valor_total_nf)}</div>
          <Botao variante="fantasma" onClick={() => { setResultado(null); setItens([]); setChaveNfe(''); setChaveCte(''); }}>Trocar nota</Botao>
        </div>
      </div>

      {(resultado?.avisos || []).map((a, i) => <Aviso key={i} tipo={a.startsWith('ATENÇÃO') ? 'erro' : 'alerta'}>{a}</Aviso>)}
      {erro && <Aviso tipo="erro" onFechar={() => setErro(null)}>{erro}</Aviso>}

      {/* Totais e impostos embutidos */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
        {[
          ['Produtos', t.valor_produtos],
          ['IPI', t.valor_ipi],
          ['ICMS-ST', (t.valor_st || 0) + (t.valor_fcp_st || 0)],
          ['ICMS destacado', t.valor_icms],
          ['Frete (nota + CT-e)', (t.valor_frete || 0) + (cte?.frete_da_loja ? cte.valor_frete_total || 0 : 0)],
          ['Créditos recuperados', resumo.creditos_total],
          ['Custo líquido total', resumo.custo_liquido_total],
        ].map(([rotulo, valor]) => (
          <div key={rotulo as string} style={{ ...card, padding: '12px' }}>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{rotulo}</div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-main)' }}>{brl(valor as number)}</div>
          </div>
        ))}
      </div>

      {/* CT-e */}
      <div style={{ ...card, display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
        <Truck size={18} color="var(--text-muted)" />
        {cte?.carregado ? (
          <div style={{ flex: 1, fontSize: '13px', color: 'var(--text-main)' }}>
            CT-e {cte.numero_cte} · {cte.transportadora?.razao_social} · frete <strong>{brl(cte.valor_frete_total)}</strong>
            {cte.icms?.v_icms ? <> · ICMS {brl(cte.icms.v_icms)}</> : null}
            {!cte.frete_da_loja && <> · <Chip cor="#f59e0b">loja não é a pagadora - fora do custo</Chip></>}
          </div>
        ) : (
          <div style={{ flex: 1, fontSize: '13px', color: 'var(--text-muted)' }}>
            {cte?.mensagem || 'Sem CT-e de transportadora.'} Se houver frete pago à transportadora, importe o XML do CT-e.
          </div>
        )}
        <Botao variante="secundario" icone={<Upload size={14} />} onClick={() => uploadRef.current?.click()}>Importar XML do CT-e</Botao>
        <input ref={uploadRef} type="file" accept=".xml" hidden onChange={(e) => e.target.files?.[0] && importarXml(e.target.files[0])} />
      </div>

      {/* Itens */}
      <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
        <div style={{ padding: '14px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <strong style={{ color: 'var(--text-main)' }}>Itens da nota ({itens.length})</strong>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px', color: 'var(--text-muted)' }}>
            Ratear frete/despesas por
            <select style={{ ...input, width: 'auto' }} value={tipoRateio}
              onChange={(e) => { const v = e.target.value as 'valor' | 'quantidade'; setTipoRateio(v); recalcular({ rateio: v }); }}>
              <option value="valor">valor</option>
              <option value="quantidade">quantidade</option>
            </select>
          </div>
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '980px' }}>
          <thead>
            <tr>
              <th style={th}>#</th>
              <th style={th}>Produto na nota</th>
              <th style={th}>Qtd</th>
              <th style={th}>Valor</th>
              <th style={th}>Impostos</th>
              <th style={th}>Produto na loja (Softsystem)</th>
              <th style={th}>Custo real un.</th>
            </tr>
          </thead>
          <tbody>
            {itens.map((it, idx) => {
              const unidadeDifere = it.softsystem_unidade && it.softsystem_unidade !== it.unidade;
              return (
                <tr key={idx}>
                  <td style={td}>{it.numero_item}</td>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{it.descricao_fornecedor}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      Cód. {it.codigo_fornecedor} · EAN {it.ean || '—'} · NCM {it.ncm} · CFOP {it.cfop}
                    </div>
                  </td>
                  <td style={td}>
                    {it.quantidade} {it.unidade}
                    {(unidadeDifere || it.fator_conversao_sugerido || (it.fator_conversao || 1) !== 1) && (
                      <div style={{ marginTop: '4px', fontSize: '11px', color: 'var(--text-muted)' }}>
                        1 {it.unidade} =
                        <input type="number" min={0.0001} step="any" style={{ ...input, width: '64px', padding: '3px 6px', margin: '0 4px', display: 'inline-block' }}
                          value={it.fator_conversao || it.fator_conversao_sugerido || 1}
                          onChange={(e) => alterarFator(idx, parseFloat(e.target.value))} />
                        {it.softsystem_unidade || 'UN'}
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    {brl(it.valor_total)}
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{brl(it.valor_unitario)} un.</div>
                  </td>
                  <td style={{ ...td, fontSize: '12px' }}>
                    {it.v_icms ? <div>ICMS {brl(it.v_icms)}</div> : null}
                    {it.v_icms_st ? <div>ST {brl(it.v_icms_st)}</div> : null}
                    {it.v_ipi ? <div>IPI {brl(it.v_ipi)}</div> : null}
                    {it.tem_st && <Chip cor="#a855f7">com ST</Chip>}
                  </td>
                  <td style={td}>
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                    <FotoProduto foto={fotos[String(it.softsystem_prod_codigo || it.produto_modelo_codigo || '')]}
                      codproduto={it.softsystem_prod_codigo} descricao={it.softsystem_descricao || it.descricao_fornecedor} onTrocada={() => setVersaoFotos((v) => v + 1)} />
                    <div>
                    {it.softsystem_prod_codigo ? (
                      <>
                        <Chip cor="#22c55e">
                          <CheckCircle size={11} /> {it.vinculo_metodo === 'codigo_fornecedor' ? 'pelo cód. do fornecedor' : it.vinculo_metodo === 'ean' ? 'pelo EAN' : 'vinculado'}
                        </Chip>
                        <div style={{ marginTop: '4px' }}>#{it.softsystem_prod_codigo} {it.softsystem_descricao}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          Estoque {it.softsystem_estoque ?? '—'} · preço atual {brl(it.softsystem_preco_venda)}
                        </div>
                        {it.alerta_ncm_diferente && <Chip cor="#f59e0b">NCM da loja ({it.softsystem_ncm}) difere da nota</Chip>}
                      </>
                    ) : it.produto_modelo_codigo ? (
                      <>
                        <Chip cor="#3b82f6"><Copy size={11} /> produto novo</Chip>
                        <div style={{ marginTop: '4px', fontSize: '12px' }}>Cadastro copiado de #{it.produto_modelo_codigo} {it.produto_modelo_descricao}</div>
                      </>
                    ) : (
                      <Chip cor="#ef4444"><AlertTriangle size={11} /> não existe na loja</Chip>
                    )}
                    <div style={{ marginTop: '6px' }}>
                      <Botao variante="secundario" icone={<Link2 size={12} />} style={{ padding: '4px 10px', fontSize: '12px' }} onClick={() => setVinculoIdx(idx)}>
                        {it.softsystem_prod_codigo || it.produto_modelo_codigo ? 'Trocar' : 'Escolher similar'}
                      </Botao>
                    </div>
                    </div>
                    </div>
                  </td>
                  <td style={td}>
                    <strong>{brl(it.custo_unitario_real)}</strong>
                    {it.credito_icms ? <div style={{ fontSize: '11px', color: '#22c55e' }}>−{brl(it.credito_icms)} crédito ICMS</div> : null}
                    {it.variacao_custo_pct !== null && it.variacao_custo_pct !== undefined && Math.abs(it.variacao_custo_pct) >= 1 && (
                      <div style={{ fontSize: '11px', color: it.variacao_custo_pct > 0 ? '#f87171' : '#22c55e' }}>
                        {it.variacao_custo_pct > 0 ? '▲' : '▼'} {Math.abs(it.variacao_custo_pct).toFixed(0)}% vs custo atual
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        <div style={card}>
          <ParcelasEditor titulo="Vencimentos do fornecedor" parcelas={parcelas} valorEsperado={t.valor_total_nf} dataBase={nota.data_emissao?.slice(0, 10)} onChange={setParcelas} />
        </div>
        {cte?.carregado && cte.frete_da_loja && (
          <div style={card}>
            <ParcelasEditor titulo="Vencimento do frete (transportadora)" parcelas={parcelasCte} valorEsperado={cte.valor_frete_total || 0} dataBase={nota.data_emissao?.slice(0, 10)} onChange={setParcelasCte} />
          </div>
        )}
        <div style={card}>
          <strong style={{ fontSize: '14px', color: 'var(--text-main)' }}>Outras despesas desta compra</strong>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 10px' }}>Ex.: frete pago a motoboy, taxa de boleto, descarga. Rateadas no custo dos itens.</p>
          {despesas.map((d) => (
            <div key={d.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', padding: '4px 0', color: 'var(--text-main)' }}>
              <span>{d.descricao}</span>
              <span>{brl(d.valor)}
                <Botao variante="fantasma" icone={<Trash2 size={12} />} onClick={() => { const n = despesas.filter((x) => x.id !== d.id); setDespesas(n); recalcular({ despesasNovas: n }); }} />
              </span>
            </div>
          ))}
          <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
            <input style={input} placeholder="Descrição" value={novaDesp.descricao} onChange={(e) => setNovaDesp({ ...novaDesp, descricao: e.target.value })} />
            <input style={{ ...input, width: '110px' }} placeholder="R$" value={novaDesp.valor} onChange={(e) => setNovaDesp({ ...novaDesp, valor: e.target.value })}
              onKeyDown={(e) => e.key === 'Enter' && adicionarDespesa()} />
            <Botao variante="secundario" icone={<Plus size={13} />} onClick={adicionarDespesa} />
          </div>
        </div>
      </div>

      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '13px', color: 'var(--text-muted)', maxWidth: '620px' }}>
          {pendentes.length > 0
            ? <span style={{ color: '#f59e0b' }}>{pendentes.length} item(ns) ainda sem produto da loja. Dá para salvar e resolver depois, mas a entrada só fecha com todos vinculados.</span>
            : 'Tudo vinculado.'}{' '}
          Ao salvar, a entrada vai para a <strong>contagem cega</strong>: quem conferir a mercadoria não vê a quantidade da nota.
        </div>
        <Botao icone={<ClipboardList size={15} />} onClick={salvar} disabled={salvando}>
          {salvando ? 'Salvando...' : 'Salvar e liberar para contagem'}
        </Botao>
      </div>

      {vinculoIdx !== null && (
        <ProdutoVinculoModal empresa={empresa} item={itens[vinculoIdx]} onFechar={() => setVinculoIdx(null)} onEscolher={escolherProduto} />
      )}
    </div>
  );
};
