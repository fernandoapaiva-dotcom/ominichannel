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

  const triggerNextAudio = useCallback(() => {
    const current = activeAudioRef.current;
    const rawMsgs = currentMessagesRef.current;
    console.log('[AudioContext] triggerNextAudio called. Current:', current?.msgId, 'Msgs count:', rawMsgs?.length);

    if (!current || !rawMsgs || rawMsgs.length === 0) {
      setActiveAudio(null);
      activeAudioRef.current = null;
      return;
    }

    const currentIndex = rawMsgs.findIndex(m => Number(m.id) === Number(current.msgId));
    console.log('[AudioContext] currentIndex:', currentIndex);

    let nextAudioMsg: Message | undefined = undefined;
    if (currentIndex !== -1) {
      nextAudioMsg = rawMsgs.slice(currentIndex + 1).find(m => {
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

    console.log('[AudioContext] Next audio found:', nextAudioMsg?.id);

    if (nextAudioMsg && playAudioRef.current) {
      playAudioRef.current(nextAudioMsg, currentConvRef.current, rawMsgs);
      return;
    }

    // Finished sequential audios
    setActiveAudio(null);
    activeAudioRef.current = null;
  }, []);

  const playAudioTrack = useCallback((msg: Message, conversation?: Conversation, allMessages?: Message[]) => {
    if (!audioRef.current) return;
    const url = getAudioUrl(msg.conteudo || '', msg.id);
    if (!url) return;

    if (allMessages && allMessages.length > 0) {
      currentMessagesRef.current = allMessages;
    }
    if (conversation) {
      currentConvRef.current = conversation;
    }

    const audio = audioRef.current;

    // 1. Detach onended temporarily so changing source doesn't fire spurious ended events
    audio.onended = null;
    audio.pause();
    try {
      audio.currentTime = 0;
    } catch {}

    const senderName = msg.remetente === 'cliente'
      ? (conversation?.contact?.nome || 'Cliente')
      : (msg.agent_name || 'Atendente');
    const senderAvatar = msg.remetente === 'cliente' ? conversation?.contact?.foto_perfil_url : undefined;
    const currentSpeed = speedRef.current || 1;

    // 2. Set new audio source and playback speed
    audio.src = url;
    audio.playbackRate = currentSpeed;

    const startState: ActiveAudioState = {
      msgId: Number(msg.id),
      url,
      senderName,
      senderAvatar,
      conversationId: msg.conversation_id || conversation?.id || 0,
      duration: 0,
      currentTime: 0,
      isPlaying: true,
      speed: currentSpeed
    };
    activeAudioRef.current = startState;
    setActiveAudio(startState);

    // 3. Attach onended handler strictly when audio actually starts playing
    const attachEndedHandler = () => {
      audio.onended = () => {
        console.log('[AudioContext] Track ended naturally for msgId:', msg.id);
        triggerNextAudio();
      };
    };

    audio.onplaying = () => {
      attachEndedHandler();
    };

    // 4. Play audio immediately with fallback
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.warn('[AudioContext] Play interrupted, playing on canplay:', err);
        const onCanPlay = () => {
          audio.playbackRate = speedRef.current || 1;
          audio.play()
            .then(attachEndedHandler)
            .catch(e => console.error('[AudioContext] play() failed after canplay:', e));
        };
        audio.addEventListener('canplay', onCanPlay, { once: true });
      });
    }
  }, [triggerNextAudio]);

  playAudioRef.current = playAudioTrack;

  useEffect(() => {
    const audio = new Audio();
    audioRef.current = audio;

    audio.ontimeupdate = () => {
      setActiveAudio(prev => {
        if (!prev) return null;
        return {
          ...prev,
          currentTime: audio.currentTime,
          duration: audio.duration || prev.duration || 0
        };
      });
    };

    audio.onloadedmetadata = () => {
      setActiveAudio(prev => {
        if (!prev) return null;
        return {
          ...prev,
          duration: audio.duration || prev.duration || 0
        };
      });
    };

    return () => {
      audio.ontimeupdate = null;
      audio.onloadedmetadata = null;
      audio.onplaying = null;
      audio.onended = null;
      audio.pause();
      audio.src = '';
    };
  }, []);

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
      playAudioTrack(msg, conversation, allMessages);
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
      playAudio: playAudioTrack,
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
