import React, { useState, useEffect } from 'react';
import { Plus, Shield, Phone, Users, Database, Settings, Check, Key, Link2, Activity, Clock, FileText, Pencil, Trash2, X, QrCode, RefreshCw, CheckCircle2, MessageSquare, Bot, Camera, Cpu, Wrench, Building } from 'lucide-react';
import { WhatsAppNumber, User, WhatsAppGroup, AuthorizedTechnician } from '../types';
import { apiFetch } from '../services/api';
import { AvatarCropModal } from './AvatarCropModal';

export const AdminPanel: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'numbers' | 'users' | 'rag' | 'technicians' | 'integrations' | 'groups' | 'pix'>('numbers');
  const [numbers, setNumbers] = useState<WhatsAppNumber[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [groups, setGroups] = useState<WhatsAppGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [syncingGroups, setSyncingGroups] = useState(false);

  // QR Code Modal & Connection Status State
  const [qrModalNumber, setQrModalNumber] = useState<WhatsAppNumber | null>(null);
  const [qrCodeBase64, setQrCodeBase64] = useState<string | null>(null);
  const [pairingCode, setPairingCode] = useState<string | null>(null);
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
  const [userAvatar, setUserAvatar] = useState<string | null>(null);
  const [isAvatarCropOpen, setIsAvatarCropOpen] = useState(false);
  const [userRole, setUserRole] = useState<'admin' | 'atendente'>('atendente');
  const [selectedNumIds, setSelectedNumIds] = useState<number[]>([]);

  // RAG Upload & Progress State
  const [ragScope, setRagScope] = useState<'geral' | 'setor'>('geral');
  const [ragDeptId, setRagDeptId] = useState<number | ''>('');
  const [ragTitle, setRagTitle] = useState('');
  const [ragContent, setRagContent] = useState('');
  const [ragFiles, setRagFiles] = useState<FileList | null>(null);
  const [ragDocuments, setRagDocuments] = useState<any[]>([]);
  const [ragLoading, setRagLoading] = useState(false);

  // Progress Bar State
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [uploadProgressPercent, setUploadProgressPercent] = useState(0);
  const [uploadProgressIndex, setUploadProgressIndex] = useState(0);
  const [uploadProgressTotal, setUploadProgressTotal] = useState(0);
  const [uploadCurrentFileName, setUploadCurrentFileName] = useState('');
  const [uploadCompletedCount, setUploadCompletedCount] = useState(0);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);

  // Integration Settings State
  const [maskedSettings, setMaskedSettings] = useState<any>(null);
  const [geminiKeyInput, setGeminiKeyInput] = useState('');
  const [geminiModelInput, setGeminiModelInput] = useState('gemini-2.5-flash');

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

  // Pix Keys State
  const [pixKeys, setPixKeys] = useState<any[]>([]);
  const [pixLoading, setPixLoading] = useState(false);
  const [editingPixId, setEditingPixId] = useState<number | null>(null);
  const [pixTitle, setPixTitle] = useState('');
  const [pixKeyType, setPixKeyType] = useState<string>('CNPJ');
  const [pixKeyVal, setPixKeyVal] = useState('');
  const [pixFavorecido, setPixFavorecido] = useState('');
  const [pixCidade, setPixCidade] = useState('BRASILIA');
  const [pixDescricao, setPixDescricao] = useState('');
  const [pixAtivo, setPixAtivo] = useState(true);

  const loadPixKeys = async () => {
    try {
      setPixLoading(true);
      const data = await apiFetch('/pix-keys/');
      setPixKeys(data || []);
    } catch (err) {
      console.error('Error loading pix keys:', err);
    } finally {
      setPixLoading(false);
    }
  };

  const resetPixForm = () => {
    setEditingPixId(null);
    setPixTitle('');
    setPixKeyType('CNPJ');
    setPixKeyVal('');
    setPixFavorecido('');
    setPixCidade('BRASILIA');
    setPixDescricao('');
    setPixAtivo(true);
  };

  const handleSavePixKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pixTitle.trim() || !pixKeyVal.trim() || !pixFavorecido.trim()) {
      alert('Por favor, preencha Título, Chave Pix e Favorecido.');
      return;
    }

    try {
      if (editingPixId) {
        await apiFetch(`/pix-keys/${editingPixId}`, {
          method: 'PUT',
          body: JSON.stringify({
            titulo: pixTitle,
            tipo_chave: pixKeyType,
            chave: pixKeyVal,
            favorecido: pixFavorecido,
            cidade: pixCidade,
            descricao: pixDescricao || null,
            ativo: pixAtivo
          })
        });
      } else {
        await apiFetch('/pix-keys/', {
          method: 'POST',
          body: JSON.stringify({
            titulo: pixTitle,
            tipo_chave: pixKeyType,
            chave: pixKeyVal,
            favorecido: pixFavorecido,
            cidade: pixCidade,
            descricao: pixDescricao || null,
            ativo: pixAtivo
          })
        });
      }
      resetPixForm();
      await loadPixKeys();
    } catch (err: any) {
      alert('Erro ao salvar chave Pix: ' + err.message);
    }
  };

  const handleDeletePixKey = async (id: number) => {
    if (!confirm('Deseja realmente excluir esta chave Pix?')) return;
    try {
      await apiFetch(`/pix-keys/${id}`, { method: 'DELETE' });
      await loadPixKeys();
    } catch (err: any) {
      alert('Erro ao excluir chave Pix: ' + err.message);
    }
  };

  const handleEditPixKey = (item: any) => {
    setEditingPixId(item.id);
    setPixTitle(item.titulo);
    setPixKeyType(item.tipo_chave);
    setPixKeyVal(item.chave);
    setPixFavorecido(item.favorecido);
    setPixCidade(item.cidade || 'BRASILIA');
    setPixDescricao(item.descricao || '');
    setPixAtivo(item.ativo);
  };

  // --- Store Employees & Technicians State & Handlers ---
  const [technicians, setTechnicians] = useState<AuthorizedTechnician[]>([]);
  const [techLoading, setTechLoading] = useState(false);
  const [editingTechId, setEditingTechId] = useState<number | null>(null);
  const [techName, setTechName] = useState('');
  const [techPhone, setTechPhone] = useState('');
  const [techCargo, setTechCargo] = useState('Técnico');
  const [techDept, setTechDept] = useState('Assistência Técnica');
  const [techSpecialty, setTechSpecialty] = useState('');
  const [techAtivo, setTechAtivo] = useState(true);

  const loadTechnicians = async () => {
    try {
      setTechLoading(true);
      const data = await apiFetch('/technicians/');
      setTechnicians(data || []);
    } catch (err) {
      console.error('Error loading technicians:', err);
    } finally {
      setTechLoading(false);
    }
  };

  const resetTechForm = () => {
    setEditingTechId(null);
    setTechName('');
    setTechPhone('');
    setTechCargo('Técnico');
    setTechDept('Assistência Técnica');
    setTechSpecialty('');
    setTechAtivo(true);
  };

  const handleSaveTechnician = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!techName.trim() || !techPhone.trim()) {
      alert('Por favor, preencha o Nome e o Telefone do Funcionário.');
      return;
    }
    try {
      if (editingTechId) {
        await apiFetch(`/technicians/${editingTechId}`, {
          method: 'PUT',
          body: JSON.stringify({
            nome: techName,
            telefone: techPhone,
            cargo: techCargo || null,
            departamento: techDept || null,
            especialidade: techSpecialty || null,
            ativo: techAtivo
          })
        });
      } else {
        await apiFetch('/technicians/', {
          method: 'POST',
          body: JSON.stringify({
            nome: techName,
            telefone: techPhone,
            cargo: techCargo || null,
            departamento: techDept || null,
            especialidade: techSpecialty || null,
            ativo: techAtivo
          })
        });
      }
      resetTechForm();
      await loadTechnicians();
    } catch (err: any) {
      alert('Erro ao salvar funcionário: ' + (err.message || err));
    }
  };

  const handleEditTechnician = (t: AuthorizedTechnician) => {
    setEditingTechId(t.id);
    setTechName(t.nome);
    setTechPhone(t.telefone);
    setTechCargo(t.cargo || 'Técnico');
    setTechDept(t.departamento || 'Assistência Técnica');
    setTechSpecialty(t.especialidade || '');
    setTechAtivo(t.ativo);
  };

  const handleDeleteTechnician = async (id: number) => {
    if (!confirm('Deseja realmente remover este técnico autorizado?')) return;
    try {
      await apiFetch(`/technicians/${id}`, { method: 'DELETE' });
      await loadTechnicians();
    } catch (err: any) {
      alert('Erro ao remover técnico: ' + err.message);
    }
  };

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
      setGeminiModelInput(settingsData.gemini_model_name || 'gemini-2.5-flash');

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

  const loadWhatsAppGroups = async () => {
    try {
      setGroupsLoading(true);
      const data: WhatsAppGroup[] = await apiFetch('/whatsapp-groups/');
      setGroups(data);
    } catch (err: any) {
      console.error('Error loading whatsapp groups:', err);
    } finally {
      setGroupsLoading(false);
    }
  };

  const handleSyncGroups = async () => {
    try {
      setSyncingGroups(true);
      const res = await apiFetch('/whatsapp-groups/sync', { method: 'POST' });
      alert(res.message || 'Sincronização de grupos concluída com sucesso!');
      await loadWhatsAppGroups();
    } catch (err: any) {
      alert('Erro ao varrer grupos do WhatsApp: ' + err.message);
    } finally {
      setSyncingGroups(false);
    }
  };

  const handleToggleGroupIA = async (groupId: number, currentStatus: boolean) => {
    try {
      const newStatus = !currentStatus;
      await apiFetch(`/whatsapp-groups/${groupId}/toggle-ia`, {
        method: 'PUT',
        body: JSON.stringify({ ia_ativa: newStatus })
      });
      setGroups(prev => prev.map(g => g.id === groupId ? { ...g, ia_ativa: newStatus } : g));
    } catch (err: any) {
      alert('Erro ao alterar permissão da IA para o grupo: ' + err.message);
    }
  };

  useEffect(() => {
    loadData();
    loadSettingsAndAudit();
    loadWhatsAppGroups();
    loadRagDocuments();


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
    setPairingCode(null);

    try {
      const res = await apiFetch(`/whatsapp-numbers/${num.id}/qrcode`);
      if (res.qrcode) {
        setQrCodeBase64(res.qrcode);
        setPairingCode(res.pairing_code || res.pairingCode || null);
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

  const handleResetQrConnection = async (num: WhatsAppNumber) => {
    try {
      setQrModalNumber(num);
      setQrLoading(true);
      setQrError(null);
      setQrCodeBase64(null);
      setPairingCode(null);
      setQrConnectedSuccess(false);

      const res = await apiFetch(`/whatsapp-numbers/${num.id}/reset-connection`, { method: 'POST' });
      if (res.qrcode) {
        setQrCodeBase64(res.qrcode);
        setPairingCode(res.pairing_code || res.pairingCode || null);
        setQrError(null);
      } else {
        await openQrModal(num);
      }
    } catch (err: any) {
      setQrError(err.message || 'Erro ao resetar a conexão com a Evolution API.');
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
            if (qrRes.pairing_code || qrRes.pairingCode) {
              setPairingCode(qrRes.pairing_code || qrRes.pairingCode);
            }
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

  const [syncingNumberId, setSyncingNumberId] = useState<number | null>(null);
  const [syncingAllNumbers, setSyncingAllNumbers] = useState(false);

  const handleSyncNumberHistory = async (num: WhatsAppNumber) => {
    setSyncingNumberId(num.id);
    try {
      const res = await apiFetch(`/whatsapp-numbers/${num.id}/sync_history`, { method: 'POST' });
      alert(res.message || `Sincronização do departamento ${num.nome_departamento} iniciada com sucesso!`);
    } catch (err: any) {
      alert(`Erro ao sincronizar: ${err.message}`);
    } finally {
      setSyncingNumberId(null);
    }
  };

  const handleSyncAllWhatsAppNumbers = async () => {
    setSyncingAllNumbers(true);
    try {
      const res = await apiFetch('/whatsapp-numbers/sync_all', { method: 'POST' });
      alert(res.message || 'Sincronização em massa de todos os números iniciada com sucesso!');
    } catch (err: any) {
      alert(`Erro ao sincronizar: ${err.message}`);
    } finally {
      setSyncingAllNumbers(false);
    }
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
          foto_perfil_url: userAvatar,
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
            foto_perfil_url: userAvatar,
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
    setUserAvatar(u.foto_perfil_url || null);
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
    setUserAvatar(null);
    setUserRole('atendente');
    setSelectedNumIds([]);
  };

  // --- RAG Upload & Knowledge Management Handlers ---
  const loadRagDocuments = async () => {
    try {
      setRagLoading(true);
      const docs = await apiFetch('/rag/documents');
      setRagDocuments(docs || []);
    } catch (err) {
      console.error('Error loading RAG documents:', err);
    } finally {
      setRagLoading(false);
    }
  };

  const handleUploadRAG = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const targetDept = numbers.find(n => n.id === Number(ragDeptId));
      await apiFetch('/rag/upload', {
        method: 'POST',
        body: JSON.stringify({
          doc_id: `doc_${Date.now()}`,
          titulo: ragTitle,
          content: ragContent,
          scope: ragScope,
          department_id: ragScope === 'setor' ? Number(ragDeptId) || undefined : undefined,
          department_name: ragScope === 'setor' ? (targetDept?.nome_departamento || 'Setor') : 'Geral'
        })
      });
      setRagTitle('');
      setRagContent('');
      await loadRagDocuments();
      alert('Conhecimento RAG em texto cadastrado com sucesso!');
    } catch (err: any) {
      alert(err.message);
    }
  };

  const handleUploadFilesRAG = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ragFiles || ragFiles.length === 0) {
      alert('Selecione ao menos 1 arquivo (.pdf, .txt, .docx, .md) para enviar.');
      return;
    }

    const total = ragFiles.length;
    const targetDept = numbers.find(n => n.id === Number(ragDeptId));
    const token = localStorage.getItem('token');

    setIsUploadingFiles(true);
    setRagLoading(true);
    setUploadProgressTotal(total);
    setUploadProgressIndex(0);
    setUploadProgressPercent(0);
    setUploadCompletedCount(0);
    setUploadErrors([]);

    let successCount = 0;
    const errList: string[] = [];

    for (let i = 0; i < total; i++) {
      const file = ragFiles[i];
      setUploadProgressIndex(i + 1);
      setUploadCurrentFileName(file.name);
      const currentPercent = Math.round((i / total) * 100);
      setUploadProgressPercent(currentPercent);

      const formData = new FormData();
      formData.append('files', file);
      formData.append('scope', ragScope);
      if (ragScope === 'setor' && ragDeptId) {
        formData.append('department_id', String(ragDeptId));
        formData.append('department_name', targetDept?.nome_departamento || 'Setor');
      } else {
        formData.append('scope', 'geral');
        formData.append('department_name', 'Geral');
      }

      try {
        const res = await fetch('/api/v1/rag/upload-files', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          body: formData
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Erro ao enviar ${file.name}`);
        successCount++;
        setUploadCompletedCount(successCount);

        // Real-time table refresh after each file completion!
        await loadRagDocuments();
      } catch (err: any) {
        console.error(`Error uploading ${file.name}:`, err);
        errList.push(`${file.name}: ${err.message}`);
        setUploadErrors(prev => [...prev, `${file.name}: ${err.message}`]);
      }

      const completedPercent = Math.round(((i + 1) / total) * 100);
      setUploadProgressPercent(completedPercent);
    }

    setIsUploadingFiles(false);
    setRagLoading(false);
    setRagFiles(null);
    const fileInput = document.getElementById('rag-file-input') as HTMLInputElement;
    if (fileInput) fileInput.value = '';

    if (errList.length === 0) {
      alert(`🎉 Processamento Concluído! Todos os ${successCount} arquivo(s) foram extraídos e indexados com sucesso no ChromaDB.`);
    } else {
      alert(`⚠️ Processamento Finalizado!\n- ${successCount} arquivo(s) indexado(s) com sucesso.\n- ${errList.length} falha(s):\n${errList.slice(0, 3).join('\n')}`);
    }
  };

  const handleDeleteRAGDoc = async (docId: string, title: string) => {
    if (!window.confirm(`Deseja realmente excluir o documento '${title}' da base RAG?`)) return;
    try {
      await apiFetch(`/rag/documents/${docId}`, { method: 'DELETE' });
      await loadRagDocuments();
      alert('Documento removido da base RAG com sucesso!');
    } catch (err: any) {
      alert(`Erro ao excluir documento: ${err.message}`);
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
            onClick={() => { setActiveSubTab('rag'); loadRagDocuments(); loadData(); }}
            className={activeSubTab === 'rag' ? 'btn-primary' : 'btn-secondary'}
          >
            <Database size={16} /> Base RAG (IA Concierge)
          </button>
          <button
            onClick={() => { setActiveSubTab('technicians'); loadTechnicians(); }}
            className={activeSubTab === 'technicians' ? 'btn-primary' : 'btn-secondary'}
          >
            <Users size={16} /> Funcionários & Equipe da Loja
          </button>
          <button
            onClick={() => setActiveSubTab('integrations')}
            className={activeSubTab === 'integrations' ? 'btn-primary' : 'btn-secondary'}
          >
            <Key size={16} /> Integrações & Segurança (Fernet)
          </button>
          <button
            onClick={() => { setActiveSubTab('groups'); loadWhatsAppGroups(); }}
            className={activeSubTab === 'groups' ? 'btn-primary' : 'btn-secondary'}
          >
            <MessageSquare size={16} /> Grupos do WhatsApp
          </button>
          <button
            onClick={() => { setActiveSubTab('pix'); loadPixKeys(); }}
            className={activeSubTab === 'pix' ? 'btn-primary' : 'btn-secondary'}
          >
            <QrCode size={16} /> Chaves Pix & QR Code
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
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px', margin: 0 }}>Números Ativos ({numbers.length})</h3>
                <button
                  onClick={handleSyncAllWhatsAppNumbers}
                  disabled={syncingAllNumbers}
                  className="btn-secondary"
                  style={{
                    height: '32px',
                    padding: '0 10px',
                    fontSize: '12px',
                    fontWeight: '600',
                    color: 'var(--accent-primary)',
                    borderColor: 'rgba(0, 230, 153, 0.4)',
                    backgroundColor: 'rgba(0, 230, 153, 0.08)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                  title="Sincronizar histórico e contatos de todas as conexões ativas"
                >
                  <RefreshCw size={13} className={syncingAllNumbers ? 'spin' : ''} />
                  {syncingAllNumbers ? 'Sincronizando...' : 'Sincronizar Histórico de Todos'}
                </button>
              </div>
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
                          <>
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
                            <button
                              onClick={() => handleSyncNumberHistory(num)}
                              disabled={syncingNumberId === num.id}
                              title="Sincronizar todo o histórico antigo e contatos deste WhatsApp"
                              style={{
                                background: 'rgba(0, 230, 153, 0.1)',
                                color: 'var(--accent-primary)',
                                border: '1px solid rgba(0, 230, 153, 0.3)',
                                padding: '6px 10px',
                                borderRadius: 'var(--radius-sm)',
                                fontSize: '12px',
                                fontWeight: '600',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                cursor: 'pointer'
                              }}
                            >
                              <RefreshCw size={12} className={syncingNumberId === num.id ? 'spin' : ''} />
                              {syncingNumberId === num.id ? 'Sincronizando...' : 'Sincronizar WA'}
                            </button>
                            <button
                              onClick={() => handleResetQrConnection(num)}
                              title="Resetar instância e gerar novo QR Code limpo"
                              style={{
                                background: 'rgba(239, 68, 68, 0.15)',
                                color: '#f87171',
                                border: '1px solid rgba(239, 68, 68, 0.3)',
                                padding: '6px 10px',
                                borderRadius: 'var(--radius-sm)',
                                fontSize: '12px',
                                fontWeight: '600',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '4px',
                                cursor: 'pointer'
                              }}
                            >
                              <RefreshCw size={12} />
                              Resetar QR
                            </button>
                          </>
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

                      {pairingCode && (
                        <div style={{ marginBottom: '16px', padding: '12px 14px', backgroundColor: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)', borderRadius: 'var(--radius-md)' }}>
                          <div style={{ fontSize: '11px', color: '#60a5fa', fontWeight: '600', marginBottom: '4px' }}>
                            🔑 OU CONECTE VIA CÓDIGO DE PAREAMENTO (8 DÍGITOS):
                          </div>
                          <div style={{ fontSize: '22px', fontWeight: '800', fontFamily: 'monospace', color: '#ffffff', letterSpacing: '3px' }}>
                            {pairingCode}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                            No celular: <em>Conectar um aparelho</em> {'>'} <strong>Conectar com número de telefone</strong>
                          </div>
                        </div>
                      )}

                      <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.5', margin: '0 0 12px 0' }}>

                        Abra o WhatsApp no celular {'>'} <strong>Aparelhos conectados</strong> {'>'} <strong>Conectar um aparelho</strong> e aponte a câmera para a imagem acima.
                      </p>

                      <button
                        type="button"
                        onClick={() => handleResetQrConnection(qrModalNumber)}
                        disabled={qrLoading}
                        style={{
                          width: '100%',
                          padding: '8px 12px',
                          backgroundColor: 'rgba(239, 68, 68, 0.1)',
                          border: '1px solid rgba(239, 68, 68, 0.3)',
                          color: '#f87171',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '12px',
                          fontWeight: '600',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '6px',
                          marginBottom: '10px'
                        }}
                      >
                        <RefreshCw size={14} className={qrLoading ? "spin" : ""} />
                        {qrLoading ? 'Resetando Instância...' : 'Resetar Instância & Gerar Novo QR Code'}
                      </button>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-muted)' }}>
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
          <>
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
                {/* User Avatar Upload & Crop Section */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '12px', backgroundColor: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                  {userAvatar ? (
                    <img
                      src={userAvatar}
                      alt="Foto de Perfil"
                      style={{ width: '56px', height: '56px', borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--accent-primary)', boxShadow: '0 4px 10px rgba(0,0,0,0.3)', flexShrink: 0 }}
                    />
                  ) : (
                    <div style={{
                      width: '56px',
                      height: '56px',
                      borderRadius: '50%',
                      background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
                      color: '#051a12',
                      fontWeight: '700',
                      fontSize: '20px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0
                    }}>
                      {(userName || 'U').charAt(0).toUpperCase()}
                    </div>
                  )}

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-main)' }}>
                      Foto de Perfil do Atendente
                    </span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        type="button"
                        onClick={() => setIsAvatarCropOpen(true)}
                        style={{
                          background: 'rgba(0, 230, 153, 0.15)',
                          border: '1px solid rgba(0, 230, 153, 0.3)',
                          borderRadius: '6px',
                          padding: '5px 10px',
                          color: 'var(--accent-primary)',
                          fontSize: '11px',
                          fontWeight: '600',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                      >
                        <Camera size={13} /> {userAvatar ? 'Alterar / Enquadrar' : 'Adicionar Foto'}
                      </button>

                      {userAvatar && (
                        <button
                          type="button"
                          onClick={() => setUserAvatar(null)}
                          style={{
                            background: 'rgba(239, 68, 68, 0.1)',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            borderRadius: '6px',
                            padding: '5px 8px',
                            color: '#f87171',
                            fontSize: '11px',
                            cursor: 'pointer'
                          }}
                        >
                          Remover
                        </button>
                      )}
                    </div>
                  </div>
                </div>

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
                  <div key={u.id} style={{ padding: '14px', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(255, 255, 255, 0.02)', display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {u.foto_perfil_url ? (
                      <img
                        src={u.foto_perfil_url}
                        alt={u.nome}
                        style={{ width: '42px', height: '42px', borderRadius: '50%', objectFit: 'cover', border: '1.5px solid var(--accent-primary)', flexShrink: 0 }}
                      />
                    ) : (
                      <div style={{
                        width: '42px',
                        height: '42px',
                        borderRadius: '50%',
                        background: 'linear-gradient(135deg, #00e699 0%, #00b377 100%)',
                        color: '#051a12',
                        fontWeight: '700',
                        fontSize: '16px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0
                      }}>
                        {u.nome.charAt(0).toUpperCase()}
                      </div>
                    )}

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div>
                          <span style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)' }}>{u.nome}</span>
                          <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: '6px' }}>({u.login})</span>
                          <span className="badge badge-com_humano" style={{ marginLeft: '8px' }}>{u.role}</span>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <button
                            onClick={() => handleEditUser(u)}
                            title="Editar Usuário"
                            style={{ background: 'rgba(255, 255, 255, 0.08)', color: 'var(--text-main)', padding: '6px', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            onClick={() => handleDeleteUser(u)}
                            title="Excluir Usuário"
                            style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '6px', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                      <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
                        Departamentos: {u.whatsapp_numbers.map(n => n.nome_departamento).join(', ') || 'Todos (Admin)'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <AvatarCropModal
            isOpen={isAvatarCropOpen}
            onClose={() => setIsAvatarCropOpen(false)}
            onSave={(croppedUrl) => setUserAvatar(croppedUrl)}
            initialImageUrl={userAvatar}
          />
          </>
        )}

        {/* 3. RAG Knowledge Upload & Management Tab */}
        {activeSubTab === 'rag' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ fontSize: '18px', margin: 0 }}>Ensino e Base de Conhecimento RAG (IA Concierge)</h3>
                <button
                  type="button"
                  onClick={loadRagDocuments}
                  className="btn-secondary"
                  style={{ fontSize: '12px', padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <RefreshCw size={14} className={ragLoading ? "spin" : ""} />
                  Atualizar Lista
                </button>
              </div>

              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '20px' }}>
                Ensine a IA Concierge sobre a sua empresa! Escolha se o conhecimento é <strong>Geral (Todos os Setores)</strong> como horário de funcionamento e localização da loja, ou <strong>Específico do Setor</strong> (ex: preços de produtos para Vendas ou manuais de erro para Assistência).
              </p>

              {/* Scope & Department Selection Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
                <div
                  onClick={() => { setRagScope('geral'); setRagDeptId(''); }}
                  style={{
                    padding: '16px',
                    borderRadius: 'var(--radius-md)',
                    border: ragScope === 'geral' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                    backgroundColor: ragScope === 'geral' ? 'rgba(0, 230, 153, 0.08)' : 'var(--bg-secondary)',
                    cursor: 'pointer'
                  }}
                >
                  <div style={{ fontWeight: '700', fontSize: '14px', marginBottom: '4px', color: 'var(--text-main)' }}>
                    🌐 1. RAG Geral (Toda a Empresa)
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Aplicado a todos os atendimentos (ex: horário de funcionamento, localização/endereço da loja, política de trocas, formas de pagamento).
                  </div>
                </div>

                <div
                  onClick={() => { setRagScope('setor'); if (numbers.length > 0 && !ragDeptId) setRagDeptId(numbers[0].id); }}
                  style={{
                    padding: '16px',
                    borderRadius: 'var(--radius-md)',
                    border: ragScope === 'setor' ? '2px solid var(--accent-primary)' : '1px solid var(--border-color)',
                    backgroundColor: ragScope === 'setor' ? 'rgba(0, 230, 153, 0.08)' : 'var(--bg-secondary)',
                    cursor: 'pointer'
                  }}
                >
                  <div style={{ fontWeight: '700', fontSize: '14px', marginBottom: '4px', color: 'var(--text-main)' }}>
                    🎯 2. RAG Específica por Setor / Departamento
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Aplicado apenas ao setor selecionado (ex: tabela de cotações para Vendas, manuais técnicos para Assistência).
                  </div>
                </div>
              </div>

              {/* Department Dropdown if Setor is selected */}
              {ragScope === 'setor' && (
                <div style={{ marginBottom: '20px', padding: '14px 18px', backgroundColor: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <label style={{ fontSize: '13px', fontWeight: '700', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Building size={15} /> Selecione o Setor / Departamento Alvo:
                    </label>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {numbers.length} setor(es) disponível(is)
                    </span>
                  </div>
                  
                  {numbers.length === 0 ? (
                    <div style={{ padding: '10px', fontSize: '12px', color: '#fca5a5', backgroundColor: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px' }}>
                      Nenhum setor/número cadastrado. Cadastre um número na aba "Números / Departamentos" primeiro.
                    </div>
                  ) : (
                    <select
                      value={ragDeptId || numbers[0]?.id}
                      onChange={(e) => setRagDeptId(Number(e.target.value))}
                      style={{
                        width: '100%',
                        padding: '12px 14px',
                        backgroundColor: '#0f172a',
                        border: '1.5px solid var(--accent-primary)',
                        borderRadius: 'var(--radius-md)',
                        color: '#ffffff',
                        fontSize: '13px',
                        fontWeight: '600',
                        outline: 'none',
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(0, 230, 153, 0.15)'
                      }}
                    >
                      {numbers.map(num => (
                        <option
                          key={num.id}
                          value={num.id}
                          style={{
                            backgroundColor: '#0f172a',
                            color: '#ffffff',
                            padding: '8px'
                          }}
                        >
                          🏢 Setor: {num.nome_departamento} ({num.numero || num.instancia_evolution_api})
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}

              {/* Forms Section: Multi-File Upload + Direct Text Upload */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                {/* 1. Multi-File Uploader Form */}
                <form onSubmit={handleUploadFilesRAG} style={{ padding: '20px', backgroundColor: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <h4 style={{ margin: 0, fontSize: '15px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Plus size={18} color="var(--accent-primary)" /> Enviar Arquivos (.pdf, .txt, .docx, .md)
                  </h4>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                    Selecione um ou múltiplos arquivos para aprendizado automático. O texto será extraído e indexado no ChromaDB.
                  </p>

                  <input
                    id="rag-file-input"
                    type="file"
                    multiple
                    accept=".pdf,.txt,.docx,.doc,.md"
                    onChange={(e) => setRagFiles(e.target.files)}
                    style={{ padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px dashed var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', cursor: 'pointer' }}
                  />

                  {/* Real-Time Upload Progress Bar & Status */}
                  {isUploadingFiles && (
                    <div style={{
                      marginTop: '10px',
                      padding: '14px',
                      backgroundColor: 'rgba(0, 230, 153, 0.06)',
                      border: '1px solid rgba(0, 230, 153, 0.3)',
                      borderRadius: 'var(--radius-md)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '13px', fontWeight: '600' }}>
                        <span style={{ color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <RefreshCw size={15} style={{ animation: 'spin 1s linear infinite' }} />
                          Processando {uploadProgressIndex} de {uploadProgressTotal} arquivo(s)...
                        </span>
                        <span style={{ color: '#fff', fontWeight: '700', fontSize: '14px' }}>
                          {uploadProgressPercent}%
                        </span>
                      </div>

                      {/* Outer Bar Track */}
                      <div style={{
                        width: '100%',
                        height: '10px',
                        backgroundColor: 'rgba(255, 255, 255, 0.1)',
                        borderRadius: 'var(--radius-full)',
                        overflow: 'hidden'
                      }}>
                        {/* Animated Progress Fill */}
                        <div style={{
                          width: `${uploadProgressPercent}%`,
                          height: '100%',
                          background: 'var(--accent-gradient)',
                          borderRadius: 'var(--radius-full)',
                          transition: 'width 0.3s ease-in-out'
                        }} />
                      </div>

                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                        📄 Extraindo texto e indexando no ChromaDB: <strong>{uploadCurrentFileName}</strong>
                      </div>

                      {uploadCompletedCount > 0 && (
                        <div style={{ fontSize: '11px', color: '#34d399', fontWeight: '600' }}>
                          ✅ {uploadCompletedCount} de {uploadProgressTotal} concluído(s) e já visíveis na tabela abaixo!
                        </div>
                      )}

                      {uploadErrors.length > 0 && (
                        <div style={{ fontSize: '11px', color: '#ef4444', fontWeight: '500' }}>
                          ⚠️ {uploadErrors.length} alerta(s) de processamento (verifique arquivos em branco/protegidos).
                        </div>
                      )}
                    </div>
                  )}

                  <button type="submit" className="btn-primary" disabled={ragLoading || !ragFiles || ragFiles.length === 0} style={{ fontSize: '13px', padding: '10px' }}>
                    <Database size={16} /> {ragLoading ? `Processando (${uploadProgressPercent}%)...` : 'Indexar Arquivo(s) no RAG'}
                  </button>
                </form>

                {/* 2. Direct Text Snippet Form */}
                <form onSubmit={handleUploadRAG} style={{ padding: '20px', backgroundColor: 'var(--bg-secondary)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <h4 style={{ margin: 0, fontSize: '15px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Database size={18} color="var(--accent-primary)" /> Cadastrar Texto Direto / FAQ
                  </h4>

                  <div>
                    <label style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Título da Regra ou Assunto</label>
                    <input
                      type="text"
                      required
                      placeholder="Ex: Endereço e Horário da Loja"
                      value={ragTitle}
                      onChange={(e) => setRagTitle(e.target.value)}
                      style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>

                  <div>
                    <label style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Instrução ou Conteúdo</label>
                    <textarea
                      required
                      rows={4}
                      placeholder="Ex: A Servweld fica na SOF Q 5 Lote 05 Loja 02 Conjunto A - Guará, Brasília - DF, 71215-226. Atendemos de Seg a Sex das 08h às 18h."
                      value={ragContent}
                      onChange={(e) => setRagContent(e.target.value)}
                      style={{ width: '100%', padding: '8px 10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', resize: 'vertical' }}
                    />
                  </div>

                  <button type="submit" className="btn-secondary" disabled={ragLoading} style={{ fontSize: '13px', padding: '10px' }}>
                    Salvar Texto no RAG
                  </button>
                </form>
              </div>
            </div>

            {/* List of Currently Indexed RAG Documents */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '17px', marginBottom: '16px', color: 'var(--text-main)' }}>
                Conhecimentos Cadastrados no RAG ({ragDocuments.length})
              </h3>

              {ragDocuments.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)', fontSize: '13px' }}>
                  Nenhum documento ou texto cadastrado até o momento. Utilize o formulário acima para adicionar.
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {ragDocuments.map((doc) => (
                    <div
                      key={doc.id}
                      style={{
                        padding: '14px 18px',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div style={{ flex: 1, marginRight: '16px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                          <span style={{ fontWeight: '700', fontSize: '14px', color: 'var(--text-main)' }}>
                            {doc.titulo}
                          </span>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '10px',
                              backgroundColor: doc.scope === 'geral' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(168, 85, 247, 0.15)',
                              color: doc.scope === 'geral' ? '#60a5fa' : '#c084fc',
                              fontWeight: '600',
                              border: doc.scope === 'geral' ? '1px solid rgba(59, 130, 246, 0.3)' : '1px solid rgba(168, 85, 247, 0.3)'
                            }}
                          >
                            {doc.scope === 'geral' ? '🌐 RAG Geral (Todos)' : `🎯 Setor: ${doc.department_name}`}
                          </span>
                        </div>
                        <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: 0 }}>
                          {doc.snippet}
                        </p>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleDeleteRAGDoc(doc.id, doc.titulo)}
                        style={{
                          backgroundColor: 'rgba(239, 68, 68, 0.15)',
                          color: '#f87171',
                          border: '1px solid rgba(239, 68, 68, 0.3)',
                          padding: '6px 12px',
                          borderRadius: 'var(--radius-sm)',
                          fontSize: '12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '4px'
                        }}
                      >
                        <Trash2 size={14} /> Excluir
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
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
                    <label style={{ fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      Google Gemini API Key
                      {maskedSettings?.gemini_configured && (
                        <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '12px', backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#34d399', border: '1px solid rgba(16, 185, 129, 0.3)', fontWeight: '600' }}>
                          🟢 Ativa & Salva no Banco
                        </span>
                      )}
                    </label>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      Chave Criptografada: <code style={{ color: 'var(--accent-primary)', fontWeight: '600' }}>{maskedSettings?.gemini_api_key_masked}</code>
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', marginBottom: '8px' }}>
                    <input
                      type="password"
                      placeholder={maskedSettings?.gemini_configured ? "•••••••••••••••• (Chave salva e ativa no banco. Digite apenas se desejar alterar)" : "Digite sua API Key do Gemini (ex: AIzaSy...)"}
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
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '0 0 12px 0' }}>
                    💡 <strong>Sua chave já está gravada de forma permanente e segura no banco de dados</strong> (criptografada via Fernet). Você não precisa reescrevê-la a cada login.
                  </p>

                  {/* Configurable Gemini Model Select Dropdown */}
                  <div style={{ marginBottom: '12px' }}>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
                      Modelo da Gemini API (Selecione o modelo oficial da Google Generative AI)
                    </label>
                    <select
                      value={geminiModelInput}
                      onChange={(e) => setGeminiModelInput(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    >
                      <option value="gemini-2.5-flash">gemini-2.5-flash (Recomendado - Rápido e Atual)</option>
                      <option value="gemini-2.5-pro">gemini-2.5-pro (Raciocínio Avançado)</option>
                      <option value="gemini-2.0-flash">gemini-2.0-flash (Velocidade Ultra-rápida)</option>
                      <option value="gemini-1.5-flash">gemini-1.5-flash (Estável)</option>
                      <option value="gemini-1.5-pro">gemini-1.5-pro (Leitura Estendida)</option>
                    </select>
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

        {/* 5. WhatsApp Groups AI Control Tab */}
        {activeSubTab === 'groups' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Info Header Box */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)', borderLeft: '4px solid var(--accent-primary)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                <div>
                  <h3 style={{ fontSize: '18px', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Bot size={20} style={{ color: 'var(--accent-primary)' }} />
                    Controle de IA em Grupos do WhatsApp
                  </h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '6px', maxWidth: '750px', lineHeight: '1.5' }}>
                    Por padrão, a IA Concierge <strong>NÃO</strong> responde em conversas de grupos.
                    Clique em <strong>"Varrer Grupos de WhatsApp"</strong> para identificar todos os grupos das suas instâncias conectadas e marque a caixa de seleção dos grupos internos da empresa onde a IA está autorizada a responder.
                  </p>
                </div>
                <button
                  onClick={handleSyncGroups}
                  disabled={syncingGroups}
                  className="btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 20px' }}
                >
                  <RefreshCw size={16} style={{ animation: syncingGroups ? 'spin 1s linear infinite' : 'none' }} />
                  {syncingGroups ? 'Varrendo Grupos...' : 'Varrer Grupos de WhatsApp'}
                </button>
              </div>
            </div>

            {/* Groups Table Card */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h4 style={{ fontSize: '16px', fontWeight: '600' }}>
                  Grupos Encontrados ({groups.length})
                </h4>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {groups.filter(g => g.ia_ativa).length} de {groups.length} grupos com IA autorizada
                </span>
              </div>

              {groupsLoading ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '14px', textAlign: 'center', padding: '32px 0' }}>
                  Carregando lista de grupos do WhatsApp...
                </p>
              ) : groups.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', border: '1px dashed var(--border-color)', borderRadius: 'var(--radius-md)' }}>
                  <MessageSquare size={36} style={{ color: 'var(--text-muted)', marginBottom: '12px', opacity: 0.5 }} />
                  <p style={{ fontSize: '14px', color: 'var(--text-muted)', marginBottom: '16px' }}>
                    Nenhum grupo do WhatsApp encontrado no banco de dados.
                  </p>
                  <button onClick={handleSyncGroups} className="btn-secondary" style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    <RefreshCw size={14} /> Executar Primeira Varredura de Grupos
                  </button>
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '12px 16px', width: '160px' }}>IA Pode Interagir</th>
                        <th style={{ padding: '12px 16px' }}>Nome do Grupo</th>
                        <th style={{ padding: '12px 16px' }}>Instância / Departamento</th>
                        <th style={{ padding: '12px 16px' }}>JID do Grupo (ID WhatsApp)</th>
                        <th style={{ padding: '12px 16px', width: '140px' }}>Status da IA</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groups.map((group) => (
                        <tr key={group.id} style={{ borderBottom: '1px solid var(--border-color)', backgroundColor: group.ia_ativa ? 'rgba(16, 185, 129, 0.04)' : 'transparent' }}>
                          <td style={{ padding: '14px 16px' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: '500' }}>
                              <input
                                type="checkbox"
                                checked={group.ia_ativa}
                                onChange={() => handleToggleGroupIA(group.id, group.ia_ativa)}
                                style={{ width: '18px', height: '18px', accentColor: 'var(--accent-primary)', cursor: 'pointer' }}
                              />
                              <span style={{ fontSize: '12px', color: group.ia_ativa ? 'var(--accent-primary)' : 'var(--text-muted)' }}>
                                {group.ia_ativa ? 'Permitido' : 'Desativado'}
                              </span>
                            </label>
                          </td>
                          <td style={{ padding: '14px 16px', fontWeight: '600', color: 'var(--text-main)' }}>
                            {group.nome}
                          </td>
                          <td style={{ padding: '14px 16px', color: 'var(--text-muted)' }}>
                            {group.departamento || 'Geral'} {group.instancia ? `(${group.instancia})` : ''}
                          </td>
                          <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-muted)' }}>
                            {group.group_jid}
                          </td>
                          <td style={{ padding: '14px 16px' }}>
                            {group.ia_ativa ? (
                              <span style={{ padding: '4px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: '600', backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#10b981', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                <CheckCircle2 size={12} /> Responde IA
                              </span>
                            ) : (
                              <span style={{ padding: '4px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: '500', backgroundColor: 'rgba(255, 255, 255, 0.05)', color: 'var(--text-muted)' }}>
                                Silencioso (Sem IA)
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 6. Pix Keys Management Tab */}
        {activeSubTab === 'pix' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            {/* Form */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '700' }}>
                  {editingPixId ? 'Editar Chave Pix' : 'Cadastrar Nova Chave Pix'}
                </h3>
                {editingPixId && (
                  <button onClick={resetPixForm} style={{ background: 'transparent', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', border: 'none', cursor: 'pointer' }}>
                    <X size={14} /> Cancelar
                  </button>
                )}
              </div>

              <form onSubmit={handleSavePixKey} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
                    Título / Identificador da Chave
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: Pix Principal Servweld - CNPJ"
                    value={pixTitle}
                    onChange={(e) => setPixTitle(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Tipo</label>
                    <select
                      value={pixKeyType}
                      onChange={(e) => setPixKeyType(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    >
                      <option value="CNPJ">CNPJ</option>
                      <option value="CPF">CPF</option>
                      <option value="EMAIL">E-mail</option>
                      <option value="TELEFONE">Telefone</option>
                      <option value="EVP">Aleatória (EVP)</option>
                    </select>
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Chave Pix</label>
                    <input
                      type="text"
                      required
                      placeholder="Ex: 54804458000122 ou e-mail"
                      value={pixKeyVal}
                      onChange={(e) => setPixKeyVal(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>
                    Favorecido / Razão Social ou Nome
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: Servweld Equipamentos e Serviços Ltda"
                    value={pixFavorecido}
                    onChange={(e) => setPixFavorecido(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Cidade</label>
                    <input
                      type="text"
                      placeholder="Ex: BRASILIA"
                      value={pixCidade}
                      onChange={(e) => setPixCidade(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Descrição / Instruções (Opcional)</label>
                    <input
                      type="text"
                      placeholder="Ex: Usar para vendas à vista da Loja SOF Sul"
                      value={pixDescricao}
                      onChange={(e) => setPixDescricao(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)' }}
                    />
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                  <input
                    type="checkbox"
                    id="pixAtivo"
                    checked={pixAtivo}
                    onChange={(e) => setPixAtivo(e.target.checked)}
                  />
                  <label htmlFor="pixAtivo" style={{ fontSize: '13px', color: 'var(--text-main)', cursor: 'pointer' }}>
                    Chave Ativa para uso nos chats
                  </label>
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                  <button type="submit" className="btn-primary" style={{ flex: 1 }}>
                    <Check size={16} /> {editingPixId ? 'Atualizar Chave Pix' : 'Salvar Chave Pix'}
                  </button>
                  {editingPixId && (
                    <button type="button" onClick={resetPixForm} className="btn-secondary">
                      Cancelar
                    </button>
                  )}
                </div>
              </form>
            </div>

            {/* List */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <h3 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '16px' }}>
                Chaves Pix Cadastradas ({pixKeys.length})
              </h3>
              {pixLoading ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>Carregando chaves...</div>
              ) : pixKeys.length === 0 ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  Nenhuma chave Pix cadastrada ainda. Preencha o formulário para adicionar a chave da sua empresa!
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '500px', overflowY: 'auto' }}>
                  {pixKeys.map(item => (
                    <div
                      key={item.id}
                      style={{
                        padding: '14px 16px',
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 'var(--radius-md)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{
                          width: '36px',
                          height: '36px',
                          borderRadius: '50%',
                          backgroundColor: 'rgba(234, 179, 8, 0.15)',
                          color: '#eab308',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}>
                          <QrCode size={20} />
                        </div>
                        <div>
                          <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-main)' }}>
                            {item.titulo} <span style={{ fontSize: '11px', color: 'var(--accent-primary)', marginLeft: '6px' }}>[{item.tipo_chave}]</span>
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            🔑 <strong>Chave:</strong> {item.chave} • 🏢 <strong>Favorecido:</strong> {item.favorecido}
                          </div>
                          {item.descricao && (
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              📝 {item.descricao}
                            </div>
                          )}
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                          type="button"
                          onClick={() => handleEditPixKey(item)}
                          className="btn-secondary"
                          style={{ padding: '6px 10px', fontSize: '12px' }}
                          title="Editar Chave"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeletePixKey(item.id)}
                          className="btn-secondary"
                          style={{ padding: '6px 10px', fontSize: '12px', color: '#f87171' }}
                          title="Excluir Chave"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* 7. Store Employees & Technicians Tab */}
        {activeSubTab === 'technicians' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: '24px' }}>
            {/* Form */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '700', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Users size={20} color="var(--accent-primary)" />
                  {editingTechId ? 'Editar Funcionário da Loja' : 'Cadastrar Funcionário da Loja'}
                </h3>
                {editingTechId && (
                  <button onClick={resetTechForm} style={{ background: 'transparent', color: 'var(--text-muted)', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', border: 'none', cursor: 'pointer' }}>
                    <X size={14} /> Cancelar Edição
                  </button>
                )}
              </div>

              {/* Informational Guidance Banner */}
              <div style={{
                backgroundColor: 'rgba(0, 230, 153, 0.08)',
                border: '1px solid rgba(0, 230, 153, 0.25)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 14px',
                marginBottom: '16px',
                fontSize: '12px',
                lineHeight: '1.5',
                color: '#d1fae5'
              }}>
                <strong>👥 Integração com Agenda de Tarefas & WhatsApp da IA:</strong>
                <ul style={{ margin: '6px 0 0 0', paddingLeft: '18px', fontSize: '11px', color: '#a7f3d0' }}>
                  <li><strong>Lembretes Automáticos de Tarefas:</strong> Ao agendar visitas técnicas, entregas de gás, manutenções ou atendimentos na Agenda de Tarefas e vincular a este funcionário, a IA enviará lembretes no WhatsApp dele no momento do agendamento, no dia do evento e horas antes com botão de confirmação!</li>
                  <li><strong>Copiloto RAG Técnico:</strong> Se o cargo for Técnico, a IA atuará como copiloto avançado com esquemas elétricos quando ele conversar pelo WhatsApp.</li>
                </ul>
              </div>

              <form onSubmit={handleSaveTechnician} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Nome do Funcionário *</label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: Carlos Oliveira"
                    value={techName}
                    onChange={(e) => setTechName(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Telefone WhatsApp (com DDD) *</label>
                  <input
                    type="text"
                    required
                    placeholder="Ex: 5561999998888 ou 61999998888"
                    value={techPhone}
                    onChange={(e) => setTechPhone(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Cargo / Função</label>
                    <select
                      value={techCargo}
                      onChange={(e) => setTechCargo(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                    >
                      <option value="Técnico">Técnico / Especialista</option>
                      <option value="Entregador">Entregador / Motorista</option>
                      <option value="Vendedor">Vendedor / Comercial</option>
                      <option value="Consultor">Consultor Técnico</option>
                      <option value="Atendente">Atendente / Operacional</option>
                      <option value="Gerente">Gerente / Supervisor</option>
                    </select>
                  </div>

                  <div>
                    <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Departamento</label>
                    <select
                      value={techDept}
                      onChange={(e) => setTechDept(e.target.value)}
                      style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                    >
                      <option value="Assistência Técnica">Assistência Técnica</option>
                      <option value="Vendas e E-commerce">Vendas e E-commerce</option>
                      <option value="Locação de Máquinas">Locação de Máquinas</option>
                      <option value="Financeiro">Financeiro</option>
                      <option value="Geral">Geral / Toda a Loja</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Especialidade / Observações (Opcional)</label>
                  <input
                    type="text"
                    placeholder="Ex: Entrega de cilindros de gás, inversores MIG/MAG, visitas externas"
                    value={techSpecialty}
                    onChange={(e) => setTechSpecialty(e.target.value)}
                    style={{ width: '100%', padding: '10px', backgroundColor: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', color: 'var(--text-main)', boxSizing: 'border-box' }}
                  />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                  <input
                    type="checkbox"
                    id="techAtivo"
                    checked={techAtivo}
                    onChange={(e) => setTechAtivo(e.target.checked)}
                  />
                  <label htmlFor="techAtivo" style={{ fontSize: '13px', color: 'var(--text-main)', cursor: 'pointer' }}>
                    Funcionário Ativo (Receber lembretes de tarefas e compromissos)
                  </label>
                </div>

                <div style={{ display: 'flex', gap: '10px', marginTop: '10px' }}>
                  <button type="submit" className="btn-primary" style={{ flex: 1 }}>
                    <Check size={16} /> {editingTechId ? 'Atualizar Funcionário' : 'Salvar Funcionário'}
                  </button>
                  {editingTechId && (
                    <button type="button" onClick={resetTechForm} className="btn-secondary">
                      Cancelar
                    </button>
                  )}
                </div>
              </form>
            </div>

            {/* List */}
            <div className="glass-panel" style={{ padding: '24px', borderRadius: 'var(--radius-lg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <h3 style={{ fontSize: '18px', fontWeight: '700', margin: 0 }}>
                  Equipe Cadastrada ({technicians.length})
                </h3>
                <button onClick={loadTechnicians} className="btn-secondary" style={{ padding: '4px 8px', fontSize: '11px' }}>
                  <RefreshCw size={12} className={techLoading ? "animate-spin" : ""} /> Atualizar
                </button>
              </div>

              {techLoading ? (
                <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>Carregando funcionários...</div>
              ) : technicians.length === 0 ? (
                <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px', lineHeight: '1.6' }}>
                  Nenhum funcionário cadastrado ainda. Adicione o telefone e cargo dos membros da sua equipe para vinculá-los às tarefas e lembretes da loja!
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '550px', overflowY: 'auto' }}>
                  {technicians.map(item => (
                    <div
                      key={item.id}
                      style={{
                        padding: '14px 16px',
                        backgroundColor: 'var(--bg-secondary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 'var(--radius-md)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{
                          width: '38px',
                          height: '38px',
                          borderRadius: '50%',
                          backgroundColor: item.ativo ? 'rgba(0, 230, 153, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                          color: item.ativo ? 'var(--accent-primary)' : 'var(--text-muted)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: '700',
                          fontSize: '15px',
                          flexShrink: 0
                        }}>
                          {item.nome.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            {item.nome}
                            {item.cargo && (
                              <span style={{ fontSize: '10px', backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', padding: '1px 6px', borderRadius: '8px', fontWeight: '600' }}>
                                {item.cargo}
                              </span>
                            )}
                            {item.ativo ? (
                              <span style={{ fontSize: '10px', backgroundColor: 'rgba(0, 230, 153, 0.2)', color: 'var(--accent-primary)', padding: '1px 6px', borderRadius: '8px', fontWeight: '600' }}>
                                Ativo
                              </span>
                            ) : (
                              <span style={{ fontSize: '10px', backgroundColor: 'rgba(239, 68, 68, 0.2)', color: '#f87171', padding: '1px 6px', borderRadius: '8px', fontWeight: '600' }}>
                                Inativo
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Phone size={11} /> <strong>WhatsApp:</strong> {item.telefone}
                            <a
                              href={`https://wa.me/${item.telefone.replace(/\D/g, '')}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ color: 'var(--accent-primary)', fontSize: '11px', textDecoration: 'none', marginLeft: '4px' }}
                            >
                              (Conversar)
                            </a>
                          </div>
                          {item.departamento && (
                            <div style={{ fontSize: '11px', color: '#93c5fd', marginTop: '2px' }}>
                              🏢 {item.departamento} {item.especialidade ? `• ${item.especialidade}` : ''}
                            </div>
                          )}
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <button
                          type="button"
                          onClick={() => handleEditTechnician(item)}
                          className="btn-secondary"
                          style={{ padding: '6px 10px', fontSize: '12px' }}
                          title="Editar Funcionário"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteTechnician(item.id)}
                          className="btn-secondary"
                          style={{ padding: '6px 10px', fontSize: '12px', color: '#f87171' }}
                          title="Remover Funcionário"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

