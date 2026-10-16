import React, { useEffect, useState } from 'react';
import { EyeOff, Save, CheckCircle, RotateCcw, ShieldAlert, Barcode, MapPin } from 'lucide-react';
import { api, Empresa } from './comprasApi';
import { FotoProduto, useFotosProdutos } from './FotoProduto';
import { Aviso, Botao, Chip, card, input } from './ui';

interface ItemContagem {
  item_id: number;
  numero_item: number;
  descricao: string;
  descricao_fornecedor: string;
  codigo_loja?: string;
  codigo_fornecedor: string;
  ean?: string;
  unidade_contagem: string;
  ja_contado: boolean;
  recontar: boolean;
  recontagens: number;
  // do Softsystem (aba Estoque do produto): onde guardar + quanto já tem na loja
  localizacao?: string | null;
  estoque_atual?: number | null;
}

interface Props {
  entradaId: number;
  isAdmin: boolean;
  onMudouStatus: () => void;
  empresa?: Empresa;
}

/**
 * Conferência física às cegas: o conferente vê o produto, mas nunca a quantidade da nota.
 * Se não bater, o sistema só diz QUAIS itens recontar (não o número certo). Persistindo a
 * diferença, só um administrador libera, com justificativa - e o estoque entra pelo contado.
 */
export const ContagemCega: React.FC<Props> = ({ entradaId, isAdmin, onMudouStatus, empresa = 'servweld' }) => {
  const [itens, setItens] = useState<ItemContagem[]>([]);
  const [status, setStatus] = useState('');
  const [valores, setValores] = useState<Record<number, string>>({});
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState<{ tipo: 'ok' | 'erro' | 'alerta'; texto: string } | null>(null);
  const [precisaAprovacao, setPrecisaAprovacao] = useState(false);
  const [justificativa, setJustificativa] = useState('');
  const [filtroEan, setFiltroEan] = useState('');
  const [versaoFotos, setVersaoFotos] = useState(0);
  const fotos = useFotosProdutos(empresa, itens.map((i) => i.codigo_loja), versaoFotos);

  const carregar = async () => {
    setCarregando(true);
    try {
      const r = await api<{ entrada: { status: string }; itens: ItemContagem[] }>(`/entradas/${entradaId}/contagem`);
      setItens(r.itens);
      setStatus(r.entrada.status);
      if (r.entrada.status === 'contagem_divergente') {
        setPrecisaAprovacao(r.itens.some((i) => i.recontar && i.recontagens > 0));
      }
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entradaId]);

  const salvar = async (): Promise<boolean> => {
    const lote = Object.entries(valores)
      .filter(([, v]) => v.trim() !== '')
      .map(([id, v]) => ({ item_id: Number(id), qtd_contada: parseFloat(v.replace(',', '.')) }));
    if (lote.some((l) => Number.isNaN(l.qtd_contada))) {
      setMensagem({ tipo: 'erro', texto: 'Há quantidade inválida digitada.' });
      return false;
    }
    if (!lote.length) return true;
    setSalvando(true);
    try {
      await api(`/entradas/${entradaId}/contagem`, { body: { itens: lote } });
      setValores({});
      await carregar();
      return true;
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
      return false;
    } finally {
      setSalvando(false);
    }
  };

  const finalizar = async () => {
    if (!(await salvar())) return;
    setSalvando(true);
    try {
      const r = await api<any>(`/entradas/${entradaId}/contagem/finalizar`, { method: 'POST' });
      if (r.status === 'contada') {
        setMensagem({ tipo: 'ok', texto: 'Contagem bateu com a nota. Pode seguir para a precificação.' });
        onMudouStatus();
      } else {
        setMensagem({ tipo: 'alerta', texto: r.mensagem });
        setPrecisaAprovacao(!!r.precisa_aprovacao);
        await carregar();
      }
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    } finally {
      setSalvando(false);
    }
  };

  const aprovar = async () => {
    try {
      await api(`/entradas/${entradaId}/aprovar-divergencia`, { body: { justificativa } });
      setMensagem({ tipo: 'ok', texto: 'Divergência aprovada. O estoque vai entrar pela quantidade contada.' });
      onMudouStatus();
    } catch (e: any) {
      setMensagem({ tipo: 'erro', texto: e.message });
    }
  };

  if (carregando) return <div style={{ ...card, color: 'var(--text-muted)' }}>Carregando itens para contagem...</div>;

  const visiveis = filtroEan.trim()
    ? itens.filter((i) => [i.ean, i.codigo_fornecedor, i.codigo_loja].some((c) => c && c.includes(filtroEan.trim())))
    : itens;
  const contados = itens.filter((i) => i.ja_contado).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <Aviso tipo="info">
        <strong><EyeOff size={13} style={{ verticalAlign: 'middle' }} /> Contagem cega:</strong> conte <strong>só as peças que chegaram nesta nota</strong>
        (a caixa/volume do fornecedor) e digite na unidade indicada. A quantidade da nota não aparece aqui de propósito.
        <div style={{ marginTop: '4px' }}>
          <strong>Não</strong> digite o total da prateleira - o estoque total você confere na etapa <strong>"3. Estoque e localização"</strong>,
          depois que a nota for lançada.
        </div>
      </Aviso>
      {mensagem && <Aviso tipo={mensagem.tipo} onFechar={() => setMensagem(null)}>{mensagem.texto}</Aviso>}

      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: '1 1 240px' }}>
          <Barcode size={14} style={{ position: 'absolute', left: '10px', top: '10px', color: 'var(--text-muted)' }} />
          <input style={{ ...input, paddingLeft: '30px' }} placeholder="Bipar código de barras para achar o item"
            value={filtroEan} onChange={(e) => setFiltroEan(e.target.value)} />
        </div>
        <Chip cor={contados === itens.length ? '#22c55e' : '#f59e0b'}>{contados}/{itens.length} contados</Chip>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {visiveis.map((it) => {
          const destacar = it.recontar;
          return (
            <div key={it.item_id} style={{
              ...card, padding: '12px 14px', display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap',
              borderColor: destacar ? '#ef4444' : it.ja_contado ? 'rgba(34,197,94,0.5)' : 'var(--border-color)',
            }}>
              <FotoProduto foto={it.codigo_loja ? fotos[it.codigo_loja] : undefined} tamanho={72}
                codproduto={it.codigo_loja} descricao={it.descricao} onTrocada={() => setVersaoFotos((v) => v + 1)} />
              <div style={{ flex: '1 1 260px' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: '14px' }}>{it.descricao}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {it.codigo_loja && `Cód. loja ${it.codigo_loja} · `}Cód. fornecedor {it.codigo_fornecedor}{it.ean && ` · EAN ${it.ean}`}
                </div>
                {it.descricao !== it.descricao_fornecedor && (
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Na nota: {it.descricao_fornecedor}</div>
                )}
                {(it.localizacao || it.estoque_atual != null) && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginTop: '3px', fontSize: '12px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 700, color: it.localizacao ? '#38bdf8' : 'var(--text-muted)' }}>
                      <MapPin size={12} /> {it.localizacao || 'sem localização no Softsystem'}
                    </span>
                    {it.estoque_atual != null && (
                      <span style={{ color: 'var(--text-muted)' }}>Já tinha na loja antes desta nota: {it.estoque_atual.toLocaleString('pt-BR')} {it.unidade_contagem} (não somar na contagem)</span>
                    )}
                  </div>
                )}
                <div style={{ marginTop: '4px', display: 'flex', gap: '6px' }}>
                  {destacar && <Chip cor="#ef4444"><RotateCcw size={11} /> recontar</Chip>}
                  {it.ja_contado && !destacar && <Chip cor="#22c55e"><CheckCircle size={11} /> contado</Chip>}
                  {it.recontagens > 0 && <Chip cor="#6b7280">{it.recontagens} recontagem(ns)</Chip>}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <input
                  inputMode="decimal"
                  style={{ ...input, width: '110px', fontSize: '18px', textAlign: 'center', padding: '10px' }}
                  placeholder={it.ja_contado ? 'recontar' : '0'}
                  value={valores[it.item_id] ?? ''}
                  onChange={(e) => setValores({ ...valores, [it.item_id]: e.target.value })}
                />
                <span style={{ fontSize: '13px', color: 'var(--text-muted)', minWidth: '28px' }}>{it.unidade_contagem}</span>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <Botao variante="secundario" icone={<Save size={14} />} onClick={salvar} disabled={salvando}>Salvar parcial</Botao>
        <Botao icone={<CheckCircle size={14} />} onClick={finalizar} disabled={salvando}>
          {status === 'contagem_divergente' ? 'Concluir recontagem' : 'Concluir contagem'}
        </Botao>
      </div>

      {status === 'contagem_divergente' && precisaAprovacao && (
        <div style={{ ...card, borderColor: '#ef4444' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', color: 'var(--text-main)', fontWeight: 600, marginBottom: '8px' }}>
            <ShieldAlert size={16} color="#ef4444" /> A diferença continuou depois da recontagem
          </div>
          {isAdmin ? (
            <>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '0 0 8px' }}>
                Confira no detalhe da entrada o que faltou/sobrou. Ao aprovar, o estoque entra pela quantidade contada e a
                diferença fica registrada para cobrar o fornecedor.
              </p>
              <textarea style={{ ...input, minHeight: '70px' }} placeholder="Justificativa (ex.: fornecedor enviou 1 caixa a menos, avisado por WhatsApp)"
                value={justificativa} onChange={(e) => setJustificativa(e.target.value)} />
              <div style={{ marginTop: '8px', textAlign: 'right' }}>
                <Botao variante="perigo" onClick={aprovar} disabled={justificativa.trim().length < 10}>Aprovar divergência</Botao>
              </div>
            </>
          ) : (
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>Chame um administrador para aprovar a divergência.</p>
          )}
        </div>
      )}
    </div>
  );
};
