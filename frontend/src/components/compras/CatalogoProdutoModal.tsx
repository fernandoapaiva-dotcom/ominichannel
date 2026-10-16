import React, { useEffect, useRef, useState } from 'react';
import { ImagePlus, Trash2, Star, Sparkles, Save, FileText, Youtube, Plus, Download, Globe } from 'lucide-react';
import { brl, catalogoApi, Empresa } from './comprasApi';
import { Aviso, Botao, Campo, Chip, Modal, input } from './ui';
import { VisualizadorFoto } from './FotoProduto';

// Etapas 5 e 6 da entrada de nota (15/10/2026): fotos com fundo branco + marca d'água Servsolda,
// PDFs técnicos, vídeos do YouTube, textos da aba "Para Lojas Web" (vão também para o Softsystem)
// e a marcação "publicar no site". A IA sugere os textos; a pessoa revisa e salva.

interface Midia { id: number; tipo: 'imagem' | 'pdf'; arquivo: string; miniatura: string; titulo?: string; origem: string; fundo_removido: boolean }
interface Spec { nome: string; valor: string }
interface Video { titulo: string; url: string }
interface Catalogo {
  publicar_site: boolean; destaque: boolean; titulo_web: string | null; descricao_web: string | null;
  especificacoes: Spec[]; videos: Video[]; keywords: string | null; dica: string | null; material: string | null;
  cor: string | null; garantia: string | null; frete_gratis: boolean; nunca_mostra_preco: boolean; desconto_web_pct: number | null;
  softsystem_erro?: string | null; novo?: boolean;
}
interface Dados {
  softsystem: { codigo: number; descricao: string; preco: number; estoque: number; marca: string; unidade: string };
  catalogo: Catalogo; midias: Midia[]; fotos_softsystem: string[]; pasta_softsystem_configurada: boolean;
}

const area: React.CSSProperties = { ...input, width: '100%', minHeight: '110px', fontFamily: 'inherit', resize: 'vertical' };
const secao: React.CSSProperties = { fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', margin: '6px 0 2px' };

export const CatalogoProdutoModal: React.FC<{ empresa: Empresa; codproduto: number; onFechar: () => void; onSalvo?: () => void }> = ({
  empresa, codproduto, onFechar, onSalvo,
}) => {
  const [dados, setDados] = useState<Dados | null>(null);
  const [c, setC] = useState<Catalogo | null>(null);
  const [msg, setMsg] = useState<{ tipo: 'ok' | 'erro' | 'alerta'; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [links, setLinks] = useState('');
  const [removerFundo, setRemoverFundo] = useState(true);
  const [pdfLink, setPdfLink] = useState('');
  const [pdfTitulo, setPdfTitulo] = useState('');
  const [ampliada, setAmpliada] = useState<string | null>(null);
  const fotoRef = useRef<HTMLInputElement>(null);
  const pdfRef = useRef<HTMLInputElement>(null);

  const carregar = async (manterTextos = false) => {
    try {
      const r = await catalogoApi<Dados>(`/produto/${codproduto}?empresa=${empresa}`);
      setDados(r);
      if (!manterTextos) setC(r.catalogo);
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    }
  };
  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codproduto, empresa]);

  const mudar = (m: Partial<Catalogo>) => setC((x) => (x ? { ...x, ...m } : x));
  const fotos = (dados?.midias || []).filter((m) => m.tipo === 'imagem');
  const pdfs = (dados?.midias || []).filter((m) => m.tipo === 'pdf');

  const executar = async (rotulo: string, fn: () => Promise<any>) => {
    setOcupado(rotulo);
    setMsg(null);
    try {
      await fn();
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    } finally {
      setOcupado(null);
    }
  };

  const enviarFotos = (arquivos?: FileList | null) => executar('Tratando as fotos (fundo branco + marca d\'água)...', async () => {
    const form = new FormData();
    form.append('empresa', empresa);
    form.append('links', links);
    form.append('remover_fundo', String(removerFundo));
    Array.from(arquivos || []).forEach((f) => form.append('arquivos', f));
    const r = await catalogoApi<any>(`/produto/${codproduto}/imagens`, { form });
    setLinks('');
    if (fotoRef.current) fotoRef.current.value = '';
    setMsg(r.erros?.length ? { tipo: 'alerta', texto: `${r.midias.length} foto(s) pronta(s). Problemas: ${r.erros.join(' · ')}` }
      : { tipo: 'ok', texto: `${r.midias.length} foto(s) pronta(s).` });
    await carregar(true);
  });

  const importarSoftsystem = () => executar('Importando as fotos do Softsystem...', async () => {
    const r = await catalogoApi<any>(`/produto/${codproduto}/importar-softsystem?empresa=${empresa}&remover_fundo=${removerFundo}`, { method: 'POST' });
    setMsg({ tipo: 'ok', texto: r.mensagem || `${r.midias.length} foto(s) importada(s) do Softsystem.` });
    await carregar(true);
  });

  const apagar = (m: Midia) => {
    if (!confirm(m.tipo === 'pdf' ? `Remover o PDF "${m.titulo}"?` : 'Remover esta foto?')) return;
    executar('Removendo...', async () => {
      await catalogoApi(`/midia/${m.id}`, { method: 'DELETE' });
      await carregar(true);
    });
  };

  const tornarCapa = (m: Midia) => executar('Salvando a ordem...', async () => {
    const ids = [m.id, ...fotos.filter((f) => f.id !== m.id).map((f) => f.id), ...pdfs.map((p) => p.id)];
    await catalogoApi(`/produto/${codproduto}/ordem?empresa=${empresa}`, { method: 'PUT', body: { ids } });
    await carregar(true);
  });

  const enviarPdf = (arquivo?: File) => executar('Guardando o PDF...', async () => {
    const form = new FormData();
    form.append('empresa', empresa);
    form.append('titulo', pdfTitulo);
    if (arquivo) form.append('arquivo', arquivo);
    else form.append('link', pdfLink);
    await catalogoApi(`/produto/${codproduto}/pdfs`, { form });
    setPdfLink('');
    setPdfTitulo('');
    if (pdfRef.current) pdfRef.current.value = '';
    await carregar(true);
  });

  const gerarTextos = () => executar('A IA está lendo os manuais da loja (RAG) e pesquisando o produto...', async () => {
    const r = await catalogoApi<any>(`/produto/${codproduto}/gerar-textos?empresa=${empresa}`, { method: 'POST' });
    const s = r.sugestao;
    mudar({
      titulo_web: s.titulo_web || c?.titulo_web || null, descricao_web: s.descricao_web || c?.descricao_web || null,
      especificacoes: s.especificacoes?.length ? s.especificacoes : c?.especificacoes || [], keywords: s.keywords || c?.keywords || null,
      dica: s.dica || c?.dica || null, material: s.material || c?.material || null, garantia: s.garantia || c?.garantia || null,
    });
    const fontes: string[] = s.fontes_rag || [];
    setMsg({
      tipo: 'alerta',
      texto: fontes.length
        ? `Textos sugeridos a partir dos manuais da loja (RAG): ${fontes.slice(0, 4).join(' · ')}${fontes.length > 4 ? ` e mais ${fontes.length - 4}` : ''} - completados com o Google. Revise antes de salvar.`
        : 'Nenhum manual da loja (RAG) era deste produto - textos sugeridos com base no Google. Revise antes de salvar.',
    });
  });

  const salvar = () => executar('Salvando...', async () => {
    if (!c) return;
    const r = await catalogoApi<any>(`/produto/${codproduto}?empresa=${empresa}`, { method: 'PUT', body: c });
    setMsg(r.aviso ? { tipo: 'alerta', texto: r.aviso } : { tipo: 'ok', texto: r.teste ? 'Salvo (Softsystem em modo TESTE: gravado só na cópia).' : 'Salvo no OminiChannel e no Softsystem (aba Para Lojas Web).' });
    onSalvo?.();
    await carregar(true);
  });

  if (!dados || !c) {
    return (
      <Modal titulo="Fotos e site do produto" onFechar={onFechar} largura={980}>
        {msg ? <Aviso tipo="erro">{msg.texto}</Aviso> : <div style={{ color: 'var(--text-muted)' }}>Carregando...</div>}
      </Modal>
    );
  }
  const sw = dados.softsystem;

  return (
    <Modal titulo={`Fotos e site · ${sw.codigo} ${sw.descricao}`} onFechar={onFechar} largura={980}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '13px' }}>
        <div style={{ color: 'var(--text-muted)' }}>
          Preço no Softsystem <strong>{brl(sw.preco)}</strong> · estoque {sw.estoque} {sw.unidade}{sw.marca && ` · marca ${sw.marca}`}
          {c.novo && <> · <Chip cor="#3b82f6">ainda não está no catálogo</Chip></>}
        </div>
        {msg && <Aviso tipo={msg.tipo} onFechar={() => setMsg(null)}>{msg.texto}</Aviso>}
        {ocupado && <Aviso tipo="info">{ocupado}</Aviso>}
        {c.softsystem_erro && <Aviso tipo="alerta">Última gravação no Softsystem falhou: {c.softsystem_erro}</Aviso>}

        {/* ---------------- fotos */}
        <div style={secao}>Fotos (a primeira é a capa no site)</div>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          {fotos.map((f, i) => (
            <div key={f.id} style={{ width: '132px', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden', background: '#fff' }}>
              <img src={f.miniatura} alt="" onClick={() => setAmpliada(f.arquivo)} style={{ width: '130px', height: '130px', objectFit: 'contain', display: 'block', cursor: 'zoom-in' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px', background: 'var(--bg-secondary)' }}>
                {i === 0 ? <Chip cor="#22c55e">capa</Chip> : (
                  <button title="Usar como capa" onClick={() => tornarCapa(f)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}><Star size={14} /></button>
                )}
                <button title="Remover" onClick={() => apagar(f)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f87171' }}><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
          {!fotos.length && <div style={{ color: 'var(--text-muted)' }}>Nenhuma foto ainda.</div>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '10px', alignItems: 'start' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <input ref={fotoRef} type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={(e) => enviarFotos(e.target.files)} />
            <Botao icone={<ImagePlus size={14} />} onClick={() => fotoRef.current?.click()} disabled={!!ocupado}>Enviar fotos do computador/celular</Botao>
            <label style={{ display: 'flex', gap: '6px', alignItems: 'center', color: 'var(--text-muted)' }}>
              <input type="checkbox" checked={removerFundo} onChange={(e) => setRemoverFundo(e.target.checked)} />
              Remover o fundo e deixar branco (fotos que já têm fundo branco ficam como estão)
            </label>
            {dados.fotos_softsystem.length > 0 && (
              <Botao variante="secundario" icone={<Download size={14} />} onClick={importarSoftsystem} disabled={!!ocupado}>
                Importar {dados.fotos_softsystem.length} foto(s) que já estão no Softsystem
              </Botao>
            )}
            {!dados.pasta_softsystem_configurada && (
              <span style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>Pasta de fotos do Softsystem desta loja ainda não ligada ao OminiChannel.</span>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <textarea style={{ ...area, minHeight: '64px' }} placeholder="Ou cole links de fotos (um por linha)" value={links} onChange={(e) => setLinks(e.target.value)} />
            <Botao variante="secundario" icone={<ImagePlus size={14} />} onClick={() => enviarFotos(null)} disabled={!!ocupado || !links.trim()}>Baixar fotos dos links</Botao>
          </div>
        </div>

        {/* ---------------- pdfs e vídeos */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '14px' }}>
          <div>
            <div style={secao}><FileText size={12} /> Manuais e fichas técnicas (PDF)</div>
            {pdfs.map((p) => (
              <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '6px', padding: '4px 0' }}>
                <a href={p.arquivo} target="_blank" rel="noreferrer">{p.titulo}</a>
                <button onClick={() => apagar(p)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f87171' }}><Trash2 size={13} /></button>
              </div>
            ))}
            <input style={{ ...input, width: '100%', marginTop: '4px' }} placeholder="Título (ex.: Manual do usuário)" value={pdfTitulo} onChange={(e) => setPdfTitulo(e.target.value)} />
            <div style={{ display: 'flex', gap: '6px', marginTop: '6px' }}>
              <input style={{ ...input, flex: 1 }} placeholder="Link do PDF do fabricante" value={pdfLink} onChange={(e) => setPdfLink(e.target.value)} />
              <Botao variante="secundario" onClick={() => enviarPdf()} disabled={!!ocupado || !pdfLink.trim()}>Baixar</Botao>
            </div>
            <input ref={pdfRef} type="file" accept="application/pdf" style={{ display: 'none' }} onChange={(e) => e.target.files?.[0] && enviarPdf(e.target.files[0])} />
            <Botao variante="fantasma" icone={<Plus size={13} />} onClick={() => pdfRef.current?.click()} disabled={!!ocupado} style={{ marginTop: '6px' }}>Enviar PDF do computador</Botao>
          </div>
          <div>
            <div style={secao}><Youtube size={12} /> Vídeos do YouTube</div>
            {c.videos.map((v, i) => (
              <div key={i} style={{ display: 'flex', gap: '6px', marginBottom: '6px' }}>
                <input style={{ ...input, width: '38%' }} placeholder="Título" value={v.titulo} onChange={(e) => mudar({ videos: c.videos.map((x, j) => (j === i ? { ...x, titulo: e.target.value } : x)) })} />
                <input style={{ ...input, flex: 1 }} placeholder="https://youtu.be/..." value={v.url} onChange={(e) => mudar({ videos: c.videos.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)) })} />
                <button onClick={() => mudar({ videos: c.videos.filter((_, j) => j !== i) })} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f87171' }}><Trash2 size={13} /></button>
              </div>
            ))}
            <Botao variante="fantasma" icone={<Plus size={13} />} onClick={() => mudar({ videos: [...c.videos, { titulo: '', url: '' }] })}>Adicionar vídeo</Botao>
          </div>
        </div>

        {/* ---------------- textos */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={secao}>Textos do site (aba "Para Lojas Web" do Softsystem)</div>
          <Botao variante="secundario" icone={<Sparkles size={14} />} onClick={gerarTextos} disabled={!!ocupado}>Sugerir textos com IA</Botao>
        </div>
        <Campo rotulo="Título no site"><input style={{ ...input, width: '100%' }} maxLength={200} value={c.titulo_web || ''} placeholder={sw.descricao} onChange={(e) => mudar({ titulo_web: e.target.value })} /></Campo>
        <Campo rotulo="Descrição (aceita <p> e <ul><li>)"><textarea style={area} value={c.descricao_web || ''} onChange={(e) => mudar({ descricao_web: e.target.value })} /></Campo>
        <div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>Ficha técnica</div>
          {c.especificacoes.map((s, i) => (
            <div key={i} style={{ display: 'flex', gap: '6px', marginBottom: '4px' }}>
              <input style={{ ...input, width: '35%' }} placeholder="Ex.: Diâmetro" value={s.nome} onChange={(e) => mudar({ especificacoes: c.especificacoes.map((x, j) => (j === i ? { ...x, nome: e.target.value } : x)) })} />
              <input style={{ ...input, flex: 1 }} placeholder="Ex.: 0,8 mm" value={s.valor} onChange={(e) => mudar({ especificacoes: c.especificacoes.map((x, j) => (j === i ? { ...x, valor: e.target.value } : x)) })} />
              <button onClick={() => mudar({ especificacoes: c.especificacoes.filter((_, j) => j !== i) })} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f87171' }}><Trash2 size={13} /></button>
            </div>
          ))}
          <Botao variante="fantasma" icone={<Plus size={13} />} onClick={() => mudar({ especificacoes: [...c.especificacoes, { nome: '', valor: '' }] })}>Adicionar linha</Botao>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px' }}>
          <Campo rotulo="Palavras-chave (busca/Google)"><input style={{ ...input, width: '100%' }} maxLength={255} value={c.keywords || ''} onChange={(e) => mudar({ keywords: e.target.value })} /></Campo>
          <Campo rotulo="Dica"><input style={{ ...input, width: '100%' }} maxLength={255} value={c.dica || ''} onChange={(e) => mudar({ dica: e.target.value })} /></Campo>
          <Campo rotulo="Material"><input style={{ ...input, width: '100%' }} maxLength={200} value={c.material || ''} onChange={(e) => mudar({ material: e.target.value })} /></Campo>
          <Campo rotulo="Cor"><input style={{ ...input, width: '100%' }} maxLength={150} value={c.cor || ''} onChange={(e) => mudar({ cor: e.target.value })} /></Campo>
          <Campo rotulo="Garantia"><input style={{ ...input, width: '100%' }} maxLength={200} value={c.garantia || ''} onChange={(e) => mudar({ garantia: e.target.value })} /></Campo>
          <Campo rotulo="Desconto no site (%)"><input style={{ ...input, width: '100%' }} inputMode="decimal" value={c.desconto_web_pct ?? ''} onChange={(e) => mudar({ desconto_web_pct: e.target.value === '' ? null : Number(e.target.value.replace(',', '.')) })} /></Campo>
        </div>

        {/* ---------------- publicação */}
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', padding: '10px', borderRadius: '8px', background: 'var(--bg-secondary)' }}>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center', fontWeight: 700 }}>
            <input type="checkbox" checked={c.publicar_site} onChange={(e) => mudar({ publicar_site: e.target.checked })} /> <Globe size={14} /> Publicar no site
          </label>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}><input type="checkbox" checked={c.destaque} onChange={(e) => mudar({ destaque: e.target.checked })} /> Destaque na página inicial</label>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}><input type="checkbox" checked={c.frete_gratis} onChange={(e) => mudar({ frete_gratis: e.target.checked })} /> Frete grátis</label>
          <label style={{ display: 'flex', gap: '6px', alignItems: 'center' }}><input type="checkbox" checked={c.nunca_mostra_preco} onChange={(e) => mudar({ nunca_mostra_preco: e.target.checked })} /> Não mostrar preço ("sob consulta")</label>
        </div>

        {ampliada && <VisualizadorFoto src={ampliada} titulo={sw.descricao} onFechar={() => setAmpliada(null)} />}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
          <Botao variante="fantasma" onClick={onFechar}>Fechar</Botao>
          <Botao icone={<Save size={14} />} onClick={salvar} disabled={!!ocupado}>Salvar</Botao>
        </div>
      </div>
    </Modal>
  );
};
