import React, { useEffect, useState } from 'react';
import { Search, Link2, Copy, RefreshCw } from 'lucide-react';
import { api, brl, Empresa, ItemNota, SoftsystemProduto } from './comprasApi';
import { Botao, Chip, Modal, input, td, th } from './ui';

interface Props {
  empresa: Empresa;
  item: ItemNota;
  onFechar: () => void;
  // "vincular" = é o mesmo produto já cadastrado; "modelo" = produto novo copiando o cadastro deste
  onEscolher: (produto: SoftsystemProduto, modo: 'vincular' | 'modelo') => void;
}

/**
 * Item da nota que não existe na loja: mostra os produtos parecidos do Softsystem (mesmas
 * palavras + mesmo NCM) e deixa escolher entre "é este" ou "copiar o cadastro deste" (grupo,
 * NCM e tributação vêm do modelo; descrição, EAN e código do fornecedor vêm da nota).
 */
export const ProdutoVinculoModal: React.FC<Props> = ({ empresa, item, onFechar, onEscolher }) => {
  const [produtos, setProdutos] = useState<SoftsystemProduto[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [termo, setTermo] = useState('');
  const [erro, setErro] = useState<string | null>(null);

  const carregarSimilares = async () => {
    setCarregando(true);
    setErro(null);
    try {
      const params = new URLSearchParams({ empresa, descricao: item.descricao_fornecedor });
      if (item.ncm) params.set('ncm', item.ncm);
      const r = await api<{ produtos: SoftsystemProduto[] }>(`/softsystem/similares?${params}`);
      setProdutos(r.produtos);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  };

  const buscar = async () => {
    if (termo.trim().length < 2) return;
    setCarregando(true);
    setErro(null);
    try {
      const r = await api<{ produtos: SoftsystemProduto[] }>(
        `/softsystem/buscar-produto?empresa=${empresa}&termo=${encodeURIComponent(termo.trim())}&limite=15`
      );
      setProdutos(r.produtos);
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  };

  useEffect(() => {
    carregarSimilares();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Modal titulo="Vincular produto da nota" onFechar={onFechar} largura={960}>
      <div style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '12px' }}>
        <div style={{ color: 'var(--text-main)', fontWeight: 600 }}>{item.descricao_fornecedor}</div>
        Cód. fornecedor {item.codigo_fornecedor} · EAN {item.ean || '—'} · NCM {item.ncm || '—'} · {item.unidade}
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        <input
          style={input}
          placeholder="Buscar no Softsystem por código, código de barras ou descrição..."
          value={termo}
          onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && buscar()}
        />
        <Botao variante="secundario" icone={<Search size={14} />} onClick={buscar}>Buscar</Botao>
        <Botao variante="fantasma" icone={<RefreshCw size={14} />} onClick={carregarSimilares}>Parecidos</Botao>
      </div>

      {erro && <div style={{ color: '#f87171', fontSize: '13px', marginBottom: '8px' }}>{erro}</div>}
      {carregando ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Consultando o Softsystem...</div>
      ) : produtos.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>Nenhum produto parecido encontrado.</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>Produto da loja</th>
                <th style={th}>Grupo</th>
                <th style={th}>NCM</th>
                <th style={th}>Estoque</th>
                <th style={th}>Preço</th>
                <th style={th}></th>
              </tr>
            </thead>
            <tbody>
              {produtos.map((p) => (
                <tr key={p.codigo}>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{p.descricao}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      #{p.codigo} · {p.cod_original || 'sem cód. original'} {p.cod_barras && `· EAN ${p.cod_barras}`}
                    </div>
                    {p.similaridade !== undefined && (
                      <Chip cor={p.similaridade >= 70 ? '#22c55e' : p.similaridade >= 45 ? '#f59e0b' : '#6b7280'}>
                        {p.similaridade}% parecido
                      </Chip>
                    )}
                  </td>
                  <td style={td}>{p.grupo}<div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.subgrupo}</div></td>
                  <td style={td}>
                    {p.ncm || '—'}
                    {item.ncm && p.ncm && p.ncm !== item.ncm && <div><Chip cor="#f59e0b">difere da nota</Chip></div>}
                  </td>
                  <td style={td}>{p.estoque} {p.unidade}</td>
                  <td style={td}>{brl(p.preco_venda)}</td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      <Botao icone={<Link2 size={13} />} onClick={() => onEscolher(p, 'vincular')} title="O item da nota É este produto">
                        É este
                      </Botao>
                      <Botao variante="secundario" icone={<Copy size={13} />} onClick={() => onEscolher(p, 'modelo')}
                        title="Produto novo: copiar grupo, NCM e tributação deste">
                        Copiar cadastro
                      </Botao>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
};
