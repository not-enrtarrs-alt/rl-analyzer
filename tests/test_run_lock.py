"""Lock tests use temporary files only."""

import json
import os
import time

import pytest

from rl_analyzer.run_lock import RunLock


def test_lock_is_atomic_and_released(tmp_path):
    path = tmp_path / "data" / "run.lock"
    with RunLock(path) as acquired:
        assert acquired
        assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid()
        with RunLock(path) as other:
            assert not other
        assert path.exists()
    assert not path.exists()


def test_stale_lock_is_removed_and_replaced(tmp_path):
    path = tmp_path / "run.lock"
    path.write_text("old", encoding="utf-8")
    old = time.time() - 7201
    os.utime(path, (old, old))
    with RunLock(path) as acquired:
        assert acquired and json.loads(path.read_text(encoding="utf-8"))["token"]
    assert not path.exists()


def test_lock_does_not_remove_new_owner(tmp_path):
    path = tmp_path / "run.lock"
    with RunLock(path) as acquired:
        assert acquired
        path.write_text('{"token":"other-owner"}', encoding="utf-8")
    assert path.exists()


def test_lock_released_on_exception(tmp_path):
    path = tmp_path / "run.lock"
    with pytest.raises(RuntimeError):
        with RunLock(path) as acquired:
            assert acquired
            raise RuntimeError("fail")
    assert not path.exists()
