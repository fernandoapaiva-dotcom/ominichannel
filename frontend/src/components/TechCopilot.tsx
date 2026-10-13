import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Send, FileText, X, Loader2, Menu, Plus, MessageSquare, PanelLeftClose, ZoomIn, ZoomOut, Maximize2, Lock } from 'lucide-react';
import { techApiFetch, techApiFetchBlob } from '../services/techApi';
import * as pdfjsLib from 'pdfjs-dist';
// @ts-ignore - Vite resolve o worker como URL de asset; é o padrão recomendado do pdfjs-dist com Vite.
import pdfjsWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorkerUrl;

interface CopilotMsg {
  id: number;
  thread_id: string;
  remetente: 'tecnico' | 'assistente';
  conteudo: string;
  documento_titulo?: string | null;
  tem_documento: boolean;
  documento_busca?: string | null;
  criado_em: string;
}

interface CopilotThread {
  thread_id: string;
  titulo: string | null;
  ultima_em: string | null;
}

interface TechCopilotProps {
  techName: string;
  techPhone?: string | null;
}

// Proteção do conteúdo do Copiloto - pedido do usuário em 13/10/2026: "não seja uma tela que possa
// bater print nem compartilhar nada, somente o visual dentro dela".
//
// LIMITE HONESTO: página web não consegue impedir o print do sistema operacional (botão do celular,
// PrintScreen, câmera de outro celular). O bloqueio de verdade no Android só vem com o app nativo
// usando FLAG_SECURE (print e gravação saem pretos) - o Portal hoje é um TWA (Chrome por dentro), que
// não permite isso. O que dá pra fazer aqui, e faz:
//   1. Marca d'água com nome + telefone do técnico + data/hora por cima do chat e de cada página do
//      PDF - um print que vazar sai identificado (o maior desestímulo possível no navegador);
//   2. Sem seleção/cópia de texto, sem menu de "salvar imagem" (toque longo / botão direito), sem
//      arrastar imagem, sem imprimir (Ctrl+P sai em branco) nem Ctrl+S;
//   3. Tecla PrintScreen (computador): limpa a área de transferência e esconde o conteúdo;
//   4. Ao sair do app / trocar de janela, o conteúdo é escondido (miniatura de "apps recentes" e
//      algumas ferramentas de recorte pegam a tela coberta).
// Os documentos já nunca vão como arquivo baixável (ver copilot_document no backend).

const watermarkUrl = (text: string, onPaper: boolean) => {
  const safe = text.replace(/[<>&"']/g, '');
  const fill = onPaper ? 'rgba(30,41,59,0.14)' : 'rgba(148,163,184,0.16)';
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='520' height='240'><text x='20' y='140' transform='rotate(-22 260 120)' fill='${fill}' font-family='Inter,Arial,sans-serif' font-size='13' font-weight='700'>${safe}</text></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
};

const useWatermarkText = (techName: string, techPhone?: string | null) => {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(t);
  }, []);
  const digits = (techPhone || '').replace(/\D/g, '');
  const phone = digits ? ` · ${digits.slice(-11)}` : '';
  const stamp = now.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  return `${techName}${phone} · ${stamp} · CONFIDENCIAL SERVWELD`;
};

const Watermark: React.FC<{ text: string; onPaper?: boolean }> = ({ text, onPaper }) => (
  <div
    aria-hidden
    style={{
      position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 20,
      backgroundImage: watermarkUrl(text, !!onPaper), backgroundRepeat: 'repeat',
    }}
  />
);

// O campo onde o técnico digita continua aceitando copiar/colar/menu - o resto não.
const blockEvent = (e: React.SyntheticEvent) => {
  const el = e.target as HTMLElement | null;
  if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return;
  e.preventDefault();
};

// Esconde o conteúdo quando o app sai de foco / vai pro fundo, bloqueia atalhos e a impressão.
const useContentShield = () => {
  const [shielded, setShielded] = useState(false);
  useEffect(() => {
    const hide = () => setShielded(true);
    const show = () => { if (!document.hidden) setShielded(false); };
    const onVisibility = () => (document.hidden ? hide() : show());
    const onKey = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (e.key === 'PrintScreen' || e.key === 'Snapshot') {
        hide();
        try { navigator.clipboard?.writeText(''); } catch { /* sem permissão - segue */ }
        setTimeout(show, 1500);
        return;
      }
      if ((e.ctrlKey || e.metaKey) && ['c', 'x', 's', 'p', 'u'].includes(k)) {
        const el = e.target as HTMLElement | null;
        if (k === 'c' || k === 'x') {
          if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return; // copiar o que ele mesmo digitou
        }
        e.preventDefault();
      }
    };
    const style = document.createElement('style');
    style.setAttribute('data-copilot-shield', '');
    style.textContent = '@media print { body * { visibility: hidden !important; } }';
    document.head.appendChild(style);
    window.addEventListener('blur', hide);
    window.addEventListener('focus', show);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('keyup', onKey, true);
    return () => {
      style.remove();
      window.removeEventListener('blur', hide);
      window.removeEventListener('focus', show);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('keyup', onKey, true);
    };
  }, []);
  return shielded;
};

const ShieldCover: React.FC = () => (
  <div style={{ position: 'fixed', inset: 0, zIndex: 70000, background: '#0b0f19', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '10px', color: 'var(--text-muted, #94a3b8)', fontSize: '14px', fontWeight: 700 }}>
    <Lock size={28} />
    Conteúdo protegido - toque para voltar ao Copiloto
  </div>
);

// Props comuns pra área protegida (sem seleção, sem menu de contexto, sem cópia, sem arrastar)
const protectedProps = {
  onContextMenu: blockEvent,
  onCopy: blockEvent,
  onCut: blockEvent,
  onDragStart: blockEvent,
};
const protectedStyle: React.CSSProperties = {
  userSelect: 'none',
  WebkitUserSelect: 'none',
  WebkitTouchCallout: 'none',
} as React.CSSProperties;


// Leitor de PDF contínuo, estilo Acrobat Reader - pedido do usuário em 13/10/2026: "abre o arquivo,
// dá zoom, passa pra próxima página rolando, descendo; hoje você tem que passar de página em página e
// num manual gigante é ruim". Todas as páginas ficam numa coluna só, rolando; cada página só é
// desenhada quando chega perto da tela (e apagada quando se afasta bastante), pra um manual de 300+
// páginas não estourar a memória do celular. Zoom: pinça (2 dedos), Ctrl+rodinha, ou os botões.
// Continua renderizando via PDF.js em canvas (não iframe - ver nota de 11/10/2026 abaixo) e sem
// botão de baixar/compartilhar, pedido explícito do usuário.
//
// Nota de 11/10/2026 (mantida): o Portal do Técnico roda como TWA (app instalado), e o WebView do
// Android geralmente não tem visualizador de PDF embutido - um <iframe> ficaria em branco.
const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4];
const PAGE_GAP = 12;

const DocumentViewerModal: React.FC<{ messageId: number; titulo: string; busca?: string | null; watermark: string; onClose: () => void }> = ({ messageId, titulo, busca, watermark, onClose }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageSizes, setPageSizes] = useState<{ w: number; h: number }[]>([]); // tamanho na escala 1
  const [fitWidth, setFitWidth] = useState(800);
  const [zoom, setZoom] = useState(1); // 1 = página na largura da tela
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchStatus, setSearchStatus] = useState<string | null>(null);
  const canvasRefs = useRef<(HTMLCanvasElement | null)[]>([]);
  const renderTasks = useRef<Map<number, pdfjsLib.RenderTask>>(new Map());
  const renderedAt = useRef<Map<number, number>>(new Map()); // página -> escala com que foi desenhada
  const visible = useRef<Set<number>>(new Set());
  const pinch = useRef<{ startDist: number; startZoom: number } | null>(null);
  const zoomRef = useRef(1);
  const pinchScaleRef = useRef(1);
  const applyZoomRef = useRef<(z: number) => void>(() => {});
  const [pinchScale, setPinchScale] = useState(1); // prévia do zoom durante a pinça (CSS), aplicado ao soltar

  // Carrega o documento + o tamanho de todas as páginas (só metadados, rápido)
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    techApiFetchBlob(`/copilot/document/${messageId}`)
      .then(blob => blob.arrayBuffer())
      .then(buf => pdfjsLib.getDocument({ data: buf }).promise)
      .then(async doc => {
        if (cancelled) return;
        pdfRef.current = doc;
        const sizes: { w: number; h: number }[] = [];
        const first = (await doc.getPage(1)).getViewport({ scale: 1 });
        for (let i = 1; i <= doc.numPages; i++) {
          if (i === 1) { sizes.push({ w: first.width, h: first.height }); continue; }
          try { const v = (await doc.getPage(i)).getViewport({ scale: 1 }); sizes.push({ w: v.width, h: v.height }); }
          catch { sizes.push({ w: first.width, h: first.height }); }
        }
        if (cancelled) return;
        setPageSizes(sizes);
        setNumPages(doc.numPages);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) { setError('Não foi possível abrir o documento.'); setLoading(false); } });
    return () => {
      cancelled = true;
      renderTasks.current.forEach(t => t.cancel());
      pdfRef.current?.destroy();
    };
  }, [messageId]);

  // Largura útil da tela (página "na largura") - acompanha girar o celular / redimensionar
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setFitWidth(Math.max(240, el.clientWidth - 24)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [loading]);

  const pageScale = useCallback((i: number) => {
    const s = pageSizes[i];
    return s ? (fitWidth / s.w) * zoom : 1;
  }, [pageSizes, fitWidth, zoom]);

  const renderPage = useCallback((i: number) => {
    const pdf = pdfRef.current;
    const canvas = canvasRefs.current[i];
    if (!pdf || !canvas) return;
    const scale = pageScale(i);
    if (renderedAt.current.get(i) === scale) return;
    renderTasks.current.get(i)?.cancel();
    pdf.getPage(i + 1).then(page => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale: scale * dpr });
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const task = page.render({ canvasContext: ctx, viewport });
      renderTasks.current.set(i, task);
      renderedAt.current.set(i, scale);
      task.promise.catch(() => renderedAt.current.delete(i));
    }).catch(() => renderedAt.current.delete(i));
  }, [pageScale]);

  const clearPage = (i: number) => {
    renderTasks.current.get(i)?.cancel();
    renderTasks.current.delete(i);
    renderedAt.current.delete(i);
    const c = canvasRefs.current[i];
    if (c) { c.width = 0; c.height = 0; }
  };

  // Desenha só as páginas perto da tela; apaga as que ficaram bem longe (memória do celular)
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !numPages) return;
    const near = new IntersectionObserver(entries => {
      entries.forEach(e => {
        const i = Number((e.target as HTMLElement).dataset.page);
        if (e.isIntersecting) { visible.current.add(i); renderPage(i); }
        else { visible.current.delete(i); }
      });
    }, { root, rootMargin: '1200px 0px' });
    const far = new IntersectionObserver(entries => {
      entries.forEach(e => { if (!e.isIntersecting) clearPage(Number((e.target as HTMLElement).dataset.page)); });
    }, { root, rootMargin: '4000px 0px' });
    root.querySelectorAll('[data-page]').forEach(el => { near.observe(el); far.observe(el); });
    return () => { near.disconnect(); far.disconnect(); };
  }, [numPages, renderPage]);

  // Zoom mudou: redesenha as páginas que estão perto da tela na escala nova
  useEffect(() => { visible.current.forEach(i => renderPage(i)); }, [zoom, fitWidth, renderPage]);

  const pageTop = (i: number) => {
    let top = 12;
    for (let k = 0; k < i; k++) top += (pageSizes[k]?.h || 0) * pageScale(k) + PAGE_GAP;
    return top;
  };

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el || !pageSizes.length) return;
    const mid = el.scrollTop + el.clientHeight / 3;
    let top = 12;
    for (let i = 0; i < pageSizes.length; i++) {
      const h = pageSizes[i].h * pageScale(i) + PAGE_GAP;
      if (mid < top + h) { if (currentPage !== i + 1) { setCurrentPage(i + 1); setPageInput(String(i + 1)); } return; }
      top += h;
    }
  };

  const goToPage = (n: number) => {
    const el = scrollRef.current;
    if (!el || !numPages) return;
    const p = Math.min(numPages, Math.max(1, n));
    el.scrollTo({ top: pageTop(p - 1) - 8 });
    setCurrentPage(p);
    setPageInput(String(p));
  };

  // Mantém a página atual no lugar quando o zoom muda (senão o leitor "pula" pra outra página)
  const applyZoom = (z: number) => {
    const el = scrollRef.current;
    const clamped = Math.min(4, Math.max(0.5, z));
    if (!el) { setZoom(clamped); return; }
    const ratio = el.scrollTop / Math.max(1, el.scrollHeight);
    setZoom(clamped);
    requestAnimationFrame(() => { el.scrollTop = ratio * el.scrollHeight; });
  };
  applyZoomRef.current = applyZoom;
  zoomRef.current = zoom;
  const stepZoom = (dir: 1 | -1) => {
    const next = dir > 0 ? ZOOM_STEPS.find(z => z > zoom + 0.01) : [...ZOOM_STEPS].reverse().find(z => z < zoom - 0.01);
    applyZoom(next ?? zoom);
  };

  // Abrir já na página da peça/termo que o bibliotecário achou (ex: o código 0742654)
  useEffect(() => {
    const pdf = pdfRef.current;
    if (!pdf || loading || !busca || !pageSizes.length) return;
    let cancelled = false;
    const alvo = busca.replace(/\s+/g, '').toLowerCase();
    setSearchStatus(`Procurando "${busca}" no documento...`);
    (async () => {
      for (let i = 1; i <= pdf.numPages; i++) {
        if (cancelled) return;
        try {
          const tc = await (await pdf.getPage(i)).getTextContent();
          const txt = tc.items.map((it: any) => it.str || '').join('').replace(/\s+/g, '').toLowerCase();
          if (txt.includes(alvo)) {
            if (cancelled) return;
            goToPage(i);
            setSearchStatus(`"${busca}" está na página ${i}`);
            setTimeout(() => !cancelled && setSearchStatus(null), 5000);
            return;
          }
        } catch { /* página sem texto (imagem) - segue */ }
      }
      if (!cancelled) { setSearchStatus(null); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, busca, pageSizes.length]);

  // Pinça com 2 dedos (prévia por CSS durante o gesto, redesenho nítido ao soltar). Eventos de toque
  // nativos (não pointer events): com 2 dedos o preventDefault segura a rolagem do navegador só
  // durante a pinça; com 1 dedo a rolagem normal continua.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const d = (t: TouchList) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
    const onStart = (e: TouchEvent) => {
      if (e.touches.length === 2) pinch.current = { startDist: d(e.touches), startZoom: zoomRef.current };
    };
    const onMove = (e: TouchEvent) => {
      if (!pinch.current || e.touches.length !== 2) return;
      e.preventDefault();
      const target = Math.min(4, Math.max(0.5, pinch.current.startZoom * d(e.touches) / pinch.current.startDist));
      pinchScaleRef.current = target / pinch.current.startZoom;
      setPinchScale(pinchScaleRef.current);
    };
    const onEnd = (e: TouchEvent) => {
      if (!pinch.current || e.touches.length >= 2) return;
      const target = pinch.current.startZoom * pinchScaleRef.current;
      pinch.current = null;
      pinchScaleRef.current = 1;
      setPinchScale(1);
      applyZoomRef.current(target);
    };
    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchmove', onMove, { passive: false });
    el.addEventListener('touchend', onEnd);
    el.addEventListener('touchcancel', onEnd);
    return () => {
      el.removeEventListener('touchstart', onStart);
      el.removeEventListener('touchmove', onMove);
      el.removeEventListener('touchend', onEnd);
      el.removeEventListener('touchcancel', onEnd);
    };
  }, [loading]);
  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    applyZoom(zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
  };

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const ctrlBtn: React.CSSProperties = { width: '34px', height: '34px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 };

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50000, background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'min(12px, 2vw)' }}>
      <div onClick={e => e.stopPropagation()} {...protectedProps} style={{ ...protectedStyle, width: '100%', maxWidth: '1100px', height: '100%', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color)', borderRadius: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          <FileText size={16} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{titulo}</span>
          <button onClick={onClose} title="Fechar" style={ctrlBtn}><X size={16} /></button>
        </div>

        {!loading && !error && (
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexShrink: 0, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--text-muted)' }}>
              Página
              <input
                value={pageInput}
                onChange={e => setPageInput(e.target.value.replace(/\D/g, ''))}
                onKeyDown={e => { if (e.key === 'Enter') goToPage(parseInt(pageInput || '1', 10)); }}
                onBlur={() => goToPage(parseInt(pageInput || String(currentPage), 10))}
                inputMode="numeric"
                style={{ width: '46px', padding: '5px 6px', textAlign: 'center', borderRadius: '6px', border: '1px solid var(--border-color)', background: 'var(--input-bg, var(--bg-secondary))', color: 'var(--text-main)', fontSize: '12.5px' }}
              />
              de {numPages}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <button onClick={() => stepZoom(-1)} title="Diminuir" style={ctrlBtn}><ZoomOut size={16} /></button>
              <span style={{ minWidth: '46px', textAlign: 'center', fontSize: '12.5px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{Math.round(zoom * 100)}%</span>
              <button onClick={() => stepZoom(1)} title="Aumentar" style={ctrlBtn}><ZoomIn size={16} /></button>
              <button onClick={() => applyZoom(1)} title="Ajustar à largura" style={ctrlBtn}><Maximize2 size={15} /></button>
            </div>
          </div>
        )}

        {searchStatus && (
          <div style={{ padding: '6px 12px', fontSize: '12px', fontWeight: 600, color: 'var(--accent-primary)', background: 'rgba(0,230,153,0.08)', borderBottom: '1px solid var(--border-color)', flexShrink: 0 }}>
            {searchStatus}
          </div>
        )}

        <div
          ref={scrollRef}
          onScroll={onScroll}
          onWheel={onWheel}
          style={{ flex: 1, minHeight: 0, background: '#2a2a2a', overflow: 'auto', touchAction: 'pan-x pan-y', WebkitOverflowScrolling: 'touch' as any }}
        >
          {error ? (
            <div style={{ color: '#f87171', fontSize: '13px', padding: '20px', textAlign: 'center' }}>{error}</div>
          ) : loading ? (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
              <Loader2 size={24} className="animate-spin" /> Abrindo documento...
            </div>
          ) : (
            <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: `${PAGE_GAP}px`, width: 'max-content', minWidth: '100%', boxSizing: 'border-box', transform: pinchScale !== 1 ? `scale(${pinchScale})` : undefined, transformOrigin: 'top center' }}>
              {pageSizes.map((s, i) => {
                const w = s.w * pageScale(i);
                const h = s.h * pageScale(i);
                return (
                  <div key={i} data-page={i} style={{ width: `${w}px`, height: `${h}px`, background: '#fff', boxShadow: '0 4px 20px rgba(0,0,0,0.4)', flexShrink: 0, position: 'relative' }}>
                    <canvas ref={el => { canvasRefs.current[i] = el; }} style={{ width: `${w}px`, height: `${h}px`, display: 'block', pointerEvents: 'none' }} />
                    <Watermark text={watermark} onPaper />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const groupThreads = (threads: CopilotThread[]) => {
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: { label: string; items: CopilotThread[] }[] = [
    { label: 'Hoje', items: [] }, { label: 'Ontem', items: [] }, { label: 'Últimos 7 dias', items: [] }, { label: 'Mais antigas', items: [] },
  ];
  threads.forEach(t => {
    const ts = t.ultima_em ? new Date(t.ultima_em.endsWith('Z') ? t.ultima_em : t.ultima_em + 'Z').getTime() : 0;
    if (ts >= startOfDay) groups[0].items.push(t);
    else if (ts >= startOfDay - 86400000) groups[1].items.push(t);
    else if (ts >= startOfDay - 7 * 86400000) groups[2].items.push(t);
    else groups[3].items.push(t);
  });
  return groups.filter(g => g.items.length);
};

// Largura a partir da qual o histórico fica fixo ao lado do chat (computador/tablet deitado).
// Abaixo disso (celular) vira gaveta pelo botão ☰ - mesmo comportamento do Claude.ai no celular.
const SIDEBAR_FIXED_MIN_WIDTH = 760;

export const TechCopilot: React.FC<TechCopilotProps> = ({ techName, techPhone }) => {
  const watermark = useWatermarkText(techName, techPhone);
  const shielded = useContentShield();
  const [threads, setThreads] = useState<CopilotThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CopilotMsg[]>([]);
  const [input, setInput] = useState('');
  const [loadingThreads, setLoadingThreads] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [viewerMsg, setViewerMsg] = useState<CopilotMsg | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [wide, setWide] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('copilot_sidebar_collapsed') === '1'; } catch { return false; }
  });
  const sidebarFixed = wide && !collapsed;

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWide(el.clientWidth >= SIDEBAR_FIXED_MIN_WIDTH));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const toggleSidebar = () => {
    if (wide) {
      setCollapsed(c => {
        try { localStorage.setItem('copilot_sidebar_collapsed', c ? '0' : '1'); } catch { /* sem storage - só não lembra */ }
        return !c;
      });
    } else {
      setSidebarOpen(v => !v);
    }
  };

  const loadThreads = () => {
    techApiFetch('/copilot/threads')
      .then(data => {
        setThreads(data || []);
        return data as CopilotThread[];
      })
      .catch(() => [])
      .finally(() => setLoadingThreads(false));
  };

  useEffect(() => { loadThreads(); }, []);

  const openThread = (threadId: string) => {
    setActiveThreadId(threadId);
    setSidebarOpen(false);
    setLoadingMessages(true);
    techApiFetch(`/copilot/threads/${threadId}/messages`)
      .then(data => setMessages(data || []))
      .catch(() => setMessages([]))
      .finally(() => setLoadingMessages(false));
  };

  const startNewThread = () => {
    setActiveThreadId(null);
    setMessages([]);
    setSidebarOpen(false);
  };

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const send = async () => {
    const texto = input.trim();
    if (!texto || sending) return;
    setInput('');
    setSending(true);
    setMessages(prev => [...prev, { id: -Date.now(), thread_id: activeThreadId || '', remetente: 'tecnico', conteudo: texto, tem_documento: false, criado_em: new Date().toISOString() }]);
    try {
      const resp: CopilotMsg = await techApiFetch('/copilot/ask', { method: 'POST', body: JSON.stringify({ mensagem: texto, thread_id: activeThreadId }) });
      const isNewThread = !activeThreadId;
      setMessages(prev => [...prev, resp]);
      if (isNewThread) {
        setActiveThreadId(resp.thread_id);
        loadThreads();
      } else {
        // Atualiza "última em" da conversa atual na lista lateral sem precisar recarregar tudo.
        setThreads(prev => prev.map(t => t.thread_id === resp.thread_id ? { ...t, ultima_em: resp.criado_em } : t));
      }
    } catch (err: any) {
      setMessages(prev => [...prev, { id: -Date.now(), thread_id: activeThreadId || '', remetente: 'assistente', conteudo: `⚠️ ${err.message || 'Erro ao perguntar pro Copiloto.'}`, tem_documento: false, criado_em: new Date().toISOString() }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div ref={rootRef} {...protectedProps} style={{ ...protectedStyle, flex: 1, minHeight: 0, display: 'flex', background: 'var(--bg-primary)', position: 'relative', borderRadius: 'var(--radius-lg)', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
      <Watermark text={watermark} />
      {shielded && <ShieldCover />}
      {/* Menu lateral com histórico de conversas + "Nova conversa" - layout do Claude.ai, pedido do
          usuário em 11/10/2026. Desde 13/10/2026 ("quero que o histórico fique sempre visível igual
          do Claude na barra lateral esquerda") fica FIXO ao lado do chat em tela larga; no celular
          continua gaveta pelo botão ☰ (duas colunas fixas ficariam apertadas demais). */}
      {!sidebarFixed && sidebarOpen && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: 'absolute', inset: 0, zIndex: 10, background: 'rgba(0,0,0,0.5)' }} />
      )}
      <div
        style={sidebarFixed ? {
          position: 'relative', flexShrink: 0, width: '270px',
          background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)',
          display: 'flex', flexDirection: 'column',
        } : {
          position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 11,
          width: '270px', maxWidth: '82vw',
          background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)',
          display: 'flex', flexDirection: 'column',
          transform: sidebarOpen ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 0.22s ease',
        }}
      >
        <div style={{ padding: '12px', flexShrink: 0, display: 'flex', gap: '8px' }}>
          <button
            onClick={startNewThread}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px',
              borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)',
              background: 'transparent', color: 'var(--text-main)', fontSize: '13px', fontWeight: 700, cursor: 'pointer',
            }}
          >
            <Plus size={15} /> Nova conversa
          </button>
          {sidebarFixed && (
            <button onClick={toggleSidebar} title="Recolher histórico" style={{ width: '40px', flexShrink: 0, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
              <PanelLeftClose size={16} />
            </button>
          )}
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 8px 8px' }}>
          {loadingThreads ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '16px' }}>
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--text-muted)' }} />
            </div>
          ) : threads.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--text-dim, var(--text-muted))', padding: '10px 8px' }}>Nenhuma conversa ainda.</div>
          ) : (
            groupThreads(threads).map(g => (
              <div key={g.label} style={{ marginBottom: '10px' }}>
                <div style={{ fontSize: '10.5px', fontWeight: 800, letterSpacing: '0.5px', textTransform: 'uppercase', color: 'var(--text-dim, var(--text-muted))', padding: '6px 10px 4px' }}>{g.label}</div>
                {g.items.map(t => (
              <button
                key={t.thread_id}
                onClick={() => openThread(t.thread_id)}
                style={{
                  width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '8px',
                  padding: '9px 10px', borderRadius: 'var(--radius-md)', border: 'none', marginBottom: '2px',
                  background: activeThreadId === t.thread_id ? 'rgba(0,230,153,0.12)' : 'transparent',
                  color: activeThreadId === t.thread_id ? 'var(--accent-primary)' : 'var(--text-main)',
                  fontSize: '12.5px', fontWeight: 600, cursor: 'pointer',
                }}
              >
                <MessageSquare size={13} style={{ flexShrink: 0, opacity: 0.7 }} />
                <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.titulo || 'Conversa'}</span>
              </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flexShrink: 0, padding: '14px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '10px' }}>
          {!sidebarFixed && <button
            onClick={toggleSidebar}
            title="Histórico de conversas"
            style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}
          >
            <Menu size={16} />
          </button>}
          <div style={{ width: '34px', height: '34px', borderRadius: '10px', background: 'var(--accent-gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#051a12', flexShrink: 0 }}>
            <Bot size={18} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-main)' }}>Copiloto Técnico</div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>Manuais, esquemas e peças</div>
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {loadingMessages ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
              <Loader2 size={20} className="animate-spin" style={{ color: 'var(--text-muted)' }} />
            </div>
          ) : messages.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px', padding: '30px 20px' }}>
              👋 Oi, {techName.split(' ')[0]}! Pergunta qualquer coisa de manual, esquema elétrico, código de peça ou procedimento - eu busco na base técnica da loja.
            </div>
          ) : (
            messages.map(msg => {
              const isTech = msg.remetente === 'tecnico';
              return (
                <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', alignItems: isTech ? 'flex-end' : 'flex-start', gap: '6px' }}>
                  <div
                    style={{
                      maxWidth: '88%',
                      padding: '11px 15px',
                      borderRadius: isTech ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                      background: isTech ? 'var(--bubble-outgoing, #064e3b)' : 'var(--bubble-incoming, #182234)',
                      color: isTech ? 'var(--bubble-outgoing-text, #ecfdf5)' : 'var(--bubble-incoming-text, #f0f4f8)',
                      border: isTech ? '1px solid var(--bubble-outgoing-border, rgba(0,230,153,0.3))' : '1px solid var(--bubble-incoming-border, rgba(255,255,255,0.08))',
                      fontSize: '13.5px',
                      lineHeight: 1.5,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {msg.conteudo}
                  </div>
                  {msg.tem_documento && msg.documento_titulo && (
                    <button
                      onClick={() => setViewerMsg(msg)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: '6px', padding: '7px 12px',
                        borderRadius: 'var(--radius-md)', border: '1px solid rgba(0,230,153,0.35)',
                        background: 'rgba(0,230,153,0.08)', color: 'var(--accent-primary)',
                        fontSize: '12px', fontWeight: 700, cursor: 'pointer', maxWidth: '88%',
                      }}
                    >
                      <FileText size={14} />
                      <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>Ver {msg.documento_titulo}</span>
                    </button>
                  )}
                </div>
              );
            })
          )}
          {sending && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '12px' }}>
              <Loader2 size={14} className="animate-spin" /> Copiloto pesquisando...
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div style={{ flexShrink: 0, padding: '12px 16px', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px' }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Pergunte sobre um manual, esquema, código de peça..."
            style={{
              flex: 1, padding: '11px 14px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)',
              background: 'var(--input-bg, var(--bg-secondary))', color: 'var(--text-main)', fontSize: '13.5px', outline: 'none',
              userSelect: 'text', WebkitUserSelect: 'text',
            } as React.CSSProperties}
          />
          <button
            onClick={send}
            disabled={!input.trim() || sending}
            style={{
              width: '42px', height: '42px', borderRadius: 'var(--radius-md)', border: 'none',
              background: input.trim() && !sending ? 'var(--accent-gradient)' : 'rgba(255,255,255,0.06)',
              color: input.trim() && !sending ? '#051a12' : 'var(--text-dim, var(--text-muted))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: input.trim() && !sending ? 'pointer' : 'default', flexShrink: 0,
            }}
          >
            <Send size={17} />
          </button>
        </div>
      </div>

      {viewerMsg && (
        <DocumentViewerModal messageId={viewerMsg.id} titulo={viewerMsg.documento_titulo || 'Documento'} busca={viewerMsg.documento_busca} watermark={watermark} onClose={() => setViewerMsg(null)} />
      )}
    </div>
  );
};
