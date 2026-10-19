# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Parent-side memory sampling and child-process supervision (re-exported by `benchmark.py`).

Memory is sampled from the orchestrator with system-wide counters (`psutil` for host RAM,
the Windows PDH collector for GPU memory) every 0.5 s by default. The parent never creates
an OpenVINO GPU context. Readings survive a child killed on timeout. Another application
contributes to the same counters, and shared GPU memory overlaps host RAM, so the two are
never added together. GPU counters are read only for GPU runs.

Per case, one spawned child runs `trial_runner.run_case`. The parent:

* resets the progress deadline only on valid events from the active case;
* on `iteration_start` opens a fresh memory window and acknowledges ``ready``; on
  `iteration`/`probe` closes the window, attaches it, runs the checkpoint callback and only
  then acknowledges ``recorded``;
* deduplicates records by iteration index, so `done`'s accumulated records never double
  count streamed ones;
* on timeout or Ctrl-C terminates only its own child, joins, escalates to kill, and reports
  whether death was confirmed; drains already-queued results for a bounded interval before
  declaring a crash.

Sampled windows include IPC and sampling delay around generation: they are not kernel-only
measurements.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from queue import Empty

from components.context_bench import trial_runner

MEMORY_SETTLE_TIMEOUT_SEC = 30.0
MEMORY_SETTLE_TOLERANCE_GB = 1.0
WINDOW_BOUNDARY = "sampled window from iteration_start to the record; includes IPC/sampling delay"

_NATIVE_ABORT_EXIT_CODES = {
    3221226505: "0xC0000409 STATUS_STACK_BUFFER_OVERRUN - how the CRT reports abort()/std::terminate",
    3221225477: "0xC0000005 STATUS_ACCESS_VIOLATION",
    3221225725: "0xC00000FD STATUS_STACK_OVERFLOW",
}


class CaseInterrupted(Exception):
    """Ctrl-C during a case; carries the partial result after child cleanup."""

    def __init__(self, result: dict):
        super().__init__("interrupted")
        self.result = result


class ChildCleanupError(RuntimeError):
    """The child's death could not be confirmed; no further case may start."""

    def __init__(self, result: dict):
        super().__init__("child process did not exit after terminate/kill")
        self.result = result


# ---------------------------------------------------------------------------
# Memory sampling
# ---------------------------------------------------------------------------
def _read_mem(include_gpu: bool = True) -> dict:
    ram_used = ram_pct = available_ram = None
    try:
        import psutil

        vm = psutil.virtual_memory()
        ram_used, ram_pct = vm.used / (1024 ** 3), vm.percent
        available_ram = vm.available / (1024 ** 3)
    except Exception:  # noqa: BLE001 - unavailable telemetry stays None
        pass

    gpu_gb = None
    if include_gpu:
        try:
            from monitoring.scripts.windows.collect_gpu import get_gpu_memory_total

            used_mb = get_gpu_memory_total()[0]
            if used_mb is not None:
                gpu_gb = used_mb / 1024
        except Exception:  # noqa: BLE001
            pass
    return {"ram_gb": ram_used, "ram_pct": ram_pct, "available_ram_gb": available_ram,
            "gpu_gb": gpu_gb}


class _TimeWeightedMean:
    """Mean of one counter over a window, each reading weighted by how long it stood.

    An unavailable reading contributes neither value nor time. A window shorter than one
    sample reports the standing reading (labelled instantaneous by the sampler).
    """

    __slots__ = ("_weighted", "_seconds", "_value", "_since")

    def __init__(self, value: float | None, now: float):
        self._weighted = 0.0
        self._seconds = 0.0
        self._value = value
        self._since = now

    def _settle(self, now: float) -> None:
        elapsed = now - self._since
        if self._value is not None and elapsed > 0:
            self._weighted += self._value * elapsed
            self._seconds += elapsed
        self._since = now

    def observe(self, value: float | None, now: float) -> None:
        self._settle(now)
        self._value = value

    def mean(self, now: float) -> float | None:
        self._settle(now)
        return self._weighted / self._seconds if self._seconds > 0 else self._value

    @property
    def observed_seconds(self) -> float:
        return self._seconds


class _MemorySampler(threading.Thread):
    """Case-wide peaks and the free-RAM low-water mark, plus per-iteration windows.

    The fold and the window reset share a lock: otherwise a fold racing a reset could
    write a pre-reset peak back into the new window.
    """

    def __init__(self, interval: float = 0.5, baseline: dict | None = None,
                 include_gpu: bool = True, clock=time.monotonic):
        super().__init__(daemon=True)
        self._stop_event = threading.Event()
        self._clock = clock
        self.interval = interval
        self.include_gpu = include_gpu
        self.peak_ram = None
        self.peak_ram_pct = None
        self.peak_gpu = None
        self.min_available_ram = None
        self.samples = 0
        self._window_ram = None
        self._window_gpu = None
        self._window_mean = {}
        self._window_samples = 0
        self._window_opened = clock()
        self._lock = threading.Lock()
        first = baseline if baseline is not None else _read_mem(include_gpu)
        self._open_window(first)
        self._observe(first)

    def _fold(self, m: dict, pick, key: str, attr: str) -> None:
        value = m.get(key)
        if value is None:
            return
        current = getattr(self, attr)
        setattr(self, attr, value if current is None else pick(current, value))

    def _open_window(self, m: dict) -> None:
        now = self._clock()
        with self._lock:
            self._window_ram = m.get("ram_gb")
            self._window_gpu = m.get("gpu_gb")
            self._window_mean = {key: _TimeWeightedMean(m.get(key), now)
                                 for key in ("ram_gb", "gpu_gb")}
            self._window_samples = 1
            self._window_opened = now

    def _observe(self, m: dict) -> None:
        now = self._clock()
        with self._lock:
            for key, attr in (
                ("ram_gb", "peak_ram"),
                ("gpu_gb", "peak_gpu"),
                ("ram_pct", "peak_ram_pct"),
                ("ram_gb", "_window_ram"),
                ("gpu_gb", "_window_gpu"),
            ):
                self._fold(m, max, key, attr)
            self._fold(m, min, "available_ram_gb", "min_available_ram")
            for key, accumulator in self._window_mean.items():
                accumulator.observe(m.get(key), now)
            self.samples += 1
            self._window_samples += 1

    def reset_window(self) -> None:
        # Read before taking the lock: a PDH query can take tens of milliseconds.
        self._open_window(_read_mem(self.include_gpu))

    def window(self) -> dict:
        """This iteration's memory window, keyed as the record's own fields."""
        now = self._clock()
        with self._lock:
            duration = now - self._window_opened
            ram_mean = self._window_mean["ram_gb"]
            return {
                "peak_ram_gb": self._window_ram,
                "peak_gpu_gb": self._window_gpu if self.include_gpu else None,
                "mean_ram_gb": ram_mean.mean(now),
                "mean_gpu_gb": self._window_mean["gpu_gb"].mean(now) if self.include_gpu else None,
                "memory_window": {
                    "samples": self._window_samples,
                    "duration_s": duration,
                    "observed_s": ram_mean.observed_seconds,
                    "interval_s": self.interval,
                    "instantaneous": self._window_samples <= 1 or duration <= 0,
                    "boundary": WINDOW_BOUNDARY,
                },
            }

    def run(self):
        while not self._stop_event.is_set():
            self._observe(_read_mem(self.include_gpu))
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()


def _post_load_growth(records: dict, key: str, loaded_mem: dict | None, loaded_key: str):
    """Growth over the loaded reading, from the windows after load (warm-up, iterations,
    probes); the case-wide peak would count the load spike itself."""
    if not loaded_mem:
        return None
    peaks = [r.get(key) for group in ("iteration", "probe") for r in records[group].values()
             if isinstance(r.get(key), (int, float))]
    return _delta(max(peaks), loaded_mem.get(loaded_key)) if peaks else None


def _delta(higher: float | None, lower: float | None) -> float | None:
    if higher is None or lower is None:
        return None
    return max(0.0, higher - lower)


def _wait_for_memory_settle(baseline: dict, include_gpu: bool = True,
                            timeout_sec: float = MEMORY_SETTLE_TIMEOUT_SEC) -> bool:
    """Wait (bounded) for counters to return within 1 GiB of the pre-case baseline.

    A timeout is a warning, not an error; it is never proof of native cleanup.
    """
    deadline = time.monotonic() + timeout_sec
    keys = ("ram_gb", "gpu_gb") if include_gpu else ("ram_gb",)
    while True:
        current = _read_mem(include_gpu)
        if all(
            current[key] <= baseline[key] + MEMORY_SETTLE_TOLERANCE_GB
            for key in keys
            if current.get(key) is not None and baseline.get(key) is not None
        ):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def _crash_reason(exitcode) -> str:
    detail = _NATIVE_ABORT_EXIT_CODES.get(exitcode)
    return f"child exited without a result (exit code {exitcode}" + (f": {detail})" if detail else ")")


# ---------------------------------------------------------------------------
# Event validation
# ---------------------------------------------------------------------------
def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_event(message, case_id: str) -> bool:
    """Required fields at the parent boundary; anything else is ignored, not trusted."""
    if not isinstance(message, dict) or message.get("case_id") != case_id:
        return False
    event = message.get("event")
    if event not in trial_runner.EVENTS:
        return False
    if event in ("iteration_start", "prefilled"):
        return _is_int(message.get("iteration"))
    if event == "iteration":
        return (_is_int(message.get("iteration")) and isinstance(message.get("warmup"), bool)
                and _is_int(message.get("output_size")))
    if event == "probe":
        if not _is_int(message.get("iteration")):
            return False
        if message.get("status") == "skipped":
            return True
        return message.get("status") == "ok" and _is_int(message.get("output_size"))
    if event == "done":
        return isinstance(message.get("load_ok"), bool)
    return True


def _stop_child(process, graceful: bool, join_timeout: float, kill_timeout: float) -> bool:
    """Join (after a normal `done`) or terminate -> join -> kill; True when death confirmed."""
    try:
        if graceful:
            process.join(join_timeout)
        if process.is_alive():
            process.terminate()
            process.join(join_timeout)
        if process.is_alive():
            process.kill()
            process.join(kill_timeout)
        return not process.is_alive()
    except Exception:  # noqa: BLE001 - an unknown process state is not a confirmed death
        return False


def _close_queue(queue) -> None:
    for method in ("cancel_join_thread", "close"):
        try:
            getattr(queue, method)()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------
def _run_case_subprocess(spec: dict, timeout_sec: float, *, include_gpu: bool = True,
                         on_record=None, sample_interval: float = 0.5,
                         poll_interval: float = 0.25, drain_timeout: float = 5.0,
                         join_timeout: float = 10.0, kill_timeout: float = 5.0) -> dict:
    """Run one case in a spawned child; returns its merged result.

    Raises `CaseInterrupted` (Ctrl-C) or `ChildCleanupError` (death unconfirmed), each
    carrying the partial result. `on_record(kind, record)` runs before ``recorded`` is
    acknowledged, so a checkpoint it writes never races the next iteration.
    """
    case_id = spec["case_id"]
    baseline = _read_mem(include_gpu)
    sampler = _MemorySampler(interval=sample_interval, baseline=baseline, include_gpu=include_gpu)
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    control_queue = ctx.Queue()
    process = ctx.Process(target=trial_runner.run_case,
                          args=(spec, result_queue, control_queue))

    state = {
        "load_ok": False, "load_time_s": None, "prompt": None, "prompt_tokens": None,
        "stage_reached": trial_runner.STAGE_START, "phase": "load", "active_iteration": None,
        "device": {}, "records": {"iteration": {}, "probe": {}}, "invalid_events": 0,
        "channel_error": None,
    }
    loaded_mem = None
    done = None
    timed_out = interrupted = False

    def _ack(iteration, kind: str) -> None:
        try:
            control_queue.put({"case_id": case_id, "iteration": iteration, "ack": kind})
        except Exception as exc:  # noqa: BLE001
            state["channel_error"] = f"control channel failed: {type(exc).__name__}"

    def _consume(message: dict, child_alive: bool) -> bool:
        nonlocal loaded_mem, done
        event = message["event"]
        if event == "device":
            state["device"] = {k: v for k, v in message.items() if k not in ("event", "case_id")}
        elif event == "loaded":
            state["load_ok"] = True
            state["load_time_s"] = message.get("load_time_s")
            state["stage_reached"], state["phase"] = trial_runner.STAGE_LOADED, "prompt"
            # Only meaningful while the child lives; a post-mortem event must not fabricate it.
            if child_alive and loaded_mem is None:
                loaded_mem = _read_mem(include_gpu)
        elif event == "prompt":
            state["stage_reached"] = trial_runner.STAGE_PROMPT_BUILT
            info = {k: v for k, v in message.items() if k not in ("event", "case_id", "iteration")}
            if state["prompt"] is None or spec.get("mode") != "accuracy":
                state["prompt"] = info
            state["prompt_tokens"] = message.get("ov_tokens")
        elif event == "iteration_start":
            state["active_iteration"] = message["iteration"]
            state["stage_reached"], state["phase"] = trial_runner.STAGE_PROMPT_BUILT, "generate"
            sampler.reset_window()
            if child_alive:
                _ack(message["iteration"], trial_runner.ACK_READY)
        elif event == "prefilled":
            if message["iteration"] == state["active_iteration"]:
                state["stage_reached"] = trial_runner.STAGE_PREFILLED
        elif event in ("iteration", "probe"):
            record = {k: v for k, v in message.items() if k != "event"}
            if record.get("status", "ok") == "ok":
                state["stage_reached"] = trial_runner.STAGE_DECODED
                record.update(sampler.window())
            store = state["records"][event]
            if record["iteration"] not in store:
                store[record["iteration"]] = record
                if on_record is not None:
                    on_record(event, record)
            state["phase"] = "between iterations"
            if child_alive:
                _ack(record["iteration"], trial_runner.ACK_RECORDED)
        elif event == "done":
            done = message
            return True
        return False

    sampler.start()
    started = False
    confirmed = True
    try:
        process.start()
        started = True
        deadline = time.monotonic() + timeout_sec
        while done is None:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                message = result_queue.get(timeout=poll_interval)
            except Empty:
                if not process.is_alive():
                    break
                continue
            if not _valid_event(message, case_id):
                state["invalid_events"] += 1
                continue
            deadline = time.monotonic() + timeout_sec
            if _consume(message, child_alive=True):
                break
            if state["channel_error"]:
                break
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if started:
            confirmed = _stop_child(process, graceful=done is not None,
                                    join_timeout=join_timeout, kill_timeout=kill_timeout)
        sampler.stop()
        sampler.join(2 * sample_interval + 1)
        if done is None and confirmed and not interrupted:
            # A finished child's `done` can land between the last poll and is_alive() going
            # False; drain rather than report a completed case as a crash.
            drain_deadline = time.monotonic() + drain_timeout
            while time.monotonic() < drain_deadline:
                try:
                    message = result_queue.get(timeout=poll_interval)
                except Empty:
                    break
                except Exception:  # noqa: BLE001
                    break
                if _valid_event(message, case_id) and _consume(message, child_alive=False):
                    timed_out = False
                    break
        _close_queue(result_queue)
        _close_queue(control_queue)

    records = state["records"]
    if done is not None:
        # Merge by identity: streamed records (with memory windows) win over done's copies.
        for kind, key in (("iteration", "iterations"), ("probe", "probes")):
            for record in done.get(key) or []:
                if isinstance(record, dict) and _is_int(record.get("iteration")) \
                        and record["iteration"] not in records[kind]:
                    records[kind][record["iteration"]] = {**record, "memory_window": None}
        result = {
            "load_ok": bool(done.get("load_ok")) or state["load_ok"],
            "load_time_s": done.get("load_time_s", state["load_time_s"]),
            "prompt": done.get("prompt") or state["prompt"],
            "prompt_tokens": done.get("prompt_tokens") or state["prompt_tokens"],
            "stage_reached": done.get("stage_reached", state["stage_reached"]),
            "phase": done.get("phase", state["phase"]),
            "active_iteration": done.get("active_iteration"),
            "error": done.get("error"),
            "device": done.get("device") or state["device"],
        }
    else:
        if interrupted:
            category, message = "interrupted", "interrupted by the operator (Ctrl-C)"
        elif timed_out:
            category, message = "timeout", f"no progress for {timeout_sec:g}s"
        elif state["channel_error"]:
            category, message = "orchestration", state["channel_error"]
        else:
            category, message = "crashed", _crash_reason(getattr(process, "exitcode", None))
        result = {
            "load_ok": state["load_ok"],
            "load_time_s": state["load_time_s"],
            "prompt": state["prompt"],
            "prompt_tokens": state["prompt_tokens"],
            "stage_reached": state["stage_reached"],
            "phase": state["phase"],
            "active_iteration": state["active_iteration"],
            "error": {
                "category": category,
                "stage": trial_runner.failing_stage(state["stage_reached"]),
                "milestone": state["stage_reached"],
                "phase": state["phase"],
                "iteration": state["active_iteration"],
                "message": message,
                "exit_code": getattr(process, "exitcode", None),
            },
            "device": state["device"],
        }
    result.update({
        "case_id": case_id,
        "iterations": [records["iteration"][k] for k in sorted(records["iteration"])],
        "probes": [records["probe"][k] for k in sorted(records["probe"])],
        "invalid_events": state["invalid_events"],
        "cleanup_confirmed": confirmed,
        "exit_code": getattr(process, "exitcode", None),
        "memory_baseline": baseline,
        "peak_ram_gb": sampler.peak_ram,
        "peak_ram_pct": sampler.peak_ram_pct,
        "min_available_ram_gb": sampler.min_available_ram,
        "peak_gpu_gb": sampler.peak_gpu if include_gpu else None,
        "post_load_peak_ram_gb": _post_load_growth(records, "peak_ram_gb", loaded_mem, "ram_gb"),
        "post_load_peak_gpu_gb": (_post_load_growth(records, "peak_gpu_gb", loaded_mem, "gpu_gb")
                                  if include_gpu else None),
        "memory_samples": sampler.samples,
        "memory_sample_interval_s": sample_interval,
        "gpu_budget_driver_gb": (state["device"] or {}).get("gpu_budget_gb"),
    })
    if interrupted:
        raise CaseInterrupted(result)
    if not confirmed:
        raise ChildCleanupError(result)
    return result
