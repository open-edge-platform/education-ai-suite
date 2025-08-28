import React, { useEffect, useRef } from "react";
import "../../assets/css/TranscriptsTab.css";
import transcriptData from "../../mock-data/mock_transcript.json";
import { simulateTranscriptStream } from "../../services/streamSimulator";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import { appendTranscript, finishTranscript, startTranscript } from "../../redux/slices/transcriptSlice";
import { transcriptionComplete } from "../../redux/slices/uiSlice";

const TranscriptsTab: React.FC = () => {
  const dispatch = useAppDispatch();
  const abortRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);
  const { finalText, streamingText } = useAppSelector(s => s.transcript);
  const aiProcessing = useAppSelector(s => s.ui.aiProcessing);

  useEffect(() => {
    if (!aiProcessing || startedRef.current) return;
    startedRef.current = true;

    const aborter = new AbortController();
    abortRef.current = aborter;

    const run = async () => {
      const chunks: string[] = Array.isArray((transcriptData as any).transcript)
        ? (transcriptData as any).transcript : [];
      const stream = simulateTranscriptStream(chunks, { startDelayMs: 1200, tokenDelayMs: 120, signal: aborter.signal });
      let sentFirst = false;
      try {
        for await (const ev of stream) {
          if (ev.type === "transcript") {
            if (!sentFirst) { dispatch(startTranscript()); sentFirst = true; }
            dispatch(appendTranscript(ev.token));
          } else if (ev.type === "done") {
            dispatch(finishTranscript());
            dispatch(transcriptionComplete()); // triggers summaryEnabled
          }
        }
      } catch { /* ignore aborts */ }
    };

    run();
    return () => aborter.abort();
  }, [dispatch, aiProcessing]);

  const text = finalText ?? streamingText;

  return (
    <div className="transcripts-tab">
      <div className="transcript-content">{text}</div>
    </div>
  );
};

export default TranscriptsTab;