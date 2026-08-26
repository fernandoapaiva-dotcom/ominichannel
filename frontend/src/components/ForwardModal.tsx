import React, { useState, useEffect, useMemo } from 'react';
import { X, Search, Check, Send, Users, User as UserIcon, CornerUpRight, Image, FileText, Video, Music, Layers, Building, Filter } from 'lucide-react';
import { Conversation, Message, WhatsAppNumber } from '../types';
import { apiFetch } from '../services/api';

interface ForwardModalProps {
  isOpen: boolean;
  onClose: () => void;
  messagesToForward: Message[] | Message | null;
  conversations: Conversation[];
  whatsappNumbers?: WhatsAppNumber[];
  onForwardSuccess?: () => void;
}

interface ForwardTarget {
  key: string;
  type: 'group' | 'contact';
  conversationId: number;
  contactName: string;
  contactPhone: string;
  avatarUrl?: string;
  whatsappNumberId: number;
  departmentName: string;
}

export const ForwardModal: React.FC<ForwardModalProps> = ({
  isOpen,
  onClose,
  messagesToForward,
  conversations,
  whatsappNumbers: initialWhatsappNumbers,
  onForwardSuccess
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'all' | 'groups' | 'contacts'>('all');
  const [departmentFilter, setDepartmentFilter] = useState<number | 'all'>('all');
  const [whatsappNumbers, setWhatsappNumbers] = useState<WhatsAppNumber[]>(initialWhatsappNumbers || []);
  
  // Selected targets map: key -> { conversationId, whatsappNumberId, contactPhone, contactName, type }
  const [selectedTargets, setSelectedTargets] = useState<{ [key: string]: ForwardTarget }>({});
  const [isForwarding, setIsForwarding] = useState(false);
  const [forwardProgress, setForwardProgress] = useState<string | null>(null);

  // Fetch whatsapp numbers / departments if not provided
  useEffect(() => {
    if (isOpen && (!whatsappNumbers || whatsappNumbers.length === 0)) {
      apiFetch('/whatsapp-numbers')
        .then((data: WhatsAppNumber[]) => {
          if (Array.isArray(data)) setWhatsappNumbers(data);
        })
        .catch(() => {});
    }
  }, [isOpen, whatsappNumbers]);

  const msgsList = useMemo(() => {
    if (!messagesToForward) return [];
    return Array.isArray(messagesToForward) ? messagesToForward : [messagesToForward];
  }, [messagesToForward]);

  // Consolidate unique contacts and groups from conversations
  const availableItems = useMemo(() => {
    const items: ForwardTarget[] = [];
    const seenKeys = new Set<string>();

    for (const c of conversations) {
      const phone = c.contact?.telefone || '';
      const isGroup = Boolean(
        phone.startsWith('120363') ||
        phone.includes('@g.us') ||
        Boolean((c.dados_adicionais as any)?.is_group) ||
        c.contact?.nome?.includes('Servweld/Servsolda')
      );

      const name = c.contact?.nome || (isGroup ? 'Grupo de WhatsApp' : 'Cliente');
      const deptName = c.whatsapp_number?.nome_departamento || 'Geral';
      const wnId = c.whatsapp_number_id || (c.whatsapp_number?.id || 1);
      
      const key = isGroup ? `group_${c.id}` : `contact_${phone || c.id}`;

      if (!seenKeys.has(key)) {
        seenKeys.add(key);
        items.push({
          key,
          type: isGroup ? 'group' : 'contact',
          conversationId: c.id,
          contactName: name,
          contactPhone: phone,
          avatarUrl: c.contact?.foto_perfil_url,
          whatsappNumberId: wnId,
          departmentName: deptName
        });
      }
    }

    return items;
  }, [conversations]);

  // Filter items by Tab, Search and Department
  const filteredItems = useMemo(() => {
    return availableItems.filter(item => {
      // Tab filter
      if (activeTab === 'groups' && item.type !== 'group') return false;
      if (activeTab === 'contacts' && item.type !== 'contact') return false;

      // Department filter
      if (departmentFilter !== 'all' && item.whatsappNumberId !== departmentFilter) return false;

      // Search term filter
      if (searchTerm.trim()) {
        const term = searchTerm.toLowerCase();
        const nameMatch = item.contactName.toLowerCase().includes(term);
        const phoneMatch = item.contactPhone.toLowerCase().includes(term);
        const deptMatch = item.departmentName.toLowerCase().includes(term);
        if (!nameMatch && !phoneMatch && !deptMatch) return false;
      }

      return true;
    });
  }, [availableItems, activeTab, departmentFilter, searchTerm]);

  // Counts for tabs
  const groupCount = useMemo(() => availableItems.filter(i => i.type === 'group').length, [availableItems]);
  const contactCount = useMemo(() => availableItems.filter(i => i.type === 'contact').length, [availableItems]);

  const toggleSelectTarget = (item: ForwardTarget) => {
    setSelectedTargets(prev => {
      const next = { ...prev };
      if (next[item.key]) {
        delete next[item.key];
      } else {
        next[item.key] = { ...item };
      }
      return next;
    });
  };

  const handleTargetDeptChange = (key: string, newWnId: number) => {
    const selectedWn = whatsappNumbers.find(w => w.id === newWnId);
    setSelectedTargets(prev => {
      if (!prev[key]) return prev;
      return {
        ...prev,
        [key]: {
          ...prev[key],
          whatsappNumberId: newWnId,
          departmentName: selectedWn?.nome_departamento || prev[key].departmentName
        }
      };
    });
  };

  const handleForward = async () => {
    const targets = Object.values(selectedTargets);
    if (msgsList.length === 0 || targets.length === 0) return;

    try {
      setIsForwarding(true);
      setForwardProgress(`Iniciando encaminhamento para ${targets.length} destinos...`);

      let processed = 0;

      for (const target of targets) {
        processed++;
        setForwardProgress(`Encaminhando (${processed}/${targets.length}) para ${target.contactName}...`);

        let targetConvId = target.conversationId;

        // If it is an individual contact and department was explicitly chosen, ensure conversation in that department
        if (target.type === 'contact' && target.whatsappNumberId) {
          try {
            // Find existing conversation in target department or start/get it
            const matchedConv = conversations.find(
              c => c.whatsapp_number_id === target.whatsappNumberId &&
                   c.contact?.telefone === target.contactPhone
            );

            if (matchedConv) {
              targetConvId = matchedConv.id;
            } else {
              const startRes = await apiFetch('/conversations/start', {
                method: 'POST',
                body: JSON.stringify({
                  whatsapp_number_id: target.whatsappNumberId,
                  telefone: target.contactPhone,
                  nome: target.contactName
                })
              });
              if (startRes && startRes.id) {
                targetConvId = startRes.id;
              }
            }
          } catch (createErr) {
            console.warn(`Usando conversa original para ${target.contactName}:`, createErr);
          }
        }

        // Send all messages to target conversation
        for (const msg of msgsList) {
          await apiFetch(`/conversations/${targetConvId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
              conversation_id: targetConvId,
              conteudo: msg.conteudo,
              tipo: msg.tipo || 'texto',
              remetente: 'atendente'
            })
          });
        }
      }

      setSelectedTargets({});
      setSearchTerm('');
      if (onForwardSuccess) onForwardSuccess();
      onClose();
    } catch (err) {
      console.error('Erro ao encaminhar mensagens:', err);
      alert('Erro ao encaminhar mensagens. Verifique os logs.');
    } finally {
      setIsForwarding(false);
      setForwardProgress(null);
    }
  };

  if (!isOpen || msgsList.length === 0) return null;

  const selectedCount = Object.keys(selectedTargets).length;

  return (
    <div style={{
      position: 'fixed',
      top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div className="glass-panel" style={{
        width: '100%',
        maxWidth: '580px',
        maxHeight: '90vh',
        backgroundColor: 'var(--bg-secondary)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 24px 60px rgba(0, 0, 0, 0.6)',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          backgroundColor: 'var(--bg-primary)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '50%',
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <CornerUpRight size={20} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: 'var(--text-main)' }}>
                Encaminhar {msgsList.length > 1 ? `${msgsList.length} mensagens` : 'mensagem'} para...
              </h3>
              <p style={{ margin: '2px 0 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                Compartilhe com grupos ou pessoas no departamento correto
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isForwarding}
            style={{
              background: 'rgba(255, 255, 255, 0.06)',
              border: 'none',
              borderRadius: '50%',
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              cursor: isForwarding ? 'not-allowed' : 'pointer'
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Category Tabs & Department Filter */}
        <div style={{
          padding: '12px 18px 0 18px',
          borderBottom: '1px solid var(--border-color)',
          backgroundColor: 'var(--bg-primary)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}>
          {/* Tabs */}
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              onClick={() => setActiveTab('all')}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: activeTab === 'all' ? 'var(--accent-primary)' : 'rgba(255, 255, 255, 0.05)',
                color: activeTab === 'all' ? '#051a12' : 'var(--text-muted)',
                fontWeight: '700',
                fontSize: '12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease'
              }}
            >
              Todos ({availableItems.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('groups')}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: activeTab === 'groups' ? '#0284c7' : 'rgba(255, 255, 255, 0.05)',
                color: activeTab === 'groups' ? '#ffffff' : 'var(--text-muted)',
                fontWeight: '700',
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                transition: 'all 0.15s ease'
              }}
            >
              <Users size={14} /> Grupos ({groupCount})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('contacts')}
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: activeTab === 'contacts' ? '#10b981' : 'rgba(255, 255, 255, 0.05)',
                color: activeTab === 'contacts' ? '#ffffff' : 'var(--text-muted)',
                fontWeight: '700',
                fontSize: '12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                transition: 'all 0.15s ease'
              }}
            >
              <UserIcon size={14} /> Pessoas Individuais ({contactCount})
            </button>
          </div>

          {/* Search + Department Filter Row */}
          <div style={{ display: 'flex', gap: '8px', paddingBottom: '12px' }}>
            <div style={{
              flex: 1,
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-secondary)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-color)',
              padding: '0 10px'
            }}>
              <Search size={15} style={{ color: 'var(--text-muted)', marginRight: '6px' }} />
              <input
                type="text"
                placeholder={activeTab === 'groups' ? "Pesquisar grupo..." : activeTab === 'contacts' ? "Pesquisar pessoa ou telefone..." : "Pesquisar grupo, pessoa ou telefone..."}
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  flex: 1,
                  padding: '8px 0',
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: 'var(--text-main)',
                  fontSize: '13px',
                  outline: 'none'
                }}
              />
              {searchTerm && (
                <button
                  onClick={() => setSearchTerm('')}
                  style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px' }}
                >
                  <X size={13} />
                </button>
              )}
            </div>

            {/* Department Filter Selector */}
            {whatsappNumbers.length > 1 && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                padding: '0 10px'
              }}>
                <Building size={14} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
                <select
                  value={departmentFilter}
                  onChange={(e) => setDepartmentFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                  style={{
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: 'var(--text-main)',
                    fontSize: '12px',
                    fontWeight: '600',
                    outline: 'none',
                    cursor: 'pointer',
                    maxWidth: '160px'
                  }}
                  title="Filtrar conversas por departamento"
                >
                  <option value="all" style={{ backgroundColor: '#0f172a', color: '#fff' }}>Todos os Deptos</option>
                  {whatsappNumbers.map(w => (
                    <option key={w.id} value={w.id} style={{ backgroundColor: '#0f172a', color: '#fff' }}>
                      {w.nome_departamento || `Linha ${w.id}`}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Conversation List */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '10px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          backgroundColor: 'var(--chat-bg)'
        }}>
          {filteredItems.length === 0 ? (
            <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              Nenhum destino encontrado com os filtros selecionados.
            </div>
          ) : (
            filteredItems.map(item => {
              const isSelected = Boolean(selectedTargets[item.key]);
              const currentSelectedDeptId = selectedTargets[item.key]?.whatsappNumberId || item.whatsappNumberId;

              return (
                <div
                  key={item.key}
                  onClick={() => toggleSelectTarget(item)}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: isSelected ? 'rgba(0, 230, 153, 0.12)' : 'var(--bg-secondary)',
                    border: isSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                    boxShadow: isSelected ? '0 2px 10px rgba(0, 230, 153, 0.15)' : 'none',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: 1, minWidth: 0 }}>
                      {item.avatarUrl ? (
                        <img
                          src={item.avatarUrl}
                          alt={item.contactName}
                          style={{
                            width: '42px',
                            height: '42px',
                            borderRadius: item.type === 'group' ? '12px' : '50%',
                            objectFit: 'cover',
                            border: '1px solid var(--border-color)',
                            flexShrink: 0
                          }}
                        />
                      ) : (
                        <div style={{
                          width: '42px',
                          height: '42px',
                          borderRadius: item.type === 'group' ? '12px' : '50%',
                          backgroundColor: item.type === 'group' ? '#0284c7' : '#00e699',
                          color: item.type === 'group' ? '#fff' : '#051a12',
                          fontWeight: '700',
                          fontSize: '15px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          flexShrink: 0
                        }}>
                          {item.type === 'group' ? <Users size={18} /> : item.contactName.charAt(0).toUpperCase()}
                        </div>
                      )}

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          <span style={{
                            fontWeight: '600',
                            fontSize: '14px',
                            color: 'var(--text-main)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                          }}>
                            {item.contactName}
                          </span>
                          {item.type === 'group' ? (
                            <span style={{ fontSize: '10px', backgroundColor: 'rgba(2, 132, 199, 0.15)', color: '#38bdf8', padding: '1px 5px', borderRadius: '4px', fontWeight: '700' }}>
                              Grupo
                            </span>
                          ) : (
                            <span style={{ fontSize: '10px', backgroundColor: 'rgba(16, 185, 129, 0.15)', color: '#34d399', padding: '1px 5px', borderRadius: '4px', fontWeight: '700' }}>
                              Pessoa
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', gap: '6px', alignItems: 'center' }}>
                          <span>{item.departmentName}</span>
                          {item.contactPhone && (
                            <>
                              <span>•</span>
                              <span>{item.contactPhone}</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>

                    <div style={{
                      width: '22px',
                      height: '22px',
                      borderRadius: '50%',
                      border: isSelected ? 'none' : '2px solid var(--border-color)',
                      backgroundColor: isSelected ? 'var(--accent-primary)' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#051a12',
                      flexShrink: 0
                    }}>
                      {isSelected && <Check size={14} strokeWidth={3} />}
                    </div>
                  </div>

                  {/* Individual Contact Department Routing Selector */}
                  {item.type === 'contact' && isSelected && whatsappNumbers.length > 1 && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        padding: '6px 10px',
                        backgroundColor: 'rgba(0, 0, 0, 0.3)',
                        borderRadius: '6px',
                        border: '1px solid rgba(0, 230, 153, 0.3)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '8px',
                        fontSize: '11.5px'
                      }}
                    >
                      <span style={{ color: 'var(--accent-primary)', fontWeight: '700', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Building size={12} /> Enviar pelo WhatsApp de:
                      </span>
                      <select
                        value={currentSelectedDeptId}
                        onChange={(e) => handleTargetDeptChange(item.key, Number(e.target.value))}
                        style={{
                          backgroundColor: 'var(--bg-secondary)',
                          border: '1px solid var(--border-color)',
                          borderRadius: '4px',
                          color: '#ffffff',
                          fontSize: '11.5px',
                          fontWeight: '600',
                          padding: '3px 8px',
                          outline: 'none',
                          cursor: 'pointer'
                        }}
                      >
                        {whatsappNumbers.map(w => (
                          <option key={w.id} value={w.id} style={{ backgroundColor: '#0f172a', color: '#fff' }}>
                            {w.nome_departamento || `Linha ${w.id}`}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Message Preview & Action Footer */}
        <div style={{
          padding: '12px 18px',
          backgroundColor: 'var(--bg-primary)',
          borderTop: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px'
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', textTransform: 'uppercase', marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Layers size={13} />
              {msgsList.length > 1 ? `${msgsList.length} mensagens para encaminhar:` : 'Mensagem para encaminhar:'}
            </div>
            {msgsList.length > 1 ? (
              <div style={{ fontSize: '12px', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {msgsList.map(m => (m.tipo === 'texto' ? m.conteudo : `[${m.tipo}]`)).join(' • ')}
              </div>
            ) : (
              (() => {
                const single = msgsList[0];
                const isMedia = ['imagem', 'video', 'audio', 'arquivo'].includes(single.tipo);
                const mediaCaption = single.conteudo?.includes('|') ? single.conteudo.split('|')[1] : '';
                return isMedia ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-main)' }}>
                    {single.tipo === 'imagem' ? <Image size={16} /> : single.tipo === 'video' ? <Video size={16} /> : single.tipo === 'audio' ? <Music size={16} /> : <FileText size={16} />}
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {mediaCaption || `[Arquivo de ${single.tipo}]`}
                    </span>
                  </div>
                ) : (
                  <div style={{ fontSize: '12px', color: 'var(--text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {single.conteudo}
                  </div>
                );
              })()
            )}
          </div>

          <button
            onClick={handleForward}
            disabled={selectedCount === 0 || isForwarding}
            className="btn-primary"
            style={{
              padding: '10px 18px',
              fontSize: '13px',
              fontWeight: '700',
              opacity: selectedCount === 0 || isForwarding ? 0.5 : 1,
              cursor: selectedCount === 0 || isForwarding ? 'not-allowed' : 'pointer',
              whiteSpace: 'nowrap',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Send size={15} />
            {isForwarding ? (forwardProgress || 'Encaminhando...') : `Encaminhar para (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
};
