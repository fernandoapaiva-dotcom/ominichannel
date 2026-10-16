import React, { useEffect, useState } from 'react';
import { Plus, Save, Trash2 } from 'lucide-react';
import { api, brl, pct, Empresa, NOME_LOJA } from './comprasApi';
import { Aviso, Botao, Campo, card, input, td, th } from './ui';
import { CertificadoDigital } from './CertificadoDigital';

interface Props {
  empresa: Empresa;
  isAdmin: boolean;
}

interface CustoFixo {
  id?: number;
  categoria: string;
  descricao: string;
  valor_mensal: number;
  ativo: boolean;
}

const CATEGORIAS = [
  'Aluguel e condomínio', 'Folha + encargos', 'Pró-labore', 'Energia', 'Água', 'Internet e telefone',
  'Contabilidade', 'Sistemas (Softsystem etc.)', 'Veículos e combustível', 'Marketing', 'Manutenção',
  'Seguros', 'Tarifas bancárias', 'Outros',
];

type Params = Record<string, any>;

/**
 * Parâmetros de formação de preço de cada loja: impostos na venda conforme o regime, custos
 * fixos mensais (viram % do faturamento) e margens. Os valores iniciais são de partida -
 * conferir com o contador.
 */
export const ParametrosCustoLoja: React.FC<Props> = ({ empresa, isAdmin }) => {
  const [params, setParams] = useState<Params | null>(null);
  const [custos, setCustos] = useState<CustoFixo[]>([]);
  const [novo, setNovo] = useState<CustoFixo>({ categoria: CATEGORIAS[0], descricao: '', valor_mensal: 0, ativo: true });
  const [mensagem, setMensagem] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);

  const carregar = async () => {
    try {
      const [p, c] = await Promise.all([
        api<{ parametros: Record<string, Params> }>('/parametros-custo'),
        api<{ custos: CustoFixo[] }>(`/custos-fixos?empresa=${empresa}`),
      ]);
      setParams(p.parametros[empresa]);
      setCustos(c.custos);
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa]);

  if (!params) return <div style={{ ...card, color: 'var(--text-muted)' }}>Carregando parâmetros...</div>;

  const simples = params.regime_tributario === 'simples_nacional';
  const set = (campo: string, valor: string) => setParams({ ...params, [campo]: campo === 'condicao_pagamento_padrao' ? valor : parseFloat(valor) || 0 });

  const salvarParams = async () => {
    try {
      const campos = ['custo_fixo_operacional_pct', 'despesas_variaveis_pct', 'margem_lucro_padrao_pct', 'margem_minima_pct', 'icms_saida_pct',
        'pis_saida_pct', 'cofins_saida_pct', 'irpj_csll_pct', 'das_pct', 'das_parcela_icms_pct', 'icms_antecipacao_pct',
        'faturamento_medio_mensal', 'condicao_pagamento_padrao'];
      const body: Params = { empresa };
      campos.forEach((c) => { if (params[c] !== undefined && params[c] !== null) body[c] = params[c]; });
      if (params.custo_fixo_origem === 'custos_fixos_lancados') delete body.custo_fixo_operacional_pct;
      const r = await api<{ parametros: Params }>('/parametros-custo', { body });
      setParams(r.parametros);
      setMensagem({ tipo: 'ok', texto: 'Parâmetros salvos. Novas entradas já usam estes valores.' });
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  const salvarCusto = async (c: CustoFixo) => {
    try {
      await api('/custos-fixos', { body: { ...c, empresa } });
      setNovo({ categoria: CATEGORIAS[0], descricao: '', valor_mensal: 0, ativo: true });
      await carregar();
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  const excluirCusto = async (id: number) => {
    if (!confirm('Excluir este custo fixo?')) return;
    try {
      await api(`/custos-fixos/${id}`, { method: 'DELETE' });
      await carregar();
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  const impostosVenda = simples
    ? params.das_pct
    : (params.icms_saida_pct || 0) + (params.pis_saida_pct || 0) + (params.cofins_saida_pct || 0) + (params.irpj_csll_pct || 0);
  const deducoes = impostosVenda + (params.custo_fixo_operacional_pct || 0) + (params.despesas_variaveis_pct || 0) + (params.margem_lucro_padrao_pct || 0);
  const exemploPreco = deducoes < 95 ? 100 / (1 - deducoes / 100) : null;
  const totalFixos = custos.filter((c) => c.ativo).reduce((a, c) => a + c.valor_mensal, 0);

  const campoNum = (campo: string, rotulo: string, dica?: string) => (
    <Campo rotulo={rotulo} dica={dica}>
      <input type="number" step="0.01" style={input} disabled={!isAdmin} value={params[campo] ?? ''} onChange={(e) => set(campo, e.target.value)} />
    </Campo>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <Aviso tipo="info">
        <strong>{NOME_LOJA[empresa]}.</strong> Os valores iniciais são um ponto de partida (alíquotas usuais do regime e do DF). Confirme
        com o contador, principalmente a alíquota efetiva do DAS, que muda com o faturamento dos últimos 12 meses.
        {!isAdmin && ' Somente administradores podem alterar.'}
      </Aviso>
      {mensagem && <Aviso tipo={mensagem.tipo} onFechar={() => setMensagem(null)}>{mensagem.texto}</Aviso>}

      <CertificadoDigital empresa={empresa} isAdmin={isAdmin} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <strong style={{ color: 'var(--text-main)' }}>Impostos na venda — {simples ? 'Simples Nacional' : 'Lucro Presumido'}</strong>
          {simples ? (
            <>
              {campoNum('das_pct', 'Alíquota efetiva do DAS (%)', 'Anexo I (comércio). Pegue no último extrato do PGDAS.')}
              {campoNum('das_parcela_icms_pct', 'Parcela do ICMS dentro do DAS (%)', 'Sai do DAS quando o produto já veio com ICMS-ST.')}
              {campoNum('icms_antecipacao_pct', 'ICMS antecipado em compra de outro estado (%)', 'Use só se o DF cobrar antecipação nas suas compras interestaduais.')}
            </>
          ) : (
            <>
              {campoNum('icms_saida_pct', 'ICMS na venda (%)', 'Alíquota interna do DF. O ICMS pago na compra é creditado e sai do custo.')}
              {campoNum('pis_saida_pct', 'PIS (%)', 'Cumulativo no Presumido: 0,65%, sem crédito na compra.')}
              {campoNum('cofins_saida_pct', 'COFINS (%)', 'Cumulativo no Presumido: 3%.')}
              {campoNum('irpj_csll_pct', 'IRPJ + CSLL (%)', 'Comércio: 15% de 8% + 9% de 12% = 2,28% (sem o adicional de IR).')}
            </>
          )}
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Total de impostos na venda: <strong>{pct(impostosVenda, 2)}</strong></div>
        </div>

        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <strong style={{ color: 'var(--text-main)' }}>Margens e despesas</strong>
          {campoNum('margem_lucro_padrao_pct', 'Margem de lucro padrão (%)', 'Lucro líquido sobre o preço de venda, depois de impostos e custos.')}
          {campoNum('margem_minima_pct', 'Margem mínima (%)', 'Abaixo disso o sistema alerta na precificação.')}
          {campoNum('despesas_variaveis_pct', 'Despesas variáveis (%)', 'Taxa de cartão, comissão de vendedor, entrega.')}
          <Campo rotulo="Condição de pagamento padrão" dica="Usada quando a nota não traz duplicatas. Ex.: 30/60/90">
            <input style={input} disabled={!isAdmin} value={params.condicao_pagamento_padrao || ''} onChange={(e) => set('condicao_pagamento_padrao', e.target.value)} />
          </Campo>
        </div>

        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <strong style={{ color: 'var(--text-main)' }}>Como fica o preço</strong>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Preço = custo ÷ (1 − impostos − custo fixo − despesas − margem)<br />
            = custo ÷ (1 − {pct(deducoes, 2)})<br />
            <span style={{ color: 'var(--text-main)' }}>
              Produto que custa <strong>R$ 100,00</strong> → vende por <strong>{exemploPreco ? brl(exemploPreco) : '—'}</strong>
              {exemploPreco && <> (markup {(exemploPreco / 100).toFixed(2)}x)</>}
            </span>
          </div>
        </div>
      </div>

      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <strong style={{ color: 'var(--text-main)' }}>Custos fixos mensais da loja</strong>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', maxWidth: '640px' }}>
              Lance o que a loja paga todo mês. Total ÷ faturamento médio = % de custo fixo que cada produto precisa cobrir.
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
            <Campo rotulo="Faturamento médio mensal (R$)">
              <input type="number" step="100" style={{ ...input, width: '160px' }} disabled={!isAdmin}
                value={params.faturamento_medio_mensal ?? ''} onChange={(e) => set('faturamento_medio_mensal', e.target.value)} />
            </Campo>
            {params.custo_fixo_origem !== 'custos_fixos_lancados' && (
              <Campo rotulo="% fixo (sem lançamentos)">
                <input type="number" step="0.1" style={{ ...input, width: '110px' }} disabled={!isAdmin}
                  value={params.custo_fixo_operacional_pct ?? ''} onChange={(e) => set('custo_fixo_operacional_pct', e.target.value)} />
              </Campo>
            )}
          </div>
        </div>

        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th style={th}>Categoria</th><th style={th}>Descrição</th><th style={th}>Valor/mês</th><th style={th}>Ativo</th>{isAdmin && <th style={th}></th>}</tr></thead>
          <tbody>
            {custos.map((c) => (
              <tr key={c.id}>
                <td style={td}>{c.categoria}</td>
                <td style={td}>{c.descricao}</td>
                <td style={td}>{brl(c.valor_mensal)}</td>
                <td style={td}>
                  <input type="checkbox" checked={c.ativo} disabled={!isAdmin} onChange={(e) => salvarCusto({ ...c, ativo: e.target.checked })} />
                </td>
                {isAdmin && <td style={td}><Botao variante="fantasma" icone={<Trash2 size={13} />} onClick={() => excluirCusto(c.id!)} /></td>}
              </tr>
            ))}
            {isAdmin && (
              <tr>
                <td style={td}>
                  <select style={input} value={novo.categoria} onChange={(e) => setNovo({ ...novo, categoria: e.target.value })}>
                    {CATEGORIAS.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </td>
                <td style={td}><input style={input} placeholder="Ex.: aluguel do galpão" value={novo.descricao} onChange={(e) => setNovo({ ...novo, descricao: e.target.value })} /></td>
                <td style={td}><input type="number" step="0.01" style={input} value={novo.valor_mensal || ''} onChange={(e) => setNovo({ ...novo, valor_mensal: parseFloat(e.target.value) || 0 })} /></td>
                <td style={td}></td>
                <td style={td}>
                  <Botao variante="secundario" icone={<Plus size={13} />} disabled={!novo.descricao.trim() || novo.valor_mensal <= 0} onClick={() => salvarCusto(novo)}>Adicionar</Botao>
                </td>
              </tr>
            )}
          </tbody>
        </table>

        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>
          Total: <strong>{brl(totalFixos)}</strong>/mês
          {params.faturamento_medio_mensal ? <> ÷ {brl(params.faturamento_medio_mensal)} = <strong>{pct(params.custo_fixo_operacional_pct, 2)}</strong> de custo fixo em cada venda</> : ' — informe o faturamento médio para calcular o %'}
          {params.custo_fixo_origem !== 'custos_fixos_lancados' && totalFixos === 0 && <span style={{ color: 'var(--text-muted)' }}> (usando {pct(params.custo_fixo_operacional_pct)} manual)</span>}
        </div>
      </div>

      {isAdmin && (
        <div style={{ textAlign: 'right' }}>
          <Botao icone={<Save size={14} />} onClick={salvarParams}>Salvar parâmetros de {empresa === 'servweld' ? 'Servweld' : 'Centro Oeste'}</Botao>
        </div>
      )}
    </div>
  );
};
