"""X client behavior uses fake sessions and never sends a real request."""

from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
import requests
from requests.adapters import BaseAdapter
from requests_oauthlib import OAuth1Session

from rl_analyzer.x_client import XClient, XError

TEXT = "Ali won 3-2 with 2 demos. #RocketLeague"


class Response:
    def __init__(self, status=201, body=None):
        self.status_code = status
        self.body = body if body is not None else {"data": {"id": "tweet-1"}}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.fixture
def live_config(config):
    return replace(config, post_to_x=True, x_api_key="key", x_api_secret="secret",
                   x_access_token="token", x_access_secret="token-secret")


def test_oauth1_session_is_configured_and_posts_once(live_config, monkeypatch):
    session = Mock()
    session.post.return_value = Response()
    factory = Mock(return_value=session)
    monkeypatch.setattr("rl_analyzer.x_client.OAuth1Session", factory)
    assert XClient(live_config).post(TEXT) == "tweet-1"
    factory.assert_called_once_with(client_key="key", client_secret="secret", resource_owner_key="token", resource_owner_secret="token-secret")
    session.post.assert_called_once_with("https://api.x.com/2/tweets", json={"text": TEXT}, headers={}, timeout=30)


def test_oauth2_bearer_fallback(live_config):
    session = Mock()
    session.post.return_value = Response()
    config = replace(live_config, x_auth_mode="oauth2", x_oauth2_user_token="user-token")
    assert XClient(config, session=session).post(TEXT) == "tweet-1"
    assert session.post.call_args.kwargs["headers"] == {"Authorization": "Bearer user-token"}


@pytest.mark.parametrize(("status", "known"), [(401, True), (403, True), (429, True), (500, False), (503, False), (408, False)])
def test_http_errors_are_single_attempt(live_config, status, known):
    session = Mock()
    session.post.return_value = Response(status)
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert exc.value.outcome_known is known
    assert exc.value.status_code == status
    assert f"X HTTP {status}" in exc.value.safe_diagnostic()
    assert session.post.call_count == 1
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize("body", [{}, {"data": {}}, ValueError("token-secret"), {"data": {"id": ""}}])
def test_invalid_success_response_is_unknown(live_config, body):
    session = Mock()
    session.post.return_value = Response(body=body)
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert not exc.value.outcome_known and "token-secret" not in str(exc.value)


def test_transport_failure_is_unknown_and_secret_safe(live_config):
    session = Mock()
    session.post.side_effect = requests.Timeout("token-secret")
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert not exc.value.outcome_known and "token-secret" not in str(exc.value)
    assert session.post.call_count == 1


def test_disabled_or_unsafe_text_never_sends(config, live_config):
    session = Mock()
    with pytest.raises(XError, match="disabled"):
        XClient(config, session=session).post(TEXT)
    with pytest.raises(XError, match="safety"):
        XClient(live_config, session=session).post("Ali won 3-2! https://example.com #RocketLeague")
    session.post.assert_not_called()


def test_missing_credentials_never_sends(live_config):
    session = Mock()
    with pytest.raises(XError, match="credentials"):
        XClient(replace(live_config, x_access_secret=""), session=session).post(TEXT)
    session.post.assert_not_called()


@pytest.mark.parametrize(("status", "phrase"), [(401, "authentication"), (402, "credits"),
                                                (403, "Read and write"), (429, "rate limited")])
def test_status_guidance_does_not_use_untrusted_response(live_config, status, phrase):
    session = Mock()
    session.post.return_value = Response(status, body={"detail": "token-secret"})
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert phrase in exc.value.safe_diagnostic()
    assert "token-secret" not in exc.value.safe_diagnostic()


def test_untrusted_error_message_cannot_become_diagnostic():
    error = XError("token-secret", outcome_known=True, status_code=999, category="token-secret")
    assert error.safe_diagnostic() == "X posting failed"


def test_actual_oauth1_signing_without_network(live_config):
    class FakeAdapter(BaseAdapter):
        def __init__(self):
            self.requests = []

        def send(self, request, **kwargs):
            self.requests.append(request)
            response = requests.Response()
            response.status_code = 201
            response._content = b'{"data":{"id":"synthetic"}}'
            response.url, response.request = request.url, request
            return response

        def close(self):
            pass

    adapter = FakeAdapter()
    session = OAuth1Session(client_key="key", client_secret="secret", resource_owner_key="token", resource_owner_secret="token-secret")
    session.mount("https://", adapter)
    assert XClient(live_config, session=session).post(TEXT) == "synthetic"
    assert len(adapter.requests) == 1
    prepared = adapter.requests[0]
    authorization = prepared.headers["Authorization"]
    if isinstance(authorization, bytes):
        authorization = authorization.decode("ascii")
    assert authorization.startswith("OAuth ")
    assert all(field in authorization for field in ("oauth_consumer_key=", "oauth_token=", "oauth_signature="))
    assert "token-secret" not in authorization
    assert json.loads(prepared.body) == {"text": TEXT}


@pytest.mark.parametrize(("host", "location", "problem", "phrase"), [
    ("api.x.com", "top", "client-forbidden", "not enrolled"),
    ("api.twitter.com", "nested", "usage-capped", "usage cap"),
    ("api.x.com", "nested", "not-authorized-for-resource", "not authorized"),
    ("api.x.com", "top", "rate-limit-exceeded", "rate limit"),
])
def test_documented_problem_type_is_safe_and_actionable(live_config, host, location, problem, phrase):
    item = {"type": f"https://{host}/2/problems/{problem}", "detail": "token-secret"}
    body = item if location == "top" else {"errors": [item]}
    session = Mock()
    session.post.return_value = Response(403, body=body)
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert exc.value.outcome_known and exc.value.problem == problem
    assert phrase in exc.value.safe_diagnostic()
    assert "token-secret" not in exc.value.safe_diagnostic()


@pytest.mark.parametrize("body", [
    {"type": "https://evil.example/2/problems/client-forbidden"},
    {"type": "https://api.x.com/2/problems/client-forbidden?token=secret"},
    {"type": "token-secret"}, {"errors": [{"type": "token-secret"}]},
    [], ValueError("token-secret"),
])
def test_unknown_or_malformed_problem_never_leaks(live_config, body):
    session = Mock()
    session.post.return_value = Response(403, body=body)
    with pytest.raises(XError) as exc:
        XClient(live_config, session=session).post(TEXT)
    assert exc.value.problem is None
    assert "token-secret" not in exc.value.safe_diagnostic()
    assert "Read and write" in exc.value.safe_diagnostic()
