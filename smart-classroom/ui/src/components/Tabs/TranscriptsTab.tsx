import React, { useEffect, useRef, useState } from "react";
import "../../assets/css/TranscriptsTab.css";
import transcriptData from "../../mock-data/mock_transcript.json";

const TYPE_SPEED = 30;   // ms per character
const CHUNK_DELAY = 80;  // ms between chunks

const TranscriptsTab = () => {
  const [displayedTranscript, setDisplayedTranscript] = useState("");
  const runId = useRef(0);

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  useEffect(() => {
    const id = ++runId.current;

    const run = async () => {
      setDisplayedTranscript("");
      const chunks: string[] = Array.isArray(transcriptData.transcript)
        ? transcriptData.transcript.map((c: unknown) => String(c ?? ""))
        : [];

      for (let c = 0; c < chunks.length; c++) {
        const chunk = chunks[c];
        for (let i = 0; i < chunk.length; i++) {
          if (runId.current !== id) return; // canceled (StrictMode or unmount)
          setDisplayedTranscript((prev) => prev + chunk.charAt(i));
          await sleep(TYPE_SPEED);
        }
        if (runId.current !== id) return;
        await sleep(CHUNK_DELAY);
      }
    };

    run();
    return () => {
      // invalidate this run (stops any pending awaits)
      runId.current++;
    };
  }, []);

  return (
    <div className="transcripts-tab">
      <h2>Live Transcript</h2>
      <div className="transcript-content">{displayedTranscript}</div>
    </div>
  );
};

export default TranscriptsTab;