import React from 'react';
import { Play, Pause, X, Mic, User } from 'lucide-react';
import { useAudio } from '../context/AudioContext';

export const StickyAudioPlayer: React.FC = () => {
  const { activeAudio, pauseAudio, resumeAudio, seekAudio, setSpeed, stopAudio } = useAudio();

  if (!activeAudio) return null;

  const formatTime = (secs: number) => {
    if (!secs || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const handleSpeedToggle = () => {
    const speeds = [1, 1.5, 2];
    const nextIdx = (speeds.indexOf(activeAudio.speed) + 1) % speeds.length;
    setSpeed(speeds[nextIdx]);
  };

  const progressPercent = activeAudio.duration > 0
    ? (activeAudio.currentTime / activeAudio.duration) * 100
    : 0;

  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 99,
        backgroundColor: '#111b21',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        padding: '8px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        transition: 'all 0.2s ease'
      }}
    >
      {/* Sender Avatar / Icon */}
      <div
        style={{
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          backgroundColor: '#00a884',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
          flexShrink: 0
        }}
      >
        {activeAudio.senderAvatar ? (
          <img src={activeAudio.senderAvatar} alt={activeAudio.senderName} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <User size={20} style={{ color: '#ffffff' }} />
        )}
      </div>

      {/* Info & Progress */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '12px' }}>
          <span style={{ fontWeight: '600', color: '#e9edef', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            🎤 {activeAudio.senderName}
          </span>
          <span style={{ fontSize: '11px', color: '#8696a0', fontFamily: 'monospace' }}>
            {formatTime(activeAudio.currentTime)} / {formatTime(activeAudio.duration)}
          </span>
        </div>

        {/* Progress Bar Slider */}
        <div style={{ position: 'relative', width: '100%', height: '4px', backgroundColor: 'rgba(255,255,255,0.15)', borderRadius: '2px', cursor: 'pointer' }}>
          <input
            type="range"
            min={0}
            max={activeAudio.duration || 100}
            value={activeAudio.currentTime || 0}
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
              borderRadius: '2px',
              transition: 'width 0.1s linear'
            }}
          />
        </div>
      </div>

      {/* Control Buttons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {/* Playback Speed Badge */}
        <button
          type="button"
          onClick={handleSpeedToggle}
          style={{
            background: 'rgba(255,255,255,0.1)',
            border: 'none',
            borderRadius: '12px',
            padding: '2px 8px',
            color: '#00a884',
            fontSize: '11px',
            fontWeight: 'bold',
            cursor: 'pointer'
          }}
          title="Alterar velocidade de reprodução"
        >
          {activeAudio.speed}x
        </button>

        {/* Play/Pause Button */}
        <button
          type="button"
          onClick={activeAudio.isPlaying ? pauseAudio : resumeAudio}
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '50%',
            backgroundColor: '#00a884',
            border: 'none',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer'
          }}
        >
          {activeAudio.isPlaying ? <Pause size={18} /> : <Play size={18} style={{ marginLeft: '2px' }} />}
        </button>

        {/* Close Button */}
        <button
          type="button"
          onClick={stopAudio}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#8696a0',
            cursor: 'pointer',
            padding: '4px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title="Fechar player"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  );
};
