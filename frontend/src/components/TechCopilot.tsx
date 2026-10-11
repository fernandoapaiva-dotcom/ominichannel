import React, { useEffect, useRef, useState } from 'react';
import { Bot, Send, FileText, X, Loader2 } from 'lucide-react';
import { techApiFetch, techApiFetchBlob } from '../services/techApi';

interface CopilotMsg {
  id: number;
  remetente: 'tecnico' | 'assistente';
  conteudo: string;
  documento_titulo?: string | null;
  tem_documento: boolean;
  criado_em: string;
}

interface TechCopilotProps {
  techName: string;
}

// Visualizador de PDF embutido, só leitura - pedido do usuário em 11/10/2026: o documento nunca
// deve virar um arquivo baixável/anexo, só visualização dentro do app. O <iframe> não consegue
// mandar o header de autenticação sozinho, então busca o PDF como Blob primeiro (techApiFetchBlob)
// e monta um object URL local, descartado ao fechar.
const DocumentViewerModal: React.FC<{ messageId: number; titulo: string; onClose: () => void }> = ({ messageId, titulo, onClose }) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoke: string | null = null;
    techApiFetchBlob(`/copilot/document/${messageId}`)
      .then(blob => {
        const url = URL.createObjectURL(blob);
        revoke = url;
        setBlobUrl(url);
      })
      .catch(err => setError(err.message || 'Não foi possível abrir o documento.'));
    return () => { if (revoke) URL.revokeObjectURL(revoke); };
  }, [messageId]);

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 50000, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: '100%', maxWidth: '820px', height: '90vh', background: 'var(--bg-primary, #0b1220)', border: '1px solid var(--border-color)', borderRadius: '12px', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <FileText size={16} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
            <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{titulo}</span>
          </div>
          <button onClick={onClose} style={{ width: '30px', height: '30px', borderRadius: '8px', border: '1px solid var(--border-color)', background: 'transparent', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', flexShrink: 0 }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0, background: '#1a1a1a' }}>
          {error ? (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f87171', fontSize: '13px', padding: '20px', textAlign: 'center' }}>{error}</div>
          ) : blobUrl ? (
            <iframe
              src={`${blobUrl}#toolbar=0&navpanes=0`}
              title={titulo}
              style={{ width: '100%', height: '100%', border: 'none' }}
            />
          ) : (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
              <Loader2 size={24} className="animate-spin" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const TechCopilot: React.FC<TechCopilotProps> = ({ techName }) => {
  const [messages, setMessages] = useState<CopilotMsg[]>([]);
  const [input, setInput] = useState('');
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [sending, setSending] = useState(false);
  const [viewerMsg, setViewerMsg] = useState<CopilotMsg | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    techApiFetch('/copilot/messages')
      .then(data => setMessages(data || []))
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const send = async () => {
    const texto = input.trim();
    if (!texto || sending) return;
    setInput('');
    setSending(true);
    // Otimista: já mostra a mensagem do técnico, sem esperar o round-trip da IA.
    setMessages(prev => [...prev, { id: -Date.now(), remetente: 'tecnico', conteudo: texto, tem_documento: false, criado_em: new Date().toISOString() }]);
    try {
      const resp = await techApiFetch('/copilot/ask', { method: 'POST', body: JSON.stringify({ mensagem: texto }) });
      setMessages(prev => [...prev, resp]);
    } catch (err: any) {
      setMessages(prev => [...prev, { id: -Date.now(), remetente: 'assistente', conteudo: `⚠️ ${err.message || 'Erro ao perguntar pro Copiloto.'}`, tem_documento: false, criado_em: new Date().toISOString() }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
      <div style={{ flexShrink: 0, padding: '14px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div style={{ width: '34px', height: '34px', borderRadius: '10px', background: 'var(--accent-gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#051a12', flexShrink: 0 }}>
          <Bot size={18} />
        </div>
        <div>
          <div style={{ fontSize: '14px', fontWeight: 800, color: 'var(--text-main)' }}>Copiloto Técnico</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Manuais, esquemas e peças - converse como um chat normal</div>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {loadingHistory ? (
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

      {viewerMsg && (
        <DocumentViewerModal messageId={viewerMsg.id} titulo={viewerMsg.documento_titulo || 'Documento'} onClose={() => setViewerMsg(null)} />
      )}
    </div>
  );
};
