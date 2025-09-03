import React, { useEffect, useRef } from "react";
import "../../assets/css/AISummaryTab.css";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import { firstSummaryToken, summaryDone } from "../../redux/slices/uiSlice";
import { appendSummary, finishSummary, startSummary } from "../../redux/slices/summarySlice";
import { streamSummary } from "../../services/api";

const AISummaryTab: React.FC = () => {
  const dispatch = useAppDispatch();
  const summaryEnabled = useAppSelector(s => s.ui.summaryEnabled);
  const isLoading = useAppSelector(s => s.ui.summaryLoading);
  const { streamingText, finalText, status } = useAppSelector(s => s.summary);
  const sessionId = useAppSelector(s => s.ui.sessionId); 
  const abortRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    console.log('AISummaryTab:', {
      summaryEnabled,
      status,
      sessionId,
      started: startedRef.current
    });
    if (!summaryEnabled || status !== 'idle' || startedRef.current || !sessionId) return;
    startedRef.current = true;
    dispatch(startSummary());
    const aborter = new AbortController();
    abortRef.current = aborter;
    const run = async () => {
      const stream = streamSummary(sessionId, { signal: aborter.signal });
      let sentFirst = false;
      try {
        for await (const ev of stream) {
          console.log('Summary event:', ev);
          if (ev.type === "summary_token") {
            if (!sentFirst) { dispatch(firstSummaryToken()); sentFirst = true; }
            dispatch(appendSummary(ev.token));
          } else if (ev.type === "done") {
            dispatch(finishSummary());
            dispatch(summaryDone());
          }
        }
      } catch {/* ignore aborts */}
    };
    run();
    return () => aborter.abort();
  }, [dispatch, summaryEnabled, status, sessionId]);

  const typed = finalText ?? streamingText;
  const isComplete = status === 'done';

  return (
    <div className="summary-tab">
      {isLoading && (
        <div className="summary-loading">
          <span className="tab-spinner" aria-label="loading" />
          Generating summary…
        </div>
      )}
      <div className="summary-content">
        <p>{typed}</p>
      </div>
    </div>
  );
};

export default AISummaryTab;