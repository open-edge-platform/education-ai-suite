import mockTranscript from '../mock-data/mock_transcript.json';
import mockSummary from '../mock-data/mock_summary.json';
import configMetrics from '../mock-data/configuration_metrics.json';
import resourceMetrics from '../mock-data/metrics.json';
import {
  simulateTranscriptStream,
  simulateSummaryStream,
} from './streamSimulator';
import type { StreamEvent, StreamOptions } from './streamSimulator';

export type Settings = {
  projectName: string;
  projectLocation: string;
  microphone: string;
};

export type SessionMode = 'record' | 'upload';

export type StartSessionRequest = {
  projectName: string;
  projectLocation: string;
  microphone: string;
  mode: SessionMode;
};

export type StartSessionResponse = { sessionId: string };

const env = (import.meta as any).env ?? {};
const USE_MOCKS: boolean = String(env.VITE_USE_MOCKS ?? 'true') !== 'false';
const BASE_URL: string = env.VITE_API_BASE_URL || '/api';

const LS_SETTINGS = 'smart-classroom:settings';
const LS_LAST_SESSION = 'smart-classroom:lastSession';

function sleep(ms: number) { return new Promise((r) => setTimeout(r, ms)); }
function newSessionId() { return 'sess_' + Math.random().toString(36).slice(2, 10); }

/* Settings */
export async function saveSettings(settings: Settings): Promise<Settings> {
  if (USE_MOCKS) {
    await sleep(150);
    localStorage.setItem(LS_SETTINGS, JSON.stringify(settings));
    return settings;
  }
  const res = await fetch(`${BASE_URL}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error('Failed to save settings');
  return (await res.json()) as Settings;
}

export async function getSettings(): Promise<Settings | null> {
  if (USE_MOCKS) {
    const raw = localStorage.getItem(LS_SETTINGS);
    return raw ? (JSON.parse(raw) as Settings) : null;
  }
  const res = await fetch(`${BASE_URL}/settings`);
  if (!res.ok) return null;
  return (await res.json()) as Settings;
}

/* Session start/upload (kept for later backend integration) */
export async function startSession(req: StartSessionRequest): Promise<StartSessionResponse> {
  if (USE_MOCKS) {
    await sleep(100);
    const sessionId = newSessionId();
    localStorage.setItem(LS_LAST_SESSION, JSON.stringify({ sessionId, ...req, ts: Date.now() }));
    return { sessionId };
  }
  const res = await fetch(`${BASE_URL}/session/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error('Failed to start session');
  return (await res.json()) as StartSessionResponse;
}

export async function uploadAudio(
  file: File,
  meta: Omit<StartSessionRequest, 'mode'>
): Promise<StartSessionResponse> {
  if (USE_MOCKS) {
    await sleep(200);
    const sessionId = newSessionId();
    localStorage.setItem(
      LS_LAST_SESSION,
      JSON.stringify({ sessionId, ...meta, mode: 'upload', fileName: file.name, ts: Date.now() })
    );
    return { sessionId };
  }
  const form = new FormData();
  form.append('file', file);
  form.append('projectName', meta.projectName);
  form.append('projectLocation', meta.projectLocation);
  form.append('microphone', meta.microphone);
  const res = await fetch(`${BASE_URL}/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Failed to upload audio');
  return (await res.json()) as StartSessionResponse;
}

/* Streaming adapters (mock) */
export function streamTranscript(_sessionId: string, opts: StreamOptions = {}): AsyncGenerator<StreamEvent> {
  const chunks: string[] = Array.isArray((mockTranscript as any).transcript)
    ? ((mockTranscript as any).transcript as string[])
    : ['Transcription mock is missing.\n'];
  return simulateTranscriptStream(chunks, opts);
}

export function streamSummary(_sessionId: string, opts: StreamOptions = {}): AsyncGenerator<StreamEvent> {
  const text: string = String((mockSummary as any)?.summary ?? 'Summary mock is missing.');
  return simulateSummaryStream(text, opts);
}

/* Metrics/config (mock) */
export async function getConfigurationMetrics(): Promise<any> {
  if (USE_MOCKS) return configMetrics;
  const res = await fetch(`${BASE_URL}/configuration-metrics`);
  if (!res.ok) throw new Error('Failed to fetch configuration metrics');
  return res.json();
}

export async function getResourceMetrics(): Promise<any> {
  if (USE_MOCKS) return resourceMetrics;
  const res = await fetch(`${BASE_URL}/metrics`);
  if (!res.ok) throw new Error('Failed to fetch metrics');
  return res.json();
}

/*
Backend contract (later):
- POST /settings, GET /settings
- POST /session/start, POST /upload
- STREAM /session/:id/transcript -> {type:'transcript'|'done'}
- STREAM /session/:id/summary   -> {type:'summary_token'|'done'}
- GET /configuration-metrics, GET /metrics
*/