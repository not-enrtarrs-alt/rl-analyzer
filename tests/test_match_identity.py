"""Duplicate uploads remain deduplicated across partial match identifiers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from rl_analyzer.select import match_key, select_candidate
from rl_analyzer.store import Store, StoreError

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
TEXT = "Ali won 3-2 with two demos. #RocketLeague"


class SingleReplay:
    def __init__(self, detail, *, list_identifiers):
        self.detail = detail
        self.list_identifiers = list_identifiers
        self.detail_calls = 0

    def list_common_replays(self, ids, cutoff):
        keys = ("id", "date", "playlist_id", "match_guid", "rocket_league_id") if self.list_identifiers else ("id", "date", "playlist_id")
        return [{key: self.detail[key] for key in keys if key in self.detail}]

    def get_replay(self, replay_id):
        self.detail_calls += 1
        return self.detail


@pytest.mark.parametrize(("original_guid", "duplicate_guid", "list_identifiers"), [
    ("GUID-1", None, False), ("GUID-1", None, True),
    (None, "GUID-1", False), (None, "GUID-1", True),
])
def test_partial_identifiers_block_duplicate_selection(tmp_path, config, replay, original_guid, duplicate_guid, list_identifiers):
    original = {**replay, "id": "upload-1", "match_guid": original_guid, "rocket_league_id": "GAME-1"}
    duplicate = {**replay, "id": "upload-2", "match_guid": duplicate_guid, "rocket_league_id": "game-1"}
    api = SingleReplay(duplicate, list_identifiers=list_identifiers)
    with Store(tmp_path / "db.sqlite3") as store:
        store.reserve_analysis(original, now=NOW)
        store.save_generated("upload-1", TEXT, now=NOW)
        assert select_candidate(api, config, NOW, store=store, record_duplicates=True) is None
        assert store.get_replay("upload-2")["reason"] == "duplicate_match"
        with pytest.raises(StoreError, match="already consumed"):
            store.reserve_analysis(duplicate, now=NOW)
        assert api.detail_calls == (0 if list_identifiers else 1)


def test_retry_reuses_owner_when_guid_appears_later(tmp_path, replay):
    original = {**replay, "id": "upload-1", "match_guid": None, "rocket_league_id": "GAME-1"}
    duplicate = {**replay, "id": "upload-2", "match_guid": "GUID-1", "rocket_league_id": "game-1"}
    with Store(tmp_path / "db.sqlite3") as store:
        store.reserve_analysis(original, now=NOW)
        store.mark_analysis_failed("upload-1", now=NOW)
        retry = store.reserve_analysis(duplicate, now=NOW)
        assert (retry["replay_id"], retry["attempts"], retry["match_guid"]) == ("upload-1", 2, "GUID-1")
        store.save_generated("upload-1", TEXT, now=NOW)
        assert store.match_is_consumed("guid-1", exclude_replay_id="upload-3", match_guid="guid-1")


def test_conflicting_retry_identifiers_fail_closed(tmp_path, replay):
    original = {**replay, "id": "upload-1", "match_guid": "GUID-1", "rocket_league_id": "GAME-1"}
    duplicate = {**replay, "id": "upload-2", "match_guid": "GUID-2", "rocket_league_id": "GAME-1"}
    with Store(tmp_path / "db.sqlite3") as store:
        store.reserve_analysis(original, now=NOW)
        store.mark_analysis_failed("upload-1", now=NOW)
        with pytest.raises(StoreError, match="Conflicting match identifiers"):
            store.reserve_analysis(duplicate, now=NOW)
        assert store.get_replay("upload-1")["attempts"] == 1


def test_same_upload_can_retry_with_different_identifier_case(tmp_path, replay):
    first = {**replay, "id": "upload-1", "match_guid": "GUID-1", "rocket_league_id": "GAME-1"}
    second = {**first, "match_guid": "guid-1", "rocket_league_id": "game-1"}
    with Store(tmp_path / "db.sqlite3") as store:
        store.reserve_analysis(first, now=NOW)
        store.mark_analysis_failed("upload-1", now=NOW)
        assert store.reserve_analysis(second, now=NOW)["attempts"] == 2


def test_unrelated_identifiers_remain_eligible(tmp_path, replay):
    first = {**replay, "id": "upload-1", "match_guid": "GUID-1", "rocket_league_id": "GAME-1"}
    other = {**replay, "id": "upload-2", "match_guid": "GUID-2", "rocket_league_id": "GAME-2"}
    with Store(tmp_path / "db.sqlite3") as store:
        store.reserve_analysis(first, now=NOW)
        store.save_generated("upload-1", TEXT, now=NOW)
        assert store.reserve_analysis(other, now=NOW)["replay_id"] == "upload-2"


def test_concurrent_partial_identifiers_allow_one_reservation(tmp_path, replay):
    path = tmp_path / "db.sqlite3"
    with Store(path):
        pass
    barrier = Barrier(2)
    uploads = [{**replay, "id": "upload-1", "match_guid": None},
               {**replay, "id": "upload-2", "match_guid": "GUID-1"}]

    def attempt(item):
        with Store(path) as store:
            barrier.wait(timeout=10)
            try:
                store.reserve_analysis(item, now=NOW)
                return "reserved"
            except StoreError:
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, uploads)) == ["blocked", "reserved"]


def test_pipeline_never_calls_ai_for_partial_identifier_duplicate(tmp_path, config, replay):
    from rl_analyzer.pipeline import run_daily

    original = {**replay, "id": "upload-1", "match_guid": "GUID-1", "rocket_league_id": "GAME-1"}
    duplicate = {**replay, "id": "upload-2", "match_guid": None, "rocket_league_id": "GAME-1"}
    with Store(config.database_path) as store:
        store.reserve_analysis(original, now=NOW)
        store.save_generated("upload-1", TEXT, now=NOW)
        store.mark_manual_delivered("upload-1", now=NOW)

    class NoAI:
        calls = 0

        def generate(self, system, user):
            self.calls += 1
            raise AssertionError("AI must not be called")

    provider = NoAI()
    assert run_daily(config=config, force=True, client=SingleReplay(duplicate, list_identifiers=False),
                     provider=provider, lock_path=tmp_path / "run.lock", clock=lambda: NOW) == 0
    assert provider.calls == 0
    with Store(config.database_path, readonly=True) as store:
        assert store.get_replay("upload-2")["reason"] == "duplicate_match"
