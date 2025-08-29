import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

export type Tab = 'transcripts' | 'summary';

export interface UIState {
  aiProcessing: boolean;
  summaryEnabled: boolean;
  summaryLoading: boolean;
  activeTab: Tab;
  autoSwitched: boolean;
}

const initialState: UIState = {
  aiProcessing: false,
  summaryEnabled: false,
  summaryLoading: false,
  activeTab: 'transcripts',
  autoSwitched: false,
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
    },
    transcriptionComplete(state) {
      state.summaryEnabled = true;
      state.summaryLoading = true; // show spinner until first token
      if (!state.autoSwitched) {
        state.activeTab = 'summary';
        state.autoSwitched = true;
      }
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
  firstSummaryToken,
  summaryDone,
  setActiveTab,
  resetFlow,
} = uiSlice.actions;

export default uiSlice.reducer;