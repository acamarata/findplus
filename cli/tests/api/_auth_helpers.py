"""Constants the two split E6 auth suites share. Fixtures live in conftest.py."""

from __future__ import annotations

#: The header pair the dashboard's own fetch() sends, and the one
#: test_security_guards.py::test_the_dashboards_own_requests_pass uses. Every
#: positive-path POST carries it so nothing is accidentally caught by
#: `_require_origin_signal` instead of reaching the handler.
SAME_ORIGIN_HEADERS = {"Origin": "http://127.0.0.1:8647", "Sec-Fetch-Site": "same-origin"}

EVIL = "http://evil.example.com"

GOOGLE_JOB = "fake-google-job"
APPLE_JOB = "fake-apple-job"

APPLE_START_BODY = {"apple_id": "a@b.com", "password": "x"}
APPLE_CODE_BODY = {"job_id": APPLE_JOB, "code": "123456"}
