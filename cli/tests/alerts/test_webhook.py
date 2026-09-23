"""alerts/channels/webhook.py: real loopback HTTP, HMAC signature, non-2xx, timeout."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from findplus.alerts.channels.webhook import build_payload, send_webhook


class _RecordingHandler(BaseHTTPRequestHandler):
    response_status: int = 200
    response_headers: ClassVar[dict] = {}
    requests_seen: ClassVar[list] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _RecordingHandler.requests_seen.append(
            {"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        )
        self.send_response(_RecordingHandler.response_status)
        self.send_header("Content-Length", "0")
        for name, value in _RecordingHandler.response_headers.items():
            self.send_header(name, value)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep test output clean


@pytest.fixture
def loopback_server():
    _RecordingHandler.requests_seen = []
    _RecordingHandler.response_headers = {}
    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", _RecordingHandler.requests_seen
    server.shutdown()
    server.server_close()


def _payload() -> dict:
    when = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    return build_payload(
        event="ENTER",
        kind="device",
        subject_id="abc",
        subject_name="Tag",
        place_id=1,
        place_name="Home",
        observed_at=when,
        fetched_at=when,
        lag_minutes=3,
        confidence="high",
        note="",
    )


def test_send_no_secret(loopback_server) -> None:
    url, requests_seen = loopback_server
    result = send_webhook(_payload(), url)
    assert result.success is True
    assert "x-findplus-signature" not in requests_seen[0]["headers"]


def test_send_with_secret(loopback_server) -> None:
    url, requests_seen = loopback_server
    result = send_webhook(_payload(), url, secret="mysecret")
    assert result.success is True
    headers = requests_seen[0]["headers"]
    assert "x-findplus-signature" in headers
    expected = hmac.new(b"mysecret", requests_seen[0]["body"], hashlib.sha256).hexdigest()
    assert headers["x-findplus-signature"] == expected


def test_send_non_2xx(loopback_server) -> None:
    url, _ = loopback_server
    _RecordingHandler.response_status = 503
    try:
        result = send_webhook(_payload(), url)
    finally:
        _RecordingHandler.response_status = 200
    assert result.success is False
    assert result.status_code == 503
    assert result.retry_after_seconds is None


def test_send_429_carries_retry_after(loopback_server) -> None:
    url, _ = loopback_server
    _RecordingHandler.response_status = 429
    _RecordingHandler.response_headers = {"Retry-After": "120"}
    try:
        result = send_webhook(_payload(), url)
    finally:
        _RecordingHandler.response_status = 200
        _RecordingHandler.response_headers = {}
    assert result.success is False
    assert result.status_code == 429
    assert result.retry_after_seconds == 120


def test_build_payload_fields() -> None:
    payload = _payload()
    for key in (
        "event",
        "kind",
        "subject",
        "place",
        "observed_at",
        "fetched_at",
        "lag_minutes",
        "confidence",
        "note",
        "sent_at",
    ):
        assert key in payload


def test_send_timeout() -> None:
    # A socket that accepts the connection but never responds.
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    held_conns: list = []

    def _accept_and_stall() -> None:
        try:
            conn, _ = server_sock.accept()
            held_conns.append(conn)  # keep the fd alive (no GC close) until the test ends
        except OSError:
            pass

    thread = threading.Thread(target=_accept_and_stall, daemon=True)
    thread.start()
    try:
        result = send_webhook(_payload(), f"http://127.0.0.1:{port}", timeout=0.2)
    finally:
        for conn in held_conns:
            conn.close()
        server_sock.close()
    assert result.error == "timeout"


def test_json_serializable() -> None:
    payload = _payload()
    assert json.loads(json.dumps(payload, default=str))["event"] == "ENTER"


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://example.com/hook", True),
        ("http://127.0.0.1:8647/hook", True),
        ("http://localhost/hook", True),
        ("http://[::1]:8000/hook", True),
        ("http://localhost.evil.example/hook", False),
        ("http://127.0.0.1.evil.example/hook", False),
        ("http://10.0.0.1/hook", False),
        ("ftp://bad", False),
    ],
)
def test_is_valid_url(url: str, valid: bool) -> None:
    from findplus.alerts.channels.webhook import is_valid_url

    assert is_valid_url(url) is valid
