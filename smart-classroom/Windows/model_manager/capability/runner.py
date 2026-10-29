from threading import Semaphore, Lock
from typing import Callable, Any, Iterator


class QueueFullError(Exception):
    """Raised when the capability queue is at capacity."""
    pass


class OomError(Exception):
    """Raised when a capability call fails due to memory pressure (OOM).

    The CapabilityRunner slot is always released before this propagates, so
    the runner remains READY and subsequent requests can proceed normally.
    """
    pass


class _SlotStream:
    """Iterator that holds a runner slot until exhausted, failed or closed.

    A class, not a generator: closing a generator before its first ``next()``
    skips its ``finally`` and would leak the slot.
    """

    def __init__(self, iterator: Iterator, release: Callable[[], None]):
        self._iterator = iterator
        self._release = release
        self._closed = False
        # The response may close the stream on the event loop while the
        # generation thread closes it at the end of iteration.
        self._close_lock = Lock()

    def __iter__(self) -> "_SlotStream":
        return self

    def __next__(self) -> Any:
        if self._closed:
            raise StopIteration
        try:
            return next(self._iterator)
        except StopIteration:
            self.close()
            raise
        except (RuntimeError, MemoryError) as exc:
            self.close()
            raise OomError(str(exc)) from exc
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        # A consumer that left early (client disconnect) closes the stream so
        # native work can stop. A stream backed by native inference may hold
        # the slot until that work has actually ended (release_when_idle).
        deferred = False
        try:
            close = getattr(self._iterator, "close", None)
            if close is not None:
                close()
            defer = getattr(self._iterator, "release_when_idle", None)
            deferred = bool(defer is not None and defer(self._release))
        finally:
            if not deferred:
                self._release()

    def __del__(self) -> None:
        # Safety net for a consumer that drops the stream without closing it,
        # as the generator this replaced did on finalization.
        self.close()


class CapabilityRunner:
    def __init__(self, fn: Callable, *, max_concurrency: int = 1,
                 queue_max: int = 8, timeout_s: float | None = None):
        self._fn = fn
        self._semaphore = Semaphore(max_concurrency)
        self._queue_max = queue_max
        self._current_queue = 0
        self._lock = Lock()
        self._timeout_s = timeout_s

    def _release_slot(self) -> None:
        self._semaphore.release()
        with self._lock:
            self._current_queue -= 1

    def submit(self, *args, **kwargs) -> Any:
        with self._lock:
            if self._current_queue >= self._queue_max:
                raise QueueFullError(f"Queue full ({self._queue_max})")
            self._current_queue += 1

        acquired = self._semaphore.acquire(timeout=self._timeout_s)
        if not acquired:
            with self._lock:
                self._current_queue -= 1
            raise QueueFullError(f"Timed out acquiring capacity after {self._timeout_s}s")

        released = False
        try:
            result = self._fn(*args, **kwargs)
            if hasattr(result, "__next__") and hasattr(result, "__iter__"):
                # Streaming callable: keep the slot held until the caller
                # exhausts the iterator.
                released = True
                return _SlotStream(result, self._release_slot)
            return result
        except (RuntimeError, MemoryError) as exc:
            raise OomError(str(exc)) from exc
        finally:
            if not released:
                self._release_slot()