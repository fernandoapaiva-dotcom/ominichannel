export interface AudioQueueItem {
  id: number;
  url: string;
  senderName?: string;
  senderAvatar?: string;
  conversationId?: number;
  duration?: number;
  message?: any;
}

/**
 * AudioQueue
 * Reproduz áudios em sequência (FIFO) com elemento único persistente,
 * garantindo compatibilidade total com navegadores Mobile (iOS Safari e Android Chrome).
 */
export class AudioQueue {
  public queue: AudioQueueItem[] = [];
  public isPlaying: boolean = false;
  public currentItem: AudioQueueItem | null = null;
  public speed: number = 1;

  // Elemento HTMLAudioElement único e persistente (obrigatório para iOS Safari e Android)
  public audio: HTMLAudioElement;

  public onStart: ((item: AudioQueueItem) => void) | null = null;
  public onTimeUpdate: ((item: AudioQueueItem, currentTime: number, duration: number) => void) | null = null;
  public onEnd: ((item: AudioQueueItem) => void) | null = null;
  public onIdle: (() => void) | null = null;

  private pollInterval: any = null;
  private hasTriggeredNext: boolean = false;

  constructor() {
    this.audio = new Audio();
    this.audio.setAttribute('playsinline', 'true');
    this.audio.setAttribute('webkit-playsinline', 'true');
    this.audio.preload = 'auto';

    try {
      const saved = Number(localStorage.getItem('omini_audio_speed'));
      this.speed = [1, 1.5, 2].includes(saved) ? saved : 1;
    } catch {
      this.speed = 1;
    }
    this.audio.playbackRate = this.speed;

    // Handlers nativos no elemento persistente
    this.audio.onended = () => {
      if (this.currentItem) {
        this._advance(this.currentItem);
      }
    };

    this.audio.onerror = (e) => {
      console.warn('[AudioQueue] Audio error, advancing:', e);
      if (this.currentItem) {
        this._advance(this.currentItem);
      }
    };
  }

  setSpeed(speed: number) {
    this.speed = speed;
    try {
      localStorage.setItem('omini_audio_speed', String(speed));
    } catch {}
    this.audio.playbackRate = speed;
  }

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
    this.audio.pause();
  }

  resume() {
    this.audio.playbackRate = this.speed;
    this.audio.play().catch(() => {});
  }

  seek(time: number) {
    this.audio.currentTime = time;
  }

  clear() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.queue = [];
    this.audio.pause();
    this.audio.currentTime = 0;
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
      this.currentItem = null;
      if (this.onIdle) this.onIdle();
      return;
    }

    this.isPlaying = true;
    this.hasTriggeredNext = false;
    const item = this.queue.shift()!;
    this.currentItem = item;

    // Reutiliza o mesmo elemento de áudio (destravado pelo clique do usuário, funciona 100% no mobile)
    this.audio.src = item.url;
    this.audio.playbackRate = this.speed;
    this.audio.currentTime = 0;

    const initialDuration = (item.duration && isFinite(item.duration) && item.duration > 0) ? item.duration : 0;
    if (this.onStart) this.onStart(item);

    const getSafeDuration = (): number => {
      if (this.audio.duration && isFinite(this.audio.duration) && this.audio.duration > 0) {
        return this.audio.duration;
      }
      return initialDuration;
    };

    // Ticker contínuo a cada 40ms: atualiza a barra de progresso suavemente e detecta o fim
    this.pollInterval = setInterval(() => {
      const dur = getSafeDuration();
      const cur = this.audio.currentTime;

      if (this.onTimeUpdate && !this.audio.paused) {
        this.onTimeUpdate(item, cur, dur);
      }

      if (!this.audio.paused && dur > 0 && cur >= dur - 0.12) {
        this._advance(item);
      }
    }, 40);

    const playPromise = this.audio.play();
    if (playPromise !== undefined) {
      playPromise.catch((err) => {
        console.warn('[AudioQueue] play() waiting for canplay:', err, item.id);
        const onCanPlay = () => {
          this.audio.playbackRate = this.speed;
          this.audio.play().catch(() => this._advance(item));
        };
        this.audio.addEventListener('canplay', onCanPlay, { once: true });
      });
    }
  }
}

export default AudioQueue;
