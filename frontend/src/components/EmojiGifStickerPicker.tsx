import React, { useState, useMemo } from 'react';
import { Search, Smile, Image as ImageIcon, Sparkles, X, Plus, Upload, Heart, ThumbsUp, Zap, Clock } from 'lucide-react';

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
      '🈵', '🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '⚫', '⚪', '🟤', '🟥', '🟧', '🟨', '🟩',
      '🟦', '🟪', '⬛', '⬜', '🟫', '⭐', '🌟', '✨', '⚡', '💥', '💯', '✅', '✔️', '❌', '❎'
    ]
  }
];

// Curated GIF Library for Business, WhatsApp & Support
const GIF_COLLECTIONS = [
  {
    category: 'Saudações / Bom Dia',
    gifs: [
      { url: 'https://media.giphy.com/media/ICOgUNjpvO0PC/giphy.gif', title: 'Gatinho Acenando Olá' },
      { url: 'https://media.giphy.com/media/3o7TKtnuHOHHUjR38Y/giphy.gif', title: 'Bom Dia com Café' },
      { url: 'https://media.giphy.com/media/dzaUX7CAG0Ihi/giphy.gif', title: 'Ursinho Olá' },
      { url: 'https://media.giphy.com/media/ASd0Ukj0y3qMM/giphy.gif', title: 'Minions Olá' }
    ]
  },
  {
    category: 'Agradecimento / Sucesso',
    gifs: [
      { url: 'https://media.giphy.com/media/26gsjCZpPolPr3sBy/giphy.gif', title: 'Muito Obrigado' },
      { url: 'https://media.giphy.com/media/osjgQPWRx3cac/giphy.gif', title: 'Joinha e Sucesso' },
      { url: 'https://media.giphy.com/media/xT5LMHxhOfscxPfIfm/giphy.gif', title: 'Tudo Certo' },
      { url: 'https://media.giphy.com/media/3oEjI5VtIhHvmmY8ZE/giphy.gif', title: 'Aplausos' }
    ]
  },
  {
    category: 'Trabalho / Em Atendimento',
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
      {/* Top Tabs: Emoji | GIF | Figurinhas */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'var(--bg-primary)'
      }}>
        <button
          type="button"
          onClick={() => { setActiveTab('emoji'); setSearchTerm(''); }}
          style={{
            flex: 1,
            padding: '10px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'emoji' ? '3px solid var(--accent-primary)' : '3px solid transparent',
            color: activeTab === 'emoji' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: '700',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <Smile size={16} /> Emojis
        </button>

        <button
          type="button"
          onClick={() => { setActiveTab('gif'); setSearchTerm(''); }}
          style={{
            flex: 1,
            padding: '10px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'gif' ? '3px solid var(--accent-primary)' : '3px solid transparent',
            color: activeTab === 'gif' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: '700',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <ImageIcon size={16} /> GIFs
        </button>

        <button
          type="button"
          onClick={() => { setActiveTab('sticker'); setSearchTerm(''); }}
          style={{
            flex: 1,
            padding: '10px 0',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'sticker' ? '3px solid var(--accent-primary)' : '3px solid transparent',
            color: activeTab === 'sticker' ? 'var(--accent-primary)' : 'var(--text-muted)',
            fontWeight: '700',
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <Sparkles size={16} /> Figurinhas
        </button>

        <button
          type="button"
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            padding: '0 12px',
            cursor: 'pointer'
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Search Bar */}
      <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', backgroundColor: 'var(--bg-primary)' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--bg-secondary)',
          borderRadius: 'var(--radius-md)',
          padding: '0 10px',
          border: '1px solid var(--border-color)'
        }}>
          <Search size={14} style={{ color: 'var(--text-muted)', marginRight: '6px' }} />
          <input
            type="text"
            placeholder={activeTab === 'emoji' ? 'Pesquisar emoji...' : activeTab === 'gif' ? 'Pesquisar GIFs animados...' : 'Pesquisar figurinhas...'}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{
              flex: 1,
              padding: '6px 0',
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

      {/* Content Area */}
      {activeTab === 'emoji' && (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
          {/* Category Bar */}
          {!searchTerm && (
            <div style={{
              display: 'flex',
              gap: '4px',
              padding: '6px 8px',
              borderBottom: '1px solid var(--border-color)',
              overflowX: 'auto',
              backgroundColor: 'var(--bg-secondary)'
            }}>
              {EMOJI_CATEGORIES.map(cat => (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => setActiveCategory(cat.id)}
                  title={cat.name}
                  style={{
                    background: activeCategory === cat.id ? 'rgba(0, 230, 153, 0.15)' : 'transparent',
                    border: 'none',
                    borderRadius: '6px',
                    fontSize: '16px',
                    padding: '4px 6px',
                    cursor: 'pointer',
                    opacity: activeCategory === cat.id ? 1 : 0.65,
                    transition: 'all 0.1s ease'
                  }}
                >
                  {cat.icon}
                </button>
              ))}
            </div>
          )}

          {/* Emoji Grid */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: '10px',
            display: 'grid',
            gridTemplateColumns: 'repeat(8, 1fr)',
            gap: '4px',
            alignContent: 'start'
          }}>
            {filteredCategoryEmojis.map((emoji, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => onSelectEmoji(emoji)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '22px',
                  padding: '6px 0',
                  cursor: 'pointer',
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'transform 0.1s ease, background-color 0.1s ease'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.15)';
                  e.currentTarget.style.transform = 'scale(1.25)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.transform = 'scale(1)';
                }}
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
        <div style={{ flex: 1, overflowY: 'auto', padding: '12px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
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
