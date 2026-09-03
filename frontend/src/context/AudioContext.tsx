import React, { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { Message, Conversation } from '../types';

interface ActiveAudioState {
  msgId: number;
  url: string;
  senderName: string;
  senderAvatar?: string;
  conversationId: number;
  duration: number;
  currentTime: number;
  isPlaying: boolean;
  speed: number;
}

interface AudioContextType {
  activeAudio: ActiveAudioState | null;
  speed: number;
  playAudio: (msg: Message, conversation?: Conversation, allMessages?: Message[]) => void;
  pauseAudio: () => void;
  resumeAudio: () => void;
  toggleAudio: (msg: Message, conversation?: Conversation, allMessages?: Message[]) => void;
  seekAudio: (time: number) => void;
  setSpeed: (speed: number) => void;
  cycleSpeed: () => void;
  stopAudio: () => void;
}

const AudioContext = createContext<AudioContextType | undefined>(undefined);

export const AudioProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeAudio, setActiveAudio] = useState<ActiveAudioState | null>(null);
  const activeAudioRef = useRef<ActiveAudioState | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentMessagesRef = useRef<Message[]>([]);
  const currentConvRef = useRef<Conversation | undefined>(undefined);
  const playAudioRef = useRef<any>(null);

  // Global playback speed: 1, 1.5, or 2
  const [speed, setSpeedState] = useState<number>(() => {
    try {
      const saved = Number(localStorage.getItem('omini_audio_speed'));
      return [1, 1.5, 2].includes(saved) ? saved : 1;
    } catch {
      return 1;
    }
  });
  const speedRef = useRef<number>(speed);

  // Sync activeAudioRef with state
  useEffect(() => {
    activeAudioRef.current = activeAudio;
  }, [activeAudio]);

  const setSpeed = useCallback((newSpeed: number) => {
    speedRef.current = newSpeed;
    setSpeedState(newSpeed);
    try {
      localStorage.setItem('omini_audio_speed', String(newSpeed));
    } catch {}
    if (audioRef.current) {
      audioRef.current.playbackRate = newSpeed;
    }
    setActiveAudio(prev => prev ? { ...prev, speed: newSpeed } : null);
  }, []);

  const cycleSpeed = useCallback(() => {
    const speeds = [1, 1.5, 2];
    const nextIdx = (speeds.indexOf(speedRef.current) + 1) % speeds.length;
    setSpeed(speeds[nextIdx]);
  }, [setSpeed]);

  const triggerNextAudio = useCallback(() => {
    const current = activeAudioRef.current;
    const rawMsgs = currentMessagesRef.current;
    console.log('[AudioContext] Track ended. Current msgId:', current?.msgId, 'Total msgs in queue:', rawMsgs?.length);

    if (!current || !rawMsgs || rawMsgs.length === 0) {
      setActiveAudio(null);
      activeAudioRef.current = null;
      return;
    }

    // Sort strictly chronological (oldest to newest)
    const sortedMsgs = [...rawMsgs].sort((a, b) => {
      const tA = new Date(a.timestamp || 0).getTime();
      const tB = new Date(b.timestamp || 0).getTime();
      if (tA !== tB) return tA - tB;
      return Number(a.id || 0) - Number(b.id || 0);
    });

    const currentIndex = sortedMsgs.findIndex(m => Number(m.id) === Number(current.msgId));
    console.log('[AudioContext] Current message index:', currentIndex);

    let nextAudioMsg: Message | undefined = undefined;
    if (currentIndex !== -1) {
      nextAudioMsg = sortedMsgs.slice(currentIndex + 1).find(m => {
        const t = String(m.tipo || '').toLowerCase();
        const c = String(m.conteudo || '').toLowerCase();
        return (
          t === 'audio' ||
          c.endsWith('.ogg') ||
          c.endsWith('.mp3') ||
          c.endsWith('.wav') ||
          (c.includes('/uploads/') && (c.includes('.ogg') || c.includes('.mp3'))) ||
          c.includes('mmg.whatsapp.net')
        );
      });
    }

    console.log('[AudioContext] Next audio candidate:', nextAudioMsg?.id);

    if (nextAudioMsg && playAudioRef.current) {
      console.log('[AudioContext] Seamlessly transitioning to audio msgId:', nextAudioMsg.id);
      playAudioRef.current(nextAudioMsg, currentConvRef.current, sortedMsgs);
      return;
    }

    // No subsequent audio
    setActiveAudio(null);
    activeAudioRef.current = null;
  }, []);

  useEffect(() => {
    const audio = new Audio();
    audioRef.current = audio;

    audio.ontimeupdate = () => {
      setActiveAudio(prev => {
        if (!prev) return null;
        const updated = {
          ...prev,
          currentTime: audio.currentTime,
          duration: audio.duration || prev.duration || 0
        };
        activeAudioRef.current = updated;
        return updated;
      });
    };

    audio.onloadedmetadata = () => {
      setActiveAudio(prev => {
        if (!prev) return null;
        const updated = {
          ...prev,
          duration: audio.duration || prev.duration || 0
        };
        activeAudioRef.current = updated;
        return updated;
      });
    };

    audio.onended = () => {
      console.log('[AudioContext] Native onended event fired!');
      triggerNextAudio();
    };

    return () => {
      audio.ontimeupdate = null;
      audio.onloadedmetadata = null;
      audio.onended = null;
      audio.pause();
      audio.src = '';
    };
  }, [triggerNextAudio]);

  const getAudioUrl = (rawContent: string, msgId?: number): string => {
    if (!rawContent) return '';
    const cleanUrl = rawContent.split('|')[0].trim();
    if (cleanUrl.includes('mmg.whatsapp.net') || cleanUrl.includes('.enc')) {
      return msgId ? `/api/v1/conversations/messages/${msgId}/media` : cleanUrl;
    }
    if (cleanUrl.startsWith('http')) return cleanUrl;
    if (cleanUrl.startsWith('/uploads/')) return cleanUrl;
    return `/uploads/${cleanUrl.replace(/^\//, '')}`;
  };

  const playAudio = (msg: Message, conversation?: Conversation, allMessages: Message[] = []) => {
    if (!audioRef.current) return;
    const url = getAudioUrl(msg.conteudo || '', msg.id);
    if (!url) return;

    if (allMessages && allMessages.length > 0) {
      currentMessagesRef.current = allMessages;
    }
    if (conversation) {
      currentConvRef.current = conversation;
    }

    const senderName = msg.remetente === 'cliente'
      ? (conversation?.contact?.nome || 'Cliente')
      : (msg.agent_name || 'Atendente');
    const senderAvatar = msg.remetente === 'cliente' ? conversation?.contact?.foto_perfil_url : undefined;

    const currentSpeed = speedRef.current || 1;
    const audio = audioRef.current;

    audio.src = url;
    audio.playbackRate = currentSpeed;

    const startState: ActiveAudioState = {
      msgId: Number(msg.id),
      url,
      senderName,
      senderAvatar,
      conversationId: msg.conversation_id || conversation?.id || 0,
      duration: audio.duration || 0,
      currentTime: 0,
      isPlaying: true,
      speed: currentSpeed
    };
    activeAudioRef.current = startState;
    setActiveAudio(startState);

    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.warn('[AudioContext] play() interrupted or waiting for canplay:', err);
        const onCanPlay = () => {
          audio.playbackRate = speedRef.current || 1;
          audio.play().catch(e => console.error('[AudioContext] play() failed after canplay:', e));
        };
        audio.addEventListener('canplay', onCanPlay, { once: true });
      });
    }
  };

  playAudioRef.current = playAudio;

  const pauseAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      setActiveAudio(prev => prev ? { ...prev, isPlaying: false } : null);
    }
  };

  const resumeAudio = () => {
    if (audioRef.current && activeAudio) {
      audioRef.current.playbackRate = speedRef.current || 1;
      audioRef.current.play().then(() => {
        setActiveAudio(prev => prev ? { ...prev, isPlaying: true } : null);
      }).catch(err => console.error('Error resuming audio:', err));
    }
  };

  const toggleAudio = (msg: Message, conversation?: Conversation, allMessages: Message[] = []) => {
    if (activeAudio && Number(activeAudio.msgId) === Number(msg.id)) {
      if (activeAudio.isPlaying) {
        pauseAudio();
      } else {
        resumeAudio();
      }
    } else {
      playAudio(msg, conversation, allMessages);
    }
  };

  const seekAudio = (time: number) => {
    if (audioRef.current && activeAudio) {
      audioRef.current.currentTime = time;
      setActiveAudio(prev => prev ? { ...prev, currentTime: time } : null);
    }
  };

  const stopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setActiveAudio(null);
    activeAudioRef.current = null;
  };

  return (
    <AudioContext.Provider value={{
      activeAudio,
      speed,
      playAudio,
      pauseAudio,
      resumeAudio,
      toggleAudio,
      seekAudio,
      setSpeed,
      cycleSpeed,
      stopAudio
    }}>
      {children}
    </AudioContext.Provider>
  );
};

export const useAudio = () => {
  const context = useContext(AudioContext);
  if (!context) {
    throw new Error('useAudio must be used within an AudioProvider');
  }
  return context;
};
