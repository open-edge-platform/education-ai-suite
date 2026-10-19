// Browser live-microphone capture -> audio-analyzer realtime transcription.
//
// Captures mic audio via WebAudio, downsamples to 16 kHz mono PCM16, and streams
// it as base64 frames over the OpenAI Realtime-compatible WebSocket exposed by
// the backend at /v1/realtime (reverse-proxied to the audio-analyzer service).
// Server-side VAD segments the stream into utterances; this surfaces the
// incremental (delta) and finalized (completed) transcripts via callbacks.

const env = (import.meta as any).env ?? {};
const API_BASE_URL: string = env.VITE_API_BASE_URL || '';

const TARGET_SAMPLE_RATE = 16000;

export interface RealtimeMicCallbacks {
  /** Incremental transcript text for the in-progress utterance. */
  onDelta?: (text: string) => void;
  /** Finalized transcript text for a completed utterance. */
  onCompleted?: (text: string) => void;
  /** Fired when the server marks speech start/stop (VAD). */
  onSpeechState?: (speaking: boolean) => void;
  onError?: (error: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

export interface RealtimeMicOptions extends RealtimeMicCallbacks {
  /** Browser microphone deviceId (from enumerateDevices). Empty = default mic. */
  deviceId?: string;
  /** Microphone label (as stored by the settings UI); resolved to a deviceId. */
  microphone?: string;
  /** Language hint forwarded to the service (e.g. "en", "zh"). */
  language?: string;
  /** Session id to correlate with the rest of the pipeline. */
  sessionId?: string;
}

function realtimeWsUrl(params: Record<string, string>): string {
  // Same-origin by default so the backend WS proxy handles it; honor an
  // explicit API base (dev) when set.
  let base = API_BASE_URL;
  if (!base) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    base = `${proto}//${window.location.host}`;
  } else {
    base = base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  }
  const qs = new URLSearchParams(params).toString();
  return `${base.replace(/\/$/, '')}/v1/realtime${qs ? `?${qs}` : ''}`;
}

function floatTo16BitPCM(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function downsample(buffer: Float32Array, inRate: number, outRate: number): Float32Array {
  if (outRate >= inRate) return buffer;
  const ratio = inRate / outRate;
  const outLength = Math.floor(buffer.length / ratio);
  const result = new Float32Array(outLength);
  let offset = 0;
  for (let i = 0; i < outLength; i++) {
    const next = Math.floor((i + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let j = Math.floor(i * ratio); j < next && j < buffer.length; j++) {
      sum += buffer[j];
      count++;
    }
    result[i] = count > 0 ? sum / count : 0;
    offset = next;
  }
  return result;
}

function int16ToBase64(int16: Int16Array): string {
  const bytes = new Uint8Array(int16.buffer);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export class RealtimeMicSession {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private opts: RealtimeMicOptions;
  private stopped = false;

  constructor(opts: RealtimeMicOptions = {}) {
    this.opts = opts;
  }

  async start(): Promise<void> {
    this.stopped = false;

    // Resolve a stored microphone label to a concrete deviceId when needed.
    let deviceId = this.opts.deviceId;
    if (!deviceId && this.opts.microphone) {
      const mics = await listBrowserMicrophones();
      const match = mics.find((m) => m.label === this.opts.microphone);
      deviceId = match?.deviceId;
    }

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: deviceId
        ? { deviceId: { exact: deviceId }, channelCount: 1 }
        : { channelCount: 1 },
    });

    const params: Record<string, string> = {};
    if (this.opts.language) params.language = this.opts.language;
    if (this.opts.sessionId) params.session_id = this.opts.sessionId;
    this.ws = new WebSocket(realtimeWsUrl(params));

    this.ws.onopen = () => {
      this.ws?.send(
        JSON.stringify({
          type: 'session.update',
          session: { input_audio_format: 'pcm16', sample_rate: TARGET_SAMPLE_RATE },
        }),
      );
      this.opts.onOpen?.();
    };
    this.ws.onmessage = (ev) => this.handleServerEvent(ev.data);
    this.ws.onerror = () => this.opts.onError?.('WebSocket error');
    this.ws.onclose = () => this.opts.onClose?.();

    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    // ScriptProcessor is deprecated but universally supported and adequate for
    // 16 kHz speech; an AudioWorklet could replace it later without protocol change.
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.source.connect(this.processor);
    this.processor.connect(this.ctx.destination);

    const inRate = this.ctx.sampleRate;
    this.processor.onaudioprocess = (e) => {
      if (this.stopped || this.ws?.readyState !== WebSocket.OPEN) return;
      const input = e.inputBuffer.getChannelData(0);
      const down = downsample(input, inRate, TARGET_SAMPLE_RATE);
      const pcm16 = floatTo16BitPCM(down);
      this.ws.send(
        JSON.stringify({ type: 'input_audio_buffer.append', audio: int16ToBase64(pcm16) }),
      );
    };
  }

  private handleServerEvent(raw: string): void {
    let msg: any;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    switch (msg.type) {
      case 'conversation.item.input_audio_transcription.delta':
        if (msg.delta) this.opts.onDelta?.(msg.delta);
        break;
      case 'conversation.item.input_audio_transcription.completed':
        if (msg.transcript) this.opts.onCompleted?.(msg.transcript);
        break;
      case 'input_audio_buffer.speech_started':
        this.opts.onSpeechState?.(true);
        break;
      case 'input_audio_buffer.speech_stopped':
        this.opts.onSpeechState?.(false);
        break;
      case 'error':
        this.opts.onError?.(msg.error?.message || 'realtime error');
        break;
      default:
        break;
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    try {
      if (this.ws?.readyState === WebSocket.OPEN) {
        // Flush the final utterance before closing.
        this.ws.send(JSON.stringify({ type: 'input_audio_buffer.commit' }));
      }
    } catch {
      /* ignore */
    }
    this.processor?.disconnect();
    this.source?.disconnect();
    if (this.ctx && this.ctx.state !== 'closed') await this.ctx.close();
    this.stream?.getTracks().forEach((t) => t.stop());
    // Give the server a moment to emit the final completed event, then close.
    setTimeout(() => {
      if (this.ws && this.ws.readyState <= WebSocket.OPEN) this.ws.close();
    }, 500);
    this.processor = null;
    this.source = null;
    this.ctx = null;
    this.stream = null;
  }
}

/** Enumerate browser microphones. Requests permission first so labels populate. */
export async function listBrowserMicrophones(): Promise<MediaDeviceInfo[]> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
  } catch {
    // Permission denied: enumerateDevices still returns entries, just without labels.
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((d) => d.kind === 'audioinput');
}
