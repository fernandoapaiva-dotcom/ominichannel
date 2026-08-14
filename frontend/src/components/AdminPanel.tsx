import React, { useState, useEffect } from 'react';
import { Plus, Shield, Phone, Users, Database, Settings, Check, Key, Link2, Activity, Clock, FileText, Pencil, Trash2, X, QrCode, RefreshCw, CheckCircle2 } from 'lucide-react';
import { WhatsAppNumber, User } from '../types';
import { apiFetch } from '../services/api';

export const AdminPanel: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'numbers' | 'users' | 'rag' | 'integrations'>('numbers');
  const [numbers, setNumbers] = useState<WhatsAppNumber[]>([]);
  const [users, setUsers] = useState<User[]>([]);

  // QR Code Modal & Connection Status State
  const [qrModalNumber, setQrModalNumber] = useState<WhatsAppNumber | null>(null);
  const [qrCodeBase64, setQrCodeBase64] = useState<string | null>(null);
  const [qrLoading, setQrLoading] = useState(false);
  const [qrError, setQrError] = useState<string | null>(null);
  const [qrConnectedSuccess, setQrConnectedSuccess] = useState(false);
  const [connectionStatuses, setConnectionStatuses] = useState<{ [numberId: number]: { connected: boolean; state: string } }>({});

  // WhatsApp Number Form & Editing State
  const [editingNumberId, setEditingNumberId] = useState<number | null>(null);
  const [providerType, setProviderType] = useState<'evolution' | 'meta'>('evolution');
  const [deptName, setDeptName] = useState('');
  const [phoneNum, setPhoneNum] = useState('');
  const [instanceName, setInstanceName] = useState('');
  const [metaPhoneNumberId, setMetaPhoneNumberId] = useState('');
  const [metaWabaId, setMetaWabaId] = useState('');
  const [metaAccessToken, setMetaAccessToken] = useState('');

  // User Form & Editing State
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [userName, setUserName] = useState('');
  const [userLogin, setUserLogin] = useState('');
  const [userPassword, setUserPassword] = useState('');
  const [userRole, setUserRole] = useState<'admin' | 'atendente'>('atendente');
  const [selectedNumIds, setSelectedNumIds] = useState<number[]>([]);

  // RAG Upload State
  const [ragTitle, setRagTitle] = useState('');
  const [ragContent, setRagContent] = useState('');

  // Integration Settings State
  const [maskedSettings, setMaskedSettings] = useState<any>(null);
  const [geminiKeyInput, setGeminiKeyInput] = useState('');
  const [geminiModelInput, setGeminiModelInput] = useState('gemini-3.1-flash-lite');
  const [evoUrlInput, setEvoUrlInput] = useState('');
  const [evoKeyInput, setEvoKeyInput] = useState('');
  const [inactivityInput, setInactivityInput] = useState(30);
  const [gdriveFolderInput, setGdriveFolderInput] = useState('');
  const [gdriveClientIdInput, setGdriveClientIdInput] = useState('');
  const [gdriveClientSecretInput, setGdriveClientSecretInput] = useState('');

  // Connection Test Badges State
  const [testResult, setTestResult] = useState<{ type: string; success: boolean; message: string } | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  // Audit Logs State
  const [auditLogs, setAuditLogs] = useState<any[]>([]);

  const fetchAllStatuses = async (numList: WhatsAppNumber[]) => {
    const statuses: { [id: number]: { connected: boolean; state: string } } = {};
    for (const num of numList) {
      if (num.provider_type === 'meta') {
        statuses[num.id] = { connected: true, state: 'open' };
      } else {
        try {
          const res = await apiFetch(`/whatsapp-numbers/${num.id}/connection-status`);
          statuses[num.id] = { connected: res.connected, state: res.state };
        } catch {
          statuses[num.id] = { connected: false, state: 'close' };
        }
      }
    }
    setConnectionStatuses(statuses);
  };

  const loadData = async () => {
    try {
      const numData: WhatsAppNumber[] = await apiFetch('/whatsapp-numbers/');
      const userData = await apiFetch('/users/');
      setNumbers(numData);
      setUsers(userData);
      fetchAllStatuses(numData);
    } catch (err) {
      console.error(err);
    }
  };

  const loadSettingsAndAudit = async () => {
    try {
      const settingsData = await apiFetch('/settings/');
      setMaskedSettings(settingsData);
      setGeminiModelInput(settingsData.gemini_model_name || 'gemini-3.1-flash-lite');
      setEvoUrlInput(settingsData.evolution_api_url);
      setInactivityInput(settingsData.inatividade_minutos);
      setGdriveFolderInput(settingsData.google_drive_folder_id);
      setGdriveClientIdInput(settingsData.google_client_id || '');

      const logs = await apiFetch('/settings/audit-logs');
      setAuditLogs(logs);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadData();
    loadSettingsAndAudit();

    const interval = setInterval(() => {
      if (numbers.length > 0) {
        fetchAllStatuses(numbers);
      }
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const openQrModal = async (num: WhatsAppNumber) => {
    setQrModalNumber(num);
    setQrConnectedSuccess(false);
    setQrLoading(true);
    setQrError(null);
    setQrCodeBase64(null);

    try {
      const res = await apiFetch(`/whatsapp-numbers/${num.id}/qrcode`);
      if (res.qrcode) {
        setQrCodeBase64(res.qrcode);
        setQrError(null);
      } else if (res.error) {
        setQrError(res.error);
      } else {
        setQrError("Não foi possível gerar a imagem do QR Code. Verifique se o servidor da Evolution API está acessível.");
      }
    } catch (err: any) {
      console.error('Error fetching QR code:', err);
      setQrError(err.message || "Erro ao conectar com a Evolution API.");
    } finally {
      setQrLoading(false);
    }
  };

  // Poll connection status and refresh QR code when QR Modal is active
  // Poll connection status and refresh QR code while QR Modal is active
  useEffect(() => {
    if (!qrModalNumber) return;

    const modalInterval = setInterval(async () => {
      try {
        const statusRes = await apiFetch(`/whatsapp-numbers/${qrModalNumber.id}/connection-status`);
        if (statusRes.connected) {
          setQrConnectedSuccess(true);
          setQrError(null);
          setConnectionStatuses(prev => ({ ...prev, [qrModalNumber.id]: { connected: true, state: 'open' } }));
          setTimeout(() => {
            setQrModalNumber(null);
            setQrConnectedSuccess(false);
            loadData();
          }, 2500);
        } else if (!qrConnectedSuccess) {
          // Refresh QR Code image in real-time in case Evolution API rotated the QR token
          const qrRes = await apiFetch(`/whatsapp-numbers/${qrModalNumber.id}/qrcode`);
          if (qrRes.qrcode) {
            setQrCodeBase64(qrRes.qrcode);
            setQrError(null);
          }
        }
      } catch (err: any) {
        console.error('Error in QR status polling:', err);
      }
    }, 3000);

    return () => clearInterval(modalInterval);
  }, [qrModalNumber, qrConnectedSuccess]);

  // --- WhatsApp Numbers Handlers ---
  const handleSaveNumber = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (!deptName.trim() || !phoneNum.trim()) {
        alert('Por favor, preencha o nome do departamento e o número do WhatsApp.');
        return;
      }

      if (providerType === 'evolution') {
        if (!instanceName.trim()) {
          alert('Por favor, preencha o Nome da Instância na Evolution API.');
          return;
        }
      } else if (providerType === 'meta') {
        if (!metaPhoneNumberId.trim()) {
          alert('Por favor, preencha o Phone Number ID da Meta API.');
          return;
        }
        if (!metaWabaId.trim()) {
          alert('Por favor, preencha o WABA ID da Meta API.');
          return;
        }
        if (!editingNumberId && !metaAccessToken.trim()) {
          alert('Por favor, informe o Access Token da Meta API.');
          return;
        }
      }

      const payload: any = {
        provider_type: providerType,
        nome_departamento: deptName.trim(),
        numero: phoneNum.trim(),
        status: true
      };

      if (providerType === 'evolution') {
        payload.instancia_evolution_api = instanceName.trim();
      } else {
        payload.meta_phone_number_id = metaPhoneNumberId.trim();
        payload.meta_waba_id = metaWabaId.trim();
        if (metaAccessToken.trim()) {
          payload.meta_access_token = metaAccessToken.trim();
        }
      }

      if (editingNumberId) {
        await apiFetch(`/whatsapp-numbers/${editingNumberId}`, {
          method: 'PUT',
          body: JSON.stringify(payload)
        });
        alert('Departamento atualizado com sucesso!');
      } else {
        await apiFetch('/whatsapp-numbers/', {
          method: 'POST',
          body: JSON.stringify(payload)
        });
        alert('Número de WhatsApp / Departamento adicionado!');
      }

      resetNumberForm();
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleEditNumber = (num: WhatsAppNumber) => {
    setEditingNumberId(num.id);
    setProviderType(num.provider_type || 'evolution');
    setDeptName(num.nome_departamento);
    setPhoneNum(num.numero);
    setInstanceName(num.instancia_evolution_api || '');
    setMetaPhoneNumberId(num.meta_phone_number_id || '');
    setMetaWabaId(num.meta_waba_id || '');
    setMetaAccessToken('');
  };

  const handleDeleteNumber = async (num: WhatsAppNumber) => {
    if (!window.confirm(`Deseja realmente excluir o departamento '${num.nome_departamento}' (${num.numero})?`)) return;
    try {
      await apiFetch(`/whatsapp-numbers/${num.id}`, { method: 'DELETE' });
      loadData();
      alert('Departamento excluído com sucesso!');
    } catch (err: any) {
      alert(err.message);
    }
  };

  const resetNumberForm = () => {
    setEditingNumberId(null);
    setProviderType('evolution');
    setDeptName('');
    setPhoneNum('');
    setInstanceName('');
    setMetaPhoneNumberId('');
    setMetaWabaId('');
    setMetaAccessToken('');
  };

  // --- User Handlers ---
  const handleSaveUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingUserId) {
        const payload: any = {
          nome: userName,
          login: userLogin,
          role: userRole,
          status: true,
          whatsapp_number_ids: selectedNumIds
        };
        if (userPassword.trim()) {
          payload.senha = userPassword;
        }

        await apiFetch(`/users/${editingUserId}`, {
          method: 'PUT',
          body: JSON.stringify(payload)
        });
        alert('Atendente atualizado com sucesso!');
      } else {
        await apiFetch('/users/', {
          method: 'POST',
          body: JSON.stringify({
            nome: userName,
            login: userLogin,
            senha: userPassword,
            role: userRole,
            status: true,
            whatsapp_number_ids: selectedNumIds
          })
        });
        alert('Usuário cadastrado com sucesso!');
      }

      resetUserForm();
      loadData();
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleEditUser = (u: User) => {
    setEditingUserId(u.id);
    setUserName(u.nome);
    setUserLogin(u.login);
    setUserPassword('');
    setUserRole(u.role);
    setSelectedNumIds(u.whatsapp_numbers.map(n => n.id));
  };

  const handleDeleteUser = async (u: User) => {
    if (!window.confirm(`Deseja realmente excluir o usuário '${u.nome}' (${u.login})?`)) return;
    try {
      await apiFetch(`/users/${u.id}`, { method: 'DELETE' });
      loadData();
      alert('Usuário excluído com sucesso!');
    } catch (err: any) {
      alert(err.message);
    }
  };

  const resetUserForm = () => {
    setEditingUserId(null);
    setUserName('');
    setUserLogin('');
    setUserPassword('');
    setUserRole('atendente');
    setSelectedNumIds([]);
  };

  // --- RAG Upload Handler ---
  const handleUploadRAG = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiFetch('/rag/upload', {
        method: 'POST',
        body: JSON.stringify({
          doc_id: `doc_${Date.now()}`,
          titulo: ragTitle,
          content: ragContent
        })
      });
      setRagTitle('');
      setRagContent('');
      alert('Conhecimento RAG adicionado à IA Concierge!');
    } catch (err: any) {
      alert(err.message);
    }
  };

  // --- Integration Settings Handlers ---
  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      // Validate that placeholder strings are never sent as actual keys
      const cleanGeminiKey = geminiKeyInput.trim();
      const cleanEvoKey = evoKeyInput.trim();

      const invalidPlaceholders = ['master key', 'nova master key', 'sua chave aqui', 'placeholder'];
      if (cleanEvoKey && invalidPlaceholders.includes(cleanEvoKey.toLowerCase())) {
        alert('Por favor, insira a sua Master Key real da Evolution API (ex: admin_key_123), não um texto explicativo/placeholder.');
        return;
      }
      if (cleanGeminiKey && invalidPlaceholders.includes(cleanGeminiKey.toLowerCase())) {
        alert('Por favor, insira uma API Key real do Gemini.');
        return;
      }

      await apiFetch('/settings/', {
        method: 'POST',
        body: JSON.stringify({
          gemini_api_key: cleanGeminiKey || undefined,
          gemini_model_name: geminiModelInput,
          evolution_api_url: evoUrlInput || undefined,
          evolution_api_key: cleanEvoKey || undefined,
          inatividade_minutos: inactivityInput,
          google_drive_folder_id: gdriveFolderInput || undefined,
          google_client_id: gdriveClientIdInput || undefined,
          google_client_secret: gdriveClientSecretInput || undefined
        })
      });
      setGeminiKeyInput('');
      setEvoKeyInput('');
      setGdriveClientSecretInput('');
      loadSettingsAndAudit();
      alert('Configurações salvas e criptografadas com sucesso!');
    } catch (err: any) {
      alert(`Erro ao salvar configurações: ${err.message}`);
    }
  };

  const handleTestConnection = async (type: 'gemini' | 'evolution') => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await apiFetch('/settings/test', {
        method: 'POST',
        body: JSON.stringify({
          integration_type: type,
          test_key: type === 'gemini' ? (geminiKeyInput.trim() || undefined) : (evoKeyInput.trim() || undefined),
          test_model: type === 'gemini' ? geminiModelInput : undefined,
          test_url: type === 'evolution' ? (evoUrlInput.trim() || undefined) : undefined
        })
      });
      setTestResult({ type, success: res.success, message: res.message });
      loadSettingsAndAudit();

      if (res.success) {
        alert(`✅ SUCESSO NA CONEXÃO [${type.toUpperCase()}]!\n\n${res.message}`);
      } else {
        alert(`❌ FALHA NA CONEXÃO [${type.toUpperCase()}]!\n\n${res.message}`);
      }
    } catch (err: any) {
      const errorMsg = err.message || 'Falha ao testar conexão com a API.';
      setTestResult({ type, success: false, message: errorMsg });
      alert(`❌ ERRO AO TESTAR CONEXÃO [${type.toUpperCase()}]:\n\n${errorMsg}`);
    } finally {
      setTestLoading(false);
    }
  };

  const handleConnectGoogleOAuth = async () => {
    try {
      const res = await apiFetch('/settings/auth/google/url');
      if (res.url) {
        window.open(res.url, '_blank');
      }
    } catch (err: any) {
      alert(err.message);
    }
  };

  const toggleNumSelect = (id: number) => {
    if (selectedNumIds.includes(id)) {
      setSelectedNumIds(selectedNumIds.filter(n => n !== id));
    } else {
      setSelectedNumIds([...selectedNumIds, id]);
    }
  };

  return (
    <div style={{ flex: 1, height: '100%', padding: '32px', overflowY: 'auto', backgroundColor: 'var(--bg-primary)' }}>
      <div style={{ maxWidth: '1050px', margin: '0 auto' }}>
        <h1 style={{ fontFamily: 'var(--font-heading)', fontSize: '26px', fontWeight: '700', marginBottom: '8px' }}>
          Painel de Administração Multitenant
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '14px', marginBottom: '24px' }}>
          Gerencie departamentos, permissões N:N de atendentes, integrações criptografadas e auditoria.
        </p>

        {/* Sub-tab Navigation Bar */}
        <div style={{ display: 'flex', gap: '12px', borderBottom: '1px solid var(--border-color)', marginBottom: '24px', paddingBottom: '12px' }}>
          <button
            onClick={() => setActiveSubTab('numbers')}
            className={activeSubTab === 'numbers' ? 'btn-primary' : 'btn-secondary'}
          >
            <Phone size={16} /> Números / Departamentos
          </button>
          <button
            onClick={() => setActiveSubTab('users')}
            className={activeSubTab === 'users' ? 'btn-primary' : 'btn-secondary'}
          >
            <Users size={16} /> Atendentes & Permissões
          </button>
          <button
            onClick={() => setActiveSubTab('rag')}
            className={activeSubTab === 'rag' ? 'btn-primary' : 'btn-secondary'}
          >
            <Database size={16} /> Base RAG (IA Concierge)
          </button>
          <button
            onClick={() => setActiveSubTab('integrations')}
            className={activeSubTab === 'integrations' ? 'btn-primary' : 'btn-secondary'}
          >
            <Key size={16} /> Integrações & Segurança (Fernet)
          </button>
        </div>

        {/* 1. Numbers / Departments Tab */}
        {activeSubTab === 'numbers' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px' }}>
                  {editingNumberId ? 'Editar Número / Departamento' : 'Cadastrar Novo Número / Dpto'}
                </h3>
                {editingNumberId && (
                  <button onClick={resetNumberForm} style={{ background: 'transparent', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <X size={14} /> Cancelar Edição
                  </button>
                )}
              </div>

              <form onSubmit={handleSaveNumber} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Provedor de Conexão</label>
                  <select
                    value={providerType}
                    onChange={(e) => setProviderType(e.target.value as 'evolution' | 'meta')}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  >
                    <option value="evolution">Evolution API (Self-Hosted)</option>
                    <option value="meta">WhatsApp API Oficial (Meta)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nome do Departamento</label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: Financeiro ou Suporte Técnico"
                    value={deptName}
                    onChange={(e) => setDeptName(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Número do WhatsApp</label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: 5511999990001"
                    value={phoneNum}
                    onChange={(e) => setPhoneNum(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>

                {providerType === 'evolution' ? (
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Instância Evolution API (Self-Hosted)</label>
                    <input
                      type="text"
                      required={providerType === 'evolution'}
                      placeholder="Ex: instancia_vendas"
                      value={instanceName}
                      onChange={(e) => setInstanceName(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>
                ) : (
                  <>
                    <div>
                      <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Phone Number ID (Meta API)</label>
                      <input
                        type="text"
                        required={providerType === 'meta'}
                        placeholder="Ex: 1048209823901"
                        value={metaPhoneNumberId}
                        onChange={(e) => setMetaPhoneNumberId(e.target.value)}
                        style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>WABA ID (WhatsApp Business Account ID)</label>
                      <input
                        type="text"
                        required={providerType === 'meta'}
                        placeholder="Ex: 9283019823910"
                        value={metaWabaId}
                        onChange={(e) => setMetaWabaId(e.target.value)}
                        style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Access Token (Meta Cloud API)</label>
                      <input
                        type="password"
                        required={providerType === 'meta' && !editingNumberId}
                        placeholder={editingNumberId ? "Deixe em branco para manter o token atual" : "EAAG... (Token Permanente)"}
                        value={metaAccessToken}
                        onChange={(e) => setMetaAccessToken(e.target.value)}
                        style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                      />
                    </div>
                  </>
                )}

                <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>
                  {editingNumberId ? <Pencil size={16} /> : <Plus size={16} />}
                  {editingNumberId ? 'Salvar Alterações' : 'Salvar Número'}
                </button>
              </form>
            </div>

            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '18px', marginBottom: '16px' }}>Números Ativos ({numbers.length})</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {numbers.map(num => (
                  <div key={num.id} style={{ padding: '14px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(255, 255, 255, 0.02)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: '600', fontSize: '15px' }}>{num.nome_departamento}</span>
                        <span style={{
                          fontSize: '10px',
                          fontWeight: '700',
                          padding: '2px 6px',
                          borderRadius: '4px',
                          backgroundColor: num.provider_type === 'meta' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                          color: num.provider_type === 'meta' ? '#60a5fa' : '#34d399',
                          textTransform: 'uppercase'
                        }}>
                          {num.provider_type === 'meta' ? 'Meta Oficial' : 'Evolution'}
                        </span>
                        {/* Live Connection Status Badge */}
                        {connectionStatuses[num.id] && (
                          <span style={{
                            fontSize: '10px',
                            fontWeight: '600',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            backgroundColor: connectionStatuses[num.id].connected ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: connectionStatuses[num.id].connected ? '#34d399' : '#f87171',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                          }}>
                            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: connectionStatuses[num.id].connected ? '#34d399' : '#f87171' }} />
                            {connectionStatuses[num.id].connected ? 'Conectado' : 'Desconectado'}
                          </span>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        {num.provider_type !== 'meta' && (
                          <button
                            onClick={() => openQrModal(num)}
                            title="Conectar WhatsApp via QR Code"
                            style={{
                              background: 'linear-gradient(135deg, #10b981, #059669)',
                              color: '#fff',
                              padding: '6px 12px',
                              borderRadius: 'var(--radius-sm)',
                              fontSize: '12px',
                              fontWeight: '600',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                              border: 'none',
                              cursor: 'pointer'
                            }}
                          >
                            <QrCode size={14} />
                            Conectar WhatsApp
                          </button>
                        )}
                        <button
                          onClick={() => handleEditNumber(num)}
                          title="Editar Departamento"
                          style={{ background: 'rgba(255, 255, 255, 0.08)', color: 'var(--text-main)', padding: '6px', borderRadius: 'var(--radius-sm)' }}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => handleDeleteNumber(num)}
                          title="Excluir Departamento"
                          style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '6px', borderRadius: 'var(--radius-sm)' }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '6px' }}>
                      Número: <strong>{num.numero}</strong> | {num.provider_type === 'meta' ? (
                        <>Phone ID: <code>{num.meta_phone_number_id}</code></>
                      ) : (
                        <>Instância: <code>{num.instancia_evolution_api}</code></>
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* QR Code Modal for Evolution Provider */}
            {qrModalNumber && (
              <div style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                backgroundColor: 'rgba(0, 0, 0, 0.75)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 9999,
                backdropFilter: 'blur(4px)'
              }}>
                <div style={{
                  backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '28px',
                  maxWidth: '420px',
                  width: '90%',
                  position: 'relative',
                  textAlign: 'center',
                  boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)'
                }}>
                  <button
                    onClick={() => setQrModalNumber(null)}
                    style={{
                      position: 'absolute',
                      top: '16px',
                      right: '16px',
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer'
                    }}
                  >
                    <X size={20} />
                  </button>

                  <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '4px', color: 'var(--text-main)' }}>
                    Conectar WhatsApp
                  </h3>
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
                    {qrModalNumber.nome_departamento} ({qrModalNumber.instancia_evolution_api || qrModalNumber.numero})
                  </p>

                  {qrConnectedSuccess ? (
                    <div style={{ padding: '30px 10px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
                      <CheckCircle2 size={54} color="#10b981" />
                      <h4 style={{ fontSize: '18px', color: '#10b981', margin: 0 }}>WhatsApp Conectado!</h4>
                      <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Sua instância está ativa e pronta para enviar/receber mensagens.</p>
                    </div>
                  ) : (
                    <>
                      <div style={{
                        width: '240px',
                        height: '240px',
                        margin: '0 auto 16px auto',
                        backgroundColor: '#ffffff',
                        padding: '12px',
                        borderRadius: 'var(--radius-md)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        border: '1px solid var(--border-color)'
                      }}>
                        {qrLoading ? (
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#666' }}>
                            <RefreshCw size={32} className="spin" />
                            <span style={{ fontSize: '12px' }}>Gerando QR Code...</span>
                          </div>
                        ) : qrError ? (
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '10px', color: '#ef4444', textAlign: 'center' }}>
                            <X size={32} />
                            <span style={{ fontSize: '11px', fontWeight: '600' }}>{qrError}</span>
                            <button
                              onClick={() => openQrModal(qrModalNumber)}
                              style={{
                                marginTop: '6px',
                                padding: '6px 12px',
                                backgroundColor: '#ef4444',
                                color: '#ffffff',
                                border: 'none',
                                borderRadius: '4px',
                                fontSize: '11px',
                                fontWeight: '600',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px'
                              }}
                            >
                              <RefreshCw size={12} />
                              Tentar novamente
                            </button>
                          </div>
                        ) : qrCodeBase64 ? (
                          <img
                            src={qrCodeBase64.startsWith('data:image') ? qrCodeBase64 : `data:image/png;base64,${qrCodeBase64}`}
                            alt="QR Code WhatsApp"
                            style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                          />
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#666' }}>
                            <RefreshCw size={28} className="spin" />
                            <span style={{ fontSize: '12px' }}>Aguardando imagem...</span>
                          </div>
                        )}
                      </div>

                      {qrError && (
                        <button
                          onClick={() => openQrModal(qrModalNumber)}
                          className="btn-primary"
                          style={{
                            width: '100%',
                            marginBottom: '14px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '8px',
                            padding: '10px',
                            backgroundColor: '#3b82f6',
                            fontSize: '13px',
                            fontWeight: '600'
                          }}
                        >
                          <RefreshCw size={16} />
                          Tentar Novamente
                        </button>
                      )}

                      <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.5', margin: 0 }}>
                        Abra o WhatsApp no celular {'>'} <strong>Aparelhos conectados</strong> {'>'} <strong>Conectar um aparelho</strong> e aponte a câmera para a imagem acima.
                      </p>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '14px', fontSize: '11px', color: 'var(--text-muted)' }}>
                        <RefreshCw size={12} className="spin" />
                        <span>Atualiza automaticamente a cada 4 segundos...</span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* 2. Users & Permissions Tab */}
        {activeSubTab === 'users' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px' }}>
                  {editingUserId ? 'Editar Atendente / Usuário' : 'Criar Usuário / Atendente'}
                </h3>
                {editingUserId && (
                  <button onClick={resetUserForm} style={{ background: 'transparent', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <X size={14} /> Cancelar Edição
                  </button>
                )}
              </div>

              <form onSubmit={handleSaveUser} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Nome Completo</label>
                  <input
                    type="text"
                    required
                    placeholder="Carlos Atendente"
                    value={userName}
                    onChange={(e) => setUserName(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Login de Acesso</label>
                  <input
                    type="text"
                    required
                    placeholder="atendente1"
                    value={userLogin}
                    onChange={(e) => setUserLogin(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Senha {editingUserId ? '(deixe em branco se não quiser alterar)' : '*'}
                  </label>
                  <input
                    type="password"
                    required={!editingUserId}
                    placeholder="******"
                    value={userPassword}
                    onChange={(e) => setUserPassword(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Perfil (Role)</label>
                  <select
                    value={userRole}
                    onChange={(e) => setUserRole(e.target.value as any)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  >
                    <option value="atendente">Atendente</option>
                    <option value="admin">Administrador</option>
                  </select>
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', display: 'block' }}>
                    Permissão de Acesso aos Números/Departamentos:
                  </label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {numbers.map(num => (
                      <div
                        key={num.id}
                        onClick={() => toggleNumSelect(num.id)}
                        style={{
                          padding: '8px 12px',
                          borderRadius: 'var(--radius-md)',
                          border: selectedNumIds.includes(num.id) ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                          backgroundColor: selectedNumIds.includes(num.id) ? 'rgba(0, 230, 153, 0.1)' : 'var(--bg-secondary)',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontSize: '13px'
                        }}
                      >
                        <span>{num.nome_departamento} ({num.numero})</span>
                        {selectedNumIds.includes(num.id) && <Check size={16} style={{ color: 'var(--accent-primary)' }} />}
                      </div>
                    ))}
                  </div>
                </div>

                <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>
                  {editingUserId ? <Pencil size={16} /> : <Plus size={16} />}
                  {editingUserId ? 'Salvar Alterações' : 'Salvar Usuário'}
                </button>
              </form>
            </div>

            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '18px', marginBottom: '16px' }}>Usuários Cadastrados ({users.length})</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {users.map(u => (
                  <div key={u.id} style={{ padding: '14px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(255, 255, 255, 0.02)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <span style={{ fontWeight: '600', fontSize: '15px' }}>{u.nome} ({u.login})</span>
                        <span className="badge badge-com_humano" style={{ marginLeft: '8px' }}>{u.role}</span>
                      </div>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <button
                          onClick={() => handleEditUser(u)}
                          title="Editar Usuário"
                          style={{ background: 'rgba(255, 255, 255, 0.08)', color: 'var(--text-main)', padding: '6px', borderRadius: 'var(--radius-sm)' }}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => handleDeleteUser(u)}
                          title="Excluir Usuário"
                          style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '6px', borderRadius: 'var(--radius-sm)' }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px' }}>
                      Departamentos autorizados: {u.whatsapp_numbers.map(n => n.nome_departamento).join(', ') || 'Nenhum (ou Admin Total)'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 3. RAG Knowledge Upload Tab */}
        {activeSubTab === 'rag' && (
          <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
            <h3 style={{ fontSize: '18px', marginBottom: '12px' }}>Adicionar Conhecimento para RAG (Gemini)</h3>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
              Insira FAQs, tabelas de preços, regras de locação ou manuais técnicos para que a IA Concierge responda com precisão antes de transferir para atendente humano.
            </p>

            <form onSubmit={handleUploadRAG} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Título do Documento</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: Tabela de Preços de Locação de Andaimes 2026"
                  value={ragTitle}
                  onChange={(e) => setRagTitle(e.target.value)}
                  style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Conteúdo do Documento (Texto corrido ou FAQ)</label>
                <textarea
                  required
                  rows={8}
                  placeholder="Ex: Pergunta: Qual o horário de atendimento? Resposta: Segunda a Sexta das 08h às 18h..."
                  value={ragContent}
                  onChange={(e) => setRagContent(e.target.value)}
                  style={{ width: '100%', padding: '12px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', resize: 'vertical' }}
                />
              </div>

              <button type="submit" className="btn-primary" style={{ alignSelf: 'flex-start' }}>
                <Database size={16} /> Indexar no RAG Local (ChromaDB)
              </button>
            </form>
          </div>
        )}

        {/* 4. Integrations & Dynamic Fernet Security Tab */}
        {activeSubTab === 'integrations' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Critical Backup Warning Alert Box */}
            <div style={{
              padding: '16px 20px',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'rgba(234, 179, 8, 0.12)',
              border: '1px solid rgba(234, 179, 8, 0.35)',
              color: '#facc15',
              fontSize: '13px',
              lineHeight: '1.5',
              display: 'flex',
              gap: '12px',
              alignItems: 'flex-start'
            }}>
              <Shield size={24} style={{ flexShrink: 0, marginTop: '2px', color: '#facc15' }} />
              <div>
                <strong style={{ fontSize: '14px', display: 'block', marginBottom: '4px' }}>
                  ⚠️ AVISO CRÍTICO — BACKUP DA CHAVE MESTRA (ENCRYPTION_MASTER_KEY)
                </strong>
                Guarde uma cópia de segurança da variável <code>ENCRYPTION_MASTER_KEY</code> em um local seguro fora do servidor. 
                Todas as chaves sensíveis (Gemini API, Evolution API e Google Drive Tokens) são salvas criptografadas via Fernet.
                <strong> Se o servidor for formatado ou a chave for perdida, todos os dados de integração salvos ficarão permanentemente irrecuperáveis!</strong>
              </div>
            </div>

            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '18px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Key size={20} style={{ color: 'var(--accent-primary)' }} /> Configurações de Integração Criptografadas
              </h3>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
                As chaves sensíveis são armazenadas com criptografia simétrica **Fernet (AES-128)** no banco de dados. Os valores originais nunca são retornados via API após salvos.
              </p>

              {testResult && (
                <div style={{
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  marginBottom: '20px',
                  backgroundColor: testResult.success ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                  border: testResult.success ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                  color: testResult.success ? '#34d399' : '#f87171',
                  fontSize: '13px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <Activity size={16} /> [{testResult.type.toUpperCase()}] {testResult.message}
                </div>
              )}

              <form onSubmit={handleSaveSettings} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {/* Gemini Integration */}
                <div style={{ padding: '16px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-secondary)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <label style={{ fontWeight: '600', fontSize: '14px' }}>Google Gemini API Key</label>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Valor Salvo no Banco: <code style={{ color: 'var(--accent-primary)' }}>{maskedSettings?.gemini_api_key_masked}</code>
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
                    <input
                      type="password"
                      placeholder="Digite a nova chave para salvar (ex: AIzaSy...)"
                      value={geminiKeyInput}
                      onChange={(e) => setGeminiKeyInput(e.target.value)}
                      style={{ flex: 1, padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                    <button
                      type="button"
                      onClick={() => handleTestConnection('gemini')}
                      className="btn-secondary"
                      disabled={testLoading}
                    >
                      Testar Conexão Gemini
                    </button>
                  </div>

                  {/* Configurable Gemini Model Name Input */}
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
                      Modelo da Gemini API (ex: <code>gemini-2.0-flash</code>, <code>gemini-1.5-flash</code>)
                    </label>
                    <input
                      type="text"
                      placeholder="gemini-2.0-flash"
                      value={geminiModelInput}
                      onChange={(e) => setGeminiModelInput(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>

                  {/* RAG Flow Live Execution Button */}
                  <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '12px', marginTop: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Testar fluxo RAG de ponta a ponta com a chave do banco:</span>
                    <button
                      type="button"
                      onClick={async () => {
                        setTestLoading(true);
                        try {
                          const res = await apiFetch('/rag/test-flow', { method: 'POST' });
                          alert(`✅ SUCCESSO! Consumiu ${res.tokens.total_tokens} tokens.\n\nPergunta: "${res.pergunta}"\n\nResposta da IA:\n"${res.resposta_ia}"\n\n(Prompt: ${res.tokens.prompt_tokens} tokens | Resposta: ${res.tokens.response_tokens} tokens)`);
                          loadSettingsAndAudit();
                        } catch (err: any) {
                          alert(`❌ ERRO: ${err.message}`);
                        } finally {
                          setTestLoading(false);
                        }
                      }}
                      className="btn-primary"
                      style={{ fontSize: '12px', padding: '6px 14px' }}
                      disabled={testLoading}
                    >
                      <Activity size={14} /> Executar Teste RAG + IA (Live com Chave do Banco)
                    </button>
                  </div>
                </div>

                {/* Evolution API Integration */}
                <div style={{ padding: '16px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-secondary)' }}>
                  <label style={{ fontWeight: '600', fontSize: '14px', marginBottom: '8px', display: 'block' }}>Evolution API (Self-Hosted)</label>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                    <div>
                      <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>URL da API Server</label>
                      <input
                        type="text"
                        placeholder="http://localhost:8080"
                        value={evoUrlInput}
                        onChange={(e) => setEvoUrlInput(e.target.value)}
                        style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        API Master Key (Salva: <code style={{ color: 'var(--accent-primary)' }}>{maskedSettings?.evolution_api_key_masked || 'Não configurada'}</code>)
                      </label>
                      <input
                        type="password"
                        placeholder="Digite a chave real (ex: omini_master_key_123)"
                        value={evoKeyInput}
                        onChange={(e) => setEvoKeyInput(e.target.value)}
                        style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleTestConnection('evolution')}
                    className="btn-secondary"
                    disabled={testLoading}
                  >
                    Testar Conexão Evolution API
                  </button>
                </div>

                {/* Inactivity & Google Drive */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div style={{ padding: '16px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-secondary)' }}>
                    <label style={{ fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Clock size={16} /> Tempo de Inatividade (Minutos)
                    </label>
                    <input
                      type="number"
                      min={5}
                      max={1440}
                      value={inactivityInput}
                      onChange={(e) => setInactivityInput(parseInt(e.target.value) || 30)}
                      style={{ width: '100%', padding: '10px', marginTop: '8px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>

                  <div style={{ padding: '16px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-secondary)' }}>
                    <label style={{ fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '12px' }}>
                      <Link2 size={16} style={{ color: 'var(--accent-primary)' }} /> Google Drive Backup & Sync
                    </label>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {/* OAuth Client Credentials Inputs */}
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                        <div>
                          <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block', fontWeight: '600' }}>
                            Google OAuth Client ID
                          </label>
                          <input
                            type="text"
                            placeholder="ex: 123456789-abc.apps.googleusercontent.com"
                            value={gdriveClientIdInput}
                            onChange={(e) => setGdriveClientIdInput(e.target.value)}
                            style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '13px' }}
                          />
                        </div>
                        <div>
                          <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block', fontWeight: '600' }}>
                            Google OAuth Client Secret (Salvo: <code style={{ color: 'var(--accent-primary)' }}>{maskedSettings?.google_client_secret_masked || 'Não salvo'}</code>)
                          </label>
                          <input
                            type="password"
                            placeholder="Digite o segredo da chave Google"
                            value={gdriveClientSecretInput}
                            onChange={(e) => setGdriveClientSecretInput(e.target.value)}
                            style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '13px' }}
                          />
                        </div>
                      </div>

                      {/* OAuth Connection Status & Button */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', backgroundColor: 'var(--bg-primary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>Conexão com a Conta Google</div>
                          <div style={{ fontSize: '12px', color: maskedSettings?.google_drive_connected ? '#34d399' : '#f87171', marginTop: '2px', fontWeight: '500' }}>
                            Status: {maskedSettings?.google_drive_connected ? '● Conta Google Conectada e Autorizada' : '○ Não conectado'}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={handleConnectGoogleOAuth}
                          className="btn-secondary"
                          style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}
                        >
                          Conectar Conta Google via OAuth2
                        </button>
                      </div>

                      {/* Target Folder ID Input */}
                      <div>
                        <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block', fontWeight: '600' }}>
                          ID ou URL da Pasta Destino no Google Drive (Root Folder ID)
                        </label>
                        <input
                          type="text"
                          placeholder="Cole o ID da pasta (ex: 1ABC_GoogleDriveFolderID_Sample ou a URL completa)"
                          value={gdriveFolderInput}
                          onChange={(e) => setGdriveFolderInput(e.target.value)}
                          style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', fontSize: '13px' }}
                        />
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px', lineHeight: '1.4' }}>
                          💡 <strong>Como obter o ID:</strong> Acesse a pasta desejada no Google Drive e copie o código no final do endereço da página.<br />
                          Exemplo de URL: <code>drive.google.com/drive/folders/<strong>1ABC_ID_DA_SUA_PASTA</strong></code>
                        </p>
                      </div>

                      {/* Folder Structure Explanation Card */}
                      <div style={{ padding: '12px', backgroundColor: 'rgba(0, 230, 153, 0.05)', border: '1px solid rgba(0, 230, 153, 0.2)', borderRadius: 'var(--radius-md)', fontSize: '12px', color: 'var(--text-main)' }}>
                        <div style={{ fontWeight: '600', color: 'var(--accent-primary)', marginBottom: '6px' }}>📁 Estrutura de Salvamento Automático no Google Drive:</div>
                        <div style={{ fontFamily: 'monospace', fontSize: '11px', color: '#cbd5e1', lineHeight: '1.6' }}>
                          Sua Pasta Google Drive/<br />
                          ├── 📂 [Departamento] (ex: Vendas, Locação)<br />
                          │   └── 📂 [Nome do Cliente - Telefone]/<br />
                          │       ├── 📄 backup_historico_conversa.json<br />
                          │       └── 📷 arquivos_e_midias/
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <button type="submit" className="btn-primary" style={{ alignSelf: 'flex-start', padding: '12px 24px' }}>
                  Salvar Configurações Criptografadas
                </button>
              </form>
            </div>

            {/* Audit Logs Table */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '18px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <FileText size={18} style={{ color: 'var(--accent-primary)' }} /> Log de Auditoria do Sistema
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '300px', overflowY: 'auto' }}>
                {auditLogs.length === 0 ? (
                  <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhum evento registrado ainda.</p>
                ) : (
                  auditLogs.map(log => (
                    <div key={log.id} style={{ padding: '10px 14px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(255, 255, 255, 0.02)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <span style={{ fontWeight: '600', fontSize: '13px', color: 'var(--text-main)' }}>
                          {log.user_name || 'Sistema'} — <code style={{ color: 'var(--accent-primary)' }}>{log.acao}</code>
                        </span>
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>{log.detalhes}</p>
                      </div>
                      <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
                        {new Date(log.timestamp).toLocaleString()}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
