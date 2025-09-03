import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

interface ResourceState {
  metrics: any | null;
}

const initialState: ResourceState = { metrics: null };

const resourceSlice = createSlice({
  name: 'resource',
  initialState,
  reducers: {
    setMetrics(state, action: PayloadAction<any>) {
      state.metrics = action.payload;
    },
    resetMetrics: () => initialState,
  },
});

export const { setMetrics, resetMetrics } = resourceSlice.actions;
export default resourceSlice.reducer;