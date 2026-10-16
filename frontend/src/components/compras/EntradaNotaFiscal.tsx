import React, { useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { api, brl, dataBR, Empresa, EntradaResumo, STATUS_ENTRADA } from './comprasApi';
import { Botao, Chip, card, td, th } from './ui';
import { NovaEntrada } from './NovaEntrada';
import { EntradaDetalhe } from './EntradaDetalhe';

interface Props {
  empresa: Empresa;
  isAdmin: boolean;
}

type Tela = { tipo: 'lista' } | { tipo: 'nova' } | { tipo: 'detalhe'; id: number };

const FILTROS: { id: string; rotulo: string }[] = [
  { id: 'aguardando_contagem,contagem_divergente,contada', rotulo: 'Em andamento' },
  { id: 'aguardando_contagem,contagem_divergente', rotulo: 'Para contar' },
  { id: 'fechada,enviada_softsystem', rotulo: 'Fechadas' },
  { id: 'todos', rotulo: 'Todas' },
];

/** Aba "Entrada de NF-e": lista de entradas + fluxo chave -> conferência -> contagem cega -> preço -> fechar. */
export const EntradaNotaFiscal: React.FC<Props> = ({ empresa, isAdmin }) => {
  const [tela, setTela] = useState<Tela>({ tipo: 'lista' });
  const [entradas, setEntradas] = useState<EntradaResumo[]>([]);
  const [filtro, setFiltro] = useState(FILTROS[0].id);
  const [carregando, setCarregando] = useState(false);

  const carregar = async () => {
    setCarregando(true);
    try {
      const r = await api<{ entradas: EntradaResumo[] }>(`/entradas?empresa=${empresa}&status=${filtro}`);
      setEntradas(r.entradas);
    } catch {
      setEntradas([]);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    if (tela.tipo === 'lista') carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tela, filtro, empresa]);

  if (tela.tipo === 'nova') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div><Botao variante="fantasma" onClick={() => setTela({ tipo: 'lista' })}>← Voltar para a lista</Botao></div>
        <NovaEntrada
          empresaPadrao={empresa}
          onSalva={(id) => setTela({ tipo: 'detalhe', id })}
          onAbrirExistente={(id) => setTela({ tipo: 'detalhe', id })}
        />
      </div>
    );
  }
  if (tela.tipo === 'detalhe') {
    return <EntradaDetalhe entradaId={tela.id} isAdmin={isAdmin} onVoltar={() => setTela({ tipo: 'lista' })} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {FILTROS.map((f) => (
            <Botao key={f.id} variante={filtro === f.id ? 'primario' : 'secundario'} onClick={() => setFiltro(f.id)} style={{ padding: '6px 12px' }}>
              {f.rotulo}
            </Botao>
          ))}
          <Botao variante="fantasma" icone={<RefreshCw size={14} />} onClick={carregar} />
        </div>
        <Botao icone={<Plus size={15} />} onClick={() => setTela({ tipo: 'nova' })}>Nova entrada (chave da NF-e)</Botao>
      </div>

      <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
        {carregando ? (
          <div style={{ padding: '24px', color: 'var(--text-muted)' }}>Carregando...</div>
        ) : entradas.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
            Nenhuma entrada aqui. Clique em <strong>Nova entrada</strong> e digite a chave de acesso da NF-e.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr><th style={th}>#</th><th style={th}>Fornecedor</th><th style={th}>NF-e</th><th style={th}>Emissão</th><th style={th}>Valor</th><th style={th}>Status</th><th style={th}>Importada por</th></tr>
            </thead>
            <tbody>
              {entradas.map((e) => {
                const st = STATUS_ENTRADA[e.status] || { rotulo: e.status, cor: '#6b7280' };
                return (
                  <tr key={e.id} onClick={() => setTela({ tipo: 'detalhe', id: e.id })} style={{ cursor: 'pointer' }}>
                    <td style={td}>{e.id}</td>
                    <td style={td}>{e.fornecedor_nome}</td>
                    <td style={td}>{e.numero_nf}{e.cte_numero && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>CT-e {e.cte_numero}</div>}</td>
                    <td style={td}>{dataBR(e.data_emissao)}</td>
                    <td style={td}>{brl(e.valor_total_nota)}</td>
                    <td style={td}><Chip cor={st.cor}>{st.rotulo}</Chip></td>
                    <td style={td}>{e.criado_por}<div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{dataBR(e.criado_em)}</div></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
