"""ntfy.sh logging handler — push notifications on ERROR/CRITICAL log records.

Replaces the original Phase 14 plan's hosted Sentry with a small in-process
handler that POSTs ERROR-level records to a private ntfy.sh topic. Trevor
subscribes on his phone via the ntfy app. Same topic is reused by the
disk-fill alert (Task 4).

Design trade-off: this is sized for a small-pool MVP. No aggregation UI, no
deduplication beyond a 60-second coalesce window. When the tester pool grows
enough that push notifications become noise, swap in self-hosted Bugsink
(Sentry-API-compatible) — that's a ~30 min migration, intentionally out of
scope here.

Footgun avoided: the HTTP send is fire-and-forget on a daemon thread, and
ANY exception during sending is swallowed. Logging-during-error-reporting
cascades are textbook bad — silence is correct.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import httpx

_NTFY_BASE_URL = "https://ntfy.sh"
_DEFAULT_TIMEOUT_SECONDS = 5.0
_GC_THRESHOLD = 64


def _default_sender(url: str, *, headers: dict[str, str], content: bytes) -> None:
    """Production sender — fire HTTP POST, swallow any failure."""
    try:
        httpx.post(url, headers=headers, content=content, timeout=_DEFAULT_TIMEOUT_SECONDS)
    except Exception:
        # Never let alert-delivery raise into the caller. If ntfy is down,
        # we accept the missed notification rather than cascading errors.
        pass


class NtfyAlertHandler(logging.Handler):
    """Logging handler that posts ERROR/CRITICAL records to ntfy.sh.

    Coalesces identical messages within a window so a runaway exception
    can't spam the operator's phone. Sends are fire-and-forget on a
    daemon thread by default; tests can pass `synchronous_send=True`.
    """

    def __init__(
        self,
        topic: str,
        *,
        coalesce_seconds: int = 60,
        max_body_chars: int = 1500,
        synchronous_send: bool = False,
        sender: Callable[..., None] | None = None,
    ) -> None:
        super().__init__(level=logging.ERROR)
        self._topic = topic
        self._url = f"{_NTFY_BASE_URL}/{topic}"
        self._coalesce_seconds = coalesce_seconds
        self._max_body_chars = max_body_chars
        self._synchronous_send = synchronous_send
        self._sender = sender or _default_sender
        self._recent: dict[str, float] = {}
        self._lock = threading.Lock()

    def _should_send(self, signature: str) -> bool:
        """Return True if this signature has not been sent within the window.

        Also opportunistically GCs stale entries so the dict can't grow
        unbounded under a sustained burst of distinct messages.
        """
        now = time.monotonic()
        with self._lock:
            last = self._recent.get(signature)
            if last is not None and (now - last) < self._coalesce_seconds:
                return False
            self._recent[signature] = now
            if len(self._recent) > _GC_THRESHOLD:
                cutoff = now - self._coalesce_seconds
                self._recent = {
                    sig: ts for sig, ts in self._recent.items() if ts >= cutoff
                }
            return True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # getMessage() returns the rendered message (template + args).
            # record.msg alone would key dedup on the template, treating
            # "user 1 missing" and "user 2 missing" as identical.
            signature = record.getMessage()
            if not self._should_send(signature):
                return

            body = self.format(record)
            if len(body) > self._max_body_chars:
                body = body[: self._max_body_chars] + "\n...[truncated]"

            # NB: HTTP headers are ASCII-only; ntfy "Title" header rejects
            # non-ASCII unless RFC 2047 encoded. Plain "-" keeps it portable
            # and the title still reads naturally on the phone.
            headers = {
                "Title": "Dispatch Zero - application error",
                "Priority": "high",
                "Tags": "warning,rotating_light",
            }
            content = body.encode("utf-8", errors="replace")

            if self._synchronous_send:
                self._sender(self._url, headers=headers, content=content)
            else:
                threading.Thread(
                    target=self._sender,
                    args=(self._url,),
                    kwargs={"headers": headers, "content": content},
                    daemon=True,
                ).start()
        except Exception:
            # Belt-and-suspenders: any unexpected error in our own emit path
            # must not propagate, or logging.error() could itself crash.
            pass


def install_ntfy_handler(topic: str | None) -> None:
    """Attach an `NtfyAlertHandler` to the root logger.

    No-op when `topic` is falsy so dev/local without `NTFY_TOPIC` set
    incurs zero extra behavior. Attaches at the root so ERROR records
    from any module bubble up.
    """
    if not topic:
        return

    handler = NtfyAlertHandler(topic)
    # Default Formatter renders exc_info (traceback) automatically when
    # present on the record, so unhandled exceptions logged via
    # logger.exception()/logger.error(..., exc_info=True) include the trace.
    handler.setFormatter(
        logging.Formatter(
            fmt="%(levelname)s %(name)s %(pathname)s:%(lineno)d\n%(message)s",
        )
    )
    logging.getLogger().addHandler(handler)
