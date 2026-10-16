import React, { useEffect, useRef, useState } from 'react';
import { X, Camera, Sparkles, Trash2, Loader2 } from 'lucide-react';
import { catalogoApi, Empresa } from './comprasApi';

// Foto do produto nas telas da entrada (lançamento, contagem, preço) - pedidos de 15/10/2026:
// - "quando o produto tiver foto, aparecer quando estiver lançando";
// - a foto abria numa aba sem saída no app instalado ("aperta Esc e não acontece nada") -> agora
//   abre num visualizador dentro do sistema (X, Esc ou toque fora fecham);
// - "lançaram uma foto que não é do material: no fluxo de lançamento tem que permitir substituir a
//   foto do Softsystem por uma nova" -> botão "Trocar foto".

export interface FotoInfo { miniatura: string; foto: string; origem: 'catalogo' | 'softsystem' }

export function useFotosProdutos(empresa: Empresa, codigos: (string | number | null | undefined)[], versao = 0) {
  const [fotos, setFotos] = useState<Record<string, FotoInfo>>({});
  const chave = Array.from(new Set(codigos.filter((c) => c !== null && c !== undefined && /^\d+$/.test(String(c))).map(String))).sort().join(',');
  useEffect(() => {
    if (!chave) return;
    let vivo = true;
    catalogoApi<{ fotos: Record<string, FotoInfo> }>(`/fotos?empresa=${empresa}&cods=${chave}&v=${versao}`)
      .then((r) => vivo && setFotos(r.fotos))
      .catch(() => { /* sem foto não atrapalha o lançamento */ });
    return () => { vivo = false; };
  }, [empresa, chave, versao]);
  return fotos;
}

/** Foto em tela cheia dentro do sistema - X, Esc ou toque fora fecham. */
export const VisualizadorFoto: React.FC<{ src: string; titulo?: string; onFechar: () => void }> = ({ src, titulo, onFechar }) => {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') onFechar(); };
    window.addEventListener('keydown', tecla);
    return () => window.removeEventListener('keydown', tecla);
  }, [onFechar]);
  return (
    <div onClick={onFechar} style={{
      position: 'fixed', inset: 0, zIndex: 50000, background: 'rgba(0,0,0,0.88)', display: 'flex',
      flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '16px',
    }}>
      <button onClick={onFechar} title="Fechar (Esc)" style={{
        position: 'fixed', top: '14px', right: '14px', width: '44px', height: '44px', borderRadius: '50%', border: 'none',
        background: 'rgba(255,255,255,0.15)', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}><X size={24} /></button>
      <img src={src} alt="" onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '100%', maxHeight: 'calc(100dvh - 90px)', objectFit: 'contain', background: '#fff', borderRadius: '8px' }} />
      {titulo && <div style={{ color: '#ddd', marginTop: '10px', fontSize: '13px', textAlign: 'center' }}>{titulo}</div>}
    </div>
  );
};

/** Troca a foto do produto: foto nova (com IA) substitui a do Softsystem nas duas lojas; ou só tira a errada. */
export const TrocarFotoModal: React.FC<{ codproduto: number; descricao?: string; atual?: FotoInfo; onFechar: () => void; onTrocada: () => void }> = ({
  codproduto, descricao, atual, onFechar, onTrocada,
}) => {
  const [usarIA, setUsarIA] = useState(true);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const camRef = useRef<HTMLInputElement>(null);
  const galRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape' && !ocupado) onFechar(); };
    window.addEventListener('keydown', tecla);
    return () => window.removeEventListener('keydown', tecla);
  }, [onFechar, ocupado]);

  const enviar = async (arquivos: FileList | null) => {
    if (!arquivos?.length) return;
    setErro(null);
    setOcupado(usarIA ? 'A IA está criando a foto de venda (uns 15 segundos)...' : 'Tratando a foto...');
    try {
      const form = new FormData();
      form.append('empresa', 'servweld');
      form.append('modo', usarIA ? 'ia' : 'local');
      form.append('remover_fundo', 'true');
      Array.from(arquivos).slice(0, 5).forEach((f) => form.append('arquivos', f));
      const r = await catalogoApi<any>(`/produto/${codproduto}/imagens`, { form });
      if (!r.midias?.length) throw new Error((r.erros || []).join(' · ') || 'A foto não foi aceita.');
      onTrocada();
      onFechar();
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setOcupado(null);
    }
  };

  const retirar = async () => {
    if (!confirm('Tirar a foto atual do Softsystem (nas duas lojas)? O produto fica sem foto até alguém enviar uma nova.')) return;
    setErro(null);
    setOcupado('Retirando a foto do Softsystem...');
    try {
      await catalogoApi(`/produto/${codproduto}/retirar-fotos-softsystem`, { method: 'POST' });
      onTrocada();
      onFechar();
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setOcupado(null);
    }
  };

  const btn: React.CSSProperties = {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '12px', borderRadius: '10px',
    border: 'none', fontWeight: 700, fontSize: '14px', cursor: 'pointer', width: '100%',
  };
  return (
    <div onClick={() => !ocupado && onFechar()} style={{ position: 'fixed', inset: 0, zIndex: 45000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-secondary)', borderRadius: '14px', padding: '18px', width: '100%', maxWidth: '420px', display: 'flex', flexDirection: 'column', gap: '12px', color: 'var(--text-main)', position: 'relative' }}>
        <button onClick={onFechar} disabled={!!ocupado} title="Fechar" style={{ position: 'absolute', top: '10px', right: '10px', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}><X size={20} /></button>
        <div style={{ fontWeight: 800 }}>Trocar foto do produto</div>
        <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>#{codproduto} {descricao}</div>
        {atual && <img src={atual.miniatura} alt="" style={{ width: '120px', height: '120px', objectFit: 'contain', background: '#fff', borderRadius: '8px', alignSelf: 'center' }} />}
        <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
          A foto nova vai para o Softsystem das <strong>duas lojas</strong> e para o site, e a antiga sai da frente.
        </div>
        <label style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '13.5px' }}>
          <input type="checkbox" checked={usarIA} onChange={(e) => setUsarIA(e.target.checked)} />
          <Sparkles size={14} /> Foto de venda com IA (fundo branco, luz de estúdio)
        </label>
        <input ref={camRef} type="file" accept="image/*" capture="environment" style={{ display: 'none' }} onChange={(e) => enviar(e.target.files)} />
        <input ref={galRef} type="file" accept="image/*" multiple style={{ display: 'none' }} onChange={(e) => enviar(e.target.files)} />
        <button style={{ ...btn, background: 'var(--accent-primary)', color: '#04130d' }} disabled={!!ocupado} onClick={() => camRef.current?.click()}><Camera size={17} /> Tirar foto</button>
        <button style={{ ...btn, background: 'transparent', color: 'var(--text-main)', border: '1px solid var(--border-color)' }} disabled={!!ocupado} onClick={() => galRef.current?.click()}>Escolher do computador / galeria</button>
        {atual && (
          <button style={{ ...btn, background: 'transparent', color: '#f87171', border: '1px solid rgba(239,68,68,0.4)' }} disabled={!!ocupado} onClick={retirar}>
            <Trash2 size={15} /> Só tirar a foto errada
          </button>
        )}
        {ocupado && <div style={{ fontSize: '13px' }}><Loader2 size={13} /> {ocupado}</div>}
        {erro && <div style={{ fontSize: '13px', color: '#f87171' }}>{erro}</div>}
      </div>
    </div>
  );
};

/** Miniatura: clique amplia (sem sair do sistema); com onTrocar mostra "Trocar foto". */
export const FotoProduto: React.FC<{
  foto?: FotoInfo; tamanho?: number; codproduto?: number | string | null; descricao?: string; onTrocada?: () => void;
}> = ({ foto, tamanho = 56, codproduto, descricao, onTrocada }) => {
  const [ver, setVer] = useState(false);
  const [trocar, setTrocar] = useState(false);
  const cod = codproduto != null && /^\d+$/.test(String(codproduto)) ? Number(codproduto) : null;
  if (!foto && !(cod && onTrocada)) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px', flexShrink: 0 }}>
      {foto ? (
        <img src={foto.miniatura} alt="" loading="lazy" onClick={() => setVer(true)}
          title={foto.origem === 'catalogo' ? 'Foto do catálogo - clique para ampliar' : 'Foto do Softsystem - clique para ampliar'}
          style={{ width: tamanho, height: tamanho, objectFit: 'contain', background: '#fff', borderRadius: '6px', border: '1px solid var(--border-color)', display: 'block', cursor: 'zoom-in' }} />
      ) : (
        <div style={{ width: tamanho, height: tamanho, borderRadius: '6px', border: '1px dashed var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          <Camera size={Math.max(14, tamanho / 3)} />
        </div>
      )}
      {cod && onTrocada && (
        <button onClick={() => setTrocar(true)} style={{ background: 'none', border: 'none', color: 'var(--accent-primary)', fontSize: '11px', cursor: 'pointer', padding: 0, whiteSpace: 'nowrap' }}>
          {foto ? 'Trocar foto' : 'Pôr foto'}
        </button>
      )}
      {ver && foto && <VisualizadorFoto src={foto.foto} titulo={descricao} onFechar={() => setVer(false)} />}
      {trocar && cod && (
        <TrocarFotoModal codproduto={cod} descricao={descricao} atual={foto} onFechar={() => setTrocar(false)} onTrocada={() => onTrocada?.()} />
      )}
    </div>
  );
};
