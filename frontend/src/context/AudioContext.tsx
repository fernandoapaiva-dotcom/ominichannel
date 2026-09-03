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
  const isTransitioningRef = useRef<boolean>(false);

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
    if (isTransitioningRef.current) return;
    const current = activeAudioRef.current;
    const rawMsgs = currentMessagesRef.current;
    if (!current || !rawMsgs || rawMsgs.length === 0) {
      setActiveAudio(null);
      activeAudioRef.current = null;
      return;
    }

    isTransitioningRef.current = true;

    // Guarantee chronological ordering
    const sortedMsgs = [...rawMsgs].sort((a, b) => {
      const tA = new Date(a.timestamp || 0).getTime();
      const tB = new Date(b.timestamp || 0).getTime();
      if (tA !== tB) return tA - tB;
      return Number(a.id || 0) - Number(b.id || 0);
    });

    const currentIndex = sortedMsgs.findIndex(m => Number(m.id) === Number(current.msgId));
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

    if (nextAudioMsg && playAudioRef.current) {
      // Synchronously switch to next audio - preserving autoplay permission in the browser
      playAudioRef.current(nextAudioMsg, currentConvRef.current, sortedMsgs);
      setTimeout(() => {
        isTransitioningRef.current = false;
      }, 400);
      return;
    }

    // No subsequent audio
    setActiveAudio(null);
    activeAudioRef.current = null;
    isTransitioningRef.current = false;
  }, []);

  useEffect(() => {
    const audio = new Audio();
    audioRef.current = audio;

    const handleTimeUpdate = () => {
      if (!audio) return;
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

      // Guard for .ogg audio where browser might end slightly before firing 'ended'
      if (audio.duration > 0 && audio.currentTime >= audio.duration - 0.08 && !isTransitioningRef.current) {
        triggerNextAudio();
      }
    };

    const handleLoadedMetadata = () => {
      if (!audio) return;
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

    const handleEnded = () => {
      triggerNextAudio();
    };

    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('ended', handleEnded);

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
      audio.removeEventListener('ended', handleEnded);
      audio.pause();
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

    if (allMessages.length > 0) {
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

    try {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      audioRef.current.src = url;
      audioRef.current.playbackRate = currentSpeed;
      audioRef.current.load();
      audioRef.current.play().then(() => {
        const state: ActiveAudioState = {
          msgId: Number(msg.id),
          url,
          senderName,
          senderAvatar,
          conversationId: msg.conversation_id || conversation?.id || 0,
          duration: audioRef.current?.duration || 0,
          currentTime: 0,
          isPlaying: true,
          speed: currentSpeed
        };
        activeAudioRef.current = state;
        setActiveAudio(state);
      }).catch(err => {
        console.error('Error playing audio:', err);
      });
    } catch (e) {
      console.error('Audio play exception:', e);
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
