from __future__ import annotations

import time

from executor.heartbeat import (
    clear,
    executor_is_live,
    heartbeat_path,
    refuse_if_executor_is_live,
    seconds_since_heartbeat,
    touch,
)


class TestHeartbeat:
    def test_a_fresh_touch_reads_as_live(self, tmp_path) -> None:
        marker = tmp_path / "hb"
        touch(marker)

        assert executor_is_live(marker) is True
        assert seconds_since_heartbeat(marker) < 5

    def test_no_marker_at_all_is_not_live(self, tmp_path) -> None:
        assert seconds_since_heartbeat(tmp_path / "absent") is None
        assert executor_is_live(tmp_path / "absent") is False

    def test_an_old_marker_goes_stale_rather_than_blocking_forever(self, tmp_path) -> None:
        # A killed executor must not leave a lock that blocks every future
        # batch run — staleness is the whole reason this is a timestamp and
        # not a PID lock.
        marker = tmp_path / "hb"
        marker.write_text(str(time.time() - 3600), encoding="utf-8")

        assert executor_is_live(marker, max_age_seconds=600) is False

    def test_a_corrupt_marker_is_treated_as_absent(self, tmp_path) -> None:
        marker = tmp_path / "hb"
        marker.write_text("not-a-timestamp", encoding="utf-8")

        assert seconds_since_heartbeat(marker) is None
        assert executor_is_live(marker) is False

    def test_touch_never_raises_on_an_unwritable_path(self, tmp_path) -> None:
        # A missing heartbeat costs a batch tool its guard; it must never take
        # down the executor's poll loop.
        unwritable = tmp_path / "hb"
        unwritable.mkdir()

        touch(unwritable)

    def test_heartbeat_path_honours_the_environment(self) -> None:
        assert heartbeat_path({"JARVIS_EXECUTOR_HEARTBEAT": "custom/path"}).as_posix() == "custom/path"

    def test_clear_removes_a_touched_marker(self, tmp_path) -> None:
        marker = tmp_path / "hb"
        touch(marker)
        assert marker.exists()

        clear(marker)

        assert not marker.exists()
        # A cleared marker must read exactly like an executor that never
        # started -- no stale-but-present file left behind.
        assert seconds_since_heartbeat(marker) is None
        assert executor_is_live(marker) is False

    def test_clear_never_raises_when_there_is_nothing_to_clear(self, tmp_path) -> None:
        # A missing heartbeat only costs a batch tool its guard; clear() must
        # never take down a clean shutdown over an already-absent file.
        clear(tmp_path / "absent")

    def test_clear_never_raises_on_an_unremovable_path(self, tmp_path) -> None:
        unremovable = tmp_path / "hb"
        unremovable.mkdir()  # a directory can't be unlink()'d -- OSError

        clear(unremovable)


class TestRefusal:
    def test_refuses_while_the_executor_is_live_and_explains_why(self, tmp_path) -> None:
        marker = tmp_path / "hb"
        touch(marker)

        message = refuse_if_executor_is_live("Distilling", path=marker)

        assert message is not None
        assert "executor is running" in message
        assert "--force" in message

    def test_allows_when_the_executor_is_stopped(self, tmp_path) -> None:
        assert refuse_if_executor_is_live("Distilling", path=tmp_path / "absent") is None

    def test_allows_when_the_marker_is_stale(self, tmp_path) -> None:
        marker = tmp_path / "hb"
        marker.write_text(str(time.time() - 3600), encoding="utf-8")

        assert refuse_if_executor_is_live("Distilling", path=marker, max_age_seconds=600) is None
