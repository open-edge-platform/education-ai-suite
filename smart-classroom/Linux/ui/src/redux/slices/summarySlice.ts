import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

export interface SummaryProgress {
  stage: string;
  chunk: number;
  chunks: number;
}

interface SummaryState {
  streamingText: string;
  finalText: string | null;
  status: 'idle' | 'streaming' | 'done';
  progress: SummaryProgress | null;
}
const initialState: SummaryState = {
  streamingText: '',
  finalText: null,
  status: 'idle',
  progress: null,
};

const summarySlice = createSlice({
  name: 'summary',
  initialState,
  reducers: {
    resetSummary: () => initialState, // <-- resets status to 'idle'
    startSummary(state) {
      state.status = 'streaming';
      state.streamingText = '';
      state.finalText = null;
      state.progress = null;
    },
    appendSummary(state, action: PayloadAction<string>) {
      state.streamingText += action.payload;
      // Tokens are the summary itself, so per-chunk progress is over.
      state.progress = null;
    },
    finishSummary(state) {
      state.finalText = state.streamingText;
      state.status = 'done';
      state.progress = null;
    },
    setSummaryProgress(state, action: PayloadAction<SummaryProgress>) {
      state.progress = action.payload;
    },
  },
});

export const {
  resetSummary,
  startSummary,
  appendSummary,
  finishSummary,
  setSummaryProgress,
} = summarySlice.actions;
export default summarySlice.reducer;
