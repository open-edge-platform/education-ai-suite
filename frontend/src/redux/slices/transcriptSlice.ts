import { createSlice} from "@reduxjs/toolkit";
import type { PayloadAction } from "@reduxjs/toolkit";
interface TranscriptChunk {
  text: string;
  timestamp?: string;
  speaker?: string;
}

interface TranscriptState {
  chunks: TranscriptChunk[];
}

const initialState: TranscriptState = {
  chunks: [],
};

const transcriptSlice = createSlice({
  name: "transcript",
  initialState,
  reducers: {
    addTranscriptChunk(state, action: PayloadAction<TranscriptChunk>) {
      state.chunks.push(action.payload);
    },
    clearTranscripts(state) {
      state.chunks = [];
    },
  },
});

export const { addTranscriptChunk, clearTranscripts } = transcriptSlice.actions;
export default transcriptSlice.reducer;