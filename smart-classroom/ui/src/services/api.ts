import { simulateTranscriptStream, simulateSummaryStream } from './streamSimulator';
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
const BASE_URL: string = env.VITE_API_BASE_URL || '/api';

export async function saveSettings(settings: Settings): Promise<Settings> {
  const res = await fetch(`${BASE_URL}/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error('Failed to save settings');
  return (await res.json()) as Settings;
}

export async function getSettings(): Promise<Settings | null> {
  const res = await fetch(`${BASE_URL}/settings`);
  if (!res.ok) return null;
  return (await res.json()) as Settings;
}

export async function startSession(req: StartSessionRequest): Promise<StartSessionResponse> {
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
  const form = new FormData();
  form.append('file', file);
  form.append('projectName', meta.projectName);
  form.append('projectLocation', meta.projectLocation);
  form.append('microphone', meta.microphone);
  const res = await fetch(`${BASE_URL}/upload`, { method: 'POST', body: form });
  if (!res.ok) throw new Error('Failed to upload audio');
  return (await res.json()) as StartSessionResponse;
}

// Streaming transcript from backend (implement according to your backend API)
// For local/manual testing, you can use simulateTranscriptStream with sample data
export async function* streamTranscript(sessionId: string, opts: StreamOptions = {}): AsyncGenerator<StreamEvent> {
  // TODO: Integrate with backend streaming API
  // Example usage for local testing:
  // yield* simulateTranscriptStream(['Sample transcript line 1.', 'Sample transcript line 2.'], opts);
  throw new Error('streamTranscript not implemented. Integrate with backend streaming API.');
}

// Streaming summary from backend (implement according to your backend API)
// For local/manual testing, you can use simulateSummaryStream with sample data
export async function* streamSummary(sessionId: string, opts: StreamOptions = {}): AsyncGenerator<StreamEvent> {
  // TODO: Integrate with backend streaming API
  // Example usage for local testing:
  // yield* simulateSummaryStream('Sample summary text.', opts);
  throw new Error('streamSummary not implemented. Integrate with backend streaming API.');
}

export async function getConfigurationMetrics(): Promise<any> {
  const res = await fetch(`${BASE_URL}/configuration-metrics`);
  if (!res.ok) throw new Error('Failed to fetch configuration metrics');
  return res.json();
}


export const getResourceMetrics = async (sessionId?: string) => {
  const headers: HeadersInit = sessionId ? { "x-session-id": sessionId } : {};
  const response = await fetch(`${BASE_URL}/metrics`, {
    method: "GET",
    headers,
  });
  if (!response.ok) {
    throw new Error("Failed to fetch metrics");
  }
  const data = await response.json();
  const trimData = (arr: any[]) => (arr.length > 10 ? arr.slice(-10) : arr);
  return {
    cpu_utilization: trimData(data.cpu_utilization ?? []),
    gpu_utilization: trimData(data.gpu_utilization ?? []),
    memory: trimData(data.memory ?? []),
    power: trimData(data.power ?? []),
  };
};
