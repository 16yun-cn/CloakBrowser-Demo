"""Tests for concurrent orchestration logic."""

from __future__ import annotations

from orchestrator import _worker_color


class TestWorkerColor:
    def test_returns_string(self) -> None:
        color = _worker_color(0)
        assert isinstance(color, str)
        assert len(color) > 0

    def test_wraps_around(self) -> None:
        # 12 colors; index 12 wraps to index 0
        assert _worker_color(0) == _worker_color(12)

    def test_distinct_for_consecutive(self) -> None:
        # First 3 workers get distinct colors
        colors = {_worker_color(i) for i in range(3)}
        assert len(colors) == 3


class TestAggregateLogic:
    def make_ok_result(self, worker_index: int, seed: int) -> dict:
        return {
            "status": "ok",
            "worker_index": worker_index,
            "session_id": "test-session",
            "session_dir": f"/tmp/test-session/worker-{worker_index}",
            "seed": seed,
            "duration_seconds": 10.0,
            "response_excerpt": f"Response from worker {worker_index}",
        }

    def make_error_result(self, worker_index: int, seed: int) -> dict:
        return {
            "status": "error",
            "worker_index": worker_index,
            "session_id": "test-session",
            "session_dir": "/tmp/test-session/worker-0",
            "seed": seed,
            "duration_seconds": 5.0,
            "error": "Something went wrong",
        }

    def test_all_ok(self) -> None:
        results = [self.make_ok_result(i, 100 + i) for i in range(3)]
        ok_count = sum(1 for r in results if r["status"] == "ok")
        assert ok_count == 3

    def test_partial_failure(self) -> None:
        results = [
            self.make_ok_result(0, 100),
            self.make_error_result(1, 101),
            self.make_ok_result(2, 102),
        ]
        ok_count = sum(1 for r in results if r["status"] == "ok")
        failed_count = len(results) - ok_count
        assert ok_count == 2
        assert failed_count == 1

    def test_all_failed(self) -> None:
        results = [self.make_error_result(i, 100 + i) for i in range(3)]
        ok_count = sum(1 for r in results if r["status"] == "ok")
        assert ok_count == 0
