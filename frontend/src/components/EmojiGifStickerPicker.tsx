import React, { useState, useEffect, useMemo } from 'react';
import { Search, Smile, Image as ImageIcon, Sparkles, X, Plus, Upload, Heart, ThumbsUp, Zap, Clock, Star } from 'lucide-react';

interface EmojiGifStickerPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectEmoji: (emoji: string) => void;
  onSelectGif?: (gifUrl: string) => void;
  onSelectSticker?: (stickerUrl: string) => void;
}

// Complete Categorized WhatsApp Emoji Library
const EMOJI_CATEGORIES = [
  {
    id: 'smileys',
    name: 'Rostos e Emoções',
    icon: '😀',
    emojis: [
      '😀', '😃', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '🙃', '😉', '😊', '😇',
      '🥰', '😍', '🤩', '😘', '😗', '😚', '😙', '😋', '😛', '😜', '🤪', '😝', '🤑',
      '🤗', '🤭', '🤫', '🤔', '🤐', '🤨', '😐', '😑', '😶', '😏', '😒', '🙄', '😬',
      '🤥', '😌', '😔', '😪', '🤤', '😴', '😷', '🤒', '🤕', '🤢', '🤮', '🤧', '🥵',
      '🥶', '🥴', '😵', '🤯', '🤠', '🥳', '😎', '🤓', '🧐', '😕', '😟', '🙁', '😮',
      '😯', '😲', '😳', '🥺', '😦', '😧', '😨', '😰', '😥', '😢', '😭', '😱', '😖',
      '😣', '😞', '😓', '😩', '😫', '🥱', '😤', '😡', '😠', '🤬', '😈', '👿', '💀',
      '☠️', '💩', '🤡', '👹', '👺', '👻', '👽', '👾', '🤖'
    ]
  },
  {
    id: 'people',
    name: 'Pessoas e Gestos',
    icon: '👋',
    emojis: [
      '👋', '🤚', '🖐️', '✋', '🖖', '👌', '🤌', '🤏', '✌️', '🤞', '🤟', '🤘', '🤙',
      '👈', '👉', '👆', '🖕', '👇', '☝️', '👍', '👎', '✊', '👊', '🤛', '🤜', '👏',
      '🙌', '👐', '🤲', '🤝', '🙏', '✍️', '💅', '🤳', '💪', '🦾', '🦿', '🦵', '🦶',
      '👂', '🦻', '👃', '🧠', '🫀', '🫁', '🦷', '🦴', '👀', '👁️', '👅', '👄', '💋',
      '🧑‍💻', '👨‍💼', '👩‍💼', '👨‍🔧', '👩‍🔧', '👨‍🏭', '👩‍🏭', '👷‍♂️', '👷‍♀️', '👨‍🏫', '👩‍🏫'
    ]
  },
  {
    id: 'animals',
    name: 'Animais e Natureza',
    icon: '🐶',
    emojis: [
      '🐶', '🐱', '🐭', '🐹', '🐰', '🦊', '🐻', '🐼', '🐨', '🐯', '🦁', '🐮', '🐷',
      '🐸', '🐵', '🐔', '🐧', '🐦', '🦅', '🦆', '🦉', '🦇', '🐺', '🐗', '🐴', '🦄',
      '🐝', '🐛', '🦋', '🐌', '🐞', '🐜', '🦟', '🦗', '🕷️', '🦂', '🐢', '🐍', '🦎',
      '🐙', '🦑', '🦐', '🦞', '🦀', '🐡', '🐠', '🐟', '🐬', '🐳', '🦈', '🐊', '🐅',
      '🌸', '🌹', '🌺', '🌻', '🌼', '🌷', '🌱', '🪴', '🌲', '🌳', '🌴', '🌵', '🌾',
      '🌿', '🍀', '🍁', '🍂', '🍃', '🔥', '💧', '🌊', '☀️', '🌤️', '⛅', '🌧️', '⚡', '🌈'
    ]
  },
  {
    id: 'food',
    name: 'Comidas e Bebidas',
    icon: '🍔',
    emojis: [
      '🍏', '🍎', '🍐', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🫐', '🍈', '🍒', '🍑',
      '🥭', '🍍', '🥥', '🥝', '🍅', '🥑', '🍆', '🥔', '🥕', '🌽', '🌶️', '🫑', '🥒',
      '🥬', '🥦', '🧄', '🧅', '🍄', '🥜', '🌰', '🍞', '🥐', '🥖', '🫓', '🥨', '🥯',
      '🥞', '🧇', '🧀', '🍖', '🍗', '🥩', '🥓', '🍔', '🍟', '🍕', '🌭', '🥪', '🌮',
      '🌯', '🫔', '🍳', '🍲', '🍜', '🍝', '🍣', '🍱', '🍦', '🍧', '🍨', '🍩', '🍪',
      '🎂', '🍰', '🧁', '🍫', '🍬', '🍭', '☕', '🫖', '🍵', '🧃', '🥤', '🧋', '🍺', '🍻'
    ]
  },
  {
    id: 'activities',
    name: 'Atividades e Esportes',
    icon: '⚽',
    emojis: [
      '⚽', '🏀', '🏈', '⚾', '🥎', '🎾', '🏐', '🏉', '🥏', '🎱', '🪀', '🏓', '🏸',
      '🏒', '🏑', '🥍', '🏏', '🪃', '🥅', '⛳', '🪁', '🏹', '🎣', '🤿', '🥊', '🥋',
      '🎽', '🛹', '🛼', '🛷', '⛸️', '🥌', '🎿', '⛷️', '🏂', '🪂', '🏋️‍♂️', '🏋️‍♀️', '🤼‍♂️',
      '🤸‍♂️', '🤸‍♀️', '⛹️‍♂️', '⛹️‍♀️', '🤺', '🤾‍♂️', '🏌️‍♂️', '🏇', '🧘‍♂️', '🧘‍♀️', '🏄‍♂️', '🏊‍♂️',
      '🎯', '🎮', '🕹️', '🎰', '🎲', '🧩', '🎨', '🎬', '🎤', '🎧', '🎼', '🎹', '🥁', '🎷'
    ]
  },
  {
    id: 'objects',
    name: 'Objetos e Ferramentas',
    icon: '💡',
    emojis: [
      '💡', '🔦', '🕯️', '🪔', '💸', '💵', '💴', '💶', '💷', '💰', '💳', '💎', '⚖️',
      '🪜', '🧰', '🪛', '🔧', '🔨', '⚒️', '🛠️', '⛏️', '🪓', '🔩', '⚙️', '🪤', '🧱',
      '⛓️', '🧲', '🔫', '💣', '🧨', '🪓', '🔪', '🗡️', '🛡️', '🚬', '⚰️', '🪦', '🏺',
      '🔮', '📿', '🧿', '💈', '⚗️', '🔭', '🔬', '🕳️', '🩹', '🩺', '💊', '💉', '🩸',
      '📱', '📲', '💻', '🖥️', '🖨️', '⌨️', '🖱️', '💾', '💿', '📀', '📼', '📷', '📸',
      '📹', '🎥', '📽️', '📞', '☎️', '📟', '📠', '📺', '📻', '🎙️', '⏰', '⏱️', '⏲️'
    ]
  },
  {
    id: 'symbols',
    name: 'Símbolos e Corações',
    icon: '❤️',
    emojis: [
      '❤️', '🧡', '💛', '💚', '💙', '💜', '🖤', '🤍', '🤎', '💔', '❣️', '💕', '💞',
      '💓', '💗', '💖', '💘', '💝', '💟', '☮️', '✝️', '☪️', '🕉️', '☸️', '✡️', '🔯',
      '🕎', '☯️', '☦️', '🛐', '⛎', '♈', '♉', '♊', '♋', '♌', '♍', '♎', '♏', '♐',
      '♑', '♒', '♓', '🆔', '⚛️', '🉑', '☢️', '☣️', '📴', '📳', '🈶', '🈚', '🈸', '🈺',
      '🉐', '🉑', '㊙️', '㊗️', '🈴', '🈵', '🈲', '🈹', '🈲', '🔞', '📵', '🔕', '📶', '📳'
    ]
  }
];

// Curated WhatsApp GIFs
const GIF_COLLECTIONS = [
  {
    category: 'Reações & Respostas Rápidas',
    gifs: [
      { url: 'https://media.giphy.com/media/11ISw6cx8oTaDe/giphy.gif', title: 'Joinha / Positivo' },
      { url: 'https://media.giphy.com/media/3oz8xAFtqoOUUrsh7W/giphy.gif', title: 'Muito Obrigado' },
      { url: 'https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif', title: 'Palmas / Parabéns' },
      { url: 'https://media.giphy.com/media/26u4cqiYI30juCOGY/giphy.gif', title: 'Olá / Bem-vindo' }
    ]
  },
  {
    category: 'Trabalho & Atendimento',
    gifs: [
      { url: 'https://media.giphy.com/media/unQ3IJU2RG7DO/giphy.gif', title: 'Digitando Rápido' },
      { url: 'https://media.giphy.com/media/JIX9t2j0ZTN9S/giphy.gif', title: 'Gato no Computador' },
      { url: 'https://media.giphy.com/media/l41lI4bYmcsPJX9Go/giphy.gif', title: 'Verificando Sistema' },
      { url: 'https://media.giphy.com/media/3oKIPnAiaMCws8nOsE/giphy.gif', title: 'Processando Pedido' }
    ]
  },
  {
    category: 'Comemoração / Vendas',
    gifs: [
      { url: 'https://media.giphy.com/media/artj92V8o75VPL7AeQ/giphy.gif', title: 'Festa e Comemoração' },
      { url: 'https://media.giphy.com/media/lMameLIF8ymwx5RIHM/giphy.gif', title: 'Dança da Vitória' },
      { url: 'https://media.giphy.com/media/DhstvI3CH0n0Q/giphy.gif', title: 'Show de Bola' }
    ]
  }
];

// Curated WhatsApp Stickers (Figurinhas)
const STICKER_COLLECTIONS = [
  {
    name: 'Atendimento & Vendas',
    stickers: [
      { url: 'https://api.dicebear.com/7.x/bottts/svg?seed=Servweld1&backgroundColor=00e699', title: 'Robô Servweld' },
      { url: 'https://api.dicebear.com/7.x/bottts/svg?seed=Servweld2&backgroundColor=0284c7', title: 'Robô Atendente' },
      { url: 'https://api.dicebear.com/7.x/thumbs/svg?seed=Joinha&backgroundColor=10b981', title: 'Tudo Certo!' },
      { url: 'https://api.dicebear.com/7.x/thumbs/svg?seed=Obrigado&backgroundColor=f59e0b', title: 'Muito Obrigado!' },
      { url: 'https://api.dicebear.com/7.x/shapes/svg?seed=Solda&backgroundColor=6366f1', title: 'Equipamentos' }
    ]
  },
  {
    name: 'Expressões & Memes',
    stickers: [
      { url: 'https://api.dicebear.com/7.x/fun-emoji/svg?seed=Felix', title: 'Super Feliz' },
      { url: 'https://api.dicebear.com/7.x/fun-emoji/svg?seed=Amor', title: 'Coração Apaixonado' },
      { url: 'https://api.dicebear.com/7.x/fun-emoji/svg?seed=Oculos', title: 'Óculos Escuros' },
      { url: 'https://api.dicebear.com/7.x/fun-emoji/svg?seed=Pensando', title: 'De Olho' },
      { url: 'https://api.dicebear.com/7.x/fun-emoji/svg?seed=Rindo', title: 'Rindo Alto' }
    ]
  }
];

export const EmojiGifStickerPicker: React.FC<EmojiGifStickerPickerProps> = ({
  isOpen,
  onClose,
  onSelectEmoji,
  onSelectGif,
  onSelectSticker
}) => {
  const [activeTab, setActiveTab] = useState<'emoji' | 'gif' | 'sticker'>('emoji');
  const [activeCategory, setActiveCategory] = useState<string>('smileys');
  const [searchTerm, setSearchTerm] = useState('');

  // User's custom saved stickers bank (stored in localStorage)
  const [savedStickers, setSavedStickers] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('saved_stickers_bank') || '[]');
    } catch {
      return [];
    }
  });

  useEffect(() => {
    const handleUpdate = () => {
      try {
        setSavedStickers(JSON.parse(localStorage.getItem('saved_stickers_bank') || '[]'));
      } catch {}
    };
    window.addEventListener('saved_stickers_updated', handleUpdate);
    return () => window.removeEventListener('saved_stickers_updated', handleUpdate);
  }, []);

  const handleRemoveSavedSticker = (e: React.MouseEvent, stickerUrl: string) => {
    e.stopPropagation();
    const updated = savedStickers.filter(s => s !== stickerUrl);
    setSavedStickers(updated);
    localStorage.setItem('saved_stickers_bank', JSON.stringify(updated));
  };

  // Filter emojis based on search
  const filteredCategoryEmojis = useMemo(() => {
    if (!searchTerm.trim()) {
      const cat = EMOJI_CATEGORIES.find(c => c.id === activeCategory);
      return cat ? cat.emojis : EMOJI_CATEGORIES[0].emojis;
    }
    const term = searchTerm.toLowerCase();
    // Search across all categories
    const all = EMOJI_CATEGORIES.flatMap(c => c.emojis);
    return all.filter(e => e.includes(term));
  }, [activeCategory, searchTerm]);

  // Filter GIFs based on search
  const filteredGifs = useMemo(() => {
    const all = GIF_COLLECTIONS.flatMap(c => c.gifs);
    if (!searchTerm.trim()) return GIF_COLLECTIONS;
    const term = searchTerm.toLowerCase();
    return [{
      category: 'Resultados da Busca',
      gifs: all.filter(g => g.title.toLowerCase().includes(term))
    }];
  }, [searchTerm]);

  if (!isOpen) return null;

  return (
    <div style={{
      position: 'absolute',
      bottom: '75px',
      left: '20px',
      width: '380px',
      height: '420px',
      backgroundColor: 'var(--bg-secondary)',
      borderRadius: '16px',
      border: '1px solid var(--border-color)',
      boxShadow: '0 12px 35px rgba(0, 0, 0, 0.4)',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 1000,
      overflow: 'hidden'
    }}>
      {/* Top Navigation Tabs */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)'
      }}>
        <button
          type="button"
          onClick={() => setActiveTab('emoji')}
          style={{
            flex: 1,
            padding: '12px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'emoji' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            color: activeTab === 'emoji' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: activeTab === 'emoji' ? '700' : '500',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <Smile size={16} />
          <span>Emojis</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('gif')}
          style={{
            flex: 1,
            padding: '12px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'gif' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            color: activeTab === 'gif' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: activeTab === 'gif' ? '700' : '500',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <Sparkles size={16} />
          <span>GIFs</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('sticker')}
          style={{
            flex: 1,
            padding: '12px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'sticker' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            color: activeTab === 'sticker' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: activeTab === 'sticker' ? '700' : '500',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <ImageIcon size={16} />
          <span>Figurinhas</span>
          {savedStickers.length > 0 && (
            <span style={{
              fontSize: '10px',
              padding: '1px 5px',
              borderRadius: '10px',
              backgroundColor: '#f59e0b',
              color: '#051a12',
              fontWeight: '800'
            }}>
              {savedStickers.length}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={onClose}
          style={{
            padding: '0 12px',
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer'
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Search Bar */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--bg-primary)',
          borderRadius: '8px',
          padding: '0 10px',
          border: '1px solid var(--border-color)'
        }}>
          <Search size={14} style={{ color: 'var(--text-muted)', marginRight: '6px' }} />
          <input
            type="text"
            placeholder={activeTab === 'emoji' ? 'Pesquisar emojis...' : activeTab === 'gif' ? 'Pesquisar GIFs animados...' : 'Pesquisar figurinhas...'}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              flex: 1,
              padding: '8px 0',
              backgroundColor: 'transparent',
              border: 'none',
              color: 'var(--text-main)',
              fontSize: '12px',
              outline: 'none'
            }}
          />
          {searchTerm && (
            <button
              onClick={() => setSearchTerm('')}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '2px' }}
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* TAB CONTENT */}
      {activeTab === 'emoji' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Categories Selector Bar */}
          {!searchTerm && (
            <div style={{
              display: 'flex',
              gap: '4px',
              padding: '6px 8px',
              borderBottom: '1px solid var(--border-color)',
              overflowX: 'auto',
              backgroundColor: 'var(--bg-primary)'
            }}>
              {EMOJI_CATEGORIES.map(cat => (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => setActiveCategory(cat.id)}
                  title={cat.name}
                  style={{
                    padding: '6px 8px',
                    background: activeCategory === cat.id ? 'var(--bg-secondary)' : 'transparent',
                    border: activeCategory === cat.id ? '1px solid var(--border-active)' : '1px solid transparent',
                    borderRadius: '6px',
                    fontSize: '16px',
                    cursor: 'pointer'
                  }}
                >
                  {cat.icon}
                </button>
              ))}
            </div>
          )}

          {/* Emojis Grid */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: '10px',
            display: 'grid',
            gridTemplateColumns: 'repeat(7, 1fr)',
            gap: '6px',
            alignContent: 'start'
          }}>
            {filteredCategoryEmojis.map((emoji, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectEmoji(emoji)}
                style={{
                  fontSize: '22px',
                  background: 'transparent',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  padding: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'transform 0.1s ease'
                }}
                onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.25)')}
                onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'gif' && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '10px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {filteredGifs.map((cat, idx) => (
            <div key={idx}>
              <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', textTransform: 'uppercase', marginBottom: '8px' }}>
                {cat.category}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
                {cat.gifs.map((gif, gIdx) => (
                  <div
                    key={gIdx}
                    onClick={() => {
                      if (onSelectGif) onSelectGif(gif.url);
                      onClose();
                    }}
                    style={{
                      borderRadius: '8px',
                      overflow: 'hidden',
                      height: '95px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      cursor: 'pointer',
                      position: 'relative'
                    }}
                  >
                    <img
                      src={gif.url}
                      alt={gif.title}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                    <div style={{
                      position: 'absolute',
                      bottom: 0,
                      left: 0,
                      right: 0,
                      backgroundColor: 'rgba(0, 0, 0, 0.65)',
                      padding: '2px 6px',
                      fontSize: '10px',
                      color: '#fff',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }}>
                      {gif.title}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {activeTab === 'sticker' && (
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* 1. Minhas Figurinhas Salvas (Banco) */}
          <div>
            <div style={{ fontSize: '11px', fontWeight: '700', color: '#f59e0b', textTransform: 'uppercase', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Star size={13} fill="#f59e0b" />
              <span>Minhas Figurinhas Salvas ({savedStickers.length})</span>
            </div>
            {savedStickers.length === 0 ? (
              <div style={{
                padding: '14px',
                borderRadius: '8px',
                backgroundColor: 'var(--bg-primary)',
                border: '1px dashed var(--border-color)',
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: '12px',
                lineHeight: '1.4'
              }}>
                ⭐ Nenhuma figurinha salva ainda. Passe o mouse sobre qualquer figurinha no chat e clique na estrela ⭐ para adicioná-la aqui!
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                {savedStickers.map((url, sIdx) => (
                  <div
                    key={sIdx}
                    onClick={() => {
                      if (onSelectSticker) onSelectSticker(url);
                      onClose();
                    }}
                    title="Clique para enviar figurinha salva"
                    style={{
                      position: 'relative',
                      padding: '6px',
                      borderRadius: '8px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'transform 0.15s ease'
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.15)')}
                    onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                  >
                    <img src={url} alt="Figurinha Salva" style={{ width: '56px', height: '56px', objectFit: 'contain' }} />
                    <button
                      type="button"
                      onClick={(e) => handleRemoveSavedSticker(e, url)}
                      title="Remover do banco"
                      style={{
                        position: 'absolute',
                        top: '2px',
                        right: '2px',
                        background: 'rgba(239, 68, 68, 0.85)',
                        border: 'none',
                        borderRadius: '50%',
                        width: '16px',
                        height: '16px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#fff',
                        cursor: 'pointer',
                        padding: 0
                      }}
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 2. Pacotes Padrão */}
          {STICKER_COLLECTIONS.map((pack, idx) => (
            <div key={idx}>
              <div style={{ fontSize: '11px', fontWeight: '700', color: 'var(--accent-primary)', textTransform: 'uppercase', marginBottom: '8px' }}>
                {pack.name}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }}>
                {pack.stickers.map((stk, sIdx) => (
                  <div
                    key={sIdx}
                    onClick={() => {
                      if (onSelectSticker) onSelectSticker(stk.url);
                      onClose();
                    }}
                    title={stk.title}
                    style={{
                      padding: '6px',
                      borderRadius: '8px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'transform 0.15s ease'
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.15)')}
                    onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                  >
                    <img src={stk.url} alt={stk.title} style={{ width: '56px', height: '56px', objectFit: 'contain' }} />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
