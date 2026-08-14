import React, { useState, useEffect } from 'react';
import { Tag as TagIcon, Filter, AlertTriangle, Plus, Users, ShieldCheck, CheckCircle2, Building, Clock, Eye } from 'lucide-react';
import { apiFetch } from '../services/api';
import { WhatsAppNumber } from '../types';

interface TagItem {
  id: number;
  tenant_id: number;
  nome: string;
  cor_hex: string;
}

interface SegmentItem {
  id: number;
  nome: string;
  descricao?: string;
  regras: Record<string, any>;
  criado_em: string;
}

interface ContactPreview {
  id: number;
  nome?: string;
  telefone: string;
  total_conversations: number;
  ultima_interacao?: string;
}

export const SegmentationPanel: React.FC = () => {
  const [tags, setTags] = useState<TagItem[]>([]);
  const [segments, setSegments] = useState<SegmentItem[]>([]);
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>([]);
  
  // New Tag Form
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState('#10b981');
  
  // Segment Builder Form
  const [segmentName, setSegmentName] = useState('');
  const [segmentDesc, setSegmentDesc] = useState('');
  const [selectedWnId, setSelectedWnId] = useState<number | 'all'>('all');
  const [inactivityDays, setInactivityDays] = useState<number | 'all'>('all');
  const [selectedTagId, setSelectedTagId] = useState<number | 'all'>('all');
  
  // Preview
  const [previewContacts, setPreviewContacts] = useState<ContactPreview[]>([]);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [hasPreviewed, setHasPreviewed] = useState(false);

  useEffect(() => {
    fetchTags();
    fetchSegments();
    fetchNumbers();
  }, []);

  const fetchTags = async () => {
    try {
      const data = await apiFetch('/segments/tags');
      setTags(data);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchSegments = async () => {
    try {
      const data = await apiFetch('/segments/');
      setSegments(data);
    } catch (err) {
      console.error(err);
    }
  };

  const fetchNumbers = async () => {
    try {
      const data = await apiFetch('/whatsapp-numbers/');
      setWhatsappNumbers(data);
    } catch (err) {
      console.error(err);
    }
  };

  const handleCreateTag = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTagName.trim()) return;

    try {
      await apiFetch('/segments/tags', {
        method: 'POST',
        body: JSON.stringify({
          nome: newTagName.trim(),
          cor_hex: newTagColor
        })
      });
      setNewTagName('');
      fetchTags();
    } catch (err: any) {
      alert(err.message || 'Erro ao criar tag.');
    }
  };

  const handlePreviewSegment = async () => {
    try {
      setIsPreviewLoading(true);
      const payload = {
        whatsapp_number_id: selectedWnId === 'all' ? undefined : selectedWnId,
        dias_inativo: inactivityDays === 'all' ? undefined : Number(inactivityDays),
        tag_ids: selectedTagId === 'all' ? [] : [selectedTagId]
      };

      const data = await apiFetch('/segments/preview', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      setPreviewContacts(data);
      setHasPreviewed(true);
    } catch (err: any) {
      alert(err.message || 'Erro ao calcular pré-visualização.');
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const handleSaveSegment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!segmentName.trim()) {
      alert('Por favor, informe um nome para o segmento.');
      return;
    }

    try {
      await apiFetch('/segments/', {
        method: 'POST',
        body: JSON.stringify({
          nome: segmentName.trim(),
          descricao: segmentDesc.trim() || undefined,
          whatsapp_number_id: selectedWnId === 'all' ? undefined : selectedWnId,
          dias_inativo: inactivityDays === 'all' ? undefined : Number(inactivityDays),
          tag_ids: selectedTagId === 'all' ? [] : [selectedTagId]
        })
      });

      alert('Segmento salvo com sucesso!');
      setSegmentName('');
      setSegmentDesc('');
      fetchSegments();
    } catch (err: any) {
      alert(err.message || 'Erro ao salvar segmento.');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', backgroundColor: 'var(--bg-primary)', padding: '28px', overflowY: 'auto' }}>
      
      {/* Meta API & LGPD Compliance Security Banner */}
      <div style={{
        padding: '16px 20px',
        borderRadius: 'var(--radius-md)',
        backgroundColor: 'rgba(245, 158, 11, 0.12)',
        border: '1px solid rgba(245, 158, 11, 0.3)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '14px',
        marginBottom: '28px'
      }}>
        <AlertTriangle size={24} style={{ color: '#f59e0b', flexShrink: 0, marginTop: '2px' }} />
        <div>
          <h4 style={{ fontSize: '15px', fontWeight: '700', color: '#f59e0b', marginBottom: '4px' }}>
            Proteção LGPD & Conformidade WhatsApp Meta API
          </h4>
          <p style={{ fontSize: '13px', color: 'var(--text-main)', lineHeight: '1.5' }}>
            O envio em massa está <strong>temporariamente desativado</strong> por questões de segurança anti-banimento e privacidade. A funcionalidade de disparos será ativada exclusivamente quando seu número for integrado à <strong>API Oficial da Meta</strong> com <strong>Templates Aprovados</strong>.
            Esta tela permite preparar Tags, definir regras de agrupamento e simular o público-alvo.
          </p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        
        {/* Left Column: Tags & Saved Segments */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Tags Manager Card */}
          <div className="glass-panel" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: '700', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-main)' }}>
              <TagIcon size={18} style={{ color: 'var(--accent-primary)' }} /> Gerenciamento de Tags
            </h3>

            <form onSubmit={handleCreateTag} style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
              <input
                type="text"
                placeholder="Nome da tag (ex: VIP, Lead Frio...)"
                value={newTagName}
                onChange={(e) => setNewTagName(e.target.value)}
                style={{
                  flex: 1,
                  padding: '8px 12px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '13px'
                }}
              />
              <input
                type="color"
                value={newTagColor}
                onChange={(e) => setNewTagColor(e.target.value)}
                style={{ width: '38px', height: '38px', borderRadius: '6px', border: 'none', cursor: 'pointer', backgroundColor: 'transparent' }}
              />
              <button type="submit" className="btn-primary" style={{ fontSize: '13px', padding: '8px 14px' }}>
                <Plus size={16} /> Criar
              </button>
            </form>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {tags.length === 0 ? (
                <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhuma tag cadastrada ainda.</span>
              ) : (
                tags.map(t => (
                  <span
                    key={t.id}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 'var(--radius-full)',
                      backgroundColor: `${t.cor_hex}25`,
                      color: t.cor_hex,
                      border: `1px solid ${t.cor_hex}50`,
                      fontSize: '12px',
                      fontWeight: '600'
                    }}
                  >
                    #{t.nome}
                  </span>
                ))
              )}
            </div>
          </div>

          {/* Saved Segments List */}
          <div className="glass-panel" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
            <h3 style={{ fontSize: '16px', fontWeight: '700', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-main)' }}>
              <Filter size={18} style={{ color: '#3b82f6' }} /> Segmentos Salvos ({segments.length})
            </h3>

            {segments.length === 0 ? (
              <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Nenhum segmento salvo.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {segments.map(s => (
                  <div key={s.id} style={{ padding: '12px', borderRadius: 'var(--radius-md)', backgroundColor: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)' }}>
                    <div style={{ fontWeight: '600', fontSize: '14px', color: 'var(--text-main)' }}>{s.nome}</div>
                    {s.descricao && <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>{s.descricao}</div>}
                    <div style={{ fontSize: '11px', color: 'var(--accent-primary)', marginTop: '6px' }}>
                      Criado em {new Date(s.criado_em).toLocaleDateString('pt-BR')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Segment Rule Builder & Dynamic Preview */}
        <div className="glass-panel" style={{ padding: '20px', borderRadius: 'var(--radius-lg)', display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ fontSize: '16px', fontWeight: '700', marginBottom: '16px', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Users size={18} style={{ color: '#a855f7' }} /> Construtor de Regras & Pré-visualização
          </h3>

          <form onSubmit={handleSaveSegment} style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '20px' }}>
            <div>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Nome do Segmento</label>
              <input
                type="text"
                placeholder="Ex: Clientes Inativos do Suporte (+30 dias)"
                value={segmentName}
                onChange={(e) => setSegmentName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '13px'
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Departamento de Origem</label>
                <select
                  value={selectedWnId}
                  onChange={(e) => setSelectedWnId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--text-main)',
                    fontSize: '13px'
                  }}
                >
                  <option value="all">Todos Departamentos</option>
                  {whatsappNumbers.map(wn => (
                    <option key={wn.id} value={wn.id}>{wn.nome_departamento}</option>
                  ))}
                </select>
              </div>

              <div>
                <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Inatividade (Última Interação)</label>
                <select
                  value={inactivityDays}
                  onChange={(e) => setInactivityDays(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--text-main)',
                    fontSize: '13px'
                  }}
                >
                  <option value="all">Qualquer data</option>
                  <option value={30}>Inativo há mais de 30 dias</option>
                  <option value={60}>Inativo há mais de 60 dias</option>
                  <option value={90}>Inativo há mais de 90 dias</option>
                </select>
              </div>
            </div>

            <div>
              <label style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px', display: 'block' }}>Filtrar por Tag</label>
              <select
                value={selectedTagId}
                onChange={(e) => setSelectedTagId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-main)',
                  fontSize: '13px'
                }}
              >
                <option value="all">Todas as Tags</option>
                {tags.map(t => (
                  <option key={t.id} value={t.id}>#{t.nome}</option>
                ))}
              </select>
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '8px' }}>
              <button
                type="button"
                onClick={handlePreviewSegment}
                className="btn-secondary"
                disabled={isPreviewLoading}
                style={{ fontSize: '13px', padding: '8px 14px' }}
              >
                <Eye size={15} /> {isPreviewLoading ? 'Calculando...' : 'Pré-visualizar Público'}
              </button>
              <button
                type="submit"
                className="btn-primary"
                style={{ fontSize: '13px', padding: '8px 14px' }}
              >
                Salvar Segmento
              </button>
            </div>
          </form>

          {/* Dynamic Preview Results Panel */}
          <div style={{ flex: 1, borderTop: '1px solid var(--border-color)', paddingTop: '16px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h4 style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-main)' }}>
                Contatos Encontrados
              </h4>
              {hasPreviewed && (
                <span className="badge badge-com_humano" style={{ fontSize: '12px' }}>
                  {previewContacts.length} cliente{previewContacts.length !== 1 ? 's' : ''} qualificados
                </span>
              )}
            </div>

            <div style={{ flex: 1, maxHeight: '220px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {!hasPreviewed ? (
                <p style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center', margin: 'auto' }}>
                  Clique em "Pré-visualizar Público" para calcular os clientes correspondentes.
                </p>
              ) : previewContacts.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--text-muted)', textAlign: 'center', margin: 'auto' }}>
                  Nenhum contato corresponde aos critérios selecionados.
                </p>
              ) : (
                previewContacts.map(c => (
                  <div key={c.id} style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                    <span><strong>{c.nome || 'Cliente'}</strong> ({c.telefone})</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>{c.total_conversations} atendimentos</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
