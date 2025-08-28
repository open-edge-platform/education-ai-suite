import React, { useEffect, useRef } from "react";
import "../../assets/css/TranscriptsTab.css";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import { appendTranscript, finishTranscript, startTranscript } from "../../redux/slices/transcriptSlice";
import { transcriptionComplete } from "../../redux/slices/uiSlice";
import { streamTranscript } from "../../services/api";

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
      // Replace 'sessionId' with your actual session identifier
      const stream = streamTranscript('sessionId', { signal: aborter.signal });
      let sentFirst = false;
      try {
        for await (const ev of stream) {
          if (ev.type === "transcript") {
            if (!sentFirst) { dispatch(startTranscript()); sentFirst = true; }
            dispatch(appendTranscript(ev.token));
          } else if (ev.type === "done") {
            dispatch(finishTranscript());
            dispatch(transcriptionComplete());
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
      <div className="transcript-content">
        {text && text.trim().length > 0
          ? text
          : <span style={{ color: "#888" }}>Transcripts not found</span>
        }
      </div>
    </div>
  );
};

export default TranscriptsTab;