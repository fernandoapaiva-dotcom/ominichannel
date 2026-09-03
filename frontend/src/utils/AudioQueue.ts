export interface AudioQueueItem {
  id: number;
  url: string;
  senderName?: string;
  senderAvatar?: string;
  conversationId?: number;
  message?: any;
  audioElement?: HTMLAudioElement;
}

/**
 * AudioQueue
 * Reproduz áudios em sequência (FIFO): o próximo só começa
 * quando o atual termina. Áudios que chegam durante a
 * reprodução entram no fim da fila, sem interromper o atual.
 */
export class AudioQueue {
  public queue: AudioQueueItem[] = [];
  public isPlaying: boolean = false;
  public currentItem: AudioQueueItem | null = null;
  public currentAudio: HTMLAudioElement | null = null;
  public speed: number = 1;

  public onStart: ((item: AudioQueueItem) => void) | null = null;
  public onTimeUpdate: ((item: AudioQueueItem, currentTime: number, duration: number) => void) | null = null;
  public onEnd: ((item: AudioQueueItem) => void) | null = null;
  public onIdle: (() => void) | null = null;

  private pollInterval: any = null;
  private hasTriggeredNext: boolean = false;

  constructor() {
    try {
      const saved = Number(localStorage.getItem('omini_audio_speed'));
      this.speed = [1, 1.5, 2].includes(saved) ? saved : 1;
    } catch {
      this.speed = 1;
    }
  }

  setSpeed(speed: number) {
    this.speed = speed;
    try {
      localStorage.setItem('omini_audio_speed', String(speed));
    } catch {}
    if (this.currentAudio) {
      this.currentAudio.playbackRate = speed;
    }
  }

  /** Adiciona um áudio (ou lista) à fila. Só inicia a reprodução se nada estiver tocando. */
  add(item: AudioQueueItem | AudioQueueItem[], clearPrevious: boolean = false) {
    if (clearPrevious) {
      this.clear();
    }
    const items = Array.isArray(item) ? item : [item];
    this.queue.push(...items);

    if (!this.isPlaying) {
      this._playNext();
    }
  }

  pause() {
    if (this.currentAudio) {
      this.currentAudio.pause();
    }
  }

  resume() {
    if (this.currentAudio) {
      this.currentAudio.playbackRate = this.speed;
      this.currentAudio.play().catch(() => {});
    }
  }

  seek(time: number) {
    if (this.currentAudio) {
      this.currentAudio.currentTime = time;
    }
  }

  /** Esvazia a fila e para o áudio atual (ex: usuário trocou de conversa). */
  clear() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.queue = [];
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.onended = null;
      this.currentAudio.ontimeupdate = null;
      this.currentAudio.onerror = null;
      this.currentAudio = null;
    }
    this.currentItem = null;
    this.isPlaying = false;
    this.hasTriggeredNext = false;
  }

  private _advance(item: AudioQueueItem) {
    if (this.hasTriggeredNext) return;
    this.hasTriggeredNext = true;

    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }

    if (this.onEnd) this.onEnd(item);
    this._playNext();
  }

  private _playNext() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }

    if (this.queue.length === 0) {
      this.isPlaying = false;
      this.currentAudio = null;
      this.currentItem = null;
      if (this.onIdle) this.onIdle();
      return;
    }

    this.isPlaying = true;
    this.hasTriggeredNext = false;
    const item = this.queue.shift()!;
    this.currentItem = item;

    // usa o elemento já "destravado" no clique, se existir
    const audio = item.audioElement ?? new Audio(item.url);
    this.currentAudio = audio;
    audio.playbackRate = this.speed;

    if (this.onStart) this.onStart(item);

    audio.ontimeupdate = () => {
      if (this.onTimeUpdate) {
        this.onTimeUpdate(item, audio.currentTime, audio.duration || 0);
      }
    };

    audio.onended = () => {
      this._advance(item);
    };

    audio.onerror = (e) => {
      console.warn("Falha ao tocar áudio, pulando:", item, e);
      this._advance(item);
    };

    this.pollInterval = setInterval(() => {
      if (audio && !audio.paused && audio.duration > 0 && isFinite(audio.duration)) {
        if (audio.currentTime >= audio.duration - 0.12) {
          this._advance(item);
        }
      }
    }, 60);

    audio.play().catch((err) => {
      console.warn("play() bloqueado mesmo pré-criado:", err, item.id);
    });
  }
}

export default AudioQueue;
