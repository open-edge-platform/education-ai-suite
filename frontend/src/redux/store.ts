import { configureStore } from "@reduxjs/toolkit";
import transcriptReducer from "./slices/transcriptSlice";
import summaryReducer from "./slices/summarySlice";

export const store = configureStore({
  reducer: {
    transcript: transcriptReducer,
    summary: summaryReducer,
  },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;