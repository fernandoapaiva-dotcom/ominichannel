import React, { useEffect, useRef, useState } from 'react';
import { VisualizadorFoto } from './compras/FotoProduto';
import { Search, Camera, Images, Sparkles, Trash2, Star, RotateCcw, ArrowLeft, Check, Loader2, Package, MapPin, Save } from 'lucide-react';

// Aba "Fotos de Produto" do app Foto (/foto-os) - pedido do usuário em 15/10/2026: na chegada da
// mercadoria, digita o código do fornecedor / do Softsystem / a descrição, escolhe o produto, tira as
// fotos no celular e a IA transforma em FOTO DE VENDA (fundo branco, luz de estúdio) com a marca
// d'água Servsolda - e já sobe para o cadastro do produto (Catálogo do Site). A pessoa vê o
// resultado e pode voltar para a versão sem IA ou refazer.

type Empresa = 'servweld' | 'centrooeste';
interface Produto { codigo: number; descricao: string; cod_original?: string; cod_barras?: string; estoque?: number; unidade?: string; fotos: number; capa: string | null }
interface LojaLoc { localizacao: string | null; estoque: number | null; erro: string | null }
interface Midia { id: number; tipo: string; arquivo: string; miniatura: string; titulo?: string | null; fundo_removido: boolean }

const token = () => localStorage.getItem('tech_token') || localStorage.getItem('token') || '';

async function chamar<T = any>(path: string, opts: { method?: string; form?: FormData; json?: any } = {}): Promise<T> {
  const r = await fetch(`/api/v1/catalogo${path}`, {
    method: opts.method || (opts.form || opts.json ? 'POST' : 'GET'),
    headers: { Authorization: `Bearer ${token()}`, ...(opts.json ? { 'Content-Type': 'application/json' } : {}) },
    body: opts.form ?? (opts.json ? JSON.stringify(opts.json) : undefined),
  });
  let j: any = null;
  try { j = await r.json(); } catch { /* sem corpo */ }
  if (!r.ok) {
    if ([502, 503, 504].includes(r.status) && !j?.detail) throw new Error('A conexão caiu por um instante - tente de novo.');
    throw new Error(typeof j?.detail === 'string' ? j.detail : `Erro ${r.status}`);
  }
  return j as T;
}

const botao = (cor = 'var(--accent-primary)', claro = false): React.CSSProperties => ({
  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '14px', borderRadius: '12px',
  border: claro ? '1px solid var(--border-color)' : 'none', background: claro ? 'transparent' : cor,
  color: claro ? 'var(--text-main)' : '#04130d', fontWeight: 700, fontSize: '15px', cursor: 'pointer', width: '100%',
});

export const FotoProdutoApp: React.FC = () => {
  // catálogo único: o cadastro de produtos é o mesmo nos dois bancos (o Guardião replica) e a foto
  // vai para o Softsystem das duas lojas - não precisa escolher empresa
  const empresa: Empresa = 'servweld';
  const [busca, setBusca] = useState('');
  const [achados, setAchados] = useState<Produto[]>([]);
  const [buscando, setBuscando] = useState(false);
  const [produto, setProduto] = useState<Produto | null>(null);
  const [fotos, setFotos] = useState<Midia[]>([]);
  const [usarIA, setUsarIA] = useState(true);
  const [enviando, setEnviando] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  // localização (estoquista que sobe no estoque para fotografar já diz onde a peça fica)
  const [lojasLoc, setLojasLoc] = useState<Record<string, LojaLoc> | null>(null);
  const [loc, setLoc] = useState('');
  const [salvandoLoc, setSalvandoLoc] = useState(false);
  const [msgLoc, setMsgLoc] = useState<{ tipo: 'ok' | 'erro'; texto: string } | null>(null);
  const [ampliada, setAmpliada] = useState<string | null>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const galeriaRef = useRef<HTMLInputElement>(null);


  // busca enquanto digita
  useEffect(() => {
    if (produto || busca.trim().length < 2) { setAchados([]); return; }
    let vivo = true;
    setBuscando(true);
    const h = setTimeout(async () => {
      try {
        const r = await chamar<{ produtos: Produto[] }>(`/app/buscar?empresa=${empresa}&q=${encodeURIComponent(busca.trim())}`);
        if (vivo) setAchados(r.produtos);
      } catch (e: any) {
        if (vivo) setMsg({ tipo: 'erro', texto: e.message });
      } finally {
        if (vivo) setBuscando(false);
      }
    }, 400);
    return () => { vivo = false; clearTimeout(h); };
  }, [busca, empresa, produto]);

  const carregarFotos = async (cod: number) => {
    const r = await chamar<{ midias: Midia[] }>(`/produto/${cod}?empresa=${empresa}`);
    setFotos(r.midias.filter((m) => m.tipo === 'imagem'));
  };

  const carregarLoc = async (cod: number) => {
    try {
      const r = await chamar<{ lojas: Record<string, LojaLoc> }>(`/app/localizacao/${cod}`);
      setLojasLoc(r.lojas);
      setLoc(r.lojas.servweld?.localizacao || r.lojas.centrooeste?.localizacao || '');
    } catch (e: any) {
      setMsgLoc({ tipo: 'erro', texto: e.message });
    }
  };

  const salvarLoc = async () => {
    if (!produto || !loc.trim()) return;
    setSalvandoLoc(true);
    setMsgLoc(null);
    try {
      const r = await chamar<any>(`/app/localizacao/${produto.codigo}`, { method: 'PUT', json: { localizacao: loc } });
      setLojasLoc(r.lojas);
      setMsgLoc({ tipo: 'ok', texto: r.mensagem });
    } catch (e: any) {
      setMsgLoc({ tipo: 'erro', texto: e.message });
    } finally {
      setSalvandoLoc(false);
    }
  };

  const escolher = async (p: Produto) => {
    setProduto(p);
    setAchados([]);
    setMsg(null);
    setMsgLoc(null);
    setLojasLoc(null);
    setLoc('');
    carregarLoc(p.codigo);
    try { await carregarFotos(p.codigo); } catch (e: any) { setMsg({ tipo: 'erro', texto: e.message }); }
  };

  const enviar = async (lista: FileList | null) => {
    if (!produto || !lista?.length) return;
    const arquivos = Array.from(lista);
    setMsg(null);
    let ok = 0;
    const avisos: string[] = [];
    for (let i = 0; i < arquivos.length; i++) {
      setEnviando(usarIA ? `IA criando a foto de venda ${i + 1} de ${arquivos.length}... (uns 15 segundos)` : `Tratando a foto ${i + 1} de ${arquivos.length}...`);
      const form = new FormData();
      form.append('empresa', empresa);
      form.append('modo', usarIA ? 'ia' : 'local');
      form.append('remover_fundo', 'true');
      form.append('arquivos', arquivos[i]);
      try {
        const r = await chamar<any>(`/produto/${produto.codigo}/imagens`, { form });
        ok += r.midias?.length || 0;
        avisos.push(...(r.erros || []));
      } catch (e: any) {
        avisos.push(e.message);
      }
    }
    setEnviando(null);
    if (cameraRef.current) cameraRef.current.value = '';
    if (galeriaRef.current) galeriaRef.current.value = '';
    await carregarFotos(produto.codigo).catch(() => undefined);
    setMsg(avisos.length ? { tipo: ok ? 'ok' : 'erro', texto: `${ok} foto(s) pronta(s). ${avisos.join(' · ')}` }
      : { tipo: 'ok', texto: `${ok} foto(s) pronta(s) e já no cadastro do produto. Confira abaixo.` });
  };

  const refazer = async (m: Midia, modo: 'ia' | 'local') => {
    setEnviando(modo === 'ia' ? 'IA refazendo a foto de venda...' : 'Voltando para a versão sem IA...');
    setMsg(null);
    try {
      const r = await chamar<any>(`/midia/${m.id}/reprocessar?modo=${modo}`, { method: 'POST' });
      if (r.aviso) setMsg({ tipo: 'erro', texto: r.aviso });
      await carregarFotos(produto!.codigo);
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    } finally {
      setEnviando(null);
    }
  };

  const apagar = async (m: Midia) => {
    if (!confirm('Apagar esta foto do cadastro do produto?')) return;
    try {
      await chamar(`/midia/${m.id}`, { method: 'DELETE' });
      await carregarFotos(produto!.codigo);
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    }
  };

  const capa = async (m: Midia) => {
    const ids = [m.id, ...fotos.filter((f) => f.id !== m.id).map((f) => f.id)];
    try {
      await fetch(`/api/v1/catalogo/produto/${produto!.codigo}/ordem?empresa=${empresa}`, {
        method: 'PUT', headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }),
      });
      await carregarFotos(produto!.codigo);
    } catch (e: any) {
      setMsg({ tipo: 'erro', texto: e.message });
    }
  };

  // ------------------------------------------------------------ tela 1: escolher o produto
  if (!produto) {
    return (
      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '560px', margin: '0 auto' }}>
        <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>A foto vai para o cadastro do produto no Softsystem das duas lojas e para o site.</div>
        <div style={{ position: 'relative' }}>
          <Search size={18} style={{ position: 'absolute', left: '12px', top: '15px', color: 'var(--text-muted)' }} />
          <input autoFocus value={busca} onChange={(e) => setBusca(e.target.value)}
            placeholder="Código do fornecedor, código Softsystem ou descrição"
            style={{ width: '100%', padding: '14px 14px 14px 40px', fontSize: '16px', borderRadius: '12px', border: '1px solid var(--border-color)',
              background: 'var(--bg-secondary)', color: 'var(--text-main)', boxSizing: 'border-box' }} />
        </div>
        {buscando && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}><Loader2 size={13} className="spin" /> Procurando no Softsystem...</div>}
        {msg && <div style={{ color: msg.tipo === 'erro' ? '#f87171' : '#22c55e', fontSize: '13px' }}>{msg.texto}</div>}
        {achados.map((p) => (
          <button key={p.codigo} onClick={() => escolher(p)} style={{
            display: 'flex', gap: '10px', alignItems: 'center', textAlign: 'left', padding: '10px', borderRadius: '12px',
            border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-main)', cursor: 'pointer',
          }}>
            {p.capa ? <img src={p.capa} alt="" style={{ width: '52px', height: '52px', objectFit: 'contain', background: '#fff', borderRadius: '8px' }} />
              : <div style={{ width: '52px', height: '52px', borderRadius: '8px', background: 'var(--bg-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Package size={20} color="var(--text-muted)" /></div>}
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: '14px' }}>{p.descricao}</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                #{p.codigo}{p.cod_original ? ` · ${p.cod_original}` : ''} · {p.fotos ? `${p.fotos} foto(s)` : 'sem foto'}
              </div>
            </div>
          </button>
        ))}
        {!buscando && busca.trim().length >= 2 && !achados.length && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Nenhum produto encontrado.</div>}
      </div>
    );
  }

  // ------------------------------------------------------------ tela 2: fotos do produto
  return (
    <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '560px', margin: '0 auto' }}>
      <button onClick={() => { setProduto(null); setFotos([]); setMsg(null); }} style={{ ...botao('', true), padding: '8px', width: 'auto', alignSelf: 'flex-start', fontSize: '13px' }}>
        <ArrowLeft size={15} /> Trocar produto
      </button>
      <div>
        <div style={{ fontWeight: 800, fontSize: '16px', color: 'var(--text-main)' }}>{produto.descricao}</div>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>#{produto.codigo} · Servweld e Centro-Oeste</div>
      </div>

      <div style={{ padding: '12px', borderRadius: '12px', background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontWeight: 700, color: 'var(--text-main)', fontSize: '14px' }}><MapPin size={15} style={{ verticalAlign: 'middle' }} /> Localização no estoque</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input value={loc} onChange={(e) => setLoc(e.target.value.toUpperCase())} placeholder="Ex.: P.S D 03" maxLength={60}
            style={{ flex: 1, minWidth: 0, padding: '12px', fontSize: '16px', borderRadius: '10px', border: '1px solid var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-main)' }} />
          <button onClick={salvarLoc} disabled={salvandoLoc || !loc.trim()} style={{ ...botao(), width: 'auto', padding: '12px 16px' }}>
            {salvandoLoc ? <Loader2 size={16} /> : <Save size={16} />} Gravar
          </button>
        </div>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {lojasLoc ? `Servweld: ${lojasLoc.servweld?.localizacao || '—'} (estoque ${lojasLoc.servweld?.estoque ?? '—'}) · Centro-Oeste: ${lojasLoc.centrooeste?.localizacao || '—'} (estoque ${lojasLoc.centrooeste?.estoque ?? '—'})` : 'Carregando...'}
          <div>Grava nas duas lojas.</div>
        </div>
        {msgLoc && <div style={{ fontSize: '13px', color: msgLoc.tipo === 'erro' ? '#f87171' : '#22c55e' }}>{msgLoc.texto}</div>}
      </div>

      <label style={{ display: 'flex', gap: '10px', alignItems: 'center', padding: '12px', borderRadius: '12px', background: 'var(--bg-secondary)', color: 'var(--text-main)', fontSize: '14px' }}>
        <input type="checkbox" checked={usarIA} onChange={(e) => setUsarIA(e.target.checked)} style={{ width: '20px', height: '20px' }} />
        <span><Sparkles size={14} style={{ verticalAlign: 'middle' }} /> <strong>Foto de venda com IA</strong> (fundo branco, luz de estúdio). Sem marcar: só tira o fundo.</span>
      </label>

      <input ref={cameraRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }} onChange={(e) => enviar(e.target.files)} />
      <input ref={galeriaRef} type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={(e) => enviar(e.target.files)} />
      <button style={botao()} disabled={!!enviando} onClick={() => cameraRef.current?.click()}><Camera size={20} /> Tirar foto</button>
      <button style={botao('', true)} disabled={!!enviando} onClick={() => galeriaRef.current?.click()}><Images size={18} /> Escolher da galeria</button>

      {enviando && <div style={{ padding: '12px', borderRadius: '12px', background: 'rgba(59,130,246,0.12)', color: 'var(--text-main)', fontSize: '14px' }}><Loader2 size={14} /> {enviando}</div>}
      {msg && <div style={{ padding: '12px', borderRadius: '12px', fontSize: '13px', background: msg.tipo === 'erro' ? 'rgba(239,68,68,0.12)' : 'rgba(34,197,94,0.12)', color: 'var(--text-main)' }}>{msg.texto}</div>}

      <div style={{ fontSize: '12px', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', marginTop: '6px' }}>
        Fotos no cadastro ({fotos.length}) - a primeira é a capa no site
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '10px' }}>
        {fotos.map((f, i) => (
          <div key={f.id} style={{ borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--border-color)', background: 'var(--bg-secondary)' }}>
            <img src={f.miniatura} alt="" onClick={() => setAmpliada(f.arquivo)} style={{ width: '100%', aspectRatio: '1', objectFit: 'contain', background: '#fff', display: 'block', cursor: 'zoom-in' }} />
            <div style={{ padding: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
              {i === 0 ? <strong style={{ color: '#22c55e' }}>CAPA · </strong> : null}{f.titulo === 'Foto de venda (IA)' ? 'feita pela IA' : 'sem IA'}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', borderTop: '1px solid var(--border-color)' }}>
              {[
                { t: 'Capa', i: <Star size={15} />, f: () => capa(f), off: i === 0 },
                { t: 'Refazer com IA', i: <RotateCcw size={15} />, f: () => refazer(f, 'ia') },
                { t: 'Usar sem IA', i: <Check size={15} />, f: () => refazer(f, 'local') },
                { t: 'Apagar', i: <Trash2 size={15} color="#f87171" />, f: () => apagar(f) },
              ].map((b) => (
                <button key={b.t} title={b.t} disabled={!!enviando || b.off} onClick={b.f}
                  style={{ padding: '10px 0', background: 'none', border: 'none', color: 'var(--text-main)', opacity: b.off ? 0.3 : 1, cursor: 'pointer' }}>{b.i}</button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {!fotos.length && <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Este produto ainda não tem foto. Toque em "Tirar foto".</div>}
      {ampliada && <VisualizadorFoto src={ampliada} titulo={produto.descricao} onFechar={() => setAmpliada(null)} />}
    </div>
  );
};
