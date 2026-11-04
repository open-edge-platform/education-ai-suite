import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import { parseServerTimestamp } from '../../utils/serverTime';

interface ResourceMetrics {
  cpu_utilization: any[];
  gpu_utilization: any[];
  npu_utilization: any[]; 
  memory: any[];
  power: any[];
}

interface ResourceState {
  metrics: ResourceMetrics;
  lastUpdated: number | null;
  sessionStartAt: number | null;
  pendingSessionStartMs: number | null;
}

const initialState: ResourceState = {
  metrics: {
    cpu_utilization: [],
    gpu_utilization: [],
    npu_utilization: [], 
    memory: [],
    power: []
  },
  lastUpdated: null,
  sessionStartAt: null,
  pendingSessionStartMs: null
};

// Safety cap so an indefinitely long tab session can't grow the buffer
// without bound; the 45-min auto-pause (RESOURCE_METRIC_DURATION_MS) already
// keeps real usage well under this at ~1 sample/sec.
const MAX_POINTS = 3600;

function mergeSeries(existing: any[], incoming: any[] | undefined, sessionStartAt: number | null): any[] {
  if (!incoming || incoming.length === 0) return existing;
  const lastTs = existing.length > 0
    ? parseServerTimestamp(existing[existing.length - 1][0]).getTime()
    : (sessionStartAt ?? -Infinity);
  const appended = incoming.filter((row) => parseServerTimestamp(row[0]).getTime() > lastTs);
  if (appended.length === 0) return existing;
  const merged = existing.concat(appended);
  return merged.length > MAX_POINTS ? merged.slice(merged.length - MAX_POINTS) : merged;
}

// Newest sample timestamp (server clock, epoch ms) across all series, i.e. the
// collector's "now" as of this response; null if every series is empty.
function newestServerTime(metrics: ResourceMetrics): number | null {
  let newest: number | null = null;
  (Object.keys(metrics) as (keyof ResourceMetrics)[]).forEach((key) => {
    const series = metrics[key];
    if (!series || series.length === 0) return;
    const ts = parseServerTimestamp(series[series.length - 1][0]).getTime();
    if (!Number.isNaN(ts) && (newest === null || ts > newest)) newest = ts;
  });
  return newest;
}

const resourceSlice = createSlice({
  name: 'resource',
  initialState,
  reducers: {
    setMetrics: (state, action: PayloadAction<ResourceMetrics>) => {
      const incoming = action.payload;
      if (state.pendingSessionStartMs != null) {
        const serverNow = newestServerTime(incoming);
        if (serverNow !== null) {
          state.sessionStartAt = serverNow - (Date.now() - state.pendingSessionStartMs);
          state.pendingSessionStartMs = null;
        }
      }
      (Object.keys(state.metrics) as (keyof ResourceMetrics)[]).forEach((key) => {
        state.metrics[key] = mergeSeries(state.metrics[key], incoming[key], state.sessionStartAt);
      });
      state.lastUpdated = Date.now();
    },
    // Marks when this tab's first session started; a no-op on later
    // sessions so the accumulated chart isn't reset until a page refresh.
    markSessionStart: (state) => {
      if (state.sessionStartAt == null && state.pendingSessionStartMs == null) {
        state.pendingSessionStartMs = Date.now();
      }
    },
    clearMetrics: (state) => {
      state.metrics = initialState.metrics;
      state.lastUpdated = null;
      state.sessionStartAt = null;
      state.pendingSessionStartMs = null;
    }
  }
});

export const { setMetrics, markSessionStart, clearMetrics } = resourceSlice.actions;
export default resourceSlice.reducer;