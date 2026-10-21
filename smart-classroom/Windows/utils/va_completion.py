import time

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
