import React, { useEffect, useState } from 'react';
import { ImageOff, Globe } from 'lucide-react';
import { catalogoApi, Entrada } from './comprasApi';
import { Aviso, Botao, Chip, card, td, th } from './ui';
import { CatalogoProdutoModal } from './CatalogoProdutoModal';

// Etapa 4 da tela da entrada (= etapas 5/6 do roteiro, 15/10/2026): para cada produto da nota,
// fotos (fundo branco + marca d'água), vídeos, PDFs, textos e a marcação "subir no site".

interface Resumo { codproduto: number; publicar_site: boolean; capa: string | null; fotos: number; pdfs: number; videos: number; falta: string[] }

export const FotosSiteEntrada: React.FC<{ entrada: Entrada }> = ({ entrada }) => {
  const [resumo, setResumo] = useState<Record<number, Resumo>>({});
  const [aberto, setAberto] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = async () => {
    try {
      const r = await catalogoApi<{ produtos: Resumo[] }>(`/produtos?empresa=${entrada.empresa}`);
      setResumo(Object.fromEntries(r.produtos.map((p) => [p.codproduto, p])));
    } catch (e: any) {
      setErro(e.message);
    }
  };
  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entrada.id]);

  const itens = entrada.itens.filter((i) => i.softsystem_prod_codigo && /^\d+$/.test(String(i.softsystem_prod_codigo)));
  const noSite = itens.filter((i) => resumo[Number(i.softsystem_prod_codigo)]?.publicar_site).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <Aviso tipo="info">
        Para cada produto: envie as fotos (upload ou link - o fundo fica branco e entra a marca d'água Servsolda), vídeos do YouTube,
        PDFs técnicos e os textos. Marque <strong>Publicar no site</strong> para ele aparecer no site, no menu do grupo/subgrupo dele.
        <div style={{ marginTop: '4px' }}><Globe size={13} style={{ verticalAlign: 'middle' }} /> {noSite} de {itens.length} produto(s) desta nota no site.</div>
      </Aviso>
      {erro && <Aviso tipo="erro" onFechar={() => setErro(null)}>{erro}</Aviso>}
      <div style={{ ...card, padding: 0, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '640px' }}>
          <thead><tr><th style={th}></th><th style={th}>Produto</th><th style={th}>Site</th><th style={th}>Conteúdo</th><th style={th}></th></tr></thead>
          <tbody>
            {itens.map((i) => {
              const cod = Number(i.softsystem_prod_codigo);
              const r = resumo[cod];
              return (
                <tr key={i.id}>
                  <td style={{ ...td, width: '64px' }}>
                    {r?.capa ? <img src={r.capa} alt="" style={{ width: '56px', height: '56px', objectFit: 'contain', background: '#fff', borderRadius: '6px' }} />
                      : <ImageOff size={22} color="var(--text-muted)" />}
                  </td>
                  <td style={td}><strong>#{cod}</strong> {i.softsystem_descricao || i.descricao_fornecedor}</td>
                  <td style={td}>{r?.publicar_site ? <Chip cor="#22c55e">no site</Chip> : <Chip cor="#6b7280">fora do site</Chip>}</td>
                  <td style={{ ...td, fontSize: '12px' }}>
                    {r ? `${r.fotos} foto(s) · ${r.pdfs} PDF · ${r.videos} vídeo(s)` : 'nada ainda'}
                    {r && r.falta.length > 0 && <div style={{ color: '#f59e0b' }}>falta: {r.falta.join(', ')}</div>}
                  </td>
                  <td style={{ ...td, textAlign: 'right' }}><Botao onClick={() => setAberto(cod)}>Fotos e site</Botao></td>
                </tr>
              );
            })}
            {!itens.length && <tr><td colSpan={5} style={{ ...td, color: 'var(--text-muted)' }}>Nenhum item vinculado a produto do Softsystem.</td></tr>}
          </tbody>
        </table>
      </div>
      {aberto !== null && (
        <CatalogoProdutoModal empresa={entrada.empresa} codproduto={aberto} onFechar={() => { setAberto(null); carregar(); }} onSalvo={carregar} />
      )}
    </div>
  );
};
