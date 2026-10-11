import React, { useEffect, useRef, useState } from 'react';
import { Bot, Send, FileText, X, Loader2, Menu, Plus, MessageSquare, ChevronLeft, ChevronRight } from 'lucide-react';
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
  criado_em: string;
}

interface CopilotThread {
  thread_id: string;
  titulo: string | null;
  ultima_em: string | null;
}

interface TechCopilotProps {
  techName: string;
}

// Visualizador de PDF renderizado via PDF.js (canvas), não iframe nativo - pedido do usuário em
// 11/10/2026 ("o PDF não abriu"): o Portal do Técnico roda como TWA (app instalado), e o WebView
// do Android geralmente não tem o visualizador de PDF embutido que o Chrome desktop tem, então um
// <iframe> apontando pro PDF fica em branco. PDF.js renderiza em canvas puro - funciona igual em
// qualquer navegador/WebView, independente de suporte nativo a PDF. Só visualização (sem botão de
// download/compartilhar) - o documento nunca vira um arquivo baixável, pedido explícito do usuário.
const DocumentViewerModal: React.FC<{ messageId: number; titulo: string; onClose: () => void }> = ({ messageId, titulo, onClose }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const pdfRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
  const [pageNum, setPageNum] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    techApiFetchBlob(`/copilot/document/${messageId}`)
      .then(blob => blob.arrayBuffer())
      .then(buf => pdfjsLib.getDocument({ data: buf }).promise)
      .then(doc => {
        if (cancelled) return;
        pdfRef.current = doc;
        setNumPages(doc.numPages);
        setPageNum(1);
        setLoading(false);
      })
      .catch(() => { if (!cancelled) { setError('Não foi possível abrir o documento.'); setLoading(false); } });
    return () => { cancelled = true; pdfRef.current?.destroy(); };
  }, [messageId]);

  useEffect(() => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    if (!pdf || !canvas || loading) return;
    let cancelled = false;
    pdf.getPage(pageNum).then(page => {
      if (cancelled) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      const containerWidth = containerRef.current?.clientWidth || 800;
      const unscaled = page.getViewport({ scale: 1 });
      const scale = Math.min(2.2, (containerWidth - 24) / unscaled.width);
      const viewport = page.getViewport({ scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      page.render({ canvasContext: ctx, viewport, canvas });
    }).catch(() => setError('Não foi possível renderizar essa página.'));
    return () => { cancelled = true; };
  }, [pageNum, loading]);

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50000, background: 'rgba(0,0,0,0.8)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '820px', height: '92vh', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color)', borderRadius: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <FileText size={16} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{titulo}</span>
          </div>
          <button onClick={onClose} style={{ width: '30px', height: '30px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}>
            <X size={16} />
          </button>
        </div>
        <div ref={containerRef} style={{ flex: 1, minHeight: 0, background: '#2a2a2a', overflow: 'auto', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '12px' }}>
          {error ? (
            <div style={{ color: '#f87171', fontSize: '13px', padding: '20px', textAlign: 'center' }}>{error}</div>
          ) : loading ? (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
              <Loader2 size={24} className="animate-spin" />
            </div>
          ) : (
            <canvas ref={canvasRef} style={{ boxShadow: '0 4px 20px rgba(0,0,0,0.4)' }} />
          )}
        </div>
        {!loading && !error && numPages > 1 && (
          <div style={{ flexShrink: 0, padding: '10px 16px', borderTop: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px' }}>
            <button onClick={() => setPageNum(p => Math.max(1, p - 1))} disabled={pageNum <= 1} style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: pageNum <= 1 ? 'var(--text-dim, #475569)' : 'var(--text-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: pageNum <= 1 ? 'default' : 'pointer' }}>
              <ChevronLeft size={16} />
            </button>
            <span style={{ fontSize: '12.5px', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>Página {pageNum} de {numPages}</span>
            <button onClick={() => setPageNum(p => Math.min(numPages, p + 1))} disabled={pageNum >= numPages} style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: pageNum >= numPages ? 'var(--text-dim, #475569)' : 'var(--text-main)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: pageNum >= numPages ? 'default' : 'pointer' }}>
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export const TechCopilot: React.FC<TechCopilotProps> = ({ techName }) => {
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
    <div style={{ flex: 1, minHeight: 0, display: 'flex', background: 'var(--bg-primary)', position: 'relative', borderRadius: 'var(--radius-lg)', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
      {/* Menu lateral com histórico de conversas + "Nova conversa" - mesma ideia de layout do
          Claude.ai, pedido do usuário em 11/10/2026. Vira um painel deslizante por cima do chat
          em telas estreitas (o Portal do Técnico é majoritariamente usado no celular) em vez de
          dividir a tela em duas colunas permanentes, que ficaria apertado demais. */}
      {sidebarOpen && (
        <div onClick={() => setSidebarOpen(false)} style={{ position: 'absolute', inset: 0, zIndex: 10, background: 'rgba(0,0,0,0.5)' }} />
      )}
      <div
        style={{
          position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 11,
          width: '260px', maxWidth: '82vw',
          background: 'var(--bg-secondary)', borderRight: '1px solid var(--border-color)',
          display: 'flex', flexDirection: 'column',
          transform: sidebarOpen ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 0.22s ease',
        }}
      >
        <div style={{ padding: '12px', flexShrink: 0 }}>
          <button
            onClick={startNewThread}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px',
              borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)',
              background: 'transparent', color: 'var(--text-main)', fontSize: '13px', fontWeight: 700, cursor: 'pointer',
            }}
          >
            <Plus size={15} /> Nova conversa
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '0 8px 8px' }}>
          {loadingThreads ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '16px' }}>
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--text-muted)' }} />
            </div>
          ) : threads.length === 0 ? (
            <div style={{ fontSize: '12px', color: 'var(--text-dim, var(--text-muted))', padding: '10px 8px' }}>Nenhuma conversa ainda.</div>
          ) : (
            threads.map(t => (
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
            ))
          )}
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flexShrink: 0, padding: '14px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={() => setSidebarOpen(v => !v)}
            title="Histórico de conversas"
            style={{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}
          >
            <Menu size={16} />
          </button>
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
            }}
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
        <DocumentViewerModal messageId={viewerMsg.id} titulo={viewerMsg.documento_titulo || 'Documento'} onClose={() => setViewerMsg(null)} />
      )}
    </div>
  );
};
