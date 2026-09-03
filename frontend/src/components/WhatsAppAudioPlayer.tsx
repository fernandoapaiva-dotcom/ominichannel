import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, Mic, User } from 'lucide-react';
import { Message, Conversation } from '../types';
import { useAudio } from '../context/AudioContext';

/** Resolve raw message content to a playable URL */
function resolveAudioUrl(raw: string, msgId?: number): string {
  if (!raw) return '';
  const clean = raw.split('|')[0].trim();
  if (clean.includes('mmg.whatsapp.net') || clean.includes('.enc')) {
    return msgId ? `/api/v1/conversations/messages/${msgId}/media` : clean;
  }
  if (clean.startsWith('http')) return clean;
  if (clean.startsWith('/uploads/')) return clean;
  return `/uploads/${clean.replace(/^\//, '')}`;
}


interface WhatsAppAudioPlayerProps {
  message: Message;
  conversation?: Conversation;
  allMessages?: Message[];
  isCustomer: boolean;
}

export const WhatsAppAudioPlayer: React.FC<WhatsAppAudioPlayerProps> = ({
  message,
  conversation,
  allMessages = [],
  isCustomer
}) => {
  const { activeAudio, toggleAudio, seekAudio, setSpeed } = useAudio();

  const isThisPlaying = Number(activeAudio?.msgId) === Number(message.id) && activeAudio?.isPlaying;
  const isThisActive = Number(activeAudio?.msgId) === Number(message.id);

  const currentTime = isThisActive ? activeAudio.currentTime : 0;
  const activeDuration = isThisActive ? activeAudio.duration : 0;
  const speed = isThisActive ? activeAudio.speed : 1;

  // Pre-loaded duration (loaded on mount even before the user presses play)
  const [preloadedDuration, setPreloadedDuration] = useState<number>(0);
  const preloadRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const url = resolveAudioUrl(message.conteudo || '', message.id);
    if (!url) return;

    let isMounted = true;

    // 1. Web Audio API decoding (100% reliable for .ogg Opus on Chrome Desktop)
    fetch(url)
      .then((res) => res.arrayBuffer())
      .then((buffer) => {
        const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
        if (!AudioCtx) throw new Error('No AudioContext');
        const ctx = new AudioCtx();
        return ctx.decodeAudioData(buffer).then((decoded) => {
          if (isMounted && decoded && decoded.duration && isFinite(decoded.duration) && decoded.duration > 0) {
            setPreloadedDuration(decoded.duration);
          }
          ctx.close().catch(() => {});
        });
      })
      .catch(() => {
        // Fallback: HTML5 Audio
        const audio = new Audio();
        preloadRef.current = audio;
        const onLoaded = () => {
          if (isMounted && audio.duration && isFinite(audio.duration) && audio.duration > 0) {
            setPreloadedDuration(audio.duration);
          }
        };
        audio.addEventListener('loadedmetadata', onLoaded);
        audio.addEventListener('durationchange', onLoaded);
        audio.addEventListener('canplaythrough', onLoaded);
        audio.preload = 'auto';
        audio.src = url;
      });

    return () => {
      isMounted = false;
      if (preloadRef.current) {
        preloadRef.current.src = '';
        preloadRef.current = null;
      }
    };
  }, [message.conteudo]);

  // Extra duration from WhatsApp payload (dados_adicionais.seconds)
  const extraSeconds = (message as any)?.dados_adicionais?.seconds || (message as any)?.dados_adicionais?.duration || 0;

  // Use live duration when active, fall back to preloaded, fall back to extraSeconds from WhatsApp
  const duration = activeDuration > 0 ? activeDuration : (preloadedDuration > 0 ? preloadedDuration : extraSeconds);

  const formatTime = (secs: number) => {

    if (!secs || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const handleSpeedToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    const speeds = [1, 1.5, 2];
    const nextIdx = (speeds.indexOf(speed) + 1) % speeds.length;
    setSpeed(speeds[nextIdx]);
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  // Sender Avatar
  const senderAvatar = isCustomer
    ? conversation?.contact?.foto_perfil_url
    : undefined;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding: '2px 0',
        width: '100%',
        maxWidth: '220px',
        minWidth: 0,
        boxSizing: 'border-box',
        overflow: 'hidden',
        userSelect: 'none'
      }}
    >
      {/* Sender Avatar with Mic Badge */}
      <div style={{ position: 'relative', flexShrink: 0 }}>
        <div
          style={{
            width: '42px',
            height: '42px',
            borderRadius: '50%',
            backgroundColor: isCustomer ? '#1f2c34' : 'var(--accent-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden'
          }}
        >
          {senderAvatar ? (
            <img src={senderAvatar} alt="Avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          ) : (
            <User size={22} style={{ color: '#ffffff' }} />
          )}
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: '-2px',
            right: '-2px',
            width: '18px',
            height: '18px',
            borderRadius: '50%',
            backgroundColor: '#00a884',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '2px solid var(--bg-secondary)'
          }}
        >
          <Mic size={10} style={{ color: '#ffffff' }} />
        </div>
      </div>

      {/* Play/Pause Button */}
      <button
        type="button"
        onClick={() => toggleAudio(message, conversation, allMessages)}
        style={{
          width: '38px',
          height: '38px',
          borderRadius: '50%',
          backgroundColor: '#00a884',
          border: 'none',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          flexShrink: 0,
          boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
          transition: 'transform 0.1s ease'
        }}
        onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.05)')}
        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
      >
        {isThisPlaying ? <Pause size={20} /> : <Play size={20} style={{ marginLeft: '2px' }} />}
      </button>

      {/* Waveform Progress & Timer */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 }}>
        {/* Scrubbable Progress Line */}
        <div style={{ position: 'relative', width: '100%', height: '6px', backgroundColor: 'rgba(255,255,255,0.15)', borderRadius: '3px', cursor: 'pointer' }}>
          <input
            type="range"
            min={0}
            max={duration || 100}
            value={currentTime || 0}
            onChange={(e) => seekAudio(Number(e.target.value))}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              opacity: 0,
              cursor: 'pointer',
              zIndex: 2
            }}
          />
          <div
            style={{
              width: `${progressPercent}%`,
              height: '100%',
              backgroundColor: '#00a884',
              borderRadius: '3px',
              transition: 'width 0.1s linear'
            }}
          />
        </div>

        {/* Time display & Speed toggle */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-muted)' }}>
          {/* Left: currentTime when playing, total duration when idle */}
          <span>{isThisActive ? formatTime(currentTime) : formatTime(duration)}</span>

          {isThisActive && (
            <button
              type="button"
              onClick={handleSpeedToggle}
              style={{
                background: 'rgba(0, 168, 132, 0.15)',
                border: 'none',
                borderRadius: '8px',
                padding: '1px 6px',
                color: '#00a884',
                fontSize: '10px',
                fontWeight: 'bold',
                cursor: 'pointer'
              }}
              title="Velocidade de reprodução"
            >
              {speed}x
            </button>
          )}

          {/* Right: total duration when playing */}
          <span>{isThisActive && duration > 0 ? formatTime(duration) : ''}</span>
        </div>
      </div>
    </div>
  );
};
