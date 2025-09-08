import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

export type Tab = 'transcripts' | 'summary';

export interface UIState {
  aiProcessing: boolean;
  summaryEnabled: boolean;
  summaryLoading: boolean;
  activeTab: Tab;
  autoSwitched: boolean;
  sessionId: string | null;
  uploadedAudioPath: string | null;
}

const initialState: UIState = {
  aiProcessing: false,
  summaryEnabled: false,
  summaryLoading: false,
  activeTab: 'transcripts',
  autoSwitched: false,
  sessionId: null,
  uploadedAudioPath: null,
};

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    startProcessing(state) {
      state.aiProcessing = true;
      state.summaryEnabled = false;
      state.summaryLoading = false;
      state.activeTab = 'transcripts';
      state.autoSwitched = false;
      state.sessionId = null;
      state.uploadedAudioPath = null;
    },
    transcriptionComplete(state) {
      console.log('transcriptionComplete reducer called');
      state.summaryEnabled = true;
      state.summaryLoading = true; 
      if (!state.autoSwitched) {
        state.activeTab = 'summary';
        state.autoSwitched = true;
      }
    },
    setUploadedAudioPath(state, action: PayloadAction<string>) {
      state.uploadedAudioPath = action.payload;
    },
    setSessionId(state, action: PayloadAction<string | null>) {
      state.sessionId = action.payload;
    },
    firstSummaryToken(state) {
      state.summaryLoading = false; // hide spinner on first token
    },
    summaryDone(state) {
      state.aiProcessing = false; // all done, re-enable controls
    },
    setActiveTab(state, action: PayloadAction<Tab>) {
      state.activeTab = action.payload;
    },
    resetFlow() {
      return initialState;
    },
  },
});

export const {
  startProcessing,
  transcriptionComplete,
  setUploadedAudioPath,
  setSessionId,
  firstSummaryToken,
  summaryDone,
  setActiveTab,
  resetFlow,
} = uiSlice.actions;

export default uiSlice.reducer;