import { createSlice } from "@reduxjs/toolkit";
import type { PayloadAction } from "@reduxjs/toolkit";

interface SummaryItem {
  text: string;
  timestamp?: string;
}

interface SummaryState {
  items: SummaryItem[];
}

const initialState: SummaryState = {
  items: [],
};

const summarySlice = createSlice({
  name: "summary",
  initialState,
  reducers: {
    addSummaryItem(state, action: PayloadAction<SummaryItem>) {
      state.items.push(action.payload);
    },
    clearSummaries(state) {
      state.items = [];
    },
  },
});

export const { addSummaryItem, clearSummaries } = summarySlice.actions;
export default summarySlice.reducer;