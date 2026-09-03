import React, { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { Message, Conversation } from '../types';
import { AudioQueue, AudioQueueItem } from '../utils/AudioQueue';

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
  addToQueue: (item: AudioQueueItem) => void;
}

const AudioContext = createContext<AudioContextType | undefined>(undefined);

export const AudioProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeAudio, setActiveAudio] = useState<ActiveAudioState | null>(null);
  const queueRef = useRef<AudioQueue>(new AudioQueue());
  const queue = queueRef.current;

  const [speed, setSpeedState] = useState<number>(queue.speed);

  // Helper to resolve URL
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

  const isAudioMsg = (m: Message): boolean => {
    const t = String(m.tipo || '').toLowerCase();
    const c = String(m.conteudo || '').toLowerCase();
    return (
      t === 'audio' ||
      t.includes('audio') ||
      c.endsWith('.ogg') ||
      c.endsWith('.mp3') ||
      c.endsWith('.wav') ||
      c.endsWith('.m4a') ||
      (c.includes('/uploads/') && (c.includes('.ogg') || c.includes('.mp3') || c.includes('.wav') || c.includes('.m4a'))) ||
      c.includes('mmg.whatsapp.net')
    );
  };

  useEffect(() => {
    queue.onStart = (item: AudioQueueItem) => {
      console.log('[AudioQueue] onStart:', item.id, 'duration:', item.duration);
      setActiveAudio({
        msgId: item.id,
        url: item.url,
        senderName: item.senderName || 'Áudio',
        senderAvatar: item.senderAvatar,
        conversationId: item.conversationId || 0,
        duration: item.duration || 0,
        currentTime: 0,
        isPlaying: true,
        speed: queue.speed
      });
    };

    queue.onTimeUpdate = (item: AudioQueueItem, currentTime: number, duration: number) => {
      setActiveAudio(prev => {
        if (!prev || prev.msgId !== item.id) return prev;
        const validDuration = (duration && isFinite(duration) && duration > 0) ? duration : prev.duration;
        return {
          ...prev,
          currentTime,
          duration: validDuration
        };
      });
    };

    queue.onEnd = (item: AudioQueueItem) => {
      console.log('[AudioQueue] onEnd:', item.id);
    };

    queue.onIdle = () => {
      console.log('[AudioQueue] onIdle: all queued audios finished.');
      setActiveAudio(null);
    };

    return () => {
      queue.clear();
    };
  }, [queue]);

  const setSpeed = useCallback((newSpeed: number) => {
    queue.setSpeed(newSpeed);
    setSpeedState(newSpeed);
    setActiveAudio(prev => prev ? { ...prev, speed: newSpeed } : null);
  }, [queue]);

  const cycleSpeed = useCallback(() => {
    const speeds = [1, 1.5, 2];
    const nextIdx = (speeds.indexOf(queue.speed) + 1) % speeds.length;
    setSpeed(speeds[nextIdx]);
  }, [queue, setSpeed]);

  const playAudio = useCallback((msg: Message, conversation?: Conversation, allMessages?: Message[]) => {
    const msgs = (allMessages && allMessages.length > 0) ? allMessages : (conversation?.messages || []);
    const currentIndex = msgs.findIndex(m => Number(m.id) === Number(msg.id));

    const remainingMsgs = currentIndex !== -1 ? msgs.slice(currentIndex) : [msg];
    const audiosToQueue: AudioQueueItem[] = remainingMsgs
      .filter(m => isAudioMsg(m))
      .map(m => {
        const url = getAudioUrl(m.conteudo || '', m.id);
        const durationSecs = Number((m as any)?.dados_adicionais?.seconds || (m as any)?.dados_adicionais?.duration || 0);
        return {
          id: Number(m.id),
          url,
          senderName: m.remetente === 'cliente' ? (conversation?.contact?.nome || 'Cliente') : (m.agent_name || 'Atendente'),
          senderAvatar: m.remetente === 'cliente' ? conversation?.contact?.foto_perfil_url : undefined,
          conversationId: m.conversation_id || conversation?.id || 0,
          duration: durationSecs > 0 ? durationSecs : undefined,
          message: m,
        };
      })
      .filter(item => Boolean(item.url));

    queue.add(audiosToQueue, true);
  }, [queue]);

  const addToQueue = useCallback((item: AudioQueueItem) => {
    queue.add(item, false);
  }, [queue]);

  const pauseAudio = useCallback(() => {
    queue.pause();
    setActiveAudio(prev => prev ? { ...prev, isPlaying: false } : null);
  }, [queue]);

  const resumeAudio = useCallback(() => {
    queue.resume();
    setActiveAudio(prev => prev ? { ...prev, isPlaying: true } : null);
  }, [queue]);

  const toggleAudio = useCallback((msg: Message, conversation?: Conversation, allMessages?: Message[]) => {
    if (activeAudio && Number(activeAudio.msgId) === Number(msg.id)) {
      if (activeAudio.isPlaying) {
        pauseAudio();
      } else {
        resumeAudio();
      }
    } else {
      playAudio(msg, conversation, allMessages);
    }
  }, [activeAudio, pauseAudio, resumeAudio, playAudio]);

  const seekAudio = useCallback((time: number) => {
    queue.seek(time);
    setActiveAudio(prev => prev ? { ...prev, currentTime: time } : null);
  }, [queue]);

  const stopAudio = useCallback(() => {
    queue.clear();
    setActiveAudio(null);
  }, [queue]);

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
      stopAudio,
      addToQueue
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
