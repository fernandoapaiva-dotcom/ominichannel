import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Zap, Wrench, CheckCircle2, AlertTriangle, Plus, Trash2, Pencil, 
  Search, Play, RefreshCw, Save, Clock, MessageSquare, Bot, 
  HelpCircle, Sliders, Check, X, Shield, FileText, DollarSign, Send, Sparkles, UserCheck, CheckSquare, CornerDownRight
} from 'lucide-react';
import { apiFetch } from '../services/api';

export const AutomationsSettings: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Config State
  const [enabled, setEnabled] = useState(true);
  
  // OS Handler Config
  const [osEnabled, setOsEnabled] = useState(true);
  const [triggerOnAttendant, setTriggerOnAttendant] = useState(true);
  const [triggerOnCustomer, setTriggerOnCustomer] = useState(true);
  const [osMatchMode, setOsMatchMode] = useState<'any' | 'all'>('any');
  const [typingDelaySec, setTypingDelaySec] = useState(2.0);
  const [keywordsText, setKeywordsText] = useState('posto autorizado, status:, aberto a os, ordem de servico, servsolda, servweld');
  
  // Diagnostic Prices Table
  const [diagnosticPrices, setDiagnosticPrices] = useState<{ [key: string]: number }>({
    'alimentador de arame': 150,
    'filtro de ar': 60,
    'maçarico de corte': 50,
    'mig': 200,
    'cnc': 400,
    'retificador': 200,
    'teste': 60,
    'transformador de solda': 90,
    'carregador de bateria': 80,
    'ignitor': 80,
    'maçarico de solda': 50,
    'tig': 200,
    'painel de secagem': 200,
    'talha elétrica': 250,
    'tocha de solda': 50,
    'unidade de refrigeração': 100,
    'compressor de ar': 250,
    'inversor': 100,
    'plasma': 200,
    'repuxadeira': 150,
    'regulador': 50,
    'tartaruga': 150,
    'tocha de corte': 50
  });

  const [equipSearch, setEquipSearch] = useState('');
  const [newEquipName, setNewEquipName] = useState('');
  const [newEquipPrice, setNewEquipPrice] = useState<number | ''>('');
  const [editingEquipKey, setEditingEquipKey] = useState<string | null>(null);
  const [editingEquipVal, setEditingEquipVal] = useState<number | ''>('');

  // Templates
  const [templateTab, setTemplateTab] = useState<'orcamento' | 'garantia_loja' | 'garantia_fabrica'>('orcamento');
  const [templates, setTemplates] = useState<{
    orcamento: string[];
    garantia_loja: string[];
    garantia_fabrica: string[];
  }>({
    orcamento: [
      'Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊',
      '💰 *Diagnóstico Técnico:* Caso o orçamento *NÃO SEJA APROVADO*, será cobrada uma taxa de *R$ {valor_diagnostico}*. Esse valor poderá ser abatido se o serviço for autorizado posteriormente.',
      '⏳ *Validade do Orçamento:* 15 dias.\n🔧 *Garantia:* 90 dias para serviços e peças trocadas.\n📦 *Peças do cliente:* garantia somente da mão de obra.\n⚠️ Após 90 dias da liberação para retirada, o equipamento poderá ser considerado abandonado e sucateado conforme nossas condições gerais.'
    ],
    garantia_loja: [
      'Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊',
      '🔧 *Garantia de Loja:* 90 dias contados a partir do serviço anterior.\nCobre vícios de mão de obra e peças trocadas.\n📦 *Peças do cliente:* garantia apenas de mão de obra.',
      '⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado.'
    ],
    garantia_fabrica: [
      'Olá, {nome_cliente}! 👋 {saudacao}, tudo bem? 😊',
      '🏭 *Garantia de Fábrica:* Não há cobrança de diagnóstico ou orçamento. Todos os custos são arcados pela fabricante.',
      '⚠️ Após 90 dias da liberação para retirada, o equipamento pode ser considerado abandonado e sucateado.'
    ]
  });

  // Custom Rules
  const [customRules, setCustomRules] = useState<any[]>([
    {
      id: 'rule_pix',
      name: 'Chave Pix e Pagamento',
      enabled: true,
      trigger_on: 'both',
      match_mode: 'any',
      keywords: ['qual o pix', 'chave pix', 'como pagar', 'dados bancarios', 'pix da loja'],
      reply_type: 'single',
      reply_text: '📌 *Dados Oficiais para Pagamento via Pix:*\nChave: contato@servweld.com.br\nFavorecido: SERVWELD / SERVSOLDA\n\nPor favor, envie o comprovante nesta conversa para confirmação.',
      reply_sequence: []
    }
  ]);

  const [newRuleName, setNewRuleName] = useState('');
  const [newRuleKeywords, setNewRuleKeywords] = useState('');
  const [newRuleReply, setNewRuleReply] = useState('');
  const [newRuleMatchMode, setNewRuleMatchMode] = useState<'any' | 'all'>('any');
  const [isAddingRule, setIsAddingRule] = useState(false);

  // AI Copilot State
  const [isAiCopilotOpen, setIsAiCopilotOpen] = useState(false);
  const [copilotHistory, setCopilotHistory] = useState<Array<{ sender: 'user' | 'assistant'; text: string; proposedRule?: any }>>([
    {
      sender: 'assistant',
      text: '👋 Olá! Sou seu **Copilot de Automações com IA**. Diga o que você precisa que o sistema responda automaticamente (ex: regras de aprovação de OS, localização da loja, prazos de garantia ou dúvidas frequentes) que eu crio a regra completa para você!'
    }
  ]);
  const [copilotInput, setCopilotInput] = useState('');
  const [copilotLoading, setCopilotLoading] = useState(false);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // Simulator State
  const [testText, setTestText] = useState(
    'Olá. Informamos que foi aberto a OS 1841 status: Orçamento para seu produto 001 - INVERSOR DE SOLDA SUPER TORK KAB 180 MICRO Orçamento pelo posto autorizado SERVSOLDA.'
  );
  const [testClientName, setTestClientName] = useState('Fernando Aragão');
  const [testFromMe, setTestFromMe] = useState(true);
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<any | null>(null);

  useEffect(() => {
    loadAutomations();
  }, []);

  useEffect(() => {
    if (isAiCopilotOpen) {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [copilotHistory, isAiCopilotOpen]);

  const loadAutomations = async () => {
    try {
      setLoading(true);
      const data = await apiFetch('/settings/automations');
      if (data) {
        setEnabled(data.enabled ?? true);
        const os = data.os_handler || {};
        setOsEnabled(os.enabled ?? true);
        setTriggerOnAttendant(os.trigger_on_attendant ?? true);
        setTriggerOnCustomer(os.trigger_on_customer ?? true);
        setOsMatchMode(os.match_mode || 'any');
        setTypingDelaySec((os.typing_delay_ms || 2000) / 1000.0);
        if (Array.isArray(os.keywords)) {
          setKeywordsText(os.keywords.join(', '));
        }
        if (os.diagnostic_prices) {
          setDiagnosticPrices(os.diagnostic_prices);
        }
        if (os.templates) {
          setTemplates(os.templates);
        }
        if (Array.isArray(data.custom_rules)) {
          setCustomRules(data.custom_rules);
        }
      }
    } catch (err: any) {
      console.error('Error loading automations:', err);
      setErrorMessage('Erro ao carregar configurações de automação.');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setSaveSuccess(false);
      setErrorMessage(null);

      const keywords = keywordsText
        .split(',')
        .map(k => k.trim())
        .filter(k => k.length > 0);

      const payload = {
        enabled,
        os_handler: {
          enabled: osEnabled,
          trigger_on_attendant: triggerOnAttendant,
          trigger_on_customer: triggerOnCustomer,
          match_mode: osMatchMode,
          typing_delay_ms: Math.round(typingDelaySec * 1000),
          keywords,
          diagnostic_prices: diagnosticPrices,
          templates
        },
        custom_rules: customRules,
        ai_fallback_intent: true
      };

      await apiFetch('/settings/automations', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err: any) {
      console.error('Error saving automations:', err);
      setErrorMessage(err.message || 'Erro ao salvar automações.');
    } finally {
      setSaving(false);
    }
  };

  const handleSimulate = async () => {
    if (!testText.trim()) return;
    try {
      setTestLoading(true);
      setTestResult(null);

      const keywords = keywordsText
        .split(',')
        .map(k => k.trim())
        .filter(k => k.length > 0);

      const currentConfig = {
        enabled,
        os_handler: {
          enabled: osEnabled,
          trigger_on_attendant: triggerOnAttendant,
          trigger_on_customer: triggerOnCustomer,
          match_mode: osMatchMode,
          typing_delay_ms: Math.round(typingDelaySec * 1000),
          keywords,
          diagnostic_prices: diagnosticPrices,
          templates
        },
        custom_rules: customRules
      };

      const res = await apiFetch('/settings/automations/test', {
        method: 'POST',
        body: JSON.stringify({
          text: testText,
          from_me: testFromMe,
          client_name: testClientName,
          config: currentConfig
        })
      });

      setTestResult(res);
    } catch (err: any) {
      console.error('Error running simulation:', err);
      setTestResult({ matched: false, reason: err.message || 'Erro ao simular automação.' });
    } finally {
      setTestLoading(false);
    }
  };

  const handleSendCopilotMessage = async (textToSend?: string) => {
    const msg = (textToSend || copilotInput).trim();
    if (!msg || copilotLoading) return;

    const newHistory = [...copilotHistory, { sender: 'user' as const, text: msg }];
    setCopilotHistory(newHistory);
    setCopilotInput('');
    setCopilotLoading(true);

    try {
      const historyPayload = newHistory.map(h => ({
        sender: h.sender,
        text: h.text
      }));

      const res = await apiFetch('/settings/automations/ai-copilot', {
        method: 'POST',
        body: JSON.stringify({
          history: historyPayload,
          message: msg
        })
      });

      if (res && res.reply) {
        setCopilotHistory(prev => [
          ...prev,
          {
            sender: 'assistant',
            text: res.reply,
            proposedRule: res.proposed_rule
          }
        ]);
      }
    } catch (err: any) {
      console.error('Error chatting with copilot:', err);
      setCopilotHistory(prev => [
        ...prev,
        {
          sender: 'assistant',
          text: `❌ Falha ao conversar com a IA: ${err.message || 'Erro de conexão.'}`
        }
      ]);
    } finally {
      setCopilotLoading(false);
    }
  };

  const handleApplyProposedRule = (rule: any) => {
    if (!rule) return;
    const ruleObj = {
      id: rule.id || `rule_${Date.now()}`,
      name: rule.name || 'Nova Regra da IA',
      enabled: rule.enabled ?? true,
      trigger_on: rule.trigger_on || 'both',
      match_mode: rule.match_mode || 'any',
      keywords: Array.isArray(rule.keywords) ? rule.keywords : [],
      reply_type: rule.reply_type || (Array.isArray(rule.reply_sequence) && rule.reply_sequence.length > 0 ? 'sequence' : 'single'),
      reply_text: rule.reply_text || '',
      reply_sequence: Array.isArray(rule.reply_sequence) ? rule.reply_sequence : []
    };

    setCustomRules(prev => {
      // Replace if exists, or append
      const exists = prev.some(r => r.id === ruleObj.id);
      if (exists) {
        return prev.map(r => (r.id === ruleObj.id ? ruleObj : r));
      }
      return [...prev, ruleObj];
    });

    alert(`✨ Gatilho "${ruleObj.name}" aplicado com sucesso aos seus Gatilhos Customizados! Lembre-se de clicar em "Salvar Alterações".`);
    setIsAiCopilotOpen(false);
  };

  const handleAddEquipment = () => {
    if (!newEquipName.trim() || newEquipPrice === '' || Number(newEquipPrice) < 0) {
      alert('Por favor, informe o nome do equipamento e o valor da taxa de diagnóstico.');
      return;
    }
    const cleanKey = newEquipName.trim().toLowerCase();
    setDiagnosticPrices(prev => ({
      ...prev,
      [cleanKey]: Number(newEquipPrice)
    }));
    setNewEquipName('');
    setNewEquipPrice('');
  };

  const handleDeleteEquipment = (key: string) => {
    if (confirm(`Deseja remover "${key}" da tabela de diagnóstico?`)) {
      setDiagnosticPrices(prev => {
        const copy = { ...prev };
        delete copy[key];
        return copy;
      });
    }
  };

  const handleSaveEditEquipment = (key: string) => {
    if (editingEquipVal === '' || Number(editingEquipVal) < 0) return;
    setDiagnosticPrices(prev => ({
      ...prev,
      [key]: Number(editingEquipVal)
    }));
    setEditingEquipKey(null);
    setEditingEquipVal('');
  };

  const handleAddCustomRule = () => {
    if (!newRuleName.trim() || !newRuleKeywords.trim() || !newRuleReply.trim()) {
      alert('Preencha o Nome, Palavras-chave e a Resposta Padrão.');
      return;
    }
    const kList = newRuleKeywords.split(',').map(k => k.trim()).filter(k => k.length > 0);
    const newRule = {
      id: `rule_${Date.now()}`,
      name: newRuleName.trim(),
      enabled: true,
      trigger_on: 'both',
      match_mode: newRuleMatchMode,
      keywords: kList,
      reply_type: 'single',
      reply_text: newRuleReply.trim(),
      reply_sequence: []
    };
    setCustomRules(prev => [...prev, newRule]);
    setNewRuleName('');
    setNewRuleKeywords('');
    setNewRuleReply('');
    setIsAddingRule(false);
  };

  const handleDeleteCustomRule = (id: string) => {
    if (confirm('Deseja excluir este gatilho customizado?')) {
      setCustomRules(prev => prev.filter(r => r.id !== id));
    }
  };

  const handleToggleCustomRule = (id: string) => {
    setCustomRules(prev =>
      prev.map(r => (r.id === id ? { ...r, enabled: !r.enabled } : r))
    );
  };

  const filteredEquipments = useMemo(() => {
    const list = Object.entries(diagnosticPrices);
    if (!equipSearch.trim()) return list;
    const q = equipSearch.toLowerCase().trim();
    return list.filter(([name]) => name.toLowerCase().includes(q));
  }, [diagnosticPrices, equipSearch]);

  if (loading) {
    return (
      <div style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
        <RefreshCw size={32} className="animate-spin" style={{ margin: '0 auto 12px', color: 'var(--accent-primary)' }} />
        <p>Carregando regras de automação...</p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Header Banner & Save Action */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '20px 24px',
        backgroundColor: 'rgba(0, 230, 153, 0.06)',
        border: '1px solid rgba(0, 230, 153, 0.25)',
        borderRadius: 'var(--radius-lg)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            backgroundColor: 'rgba(0, 230, 153, 0.2)',
            color: 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(0, 230, 153, 0.25)'
          }}>
            <Zap size={24} />
          </div>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
              Automações & Gatilhos Inteligentes (OS & Respostas Padrão)
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
              Detecte ordens de serviço do posto autorizado, calcule taxas de diagnóstico automaticamente e dispare sequências inteligentes com simulação de digitação.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            type="button"
            onClick={() => setIsAiCopilotOpen(true)}
            className="btn-secondary"
            style={{
              padding: '8px 16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '13px',
              backgroundColor: 'rgba(59, 130, 246, 0.15)',
              borderColor: 'rgba(59, 130, 246, 0.4)',
              color: '#93c5fd'
            }}
          >
            <Sparkles size={16} color="#60a5fa" />
            <strong>🤖 Criar Gatilho com IA Copilot</strong>
          </button>

          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', userSelect: 'none' }}>
            <span style={{ fontSize: '13px', fontWeight: '600', color: enabled ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
              {enabled ? 'Motor Ativado' : 'Motor Pausado'}
            </span>
            <input
              type="checkbox"
              checked={enabled}
              onChange={e => setEnabled(e.target.checked)}
              style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: 'var(--accent-primary)' }}
            />
          </label>

          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="btn-primary"
            style={{ padding: '8px 18px', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}
          >
            {saving ? <RefreshCw size={15} className="animate-spin" /> : saveSuccess ? <Check size={15} /> : <Save size={15} />}
            {saveSuccess ? 'Salvo com Sucesso!' : 'Salvar Alterações'}
          </button>
        </div>
      </div>

      {errorMessage && (
        <div style={{ padding: '12px 16px', backgroundColor: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', borderRadius: '8px', color: '#fca5a5', fontSize: '13px' }}>
          ⚠️ {errorMessage}
        </div>
      )}

      {/* Grid: OS Handler & Diagnostic Table */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
        {/* LEFT COLUMN: OS Handler Configuration & Sequence Templates */}
        <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Wrench size={20} color="var(--accent-primary)" />
              <h4 style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                Handler de Ordem de Serviço (Posto Autorizado)
              </h4>
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Ativar Handler</span>
              <input
                type="checkbox"
                checked={osEnabled}
                onChange={e => setOsEnabled(e.target.checked)}
                style={{ accentColor: 'var(--accent-primary)' }}
              />
            </label>
          </div>

          {/* Trigger Triggers & Timing */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div>
              <label style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-main)', display: 'block', marginBottom: '6px' }}>
                Disparo Automático:
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={triggerOnAttendant}
                    onChange={e => setTriggerOnAttendant(e.target.checked)}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  Quando o Atendente/Sistema envia mensagem de OS
                </label>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={triggerOnCustomer}
                    onChange={e => setTriggerOnCustomer(e.target.checked)}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  Quando o Cliente envia mensagem de OS
                </label>
              </div>
            </div>

            <div>
              <label style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-main)', display: 'block', marginBottom: '6px' }}>
                Simulação de Digitando (Delay):
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="range"
                  min="0.5"
                  max="5.0"
                  step="0.5"
                  value={typingDelaySec}
                  onChange={e => setTypingDelaySec(parseFloat(e.target.value))}
                  style={{ flex: 1, accentColor: 'var(--accent-primary)' }}
                />
                <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)', minWidth: '40px' }}>
                  {typingDelaySec.toFixed(1)}s
                </span>
              </div>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
                Exibe o status "digitando..." no WhatsApp antes de disparar cada balão.
              </p>
            </div>
          </div>

          {/* Keywords & Matching Mode */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <label style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-main)' }}>
                Palavras-Chave de Ativação (separadas por vírgula):
              </label>

              {/* Mode Toggle */}
              <div style={{ display: 'flex', gap: '10px' }}>
                <label style={{ fontSize: '11px', color: osMatchMode === 'any' ? 'var(--accent-primary)' : 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <input
                    type="radio"
                    name="osMatchMode"
                    value="any"
                    checked={osMatchMode === 'any'}
                    onChange={() => setOsMatchMode('any')}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  Qualquer uma das palavras (OU)
                </label>
                <label style={{ fontSize: '11px', color: osMatchMode === 'all' ? 'var(--accent-primary)' : 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <input
                    type="radio"
                    name="osMatchMode"
                    value="all"
                    checked={osMatchMode === 'all'}
                    onChange={() => setOsMatchMode('all')}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  Todas obrigatórias (E)
                </label>
              </div>
            </div>

            <input
              type="text"
              value={keywordsText}
              onChange={e => setKeywordsText(e.target.value)}
              placeholder="ex: posto autorizado, status:, aberto a os, servsolda"
              style={{
                width: '100%',
                padding: '8px 12px',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '12px'
              }}
            />
            <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
              💡 {osMatchMode === 'any' ? 'O gatilho ativa se a mensagem contiver PELO MENOS UMA das palavras acima junto ao status da OS.' : 'O gatilho só ativará se TODAS as palavras acima estiverem presentes na mensagem.'}
            </p>
          </div>

          {/* Templates Editor */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <label style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-main)' }}>
                Mensagens em Sequência por Status da OS:
              </label>
              <div style={{ display: 'flex', gap: '4px' }}>
                <span style={{ fontSize: '10px', backgroundColor: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: '4px', color: 'var(--text-muted)' }}>
                  Tags: <code>{'{nome_cliente}'}</code>, <code>{'{saudacao}'}</code>, <code>{'{valor_diagnostico}'}</code>
                </span>
              </div>
            </div>

            {/* Template Status Tabs */}
            <div style={{ display: 'flex', gap: '6px', marginBottom: '12px' }}>
              <button
                type="button"
                onClick={() => setTemplateTab('orcamento')}
                className={templateTab === 'orcamento' ? 'btn-primary' : 'btn-secondary'}
                style={{ fontSize: '11px', padding: '5px 12px' }}
              >
                1. Status: Orçamento ({templates.orcamento.length} msgs)
              </button>
              <button
                type="button"
                onClick={() => setTemplateTab('garantia_loja')}
                className={templateTab === 'garantia_loja' ? 'btn-primary' : 'btn-secondary'}
                style={{ fontSize: '11px', padding: '5px 12px' }}
              >
                2. Garantia de Loja ({templates.garantia_loja.length} msgs)
              </button>
              <button
                type="button"
                onClick={() => setTemplateTab('garantia_fabrica')}
                className={templateTab === 'garantia_fabrica' ? 'btn-primary' : 'btn-secondary'}
                style={{ fontSize: '11px', padding: '5px 12px' }}
              >
                3. Garantia de Fábrica ({templates.garantia_fabrica.length} msgs)
              </button>
            </div>

            {/* Messages in Sequence */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {templates[templateTab].map((msgText, idx) => (
                <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                      Balão {idx + 1}:
                    </span>
                    {templates[templateTab].length > 1 && (
                      <button
                        type="button"
                        onClick={() => {
                          setTemplates(prev => ({
                            ...prev,
                            [templateTab]: prev[templateTab].filter((_, i) => i !== idx)
                          }));
                        }}
                        style={{ background: 'none', border: 'none', color: '#f87171', fontSize: '11px', cursor: 'pointer' }}
                      >
                        Remover balão
                      </button>
                    )}
                  </div>
                  <textarea
                    rows={3}
                    value={msgText}
                    onChange={e => {
                      const val = e.target.value;
                      setTemplates(prev => {
                        const copy = [...prev[templateTab]];
                        copy[idx] = val;
                        return { ...prev, [templateTab]: copy };
                      });
                    }}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      backgroundColor: 'rgba(255, 255, 255, 0.03)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-main)',
                      fontSize: '12px',
                      fontFamily: 'inherit',
                      resize: 'vertical'
                    }}
                  />
                </div>
              ))}

              <button
                type="button"
                onClick={() => {
                  setTemplates(prev => ({
                    ...prev,
                    [templateTab]: [...prev[templateTab], 'Nova mensagem adicional...']
                  }));
                }}
                className="btn-secondary"
                style={{ fontSize: '11px', padding: '6px', alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <Plus size={13} /> Adicionar balão na sequência
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN: Diagnostic Pricing Table & Equipment Fee Resolver */}
        <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <DollarSign size={20} color="var(--accent-primary)" />
              <h4 style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                Tabela de Taxas de Diagnóstico Técnico
              </h4>
            </div>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {Object.keys(diagnosticPrices).length} equipamentos
            </span>
          </div>

          {/* Add New Equipment Bar */}
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input
              type="text"
              value={newEquipName}
              onChange={e => setNewEquipName(e.target.value)}
              placeholder="Nome do equipamento (ex: inversor, mig, cnc)..."
              style={{
                flex: 1.5,
                padding: '8px 10px',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-main)',
                fontSize: '12px'
              }}
            />
            <input
              type="number"
              value={newEquipPrice}
              onChange={e => setNewEquipPrice(e.target.value === '' ? '' : Number(e.target.value))}
              placeholder="R$ Valor"
              style={{
                width: '90px',
                padding: '8px 10px',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-main)',
                fontSize: '12px'
              }}
            />
            <button
              type="button"
              onClick={handleAddEquipment}
              className="btn-primary"
              style={{ padding: '8px 12px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Plus size={14} /> Adicionar
            </button>
          </div>

          {/* Search Filter */}
          <div style={{ position: 'relative' }}>
            <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              value={equipSearch}
              onChange={e => setEquipSearch(e.target.value)}
              placeholder="Filtrar equipamento na tabela..."
              style={{
                width: '100%',
                padding: '6px 10px 6px 30px',
                backgroundColor: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-main)',
                fontSize: '12px'
              }}
            />
          </div>

          {/* Equipment List Table */}
          <div style={{ flex: 1, maxHeight: '340px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px', paddingRight: '4px' }}>
            {filteredEquipments.map(([name, price]) => (
              <div
                key={name}
                style={{
                  padding: '8px 12px',
                  backgroundColor: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}
              >
                <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-main)', textTransform: 'capitalize' }}>
                  {name}
                </span>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {editingEquipKey === name ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <input
                        type="number"
                        value={editingEquipVal}
                        onChange={e => setEditingEquipVal(e.target.value === '' ? '' : Number(e.target.value))}
                        style={{ width: '70px', padding: '4px', fontSize: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--accent-primary)', color: '#fff', borderRadius: '4px' }}
                      />
                      <button
                        type="button"
                        onClick={() => handleSaveEditEquipment(name)}
                        style={{ background: 'var(--accent-primary)', border: 'none', borderRadius: '4px', padding: '4px 6px', color: '#000', cursor: 'pointer' }}
                      >
                        <Check size={12} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingEquipKey(null)}
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ) : (
                    <span style={{ fontSize: '12px', fontWeight: '700', color: 'var(--accent-primary)' }}>
                      R$ {price.toFixed(2).replace('.', ',')}
                    </span>
                  )}

                  {editingEquipKey !== name && (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setEditingEquipKey(name);
                          setEditingEquipVal(price);
                        }}
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                        title="Editar Preço"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteEquipment(name)}
                        style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}
                        title="Remover"
                      >
                        <Trash2 size={13} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Custom Rules & Interactive Simulator */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '24px' }}>
        {/* Custom Quick Rules */}
        <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <MessageSquare size={20} color="var(--accent-primary)" />
              <h4 style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                Gatilhos Customizados de Respostas Rápidas
              </h4>
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={() => setIsAiCopilotOpen(true)}
                className="btn-secondary"
                style={{ fontSize: '11px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '4px', color: '#93c5fd' }}
              >
                <Sparkles size={13} color="#60a5fa" /> Criar com IA
              </button>
              <button
                type="button"
                onClick={() => setIsAddingRule(true)}
                className="btn-secondary"
                style={{ fontSize: '11px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <Plus size={13} /> Manual
              </button>
            </div>
          </div>

          {isAddingRule && (
            <div style={{ padding: '14px', backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid var(--accent-primary)', borderRadius: 'var(--radius-md)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <input
                type="text"
                value={newRuleName}
                onChange={e => setNewRuleName(e.target.value)}
                placeholder="Nome da regra (ex: Horário de Funcionamento)..."
                style={{ width: '100%', padding: '6px 10px', fontSize: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: '#fff', borderRadius: '4px' }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Modo de Ativação:</span>
                <div style={{ display: 'flex', gap: '10px' }}>
                  <label style={{ fontSize: '11px', color: newRuleMatchMode === 'any' ? 'var(--accent-primary)' : 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <input
                      type="radio"
                      name="newRuleMatchMode"
                      value="any"
                      checked={newRuleMatchMode === 'any'}
                      onChange={() => setNewRuleMatchMode('any')}
                      style={{ accentColor: 'var(--accent-primary)' }}
                    />
                    Qualquer palavra (OU)
                  </label>
                  <label style={{ fontSize: '11px', color: newRuleMatchMode === 'all' ? 'var(--accent-primary)' : 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <input
                      type="radio"
                      name="newRuleMatchMode"
                      value="all"
                      checked={newRuleMatchMode === 'all'}
                      onChange={() => setNewRuleMatchMode('all')}
                      style={{ accentColor: 'var(--accent-primary)' }}
                    />
                    Todas obrigatórias (E)
                  </label>
                </div>
              </div>
              <input
                type="text"
                value={newRuleKeywords}
                onChange={e => setNewRuleKeywords(e.target.value)}
                placeholder="Palavras-chave separadas por vírgula (ex: horario, que horas abre)..."
                style={{ width: '100%', padding: '6px 10px', fontSize: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: '#fff', borderRadius: '4px' }}
              />
              <textarea
                rows={3}
                value={newRuleReply}
                onChange={e => setNewRuleReply(e.target.value)}
                placeholder="Texto da resposta automática..."
                style={{ width: '100%', padding: '6px 10px', fontSize: '12px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: '#fff', borderRadius: '4px', fontFamily: 'inherit' }}
              />
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                <button type="button" onClick={() => setIsAddingRule(false)} className="btn-secondary" style={{ fontSize: '11px', padding: '4px 10px' }}>
                  Cancelar
                </button>
                <button type="button" onClick={handleAddCustomRule} className="btn-primary" style={{ fontSize: '11px', padding: '4px 12px' }}>
                  Adicionar Regra
                </button>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {customRules.map(rule => (
              <div
                key={rule.id}
                style={{
                  padding: '12px',
                  backgroundColor: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-main)' }}>{rule.name}</span>
                    <span style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: rule.enabled ? 'rgba(0,230,153,0.15)' : 'rgba(239,68,68,0.15)', color: rule.enabled ? 'var(--accent-primary)' : '#f87171' }}>
                      {rule.enabled ? 'Ativo' : 'Inativo'}
                    </span>
                    <span style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>
                      {rule.match_mode === 'all' ? 'Condição: E (Todas)' : 'Condição: OU (Qualquer)'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <button
                      type="button"
                      onClick={() => handleToggleCustomRule(rule.id)}
                      className="btn-secondary"
                      style={{ fontSize: '11px', padding: '3px 8px' }}
                    >
                      {rule.enabled ? 'Desativar' : 'Ativar'}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteCustomRule(rule.id)}
                      style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer' }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  <strong>Gatilhos:</strong> {rule.keywords?.join(', ')}
                </div>

                {Array.isArray(rule.reply_sequence) && rule.reply_sequence.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {rule.reply_sequence.map((seqMsg: string, sIdx: number) => (
                      <div key={sIdx} style={{ fontSize: '11px', color: '#fff', backgroundColor: 'rgba(0,0,0,0.25)', padding: '4px 8px', borderRadius: '4px', borderLeft: '2px solid var(--accent-primary)', whiteSpace: 'pre-wrap' }}>
                        <strong style={{ color: 'var(--accent-primary)' }}>Balão {sIdx + 1}:</strong> {seqMsg}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ fontSize: '12px', color: 'var(--text-main)', backgroundColor: 'rgba(0,0,0,0.2)', padding: '6px 8px', borderRadius: '4px', whiteSpace: 'pre-wrap' }}>
                    {rule.reply_text}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Live Simulator & Tester */}
        <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Play size={20} color="var(--accent-primary)" />
              <h4 style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                Simulador de Automação em Tempo Real
              </h4>
            </div>
            <span style={{ fontSize: '11px', color: 'var(--accent-primary)', fontWeight: '600' }}>
              Teste sem enviar ao WhatsApp
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div>
              <label style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                Mensagem enviada no chat:
              </label>
              <textarea
                rows={3}
                value={testText}
                onChange={e => setTestText(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  backgroundColor: 'rgba(255, 255, 255, 0.04)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-main)',
                  fontSize: '12px',
                  fontFamily: 'inherit',
                  resize: 'vertical'
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: '600', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>
                  Nome do Cliente Teste:
                </label>
                <input
                  type="text"
                  value={testClientName}
                  onChange={e => setTestClientName(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '6px 10px',
                    backgroundColor: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-main)',
                    fontSize: '12px'
                  }}
                />
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '16px' }}>
                <label style={{ fontSize: '12px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={testFromMe}
                    onChange={e => setTestFromMe(e.target.checked)}
                    style={{ accentColor: 'var(--accent-primary)' }}
                  />
                  Enviado pelo Atendente (fromMe)
                </label>
              </div>
            </div>

            <button
              type="button"
              onClick={handleSimulate}
              disabled={testLoading}
              className="btn-primary"
              style={{ padding: '8px 14px', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '6px' }}
            >
              {testLoading ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} fill="currentColor" />}
              {testLoading ? 'Processando Regras...' : '🚀 Simular e Pré-Visualizar Resposta'}
            </button>
          </div>

          {/* Simulation Output Area */}
          {testResult && (
            <div style={{
              padding: '12px 14px',
              backgroundColor: testResult.matched ? 'rgba(0, 230, 153, 0.08)' : 'rgba(239, 68, 68, 0.08)',
              border: `1px solid ${testResult.matched ? 'rgba(0, 230, 153, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
              borderRadius: 'var(--radius-md)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: '700', color: testResult.matched ? 'var(--accent-primary)' : '#f87171' }}>
                  {testResult.matched ? `✅ Correspondência: ${testResult.rule_type} (${testResult.count} mensagens)` : '❌ Nenhuma regra acionada'}
                </span>
                {testResult.os_status && (
                  <span style={{ fontSize: '11px', backgroundColor: 'rgba(0,230,153,0.2)', color: 'var(--accent-primary)', padding: '2px 6px', borderRadius: '4px' }}>
                    Status: {testResult.os_status}
                  </span>
                )}
              </div>

              {testResult.reason && (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0 }}>{testResult.reason}</p>
              )}

              {testResult.messages && testResult.messages.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
                  {testResult.messages.map((m: string, i: number) => (
                    <div
                      key={i}
                      style={{
                        padding: '8px 10px',
                        backgroundColor: 'rgba(0, 0, 0, 0.3)',
                        borderLeft: '3px solid var(--accent-primary)',
                        borderRadius: '0 6px 6px 0',
                        fontSize: '12px',
                        color: '#fff',
                        whiteSpace: 'pre-wrap'
                      }}
                    >
                      <strong style={{ color: 'var(--accent-primary)', display: 'block', marginBottom: '2px', fontSize: '11px' }}>
                        Balão {i + 1} ({typingDelaySec}s digitando...):
                      </strong>
                      {m}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* AI Copilot Modal / Drawer */}
      {isAiCopilotOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(4px)',
          zIndex: 9999,
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '750px',
            height: '80vh',
            backgroundColor: '#0f172a',
            border: '1px solid rgba(59, 130, 246, 0.4)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            {/* Copilot Header */}
            <div style={{
              padding: '16px 20px',
              backgroundColor: 'rgba(59, 130, 246, 0.12)',
              borderBottom: '1px solid rgba(59, 130, 246, 0.3)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '10px',
                  backgroundColor: 'rgba(59, 130, 246, 0.25)',
                  color: '#60a5fa',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}>
                  <Sparkles size={20} />
                </div>
                <div>
                  <h3 style={{ fontSize: '16px', fontWeight: '700', color: '#fff', margin: 0 }}>
                    Assistente Copilot de Criação de Gatilhos (IA)
                  </h3>
                  <p style={{ fontSize: '11px', color: '#94a3b8', margin: '2px 0 0 0' }}>
                    Converse em linguagem natural. A IA entende sua necessidade, sugere melhorias e desenvolve o gatilho automaticamente!
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setIsAiCopilotOpen(false)}
                style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Starter Suggestion Chips */}
            <div style={{
              padding: '10px 16px',
              backgroundColor: 'rgba(0,0,0,0.2)',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              gap: '8px',
              overflowX: 'auto'
            }}>
              <button
                type="button"
                onClick={() => handleSendCopilotMessage('Quero um gatilho para quando enviarmos "Aguardando aprovação" de orçamento, avisar o cliente sobre o prazo de 5 dias.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                💡 Aviso de Orçamento Aguardando Aprovação
              </button>
              <button
                type="button"
                onClick={() => handleSendCopilotMessage('Crie um gatilho para quando o cliente perguntar se consertamos máquina de solda Balmer/Esab, informando que somos autorizada e passando o endereço SOF Sul.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                💡 Assistência Autorizada & Endereço
              </button>
              <button
                type="button"
                onClick={() => handleSendCopilotMessage('Crie uma automação para quando o equipamento estiver pronto para retirada, avisando o horário e forma de pagamento.')}
                style={{ fontSize: '11px', padding: '4px 10px', backgroundColor: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', color: '#cbd5e1', cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                💡 Pronto para Retirada
              </button>
            </div>

            {/* Chat Conversation Scroll Area */}
            <div style={{
              flex: 1,
              padding: '16px 20px',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px'
            }}>
              {copilotHistory.map((item, idx) => (
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
                  </div>

                  {/* If AI proposed a ready rule, render a Card with Action Button */}
                  {item.proposedRule && (
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
                          <CheckCircle2 size={16} /> Gatilho Desenvolvido pela IA
                        </strong>
                        <span style={{ fontSize: '11px', backgroundColor: 'rgba(0, 230, 153, 0.2)', color: 'var(--accent-primary)', padding: '2px 8px', borderRadius: '12px', fontWeight: '600' }}>
                          Pronto para Aplicar
                        </span>
                      </div>

                      <div style={{ fontSize: '12px', color: '#e2e8f0' }}>
                        <div><strong>Nome:</strong> {item.proposedRule.name}</div>
                        <div><strong>Gatilhos:</strong> {item.proposedRule.keywords?.join(', ')}</div>
                        <div><strong>Condição:</strong> {item.proposedRule.match_mode === 'all' ? 'Todas as palavras obrigatórias (E)' : 'Qualquer uma das palavras (OU)'}</div>
                        <div><strong>Disparo:</strong> {item.proposedRule.trigger_on === 'attendant' ? 'Atendente' : item.proposedRule.trigger_on === 'customer' ? 'Cliente' : 'Ambos'}</div>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleApplyProposedRule(item.proposedRule)}
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
                        <Sparkles size={14} /> ✨ Aplicar Gatilho no Sistema
                      </button>
                    </div>
                  )}
                </div>
              ))}

              {copilotLoading && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#94a3b8', fontSize: '12px', fontStyle: 'italic' }}>
                  <RefreshCw size={14} className="animate-spin" color="var(--accent-primary)" />
                  A IA está analisando sua solicitação e estruturando o gatilho...
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
                value={copilotInput}
                onChange={e => setCopilotInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendCopilotMessage();
                  }
                }}
                placeholder="Ex: Quero um gatilho para quando o cliente mandar 'garantia'..."
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
                onClick={() => handleSendCopilotMessage()}
                disabled={copilotLoading || !copilotInput.trim()}
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
        </div>
      )}
    </div>
  );
};
