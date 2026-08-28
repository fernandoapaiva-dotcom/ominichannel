import React, { useState, useRef, useEffect } from 'react';
import { 
  Sparkles, X, Send, RefreshCw, CheckCircle2, AlertTriangle, 
  BookOpen, ShieldAlert, Cpu, ArrowRight, Check, Play, Search, HelpCircle 
} from 'lucide-react';
import { apiFetch } from '../services/api';

interface RagTrainingAssistantModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDocumentAdded: () => void;
  numbers: any[];
}

export const RagTrainingAssistantModal: React.FC<RagTrainingAssistantModalProps> = ({
  isOpen,
  onClose,
  onDocumentAdded,
  numbers
}) => {
  const [activeTab, setActiveTab] = useState<'chat' | 'diagnose'>('chat');

  // Chat State
  const [messages, setMessages] = useState<Array<{
    sender: 'user' | 'assistant';
    text: string;
    proposedDoc?: any;
    timestamp: Date;
  }>>([
    {
      sender: 'assistant',
      text: '👋 Olá! Sou seu **Auxiliar de Treinamento RAG & Especialista Anti-Alucinação**.\n\nMe conte o que a IA do sistema está errando ou qual assunto você deseja ensinar a ela (ex: *a IA está inventando preços*, *está dizendo que entrega fora do DF*, *não sabe regras de garantia*). Eu analiso a causa e crio a diretriz perfeita para blindar a IA!',
      timestamp: new Date()
    }
  ]);
  const [inputVal, setInputVal] = useState('');
  const [loadingChat, setLoadingChat] = useState(false);
  const [addingDocId, setAddingDocId] = useState<string | null>(null);
  const [addedSuccess, setAddedSuccess] = useState<{ [key: string]: boolean }>({});
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // Diagnose State
  const [testQuestion, setTestQuestion] = useState('Vocês entregam máquinas de solda no Rio de Janeiro ou São Paulo?');
  const [diagnoseLoading, setDiagnoseLoading] = useState(false);
  const [diagnoseResult, setDiagnoseResult] = useState<any | null>(null);

  useEffect(() => {
    if (isOpen) {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen, activeTab]);

  if (!isOpen) return null;

  const handleSendMessage = async (customText?: string) => {
    const text = (customText || inputVal).trim();
    if (!text || loadingChat) return;

    const newHist = [...messages, { sender: 'user' as const, text, timestamp: new Date() }];
    setMessages(newHist);
    setInputVal('');
    setLoadingChat(true);

    try {
      const payload = {
        history: newHist.map(m => ({ sender: m.sender, text: m.text })),
        message: text
      };

      const res = await apiFetch('/rag/ai-trainer-chat', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      if (res && res.reply) {
        setMessages(prev => [
          ...prev,
          {
            sender: 'assistant',
            text: res.reply,
            proposedDoc: res.proposed_document,
            timestamp: new Date()
          }
        ]);
      }
    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          sender: 'assistant',
          text: `❌ Falha ao consultar o Auxiliar de Treinamento: ${err.message || 'Erro de conexão'}`,
          timestamp: new Date()
        }
      ]);
    } finally {
      setLoadingChat(false);
    }
  };

  const handleApplyDocument = async (doc: any, indexKey: string) => {
    if (!doc || !doc.content) return;
    try {
      setAddingDocId(indexKey);
      await apiFetch('/rag/upload', {
        method: 'POST',
        body: JSON.stringify({
          titulo: doc.titulo || 'Diretriz Anti-Alucinação',
          content: doc.content,
          scope: doc.scope || 'geral',
          department_id: doc.department_id || null,
          department_name: doc.department_name || 'Geral'
        })
      });

      setAddedSuccess(prev => ({ ...prev, [indexKey]: true }));
      onDocumentAdded();
      alert(`✨ Diretriz "${doc.titulo}" indexada com sucesso na Base RAG! A IA Concierge já aprendeu essa regra factual.`);
    } catch (err: any) {
      alert(`Erro ao salvar diretriz RAG: ${err.message}`);
    } finally {
      setAddingDocId(null);
    }
  };

  const handleRunDiagnose = async () => {
    if (!testQuestion.trim() || diagnoseLoading) return;
    setDiagnoseLoading(true);
    setDiagnoseResult(null);

    try {
      const res = await apiFetch('/rag/diagnose-hallucination', {
        method: 'POST',
        body: JSON.stringify({ question: testQuestion })
      });
      setDiagnoseResult(res);
    } catch (err: any) {
      alert(`Erro no diagnóstico: ${err.message}`);
    } finally {
      setDiagnoseLoading(false);
    }
  };

  const handleSendDiagnoseToTrainer = () => {
    if (!diagnoseResult) return;
    setActiveTab('chat');
    const msg = `O cliente perguntou: "${diagnoseResult.question}". A IA respondeu: "${diagnoseResult.ia_answer}". ${diagnoseResult.diagnosis}. Por favor, crie a diretriz factual para corrigir isso na base RAG.`;
    handleSendMessage(msg);
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      backdropFilter: 'blur(5px)',
      zIndex: 9999,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      padding: '20px'
    }}>
      <style>{`
        @keyframes custom-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .custom-spin-anim {
          animation: custom-spin 1s linear infinite;
        }
      `}</style>
      <div style={{
        width: '100%',
        maxWidth: '850px',
        height: '85vh',
        backgroundColor: '#0f172a',
        border: '1px solid rgba(0, 230, 153, 0.4)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: '0 25px 50px -12px rgba(0,0,0,0.7)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          backgroundColor: 'rgba(0, 230, 153, 0.1)',
          borderBottom: '1px solid rgba(0, 230, 153, 0.25)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '38px',
              height: '38px',
              borderRadius: '10px',
              backgroundColor: 'rgba(0, 230, 153, 0.2)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Sparkles size={22} />
            </div>
            <div>
              <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#fff', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                IA Auxiliar de Treinamento RAG & Anti-Alucinação
              </h3>
              <p style={{ fontSize: '11px', color: '#94a3b8', margin: '2px 0 0 0' }}>
                Treine a IA Concierge, elimine invenções de dados e crie regras factuais perfeitas conversando em português.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Subtab Toggle (Chat vs Diagnostics) */}
        <div style={{
          display: 'flex',
          gap: '8px',
          padding: '10px 20px',
          backgroundColor: 'rgba(0,0,0,0.25)',
          borderBottom: '1px solid rgba(255,255,255,0.08)'
        }}>
          <button
            type="button"
            onClick={() => setActiveTab('chat')}
            className={activeTab === 'chat' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Sparkles size={14} /> 🤖 Conversar com a IA Treinadora
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('diagnose')}
            className={activeTab === 'diagnose' ? 'btn-primary' : 'btn-secondary'}
            style={{ fontSize: '12px', padding: '6px 14px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <ShieldAlert size={14} /> 🧪 Testar & Diagnosticar Alucinações
          </button>
        </div>

        {/* TAB 1: Chat with RAG Trainer */}
        {activeTab === 'chat' && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {/* Quick Starter Pills */}
            <div style={{
              padding: '8px 16px',
              backgroundColor: 'rgba(0,0,0,0.15)',
              borderBottom: '1px solid rgba(255,255,255,0.05)',
              display: 'flex',
              gap: '6px',
              overflowX: 'auto'
            }}>
              <button
                type="button"
                onClick={() => handleSendMessage('A IA está inventando que nós entregamos fora de Brasília. Quero limitar o atendimento exclusivamente para DF e Entorno.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                📍 Limitar Área (Somente DF e Entorno)
              </button>
              <button
                type="button"
                onClick={() => handleSendMessage('A IA está inventando preços de conserto de máquinas. Quero que ela nunca passe preços sem orçamento técnico prévio.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                💰 Proibir Invenção de Preços
              </button>
              <button
                type="button"
                onClick={() => handleSendMessage('Quero treinar a IA com as marcas que consertamos: somos autorizada Balmer, Boxer e Esab, mas não consertamos furadeiras nem lixadeiras.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                🔧 Marcas Autorizadas & Escopo
              </button>
            </div>

            {/* Messages Scroll Area */}
            <div style={{
              flex: 1,
              padding: '16px 20px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px'
            }}>
              {messages.map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: item.sender === 'user' ? 'flex-end' : 'flex-start',
                    gap: '6px'
                  }}
                >
                  <div style={{
                    maxWidth: '85%',
                    padding: '10px 14px',
                    borderRadius: item.sender === 'user' ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                    backgroundColor: item.sender === 'user' ? 'var(--accent-primary)' : 'rgba(30, 41, 59, 0.8)',
                    color: item.sender === 'user' ? '#000' : '#f8fafc',
                    fontSize: '13px',
                    lineHeight: '1.5',
                    border: item.sender === 'user' ? 'none' : '1px solid rgba(255,255,255,0.08)',
                    whiteSpace: 'pre-wrap'
                  }}>
                    {item.text}
                    <div style={{
                      fontSize: '10px',
                      color: item.sender === 'user' ? 'rgba(0,0,0,0.5)' : '#94a3b8',
                      marginTop: '6px',
                      textAlign: 'right'
                    }}>
                      {item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                    </div>
                  </div>

                  {/* Proposed RAG Document Card */}
                  {item.proposedDoc && (
                    <div style={{
                      maxWidth: '85%',
                      padding: '14px',
                      backgroundColor: 'rgba(0, 230, 153, 0.08)',
                      border: '1px solid rgba(0, 230, 153, 0.4)',
                      borderRadius: '12px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                      marginTop: '4px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong style={{ fontSize: '13px', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <BookOpen size={16} /> Diretriz RAG Formulada
                        </strong>
                        <span style={{ fontSize: '11px', backgroundColor: 'rgba(0, 230, 153, 0.2)', color: 'var(--accent-primary)', padding: '2px 8px', borderRadius: '12px', fontWeight: '600' }}>
                          Pronta para Indexar
                        </span>
                      </div>

                      <div style={{ fontSize: '12px', color: '#e2e8f0' }}>
                        <div><strong>Título:</strong> {item.proposedDoc.titulo}</div>
                        <div><strong>Escopo:</strong> {item.proposedDoc.scope === 'setor' ? `Setor (${item.proposedDoc.department_name})` : 'Geral (Toda a Empresa)'}</div>
                      </div>

                      <div style={{ fontSize: '11px', color: '#94a3b8', backgroundColor: 'rgba(0,0,0,0.3)', padding: '8px', borderRadius: '6px', maxHeight: '120px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
                        {item.proposedDoc.content}
                      </div>

                      <button
                        type="button"
                        onClick={() => handleApplyDocument(item.proposedDoc, `doc_btn_${idx}`)}
                        disabled={addingDocId === `doc_btn_${idx}` || addedSuccess[`doc_btn_${idx}`]}
                        className="btn-primary"
                        style={{
                          padding: '8px 14px',
                          fontSize: '12px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '6px',
                          marginTop: '4px',
                          fontWeight: '700'
                        }}
                      >
                        {addingDocId === `doc_btn_${idx}` ? (
                          <RefreshCw size={14} className="custom-spin-anim" />
                        ) : addedSuccess[`doc_btn_${idx}`] ? (
                          <Check size={14} />
                        ) : (
                          <Sparkles size={14} />
                        )}
                        {addedSuccess[`doc_btn_${idx}`] ? 'Conhecimento Indexado na Base!' : '✨ Inserir Diretriz na Base RAG'}
                      </button>
                    </div>
                  )}
                </div>
              ))}

              {loadingChat && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#94a3b8', fontSize: '12px', fontStyle: 'italic' }}>
                  <RefreshCw size={14} className="custom-spin-anim" color="var(--accent-primary)" />
                  O Engenheiro de RAG está formulando a diretriz anti-alucinação...
                </div>
              )}
              <div ref={chatBottomRef} />
            </div>

            {/* Input Bar */}
            <div style={{
              padding: '12px 16px',
              backgroundColor: 'rgba(15, 23, 42, 0.95)',
              borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              display: 'flex',
              gap: '8px',
              alignItems: 'center'
            }}>
              <input
                type="text"
                value={inputVal}
                onChange={e => setInputVal(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
                placeholder="Ex: A IA está inventando que consertamos geladeira..."
                style={{
                  flex: 1,
                  padding: '10px 14px',
                  backgroundColor: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  borderRadius: 'var(--radius-md)',
                  color: '#fff',
                  fontSize: '13px'
                }}
              />
              <button
                type="button"
                onClick={() => handleSendMessage()}
                disabled={loadingChat || !inputVal.trim()}
                className="btn-primary"
                style={{
                  padding: '10px 16px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '13px'
                }}
              >
                <Send size={15} /> Enviar
              </button>
            </div>
          </div>
        )}

        {/* TAB 2: Live Hallucination Diagnostics & Stress Test */}
        {activeTab === 'diagnose' && (
          <div style={{ flex: 1, padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ padding: '14px', backgroundColor: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.3)', borderRadius: 'var(--radius-md)' }}>
              <h4 style={{ fontSize: '14px', fontWeight: '700', color: '#93c5fd', margin: '0 0 6px 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <ShieldAlert size={16} /> Como funciona o Testador de Alucinação?
              </h4>
              <p style={{ fontSize: '12px', color: '#cbd5e1', margin: 0 }}>
                Faça uma pergunta capciosa ou difícil para o sistema. O diagnóstico busca os documentos na base RAG, gera a resposta real da IA Concierge e analisa linha por linha se a IA inventou dados ou se manteve 100% factual.
              </p>
            </div>

            <div>
              <label style={{ fontSize: '12px', fontWeight: '700', color: '#e2e8f0', display: 'block', marginBottom: '6px' }}>
                Pergunta de Teste do Cliente:
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="text"
                  value={testQuestion}
                  onChange={e => setTestQuestion(e.target.value)}
                  placeholder="Ex: Vocês entregam em Goiânia? Quanto é a diária do gerador?"
                  style={{
                    flex: 1,
                    padding: '10px 14px',
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    color: '#fff',
                    fontSize: '13px'
                  }}
                />
                <button
                  type="button"
                  onClick={handleRunDiagnose}
                  disabled={diagnoseLoading || !testQuestion.trim()}
                  className="btn-primary"
                  style={{ padding: '10px 18px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
                >
                  {diagnoseLoading ? <RefreshCw size={15} className="custom-spin-anim" /> : <Play size={15} fill="currentColor" />}
                  {diagnoseLoading ? 'Diagnosticando...' : 'Executar Diagnóstico'}
                </button>
              </div>
            </div>

            {diagnoseResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {/* 1. Status Banner */}
                <div style={{
                  padding: '14px',
                  borderRadius: 'var(--radius-md)',
                  backgroundColor: diagnoseResult.hallucination_detected ? 'rgba(239, 68, 68, 0.12)' : 'rgba(0, 230, 153, 0.12)',
                  border: `1px solid ${diagnoseResult.hallucination_detected ? '#ef4444' : 'var(--accent-primary)'}`,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    {diagnoseResult.hallucination_detected ? <AlertTriangle size={22} color="#f87171" /> : <CheckCircle2 size={22} color="var(--accent-primary)" />}
                    <div>
                      <strong style={{ fontSize: '14px', color: diagnoseResult.hallucination_detected ? '#f87171' : 'var(--accent-primary)' }}>
                        {diagnoseResult.hallucination_detected ? '⚠️ Alucinação / Invenção de Dados Detectada!' : '✅ Resposta 100% Factual e Segura!'}
                      </strong>
                      <p style={{ fontSize: '12px', color: '#cbd5e1', margin: '2px 0 0 0' }}>
                        {diagnoseResult.diagnosis}
                      </p>
                    </div>
                  </div>

                  {diagnoseResult.hallucination_detected && (
                    <button
                      type="button"
                      onClick={handleSendDiagnoseToTrainer}
                      className="btn-primary"
                      style={{ fontSize: '12px', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                      <Sparkles size={14} /> 🔧 Corrigir com o Auxiliar
                    </button>
                  )}
                </div>

                {/* 2. RAG Context vs AI Output Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                  <div style={{ padding: '12px', backgroundColor: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>
                      📄 CONTEXTO RETORNADO PELA BASE RAG:
                    </span>
                    <div style={{ fontSize: '12px', color: '#e2e8f0', whiteSpace: 'pre-wrap', maxHeight: '180px', overflowY: 'auto' }}>
                      {diagnoseResult.rag_context || '(Nenhum documento encontrado na base para essa pergunta)'}
                    </div>
                  </div>

                  <div style={{ padding: '12px', backgroundColor: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', display: 'block', marginBottom: '6px' }}>
                      🤖 RESPOSTA GERADA PELA IA CONCIERGE:
                    </span>
                    <div style={{ fontSize: '12px', color: '#fff', whiteSpace: 'pre-wrap', maxHeight: '180px', overflowY: 'auto' }}>
                      {diagnoseResult.ia_answer}
                    </div>
                  </div>
                </div>

                {/* 3. Suggested Fix if available */}
                {diagnoseResult.suggested_fix && (
                  <div style={{ padding: '12px', backgroundColor: 'rgba(0, 230, 153, 0.05)', border: '1px dashed rgba(0, 230, 153, 0.3)', borderRadius: '8px' }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', display: 'block', marginBottom: '4px' }}>
                      💡 RECOMENDAÇÃO PARA CORREÇÃO NA BASE:
                    </span>
                    <p style={{ fontSize: '12px', color: '#e2e8f0', margin: 0, whiteSpace: 'pre-wrap' }}>
                      {diagnoseResult.suggested_fix}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
