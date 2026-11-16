"""Offline replay selection and storage-interface tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from rl_analyzer.select import match_key, select_candidate

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"


def make_detail(replay, replay_id, date, guid=None):
    result = deepcopy(replay)
    result.update(id=replay_id, match_guid=guid or f"match-{replay_id}", rocket_league_id=f"game-{guid or replay_id}", date=date)
    return result


def summary(detail, include_match=False):
    result = {key: detail[key] for key in ("id", "date", "playlist_id")}
    if include_match:
        result["match_guid"] = detail["match_guid"]
    return result


class FakeClient:
    def __init__(self, summaries, details):
        self.summaries = summaries
        self.details = {detail["id"]: detail for detail in details}
        self.calls = []
        self.list_args = None

    def list_common_replays(self, ids, cutoff):
        self.list_args = ids, cutoff
        return self.summaries

    def get_replay(self, replay_id):
        self.calls.append(replay_id)
        return deepcopy(self.details[replay_id])


class FakeStore:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.duplicates = []

    @staticmethod
    def consumed(row):
        return row["status"] in {"generated", "posting", "posted", "skipped"} or (row["status"] == "analysis_failed" and row.get("attempts", 0) >= 2)

    def replay_is_consumed(self, replay_id):
        return any(row["id"] == replay_id and self.consumed(row) for row in self.rows)

    def match_is_consumed(self, key, *, exclude_replay_id, match_guid=None, rocket_league_id=None):
        return any(row["key"] == key and row["id"] != exclude_replay_id and self.consumed(row) for row in self.rows)

    def record_duplicate(self, replay, match_key):
        self.duplicates.append((replay["id"], match_key, "duplicate_match"))


def test_newest_eligible_selected_without_marking_backlog(replay, config):
    latest = make_detail(replay, "latest", "2026-10-30T18:00:00Z")
    older = make_detail(replay, "older", "2026-10-30T17:00:00Z")
    api = FakeClient([summary(older), summary(latest)], [older, latest])
    store = FakeStore()
    result = select_candidate(api, config, NOW, store=store, record_duplicates=True)
    assert result.replay["id"] == "latest"
    assert result.stats["match"]["score"] == {"trio": 3, "opponents": 2}
    assert api.calls == ["latest"]
    assert store.duplicates == []
    assert api.list_args[0] == [p.id for p in config.players]
    assert api.list_args[1] == datetime(2026, 10, 28, 19, tzinfo=timezone.utc)


@pytest.mark.parametrize("fixture", ["replay_2v2.json", "replay_split_team.json"])
def test_rejects_2v2_and_split_team(replay, config, fixture):
    bad = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    good = make_detail(replay, "older", "2026-10-30T17:00:00Z")
    api = FakeClient([summary(bad), summary(good)], [bad, good])
    assert select_candidate(api, config, NOW).replay["id"] == "older"


@pytest.mark.parametrize("change", [
    lambda r: r.update(playlist_id="ranked-duels"),
    lambda r: r.update(status="processing"),
    lambda r: r["blue"]["players"][0]["stats"]["core"].pop("score"),
    lambda r: (r["blue"].pop("goals"), r["blue"]["stats"]["core"].pop("goals")),
])
def test_rejects_ineligible_detail_and_tries_older(replay, config, change):
    bad = make_detail(replay, "bad", "2026-10-30T18:00:00Z")
    change(bad)
    good = make_detail(replay, "good", "2026-10-30T17:00:00Z")
    api = FakeClient([summary(good), summary(bad)], [bad, good])
    assert select_candidate(api, config, NOW).replay["id"] == "good"
    assert api.calls == ["bad", "good"]


def test_old_and_future_replays_are_not_fetched(replay, config):
    old = make_detail(replay, "old", "2026-10-28T18:59:59Z")
    future = make_detail(replay, "future", "2026-10-30T19:00:01Z")
    api = FakeClient([summary(old), summary(future)], [old, future])
    assert select_candidate(api, config, NOW) is None
    assert api.calls == []


def test_date_cutoff_and_offset(replay, config):
    eligible = make_detail(replay, "edge", "2026-10-28T21:00:00+02:00")
    api = FakeClient([summary(eligible)], [eligible])
    assert select_candidate(api, config, NOW).match_date.isoformat() == "2026-10-28T19:00:00+00:00"


def test_consumed_replay_and_duplicate_match_are_skipped(replay, config):
    consumed = make_detail(replay, "consumed", "2026-10-30T18:30:00Z")
    duplicate_list = make_detail(replay, "duplicate-list", "2026-10-30T18:20:00Z", "match-shared")
    duplicate_detail = make_detail(replay, "duplicate-detail", "2026-10-30T18:10:00Z", "match-shared")
    good = make_detail(replay, "good", "2026-10-30T17:00:00Z")
    api = FakeClient([summary(consumed), summary(duplicate_list, True), summary(duplicate_detail), summary(good)], [consumed, duplicate_list, duplicate_detail, good])
    store = FakeStore([{"id": "consumed", "key": "x", "status": "posted"}, {"id": "other-upload", "key": "match-shared", "status": "generated"}])
    result = select_candidate(api, config, NOW, store=store, record_duplicates=True)
    assert result.replay["id"] == "good"
    assert api.calls == ["duplicate-detail", "good"]
    assert store.duplicates == [("duplicate-list", "match-shared", "duplicate_match"), ("duplicate-detail", "match-shared", "duplicate_match")]


def test_preview_checks_duplicates_without_writing(replay, config):
    duplicate = make_detail(replay, "duplicate", "2026-10-30T18:00:00Z", "match-shared")
    api = FakeClient([summary(duplicate)], [duplicate])
    store = FakeStore([{"id": "other", "key": "match-shared", "status": "posted"}])
    assert select_candidate(api, config, NOW, store=store) is None
    assert store.duplicates == []


@pytest.mark.parametrize(("status", "attempts", "selected"), [
    ("generated", 0, False), ("posting", 0, False), ("posted", 0, False),
    ("skipped", 0, False), ("analysis_failed", 1, True), ("analysis_failed", 2, False),
])
def test_consumed_status_contract(replay, config, status, attempts, selected):
    detail = make_detail(replay, "target", "2026-10-30T18:00:00Z")
    api = FakeClient([summary(detail)], [detail])
    store = FakeStore([{"id": "target", "key": detail["match_guid"], "status": status, "attempts": attempts}])
    assert (select_candidate(api, config, NOW, store=store) is not None) is selected


def test_inspection_cap_counts_details_not_consumed_summaries(replay, config):
    a = make_detail(replay, "a", "2026-10-30T18:40:00Z")
    b = make_detail(replay, "b", "2026-10-30T18:30:00Z")
    c = make_detail(replay, "c", "2026-10-30T18:20:00Z")
    b["team_size"] = 2
    api = FakeClient([summary(a), summary(b), summary(c)], [a, b, c])
    store = FakeStore([{"id": "a", "key": "some", "status": "posted"}])
    assert select_candidate(api, replace(config, max_candidates_to_inspect=1), NOW, store=store) is None
    assert api.calls == ["b"]


def test_inconsistent_detail_date_and_id_are_ignored(replay, config):
    detail = make_detail(replay, "x", "2026-10-30T17:00:00Z")
    listing = {**summary(detail), "date": "2026-10-30T18:00:00Z"}
    api = FakeClient([listing], [detail])
    assert select_candidate(api, config, NOW) is None
    listing["id"] = "y"
    api = FakeClient([listing], [detail])
    api.details["y"] = detail
    assert select_candidate(api, config, NOW) is None


def test_match_key_precedence_and_fallback():
    assert match_key({"id": "id", "match_guid": "guid", "rocket_league_id": "game"}) == "guid"
    assert match_key({"id": "id", "rocket_league_id": "game"}) == "game"
    assert match_key({"id": "id"}) == "id"


def test_selection_with_real_store_blocks_duplicate_without_touching_backlog(tmp_path, replay, config):
    from rl_analyzer.store import Store

    original = make_detail(replay, "original", "2026-10-30T18:00:00Z", "match-shared")
    duplicate = make_detail(replay, "duplicate", "2026-10-30T18:00:00Z", "match-shared")
    backlog = make_detail(replay, "backlog", "2026-10-30T17:00:00Z")
    api = FakeClient([summary(duplicate), summary(backlog)], [duplicate, backlog])
    path = tmp_path / "test.sqlite3"
    with Store(path) as store:
        store.reserve_analysis(original, now=NOW)
        store.save_generated("original", "Ali won 3-2 with two demos. #RocketLeague", now=NOW)
        result = select_candidate(api, config, NOW, store=store, record_duplicates=True)
        assert result.replay["id"] == "backlog"
        assert store.get_replay("duplicate")["reason"] == "duplicate_match"
        assert store.get_replay("backlog") is None
    with Store(path, readonly=True) as store:
        assert store.match_is_consumed("match-shared", exclude_replay_id="another-upload")


def test_retry_from_other_upload_reuses_original_analysis_attempt(tmp_path, replay, config):
    from rl_analyzer.store import Store

    original = make_detail(replay, "original", "2026-10-30T18:00:00Z", "match-shared")
    duplicate = make_detail(replay, "duplicate", "2026-10-30T18:00:00Z", "match-shared")
    with Store(tmp_path / "test.sqlite3") as store:
        store.reserve_analysis(original, now=NOW)
        store.mark_analysis_failed("original", now=NOW)
        api = FakeClient([summary(duplicate)], [duplicate])
        candidate = select_candidate(api, config, NOW, store=store, record_duplicates=True)
        assert candidate.replay["id"] == "duplicate"
        owner = store.reserve_analysis(candidate.replay, match=candidate.stats["match"], now=NOW)
        assert (owner["replay_id"], owner["attempts"]) == ("original", 2)
        store.save_generated(owner["replay_id"], "Ali won 3-2 with two demos. #RocketLeague", now=NOW)
        assert select_candidate(api, config, NOW, store=store, record_duplicates=True) is None
        assert store.get_replay("duplicate")["reason"] == "duplicate_match"
