import React, { useState, useRef, useEffect } from 'react';
import { Mic, Trash2, Send, Pause, Play, Square } from 'lucide-react';
import { apiUpload } from '../services/api';

interface AudioRecorderProps {
  onSendAudio: (audioUrl: string) => void;
  disabled?: boolean;
}

export const AudioRecorder: React.FC<AudioRecorderProps> = ({ onSendAudio, disabled }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [isUploading, setIsUploading] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];

      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
        mimeType = 'audio/ogg;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
        mimeType = 'audio/mp4';
      }

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.start(100);
      setIsRecording(true);
      setRecordingTime(0);

      timerRef.current = setInterval(() => {
        setRecordingTime(prev => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('Error accessing microphone:', err);
      alert('Não foi possível acessar o microfone. Verifique as permissões no seu navegador.');
    }
  };

  const stopRecordingAndSend = () => {
    if (!mediaRecorderRef.current || !isRecording) return;

    if (timerRef.current) clearInterval(timerRef.current);
    setIsRecording(false);
    setIsUploading(true);

    const recorder = mediaRecorderRef.current;
    recorder.onstop = async () => {
      // Stop all microphone tracks
      recorder.stream.getTracks().forEach(track => track.stop());

      if (audioChunksRef.current.length === 0) {
        setIsUploading(false);
        setRecordingTime(0);
        return;
      }

      const mimeType = recorder.mimeType || 'audio/webm';
      const ext = mimeType.includes('ogg') ? 'ogg' : mimeType.includes('mp4') ? 'mp4' : 'webm';
      const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });

      const file = new File([audioBlob], `voice_note_${Date.now()}.${ext}`, { type: mimeType });

      try {
        const formData = new FormData();
        formData.append('file', file);
        const res = await apiUpload('/conversations/upload', formData);
        if (res && res.url) {
          onSendAudio(res.url);
        }
      } catch (err) {
        console.error('Error uploading voice note:', err);
      } finally {
        setIsUploading(false);
        setRecordingTime(0);
      }
    };

    try {
      recorder.requestData();
    } catch (e) {
      console.warn('requestData warning:', e);
    }
    recorder.stop();
  };

  const cancelRecording = () => {
    if (!mediaRecorderRef.current || !isRecording) return;

    if (timerRef.current) clearInterval(timerRef.current);
    const recorder = mediaRecorderRef.current;
    recorder.onstop = () => {
      recorder.stream.getTracks().forEach(track => track.stop());
    };
    recorder.stop();

    setIsRecording(false);
    setRecordingTime(0);
    audioChunksRef.current = [];
  };

  if (isUploading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px', fontSize: '13px', color: 'var(--text-muted)' }}>
        <span className="spinner" style={{ width: '14px', height: '14px', border: '2px solid #00a884', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
        <span>Enviando áudio...</span>
      </div>
    );
  }

  if (isRecording) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '6px 14px',
          backgroundColor: '#111b21',
          borderRadius: '24px',
          border: '1px solid rgba(0, 168, 132, 0.4)',
          width: '100%',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
          animation: 'fadeIn 0.2s ease'
        }}
      >
        {/* Pulsing Red Dot */}
        <div style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#ef4444', animation: 'pulse 1s infinite alternate' }} />

        {/* Timer */}
        <span style={{ fontSize: '13px', fontWeight: 'bold', color: '#e9edef', fontFamily: 'monospace' }}>
          {formatTime(recordingTime)}
        </span>

        {/* Waveform Visualizer simulation */}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '2px', height: '16px' }}>
          {[12, 24, 16, 28, 14, 22, 30, 18, 10, 26, 14, 20, 28, 12, 24].map((h, i) => (
            <div
              key={i}
              style={{
                flex: 1,
                backgroundColor: '#00a884',
                height: `${h}px`,
                borderRadius: '1px',
                animation: `wavePulse 0.5s ease-in-out ${i * 0.05}s infinite alternate`
              }}
            />
          ))}
        </div>

        {/* Cancel Button */}
        <button
          type="button"
          onClick={cancelRecording}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#ef4444',
            cursor: 'pointer',
            padding: '6px',
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title="Cancelar gravação"
        >
          <Trash2 size={18} />
        </button>

        {/* Send Button */}
        <button
          type="button"
          onClick={stopRecordingAndSend}
          style={{
            width: '34px',
            height: '34px',
            borderRadius: '50%',
            backgroundColor: '#00a884',
            border: 'none',
            color: '#ffffff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: '0 2px 6px rgba(0,0,0,0.3)'
          }}
          title="Enviar áudio gravado"
        >
          <Send size={16} />
        </button>

        <style>{`
          @keyframes wavePulse {
            0% { transform: scaleY(0.4); }
            100% { transform: scaleY(1.2); }
          }
          @keyframes pulse {
            0% { opacity: 0.3; transform: scale(0.9); }
            100% { opacity: 1; transform: scale(1.1); }
          }
        `}</style>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={startRecording}
      disabled={disabled}
      className="chat-mic-btn"
      style={{
        background: 'rgba(0, 230, 153, 0.12)',
        border: '1px solid rgba(0, 230, 153, 0.3)',
        color: '#00e699',
        cursor: disabled ? 'not-allowed' : 'pointer',
        width: '42px',
        height: '42px',
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        transition: 'all 0.15s ease'
      }}
      onMouseEnter={(e) => {
        if (!disabled) {
          e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.25)';
          e.currentTarget.style.transform = 'scale(1.05)';
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled) {
          e.currentTarget.style.backgroundColor = 'rgba(0, 230, 153, 0.12)';
          e.currentTarget.style.transform = 'scale(1)';
        }
      }}
      title="Gravar áudio / Mensagem de voz (Clique para gravar)"
    >
      <Mic size={20} />
    </button>
  );
};
