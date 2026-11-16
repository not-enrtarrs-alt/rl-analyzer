"""Shared AI HTTP behavior uses only fake responses."""

import logging

import pytest
import requests

from rl_analyzer.ai.base import AIError, JsonHTTPClient


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def test_retries_only_429_and_5xx():
    session = Session([Response(429), Response(503), Response(500), Response(body={"ok": True})])
    sleeps = []
    client = JsonHTTPClient(timeout=30, session=session, sleep=sleeps.append)
    assert client.post("https://example.invalid", body={}) == {"ok": True}
    assert sleeps == [1, 2, 4]
    assert len(session.calls) == 4


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status):
    session = Session([Response(status)])
    with pytest.raises(AIError, match=f"HTTP {status}"):
        JsonHTTPClient(timeout=1, session=session).post("https://example.invalid", body={})
    assert len(session.calls) == 1


def test_retries_exhausted():
    session = Session([Response(503) for _ in range(4)])
    with pytest.raises(AIError, match="retries exhausted"):
        JsonHTTPClient(timeout=1, session=session, sleep=lambda _: None).post("https://example.invalid", body={})
    assert len(session.calls) == 4


@pytest.mark.parametrize("response", [requests.ConnectionError("dummy-secret"), Response(body=ValueError("dummy-secret")), Response(body=[])])
def test_errors_do_not_leak_credentials(response):
    client = JsonHTTPClient(timeout=1, session=Session([response]))
    with pytest.raises(AIError) as exc:
        client.post("https://example.invalid", body={}, params={"key": "dummy-secret"})
    assert "dummy-secret" not in str(exc.value)


def test_http_debug_logs_redact_query_and_header(caplog):
    class LoggingSession:
        def post(self, url, **kwargs):
            logging.getLogger("urllib3.connectionpool").debug("request %s %s", kwargs["params"]["key"], kwargs["headers"]["Authorization"])
            return Response(body={"ok": True})

    with caplog.at_level(logging.DEBUG, logger="urllib3.connectionpool"):
        JsonHTTPClient(timeout=1, session=LoggingSession()).post("https://example.invalid", body={}, headers={"Authorization": "Bearer header-secret"}, params={"key": "query-secret"})
    assert "header-secret" not in caplog.text
    assert "query-secret" not in caplog.text
    assert "[REDACTED]" in caplog.text
