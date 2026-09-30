from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest

from gaium.aggregator import collect_usage, parse_window, write_calibration


class AggregatorTests(unittest.TestCase):
    def test_collects_jsonl_usage(self) -> None:
        with self.subTest("codex jsonl"):
            import tempfile

            with tempfile.TemporaryDirectory() as directory:
                log_root = Path(directory) / "sessions"
                log_root.mkdir()
                (log_root / "session.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps(
                                {
                                    "created_at": "2026-09-30T10:00:00Z",
                                    "model": "gpt-test",
                                    "usage": {"input_tokens": 100, "output_tokens": 40},
                                }
                            ),
                            json.dumps(
                                {
                                    "created_at": "2026-09-30T10:01:00Z",
                                    "model": "gpt-test-2",
                                    "prompt_tokens": 10,
                                    "completion_tokens": 5,
                                    "cost_usd": 0.01,
                                }
                            ),
                        ]
                    ),
                    encoding="utf-8",
                )

                state = collect_usage({"codex": [log_root]}, calibration_path=None)

                self.assertEqual(state["totals"]["input_tokens"], 110)
                self.assertEqual(state["totals"]["output_tokens"], 45)
                self.assertEqual(state["totals"]["total_tokens"], 155)
                self.assertEqual(state["totals"]["requests"], 2)
                self.assertEqual(state["agents"][0]["active_model"], "gpt-test-2")

    def test_collects_window_label(self) -> None:
        state = collect_usage({"codex": []}, window_label="month", calibration_path=None)

        self.assertEqual(state["window"]["label"], "month")

    def test_collects_codex_sqlite_threads(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "state_5.sqlite"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    create table threads (
                        id text primary key,
                        model text,
                        model_provider text,
                        tokens_used integer not null,
                        created_at integer,
                        created_at_ms integer,
                        updated_at integer,
                        updated_at_ms integer
                    )
                    """
                )
                connection.execute(
                    """
                    insert into threads (
                        id, model, model_provider, tokens_used, created_at, created_at_ms, updated_at, updated_at_ms
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "thread-1",
                        "gpt-5.5",
                        "openai",
                        1234,
                        1790780000,
                        1790780000000,
                        1790790000,
                        1790790000000,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            state = collect_usage({"codex": [db_path]}, calibration_path=None)

        self.assertEqual(state["totals"]["total_tokens"], 1234)
        self.assertEqual(state["totals"]["requests"], 1)
        self.assertEqual(state["agents"][0]["name"], "codex")
        self.assertEqual(state["agents"][0]["active_model"], "gpt-5.5")
        self.assertAlmostEqual(state["agents"][0]["cost_usd"], 0.00617)
        self.assertTrue(state["agents"][0]["cost_estimated"])
        self.assertEqual(state["agents"][0]["cost_notes"], ["total tokens only"])

    def test_estimates_claude_cache_pricing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            log_root = Path(directory)
            (log_root / "session.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-09-30T10:00:00Z",
                        "message": {
                            "model": "claude-opus-5",
                            "usage": {
                                "input_tokens": 2,
                                "cache_creation_input_tokens": 3000,
                                "cache_read_input_tokens": 3000,
                                "output_tokens": 400,
                                "cache_creation": {
                                    "ephemeral_5m_input_tokens": 1000,
                                    "ephemeral_1h_input_tokens": 2000,
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = collect_usage({"claude": [log_root]}, calibration_path=None)

        self.assertEqual(state["totals"]["total_tokens"], 6402)
        self.assertEqual(state["totals"]["cache_creation_input_tokens"], 3000)
        self.assertEqual(state["totals"]["cache_read_input_tokens"], 3000)
        self.assertAlmostEqual(state["totals"]["cost_usd"], 0.03776)
        self.assertFalse(state["totals"]["cost_estimated"])

    def test_applies_agent_cost_calibration(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "state_5.sqlite"
            calibration_path = root / "calibration.json"
            write_calibration({"codex": 0.5}, calibration_path)

            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    create table threads (
                        id text primary key,
                        model text,
                        model_provider text,
                        tokens_used integer not null,
                        created_at integer,
                        created_at_ms integer,
                        updated_at integer,
                        updated_at_ms integer
                    )
                    """
                )
                connection.execute(
                    """
                    insert into threads (
                        id, model, model_provider, tokens_used, created_at, created_at_ms, updated_at, updated_at_ms
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("thread-1", "gpt-5.5", "openai", 1000, 1790780000, 1790780000000, 1790790000, 1790790000000),
                )
                connection.commit()
            finally:
                connection.close()

            state = collect_usage({"codex": [db_path]}, calibration_path=calibration_path)

        self.assertAlmostEqual(state["agents"][0]["raw_cost_usd"], 0.005)
        self.assertAlmostEqual(state["agents"][0]["cost_usd"], 0.0025)
        self.assertEqual(state["agents"][0]["cost_calibration_factor"], 0.5)
        self.assertIn("calibrated", state["agents"][0]["cost_notes"])

    def test_ignores_missing_roots(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            state = collect_usage({"claude": [Path(directory) / "missing"]}, calibration_path=None)

        self.assertEqual(state["totals"]["total_tokens"], 0)
        self.assertEqual(state["agents"], [])

    def test_parse_month_window_starts_on_first_day(self) -> None:
        since, label = parse_window("month")

        self.assertEqual(label, "month")
        self.assertIsNotNone(since)
        assert since is not None
        local_since = since.astimezone()
        self.assertEqual(local_since.day, 1)
        self.assertEqual(local_since.hour, 0)
        self.assertEqual(local_since.minute, 0)
        self.assertEqual(local_since.second, 0)
        self.assertEqual(local_since.microsecond, 0)

    def test_parse_all_window_has_no_start(self) -> None:
        since, label = parse_window("all")

        self.assertIsNone(since)
        self.assertEqual(label, "all")


if __name__ == "__main__":
    unittest.main()
