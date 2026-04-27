import logging

import httpx
import respx

from dispatchzero.log_alerts import NtfyAlertHandler, install_ntfy_handler


def _make_record(msg: str = "boom", level: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=level,
        pathname="x.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def _sync_handler(topic: str = "test-topic") -> NtfyAlertHandler:
    """Build a handler whose 'send' runs synchronously, so respx asserts work
    without sleeping or joining threads."""
    h = NtfyAlertHandler(topic=topic, synchronous_send=True)
    h.setFormatter(
        logging.Formatter(fmt="%(levelname)s %(name)s\n%(message)s")
    )
    return h


@respx.mock
def test_emit_posts_to_ntfy():
    route = respx.post("https://ntfy.sh/test-topic").mock(
        return_value=httpx.Response(200)
    )
    h = _sync_handler()
    h.emit(_make_record("first"))
    assert route.call_count == 1
    sent = route.calls.last.request
    assert b"first" in sent.content
    assert sent.headers["Title"].startswith("Dispatch Zero")
    assert sent.headers["Priority"] == "high"
    assert "warning" in sent.headers["Tags"]


@respx.mock
def test_coalesces_duplicates_within_window():
    route = respx.post("https://ntfy.sh/test-topic").mock(
        return_value=httpx.Response(200)
    )
    h = _sync_handler()
    h.emit(_make_record("same"))
    h.emit(_make_record("same"))
    h.emit(_make_record("same"))
    assert route.call_count == 1


@respx.mock
def test_distinct_messages_each_send():
    route = respx.post("https://ntfy.sh/test-topic").mock(
        return_value=httpx.Response(200)
    )
    h = _sync_handler()
    h.emit(_make_record("alpha"))
    h.emit(_make_record("beta"))
    assert route.call_count == 2


@respx.mock
def test_outage_does_not_raise():
    respx.post("https://ntfy.sh/test-topic").mock(
        return_value=httpx.Response(500)
    )
    h = _sync_handler()
    # Must not raise even though ntfy "is down"
    h.emit(_make_record("boom"))


@respx.mock
def test_network_error_does_not_raise():
    respx.post("https://ntfy.sh/test-topic").mock(
        side_effect=httpx.ConnectError("network unreachable")
    )
    h = _sync_handler()
    # Even a transport-level failure is swallowed.
    h.emit(_make_record("boom-network"))


@respx.mock
def test_body_truncated_to_max_chars():
    route = respx.post("https://ntfy.sh/test-topic").mock(
        return_value=httpx.Response(200)
    )
    h = NtfyAlertHandler(topic="test-topic", synchronous_send=True, max_body_chars=100)
    h.setFormatter(logging.Formatter(fmt="%(message)s"))
    h.emit(_make_record("x" * 5000))
    assert route.call_count == 1
    body = route.calls.last.request.content.decode("utf-8")
    # 100 chars + the truncation marker
    assert len(body) <= 100 + len("\n...[truncated]")
    assert body.endswith("[truncated]")


def test_handler_level_is_error():
    h = NtfyAlertHandler(topic="test-topic", synchronous_send=True)
    assert h.level == logging.ERROR


def test_install_with_no_topic_is_noop():
    root = logging.getLogger()
    before = list(root.handlers)
    install_ntfy_handler(None)
    install_ntfy_handler("")
    assert root.handlers == before


def test_install_with_topic_attaches_handler():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        install_ntfy_handler("real-topic")
        assert any(isinstance(h, NtfyAlertHandler) for h in root.handlers)
    finally:
        # Cleanup so this doesn't pollute later tests
        root.handlers = before
