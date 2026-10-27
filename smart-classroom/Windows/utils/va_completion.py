import json
import logging
import time

logger = logging.getLogger(__name__)

# VA pipeline names, and the session vocabulary's names for them: the UI
# registers the content camera as "board" (the board/whiteboard camera).
VA_PIPELINES = ("front", "back", "content")
VA_SOURCE_ALIASES = {"board": "content"}


def va_pipeline_sources(video_sources) -> dict:
    """``{pipeline: source}`` for a session's ``video_sources``; empty sources dropped.

    Raises ValueError for a name that is no VA pipeline, or for two names of
    one pipeline ("board" and "content"). Passing an unknown name through
    used to fail only at launch, logged as a warning, while the session went
    on without that pipeline (and, for the content camera, without board OCR).
    """
    out = {}
    for name, source in (video_sources or {}).items():
        if not source:
            continue
        pipeline = VA_SOURCE_ALIASES.get(name, name)
        if pipeline not in VA_PIPELINES:
            raise ValueError(f"unknown video source {name!r}; expected one of "
                             f"{', '.join(VA_PIPELINES + tuple(VA_SOURCE_ALIASES))}")
        if pipeline in out:
            raise ValueError(f"two video sources for the {pipeline} pipeline")
        out[pipeline] = source
    return out


def wait_for_va_completion(service, wanted, done, final_status, timeout,
                           interval=2.0, grace_polls=3) -> bool:
    deadline = time.monotonic() + timeout
    down_count = 0
    while time.monotonic() < deadline:
        if done.is_set():
            final_status.update(service.pipeline_final_status)
            return True
        statuses = service.pipeline_final_status
        if statuses and all(statuses.get(n) in ("eos", "failed") for n in wanted):
            final_status.update(statuses)
            return True
        all_down = all(not service.is_pipeline_running(n) for n in wanted)
        if all_down:
            down_count += 1
            if down_count >= grace_polls:
                final_status.update(service.pipeline_final_status)
                return True
        else:
            down_count = 0
        time.sleep(interval)
    return False


def save_va_outputs(service, session_id):
    """Write a finished VA run's outputs: class_statistics.json and the engagement reports.

    Shared by the UI's VA monitor and the orchestrator's va stage, so a session
    started through /api/v1/sessions/process gets the same files the report
    generator and the artifact list read. Returns the stats, or None if they
    could not be computed. Never raises: VA itself has already finished.
    """
    from utils.scp_sender import get_scp_sender, write_engagement_reports
    from utils.session_paths import SessionPaths
    from utils.session_state_manager import SessionState
    from utils.telegram_sender import get_sender

    try:
        session_dir = str(SessionPaths.session_dir(session_id))
        front_posture = str(SessionPaths.va_dir(session_id) / "front_posture.txt")
        # Use the same engine as the /class-statistics UI endpoint
        va_stats, _ = service.get_pose_stats(front_posture)

        # Persist the video duration alongside the pose stats so
        # video-only sessions have a reliable, on-disk duration
        # source for report generation (SessionState is in-memory
        # only and is lost on restart / async re-generation).
        video_dur = SessionState.get_video_duration(session_id)
        if isinstance(video_dur, (int, float)) and video_dur > 0:
            va_stats["duration_sec"] = round(float(video_dur), 1)

        logger.info(f"[VA done] Final stats for {session_id}: {va_stats}")

        try:
            stats_path = SessionPaths.class_statistics_path(session_id)
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            stats_path.write_text(json.dumps(va_stats, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[VA done] Saved class_statistics.json to {stats_path}")
        except Exception as e:
            logger.error(f"[VA done] Failed to save class_statistics.json: {e}")

        # Always write the files regardless of sender config
        write_engagement_reports(session_id, session_dir, va_stats)
        scp = get_scp_sender()
        if scp:
            scp.send_engagement_package_async(session_id, session_dir, va_stats)
        tg = get_sender()
        if tg:
            tg.send_engagement_package_async(session_id, session_dir, front_posture)
        return va_stats
    except Exception as e:
        logger.error(f"[VA done] Failed to generate/send reports: {e}", exc_info=True)
        return None
