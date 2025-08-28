import React, { useEffect, useMemo, useRef } from "react";
import "../../assets/css/AISummaryTab.css";
import { useAppDispatch, useAppSelector } from "../../redux/hooks";
import { firstSummaryToken, summaryDone } from "../../redux/slices/uiSlice";
import { appendSummary, finishSummary, startSummary } from "../../redux/slices/summarySlice";
import summaryData from "../../mock-data/mock_summary.json";
import { simulateSummaryStream } from "../../services/streamSimulator";

const AISummaryTab: React.FC = () => {
  const dispatch = useAppDispatch();
  const summaryEnabled = useAppSelector(s => s.ui.summaryEnabled);
  const isLoading = useAppSelector(s => s.ui.summaryLoading);
  const { streamingText, finalText, status } = useAppSelector(s => s.summary);
  const abortRef = useRef<AbortController | null>(null);
  const startedRef = useRef(false);
  const summaryText = useMemo(() => String((summaryData as any)?.summary ?? ""), []);

  // Reset per session
  useEffect(() => {
    if (!summaryEnabled || status === 'idle') {
      startedRef.current = false;
      if (abortRef.current) abortRef.current.abort();
    }
  }, [summaryEnabled, status]);

  // Start streaming once when summary is enabled and status is idle
  // TypeScript
useEffect(() => {
  if (!summaryEnabled ||  status !== 'idle' || startedRef.current) return;
  startedRef.current = true;

  dispatch(startSummary());
  const aborter = new AbortController();
  abortRef.current = aborter;

  const run = async () => {
    const stream = simulateSummaryStream(summaryText, { startDelayMs: 1500, tokenDelayMs: 120, signal: aborter.signal });
    let sentFirst = false;
    try {
      for await (const ev of stream) {
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
}, [dispatch, summaryEnabled, summaryText]); // <-- status REMOVED

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
        {isComplete && Array.isArray((summaryData as any).key_points) && (summaryData as any).key_points.length > 0 && (
          <>
            <h4>Key points</h4>
            <ul>{(summaryData as any).key_points.map((pt: string, i: number) => <li key={i}>{pt}</li>)}</ul>
          </>
        )}
        {isComplete && Array.isArray((summaryData as any).actions) && (summaryData as any).actions.length > 0 && (
          <>
            <h4>Next steps</h4>
            <ul>{(summaryData as any).actions.map((pt: string, i: number) => <li key={i}>{pt}</li>)}</ul>
          </>
        )}
      </div>
    </div>
  );
};

export default AISummaryTab;