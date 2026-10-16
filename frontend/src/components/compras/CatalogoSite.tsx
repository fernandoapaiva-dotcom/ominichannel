import React, { useEffect, useState } from 'react';
import { Search, Globe, ExternalLink, ImageOff } from 'lucide-react';
import { api, brl, catalogoApi, Empresa, SoftsystemProduto } from './comprasApi';
import { Aviso, Botao, Chip, card, input, td, th } from './ui';
import { CatalogoProdutoModal } from './CatalogoProdutoModal';

// Catálogo do site (etapa 6, 15/10/2026): qualquer produto do Softsystem pode ganhar fotos, textos e
// ir para o site da Hostinger. Lista o que já foi trabalhado e o que falta em cada um.

interface ItemCatalogo {
  codproduto: number; descricao: string; titulo_web: string | null; publicar_site: boolean; destaque: boolean;
  capa: string | null; fotos: number; pdfs: number; videos: number; preco: number | null; estoque: number | null;
  falta: string[]; softsystem_erro: string | null; atualizado_por: string | null;
}

export const CatalogoSite: React.FC<{ empresa: Empresa }> = ({ empresa }) => {
  const [lista, setLista] = useState<ItemCatalogo[]>([]);
  const [busca, setBusca] = useState('');
  const [achados, setAchados] = useState<SoftsystemProduto[]>([]);
  const [aberto, setAberto] = useState<number | null>(null);
  const [soPublicados, setSoPublicados] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = async () => {
    try {
      const r = await catalogoApi<{ produtos: ItemCatalogo[] }>(`/produtos?empresa=${empresa}&so_publicados=${soPublicados}`);
      setLista(r.produtos);
    } catch (e: any) {
      setErro(e.message);
    }
  };
  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [empresa, soPublicados]);

  const buscar = async () => {
    if (busca.trim().length < 2) return;
    try {
      const r = await api<{ produtos: SoftsystemProduto[] }>(`/softsystem/buscar-produto?empresa=${empresa}&termo=${encodeURIComponent(busca.trim())}&limite=15`);
      setAchados(r.produtos);
    } catch (e: any) {
      setErro(e.message);
    }
  };

  const publicados = lista.filter((p) => p.publicar_site).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <Aviso tipo="info">
        Produtos marcados para o site aparecem no site da Servsolda (Hostinger) com as fotos tratadas (fundo branco + marca d'água),
        textos, ficha técnica, vídeos e PDFs. Preço e estoque vêm do Softsystem na hora. O menu do site segue os grupos e subgrupos do Softsystem.
      </Aviso>
      {erro && <Aviso tipo="erro" onFechar={() => setErro(null)}>{erro}</Aviso>}

      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input style={{ ...input, flex: 1 }} placeholder="Buscar produto no Softsystem (código, código de barras ou descrição) para trabalhar no site..."
            value={busca} onChange={(e) => setBusca(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && buscar()} />
          <Botao icone={<Search size={14} />} onClick={buscar}>Buscar</Botao>
        </div>
        {achados.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {achados.map((p) => (
                <tr key={p.codigo}>
                  <td style={td}><strong>#{p.codigo}</strong> {p.descricao}<div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.grupo} · estoque {p.estoque} · {brl(p.preco_venda)}</div></td>
                  <td style={{ ...td, textAlign: 'right' }}><Botao variante="secundario" onClick={() => setAberto(p.codigo)}>Fotos e site</Botao></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: '13px', color: 'var(--text-main)' }}>
          <Globe size={14} style={{ verticalAlign: 'middle' }} /> <strong>{publicados}</strong> produto(s) no site · {lista.length} trabalhado(s)
        </div>
        <label style={{ fontSize: '12.5px', color: 'var(--text-muted)', display: 'flex', gap: '6px', alignItems: 'center' }}>
          <input type="checkbox" checked={soPublicados} onChange={(e) => setSoPublicados(e.target.checked)} /> só os que estão no site
        </label>
      </div>

      <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '760px' }}>
          <thead><tr><th style={th}></th><th style={th}>Produto</th><th style={th}>Site</th><th style={th}>Conteúdo</th><th style={th}>Preço / estoque</th><th style={th}></th></tr></thead>
          <tbody>
            {lista.map((p) => (
              <tr key={p.codproduto}>
                <td style={{ ...td, width: '64px' }}>
                  {p.capa ? <img src={p.capa} alt="" style={{ width: '56px', height: '56px', objectFit: 'contain', background: '#fff', borderRadius: '6px' }} />
                    : <ImageOff size={22} color="var(--text-muted)" />}
                </td>
                <td style={td}><strong>#{p.codproduto}</strong> {p.titulo_web || p.descricao}
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.atualizado_por && `por ${p.atualizado_por}`}</div>
                  {p.softsystem_erro && <Chip cor="#f59e0b">não foi para o Softsystem</Chip>}
                </td>
                <td style={td}>{p.publicar_site ? <Chip cor="#22c55e">no site{p.destaque ? ' · destaque' : ''}</Chip> : <Chip cor="#6b7280">fora do site</Chip>}</td>
                <td style={{ ...td, fontSize: '12px' }}>
                  {p.fotos} foto(s) · {p.pdfs} PDF · {p.videos} vídeo(s)
                  {p.falta.length > 0 && <div style={{ color: '#f59e0b' }}>falta: {p.falta.join(', ')}</div>}
                </td>
                <td style={td}>{brl(p.preco)}<div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>estoque {p.estoque ?? '—'}</div></td>
                <td style={{ ...td, textAlign: 'right' }}><Botao variante="secundario" icone={<ExternalLink size={13} />} onClick={() => setAberto(p.codproduto)}>Abrir</Botao></td>
              </tr>
            ))}
            {!lista.length && <tr><td style={{ ...td, color: 'var(--text-muted)' }} colSpan={6}>Nenhum produto trabalhado ainda - busque um acima ou use a etapa "Fotos e site" da entrada de nota.</td></tr>}
          </tbody>
        </table>
      </div>

      {aberto !== null && (
        <CatalogoProdutoModal empresa={empresa} codproduto={aberto} onFechar={() => { setAberto(null); carregar(); }} onSalvo={carregar} />
      )}
    </div>
  );
};
