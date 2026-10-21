import json
import logging
import os
import threading

from utils.session_paths import SessionPaths

logger = logging.getLogger(__name__)

# One writer at a time: on Windows an append through separate handles is not
# atomic, and stages ending together (transcribe, board OCR, VA) would drop lines.
_LOCK = threading.Lock()


class StageEventWriter:
    @staticmethod
    def write(session_id, stage, status, started_at, ended_at, duration_sec,
              error_class=None, error_detail=None) -> None:
        """Append one stage event as a JSON line to <session>/stage_events.jsonl.

        Observability must never break the business flow, so any write failure is
        logged and swallowed.
        """
        event = {
            "session_id": session_id,
            "stage": stage,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_sec": duration_sec,
            "error_class": error_class,
            "error_detail": error_detail,
        }
        try:
            path = SessionPaths.stage_events_path(session_id)
            os.makedirs(path.parent, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False) + "\n"
            with _LOCK, open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.warning(f"[stage_events] failed to write event for {session_id}/{stage}: {e}")
