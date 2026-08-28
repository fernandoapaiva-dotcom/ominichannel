import React, { useState, useEffect, useMemo } from 'react';
import { 
  X, Image as ImageIcon, Mic, FileText, Video as VideoIcon, 
  Download, ExternalLink, Paperclip, Search, Eye, Play, 
  LayoutGrid, List, Music, User, Clock, File
} from 'lucide-react';
import { Conversation, Message } from '../types';
import { apiFetch } from '../services/api';

interface MediaGalleryModalProps {
  isOpen: boolean;
  onClose: () => void;
  conversation: Conversation | null;
}

const extractMediaAndCaption = (raw: string | undefined | null) => {
  if (!raw) return { mediaPath: '', caption: null as string | null };
  let str = String(raw).trim();
  let mediaPath = '';
  let caption: string | null = null;

  if (str.includes('|')) {
    const parts = str.split('|');
    mediaPath = parts[0].trim();
    caption = parts.slice(1).join('|').trim() || null;
  } else if (str.startsWith('[') && str.includes(']')) {
    const match = str.match(/^\[(.*?)\]\s*([\s\S]*)$/);
    if (match) {
      mediaPath = match[1].trim();
      caption = match[2].trim() || null;
    } else {
      mediaPath = str.trim();
    }
  } else if (str.startsWith('/uploads/') || str.startsWith('http://') || str.startsWith('https://')) {
    const lines = str.split('\n');
    mediaPath = lines[0].trim();
    caption = lines.slice(1).join('\n').trim() || null;
  } else {
    mediaPath = str;
  }

  mediaPath = mediaPath.replace(/^\[/, '').replace(/\]$/, '').trim();
  return { mediaPath, caption };
};

export const MediaGalleryModal: React.FC<MediaGalleryModalProps> = ({
  isOpen,
  onClose,
  conversation
}) => {
  const [filterType, setFilterType] = useState<'all' | 'imagem' | 'video' | 'audio' | 'arquivo'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [mediaMessages, setMediaMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewMediaUrl, setPreviewMediaUrl] = useState<{ url: string; type: string; title: string } | null>(null);

  useEffect(() => {
    if (isOpen && conversation) {
      fetchMedia();
    } else {
      setSearchQuery('');
      setPreviewMediaUrl(null);
    }
  }, [isOpen, conversation?.id]);

  const fetchMedia = async () => {
    if (!conversation) return;
    try {
      setLoading(true);
      const data = await apiFetch(`/conversations/${conversation.id}/media`);
      if (Array.isArray(data)) {
        setMediaMessages(data);
      }
    } catch (err) {
      console.error('Error fetching conversation media:', err);
      // Fallback: filter locally from loaded conversation messages
      const fallback = (conversation.messages || []).filter(m => 
        ['imagem', 'video', 'audio', 'arquivo'].includes(m.tipo)
      );
      setMediaMessages(fallback);
    } finally {
      setLoading(false);
    }
  };

  const parsedMediaItems = useMemo(() => {
    return mediaMessages.map(msg => {
      const { mediaPath, caption } = extractMediaAndCaption(msg.conteudo);
      let fullUrl = mediaPath.startsWith('http') ? mediaPath : `${mediaPath}`;
      if ((mediaPath.includes('mmg.whatsapp.net') || mediaPath.includes('.enc') || (!mediaPath.startsWith('/uploads/') && !mediaPath.startsWith('http'))) && msg.id && msg.id > 0) {
        fullUrl = `/api/v1/conversations/messages/${msg.id}/media`;
      }
      
      const rawFileName = mediaPath.split('/').pop() || 'Arquivo';
      const isPdf = fullUrl.toLowerCase().endsWith('.pdf') || fullUrl.toLowerCase().includes('.pdf') || rawFileName.toLowerCase().endsWith('.pdf');
      
      let displayTitle = caption || rawFileName;
      if (displayTitle.length > 35 && !displayTitle.includes(' ')) {
        displayTitle = displayTitle.substring(0, 28) + '...' + (isPdf ? '.pdf' : '');
      }

      return {
        id: msg.id,
        tipo: msg.tipo,
        raw: msg.conteudo,
        mediaPath,
        fullUrl,
        rawFileName,
        isPdf,
        displayTitle,
        caption,
        timestamp: msg.timestamp,
        remetente: msg.remetente
      };
    });
  }, [mediaMessages]);

  const filteredItems = useMemo(() => {
    return parsedMediaItems.filter(item => {
      // 1. Type filter
      if (filterType !== 'all' && item.tipo !== filterType) {
        return false;
      }

      // 2. Search query filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchesTitle = item.displayTitle.toLowerCase().includes(q);
        const matchesCaption = item.caption ? item.caption.toLowerCase().includes(q) : false;
        const matchesFilename = item.rawFileName.toLowerCase().includes(q);
        const matchesSender = (item.remetente === 'cliente' ? 'cliente' : 'atendente').includes(q);
        const formattedDate = new Date(item.timestamp).toLocaleDateString('pt-BR');
        const matchesDate = formattedDate.includes(q);

        return matchesTitle || matchesCaption || matchesFilename || matchesSender || matchesDate;
      }

      return true;
    });
  }, [parsedMediaItems, filterType, searchQuery]);

  if (!isOpen || !conversation) return null;

  const counts = {
    all: parsedMediaItems.length,
    imagem: parsedMediaItems.filter(m => m.tipo === 'imagem').length,
    video: parsedMediaItems.filter(m => m.tipo === 'video').length,
    audio: parsedMediaItems.filter(m => m.tipo === 'audio').length,
    arquivo: parsedMediaItems.filter(m => m.tipo === 'arquivo').length,
  };

  const handleDownload = (e: React.MouseEvent, url: string, filename: string) => {
    e.stopPropagation();
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.82)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '16px'
    }}>
      <div className="glass-panel animate-fade-in" style={{
        width: '100%',
        maxWidth: '850px',
        height: '88vh',
        maxHeight: '900px',
        borderRadius: 'var(--radius-lg)',
        padding: '24px',
        backgroundColor: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
        position: 'relative',
        overflow: 'hidden'
      }}>
        {/* Modal Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '10px',
              backgroundColor: 'rgba(0, 230, 153, 0.15)',
              color: 'var(--accent-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(0, 230, 153, 0.2)'
            }}>
              <Paperclip size={22} />
            </div>
            <div>
              <h3 style={{ fontSize: '19px', fontWeight: '700', color: 'var(--text-main)', margin: 0 }}>
                Repositório de Mídias & Arquivos
              </h3>
              <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '2px 0 0 0' }}>
                {conversation.contact?.nome || 'Cliente'} • {conversation.contact?.telefone || 'Sem telefone'} ({counts.all} itens salvos)
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {/* View Mode Toggle */}
            <div style={{ 
              display: 'flex', 
              backgroundColor: 'rgba(255, 255, 255, 0.05)', 
              borderRadius: 'var(--radius-md)', 
              padding: '2px',
              border: '1px solid var(--border-color)' 
            }}>
              <button
                type="button"
                onClick={() => setViewMode('grid')}
                title="Visualização em Grade / Galeria"
                style={{
                  background: viewMode === 'grid' ? 'var(--accent-primary)' : 'transparent',
                  color: viewMode === 'grid' ? '#000' : 'var(--text-muted)',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  padding: '5px 8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <LayoutGrid size={15} />
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                title="Visualização em Lista Detalhada"
                style={{
                  background: viewMode === 'list' ? 'var(--accent-primary)' : 'transparent',
                  color: viewMode === 'list' ? '#000' : 'var(--text-muted)',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  padding: '5px 8px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <List size={15} />
              </button>
            </div>

            <button
              onClick={onClose}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                color: 'var(--text-muted)',
                border: '1px solid var(--border-color)',
                borderRadius: '50%',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#fff')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Search & Filter Toolbar */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px' }}>
          {/* Search Input */}
          <div style={{ position: 'relative', width: '100%' }}>
            <Search size={16} style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Pesquisar por nome, legenda, atendente ou data..."
              style={{
                width: '100%',
                padding: '9px 12px 9px 38px',
                backgroundColor: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-main)',
                fontSize: '13px',
                outline: 'none'
              }}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                style={{
                  position: 'absolute',
                  right: '10px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer'
                }}
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Filter Pills */}
          <div style={{ display: 'flex', gap: '8px', overflowX: 'auto', paddingBottom: '4px' }}>
            <button
              onClick={() => setFilterType('all')}
              className={filterType === 'all' ? 'btn-primary' : 'btn-secondary'}
              style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              Todas ({counts.all})
            </button>
            <button
              onClick={() => setFilterType('imagem')}
              className={filterType === 'imagem' ? 'btn-primary' : 'btn-secondary'}
              style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <ImageIcon size={14} /> Imagens ({counts.imagem})
            </button>
            <button
              onClick={() => setFilterType('video')}
              className={filterType === 'video' ? 'btn-primary' : 'btn-secondary'}
              style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <VideoIcon size={14} /> Vídeos ({counts.video})
            </button>
            <button
              onClick={() => setFilterType('audio')}
              className={filterType === 'audio' ? 'btn-primary' : 'btn-secondary'}
              style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Mic size={14} /> Áudios ({counts.audio})
            </button>
            <button
              onClick={() => setFilterType('arquivo')}
              className={filterType === 'arquivo' ? 'btn-primary' : 'btn-secondary'}
              style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <FileText size={14} /> Documentos / PDFs ({counts.arquivo})
            </button>
          </div>
        </div>

        {/* Media Stream / Gallery Grid */}
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: '4px' }}>
          {loading ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '260px', gap: '12px' }}>
              <div style={{ width: '32px', height: '32px', border: '3px solid rgba(0, 230, 153, 0.3)', borderTopColor: 'var(--accent-primary)', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
              <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>Carregando mídias e arquivos da conversa...</p>
            </div>
          ) : filteredItems.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '260px', color: 'var(--text-muted)', gap: '12px' }}>
              <Paperclip size={44} style={{ opacity: 0.3 }} />
              <p style={{ fontSize: '14px', margin: 0 }}>
                {searchQuery ? `Nenhum resultado encontrado para "${searchQuery}".` : 'Nenhum arquivo ou mídia encontrado nesta categoria.'}
              </p>
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="btn-secondary"
                  style={{ fontSize: '12px', padding: '4px 10px' }}
                >
                  Limpar busca
                </button>
              )}
            </div>
          ) : viewMode === 'grid' ? (
            /* --- GRID VIEW --- */
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
              gap: '14px'
            }}>
              {filteredItems.map(item => (
                <div
                  key={item.id}
                  style={{
                    backgroundColor: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column',
                    transition: 'transform 0.15s ease, border-color 0.15s ease',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.borderColor = 'var(--accent-primary)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.borderColor = 'var(--border-color)';
                  }}
                >
                  {/* Thumbnail / Cover Area */}
                  <div
                    style={{
                      position: 'relative',
                      width: '100%',
                      height: '135px',
                      backgroundColor: item.isPdf ? '#ffffff' : '#0f172a',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      overflow: 'hidden'
                    }}
                    onClick={() => setPreviewMediaUrl({ url: item.fullUrl, type: item.tipo, title: item.displayTitle })}
                  >
                    {item.tipo === 'imagem' ? (
                      <img
                        src={item.fullUrl}
                        alt={item.displayTitle}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        onError={(e) => {
                          e.currentTarget.style.display = 'none';
                        }}
                      />
                    ) : item.tipo === 'video' ? (
                      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
                        <video
                          src={item.fullUrl}
                          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                        <div style={{
                          position: 'absolute',
                          inset: 0,
                          backgroundColor: 'rgba(0,0,0,0.35)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}>
                          <div style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            backgroundColor: 'rgba(0, 230, 153, 0.9)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: '#000',
                            boxShadow: '0 4px 10px rgba(0,0,0,0.5)'
                          }}>
                            <Play size={18} fill="#000" style={{ marginLeft: '2px' }} />
                          </div>
                        </div>
                      </div>
                    ) : item.tipo === 'audio' ? (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#c084fc' }}>
                        <Music size={36} />
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Áudio Gravado</span>
                      </div>
                    ) : item.isPdf ? (
                      /* Live PDF 1st page Cover Preview */
                      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
                        <iframe
                          src={`${item.fullUrl}#page=1&view=FitH&toolbar=0&navpanes=0&scrollbar=0`}
                          title="Capa do PDF"
                          style={{ width: '100%', height: '100%', border: 'none', pointerEvents: 'none', display: 'block' }}
                        />
                        <div style={{
                          position: 'absolute',
                          top: '6px',
                          left: '6px',
                          backgroundColor: '#ef4444',
                          color: '#fff',
                          fontSize: '10px',
                          fontWeight: '800',
                          padding: '2px 5px',
                          borderRadius: '4px',
                          boxShadow: '0 2px 4px rgba(0,0,0,0.4)'
                        }}>
                          PDF
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px', color: '#34d399' }}>
                        <FileText size={36} />
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Documento</span>
                      </div>
                    )}

                    {/* Quick Hover Eye Overlay */}
                    <div style={{
                      position: 'absolute',
                      bottom: '6px',
                      right: '6px',
                      backgroundColor: 'rgba(0, 0, 0, 0.75)',
                      color: '#fff',
                      fontSize: '10px',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}>
                      <Eye size={11} /> Abrir
                    </div>
                  </div>

                  {/* Card Details & Actions */}
                  <div style={{ padding: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ minWidth: 0 }}>
                      <p style={{
                        fontSize: '12px',
                        fontWeight: '600',
                        color: 'var(--text-main)',
                        margin: 0,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                      }} title={item.displayTitle}>
                        {item.displayTitle}
                      </p>
                      {item.caption && item.caption !== item.displayTitle && (
                        <p style={{
                          fontSize: '11px',
                          color: 'var(--accent-primary)',
                          margin: '2px 0 0 0',
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis'
                        }}>
                          {item.caption}
                        </p>
                      )}
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
                      <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                        {item.remetente === 'cliente' ? 'Cliente' : 'Atendente'} • {new Date(item.timestamp).toLocaleDateString('pt-BR')}
                      </span>

                      <button
                        type="button"
                        onClick={(e) => handleDownload(e, item.fullUrl, item.rawFileName)}
                        title="Baixar arquivo"
                        style={{
                          background: 'rgba(255, 255, 255, 0.08)',
                          border: '1px solid var(--border-color)',
                          borderRadius: '4px',
                          padding: '4px 6px',
                          color: 'var(--accent-primary)',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}
                      >
                        <Download size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            /* --- LIST VIEW --- */
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {filteredItems.map(item => (
                <div
                  key={item.id}
                  style={{
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid var(--border-color)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '14px',
                    transition: 'background-color 0.15s ease'
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.06)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.03)')}
                >
                  {/* Thumbnail */}
                  <div
                    style={{
                      width: '52px',
                      height: '52px',
                      borderRadius: '8px',
                      overflow: 'hidden',
                      backgroundColor: item.isPdf ? '#ffffff' : '#0f172a',
                      flexShrink: 0,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      border: '1px solid var(--border-color)'
                    }}
                    onClick={() => setPreviewMediaUrl({ url: item.fullUrl, type: item.tipo, title: item.displayTitle })}
                  >
                    {item.tipo === 'imagem' ? (
                      <img src={item.fullUrl} alt={item.displayTitle} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : item.tipo === 'video' ? (
                      <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#000' }}>
                        <Play size={18} color="#00e699" fill="#00e699" />
                      </div>
                    ) : item.tipo === 'audio' ? (
                      <Music size={22} color="#c084fc" />
                    ) : item.isPdf ? (
                      <div style={{ position: 'relative', width: '100%', height: '100%' }}>
                        <iframe
                          src={`${item.fullUrl}#page=1&view=FitH&toolbar=0&navpanes=0&scrollbar=0`}
                          title="Miniatura PDF"
                          style={{ width: '100%', height: '100%', border: 'none', pointerEvents: 'none' }}
                        />
                      </div>
                    ) : (
                      <FileText size={22} color="#34d399" />
                    )}
                  </div>

                  {/* Info */}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{
                      fontSize: '13px',
                      fontWeight: '600',
                      color: 'var(--text-main)',
                      margin: 0,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>
                      {item.displayTitle}
                    </p>
                    {item.caption && (
                      <p style={{ fontSize: '12px', color: 'var(--accent-primary)', margin: '2px 0 0 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.caption}
                      </p>
                    )}
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '2px 0 0 0' }}>
                      {item.remetente === 'cliente' ? 'Enviado pelo Cliente' : 'Enviado pelo Atendente'} • {new Date(item.timestamp).toLocaleString('pt-BR')}
                    </p>
                  </div>

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                      type="button"
                      onClick={() => setPreviewMediaUrl({ url: item.fullUrl, type: item.tipo, title: item.displayTitle })}
                      className="btn-secondary"
                      style={{ fontSize: '12px', padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <Eye size={13} /> Visualizar
                    </button>
                    <button
                      type="button"
                      onClick={(e) => handleDownload(e, item.fullUrl, item.rawFileName)}
                      className="btn-secondary"
                      style={{ fontSize: '12px', padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-primary)' }}
                    >
                      <Download size={13} /> Baixar
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* --- LIGHTBOX MODAL PREVIEW --- */}
        {previewMediaUrl && (
          <div
            style={{
              position: 'fixed',
              inset: 0,
              backgroundColor: 'rgba(0, 0, 0, 0.9)',
              backdropFilter: 'blur(8px)',
              zIndex: 2000,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '20px'
            }}
            onClick={() => setPreviewMediaUrl(null)}
          >
            {/* Top Bar */}
            <div
              style={{
                position: 'absolute',
                top: '16px',
                left: '24px',
                right: '24px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                color: '#fff',
                zIndex: 10
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h4 style={{ fontSize: '16px', fontWeight: '600', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                {previewMediaUrl.title}
              </h4>
              <div style={{ display: 'flex', gap: '10px' }}>
                <a
                  href={previewMediaUrl.url}
                  download
                  target="_blank"
                  rel="noreferrer"
                  className="btn-primary"
                  style={{ fontSize: '12px', padding: '6px 12px', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <Download size={14} /> Baixar
                </a>
                <button
                  type="button"
                  onClick={() => setPreviewMediaUrl(null)}
                  style={{
                    background: 'rgba(255, 255, 255, 0.1)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    color: '#fff',
                    borderRadius: '50%',
                    width: '34px',
                    height: '34px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer'
                  }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Media Content */}
            <div
              style={{
                maxWidth: '90vw',
                maxHeight: '80vh',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {previewMediaUrl.type === 'imagem' ? (
                <img
                  src={previewMediaUrl.url}
                  alt={previewMediaUrl.title}
                  style={{
                    maxWidth: '85vw',
                    maxHeight: '75vh',
                    objectFit: 'contain',
                    borderRadius: '8px',
                    boxShadow: '0 10px 40px rgba(0,0,0,0.8)'
                  }}
                />
              ) : previewMediaUrl.type === 'video' ? (
                <video
                  src={previewMediaUrl.url}
                  controls
                  autoPlay
                  style={{
                    maxWidth: '85vw',
                    maxHeight: '75vh',
                    borderRadius: '8px',
                    boxShadow: '0 10px 40px rgba(0,0,0,0.8)'
                  }}
                />
              ) : previewMediaUrl.type === 'audio' ? (
                <div style={{
                  padding: '30px 40px',
                  backgroundColor: 'var(--bg-secondary)',
                  borderRadius: '16px',
                  border: '1px solid var(--border-color)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '16px'
                }}>
                  <Music size={48} color="#c084fc" />
                  <audio src={previewMediaUrl.url} controls autoPlay style={{ width: '320px' }} />
                </div>
              ) : (
                <iframe
                  src={previewMediaUrl.url}
                  title="Visualizador de Documento"
                  style={{
                    width: '80vw',
                    height: '75vh',
                    border: '1px solid var(--border-color)',
                    borderRadius: '12px',
                    backgroundColor: '#fff',
                    boxShadow: '0 10px 40px rgba(0,0,0,0.8)'
                  }}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
