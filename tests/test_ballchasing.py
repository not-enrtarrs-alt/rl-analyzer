"""Ballchasing requests are exercised entirely with fake HTTP."""

from datetime import datetime, timezone, timedelta

import pytest
import requests

from rl_analyzer.ballchasing import BallchasingClient, BallchasingError


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self.body = body
        self.headers = headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def clock():
    return FakeClock()


def client(config, session, clock):
    return BallchasingClient(config, session=session, clock=clock.clock, sleep=clock.sleep)


def test_list_auth_query_and_detail(config, clock):
    session = Session([Response(body={"list": [{"id": "a"}]}), Response(body={"id": "a"})])
    api = client(config, session, clock)
    cutoff = datetime(2026, 10, 30, 12, tzinfo=timezone(timedelta(hours=2)))
    assert api.list_replays("steam:123", cutoff) == [{"id": "a"}]
    assert api.get_replay("a") == {"id": "a"}
    url, request = session.calls[0]
    assert url == "https://ballchasing.com/api/replays"
    assert request["headers"] == {"Authorization": "dummy-secret"}
    assert request["params"] == {"player-id": "steam:123", "replay-date-after": "2026-10-30T10:00:00Z", "count": 200, "sort-by": "replay-date", "sort-dir": "desc"}
    assert request["timeout"] == 30
    assert session.calls[1][0].endswith("/replays/a")
    assert clock.sleeps == [0.6]


def test_three_independent_lists_are_intersected(config, clock):
    session = Session([Response(body={"list": [dict(id="a"), dict(id="b"), dict(id="b")]}),
                       Response(body={"list": [dict(id="b"), dict(id="c")]}),
                       Response(body={"list": [dict(id="b"), dict(id="d")]})])
    items = client(config, session, clock).list_common_replays(
        [p.id for p in config.players], datetime(2026, 10, 30, tzinfo=timezone.utc))
    assert items == [{"id": "b"}]
    assert [call[1]["params"]["player-id"] for call in session.calls] == [p.id for p in config.players]
    assert clock.sleeps == [0.6, 0.6]


def test_retry_backoff_and_retry_after(config, clock):
    session = Session([Response(429, headers={"Retry-After": "3"}), Response(503), Response(500), Response(body={"id": "a"})])
    assert client(config, session, clock).get_replay("a") == {"id": "a"}
    assert clock.sleeps == [3.0, 2, 4]
    assert len(session.calls) == 4


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_has_safe_message(config, clock, status):
    session = Session([Response(status)])
    with pytest.raises(BallchasingError, match="check BALLCHASING_TOKEN") as exc:
        client(config, session, clock).get_replay("a")
    assert "dummy-secret" not in str(exc.value)
    assert len(session.calls) == 1


def test_retries_exhausted(config, clock):
    session = Session([Response(503) for _ in range(4)])
    with pytest.raises(BallchasingError, match="retries exhausted"):
        client(config, session, clock).get_replay("a")
    assert clock.sleeps == [1, 2, 4]


@pytest.mark.parametrize("response", [Response(400), Response(body=ValueError("secret")), Response(body=[]), requests.ConnectionError("dummy-secret")])
def test_errors_do_not_expose_secrets(config, clock, response):
    session = Session([response])
    with pytest.raises(BallchasingError) as exc:
        client(config, session, clock).get_replay("a")
    assert "secret" not in str(exc.value)
    assert len(session.calls) == 1


def test_bad_list_and_invalid_replay_id(config, clock):
    api = client(config, Session([Response(body={"list": "bad"})]), clock)
    with pytest.raises(BallchasingError, match="invalid replay list"):
        api.list_replays("steam:123", datetime.now(timezone.utc))
    with pytest.raises(BallchasingError, match="Invalid replay ID"):
        api.get_replay("../secret")


def test_retry_after_http_date():
    assert BallchasingClient._retry_after("Thu, 01 Jan 1970 00:00:00 GMT") == 0
    assert BallchasingClient._retry_after("not-a-date") == 0


def test_client_selection_stats_integration(config, replay, clock):
    from rl_analyzer.select import select_candidate

    listing = {"id": replay["id"], "date": replay["date"], "playlist_id": replay["playlist_id"]}
    session = Session([Response(body={"list": [listing]}) for _ in range(3)] + [Response(body=replay)])
    api = client(config, session, clock)
    selected = select_candidate(api, config, datetime(2026, 10, 30, 19, tzinfo=timezone.utc))
    assert selected.match_key == "match-1"
    assert selected.stats["match"]["result"] == "win"
    assert selected.stats["players"][0]["alias"] == "Ali"
    assert len(session.calls) == 4
    assert all(delay >= 0.599999 for delay in clock.sleeps)
