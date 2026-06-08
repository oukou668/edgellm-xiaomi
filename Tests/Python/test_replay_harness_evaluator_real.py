#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "replay_harness_evaluator.py"
FIXTURE = ROOT / "fixtures" / "replay_harness_minimal" / "entries.jsonl"

spec = importlib.util.spec_from_file_location("replay_harness_evaluator", SCRIPT)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
sys.modules["replay_harness_evaluator"] = replay
spec.loader.exec_module(replay)


class RealHarnessReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        capabilities = replay.check_harness_capabilities()
        if not capabilities["ok"]:
            missing = [
                name
                for name, result in capabilities["required_imports"].items()
                if not result["available"]
            ]
            raise AssertionError(
                "Real harness tests require .venv-lm-eval-replay with lm-eval[math]. "
                f"Missing imports: {', '.join(missing)}"
            )
        cls.entries = replay.read_jsonl(FIXTURE)
        cls.evaluator = replay.ReplayEvaluator(
            task_parsers=replay.default_task_parsers(),
            aggregation_policy={entry["task_name"]: "avg" for entry in cls.entries},
            harness_commit=replay.harness_commit(),
        )
        cls.scored = cls.evaluator.evaluate(cls.entries)
        cls.by_case = {row["case_id"]: row for row in cls.scored}

    def test_fixture_expected_outputs(self) -> None:
        self.assertEqual(len(self.entries), len(self.scored))
        positive_families: set[str] = set()
        for entry in self.entries:
            row = self.by_case[entry["case_id"]]
            with self.subTest(case_id=entry["case_id"]):
                self.assertEqual(row["skipped_reason"], entry["expected_skip_reason"])
                self.assertNotEqual(row["skipped_reason"], "parser_error", row)
                if entry["expected_skip_reason"]:
                    self.assertFalse(row["supported_by_harness"], row)
                    self.assertIn(row["evaluation_status"], {"skipped", "error"})
                    self.assertEqual(row["answer_status"], "unscored")
                    self.assertFalse(row["is_wrong_answer"])
                    continue

                self.assertTrue(row["supported_by_harness"], row)
                self.assertEqual(row["evaluation_status"], "scored")
                self.assertIsInstance(row["score"], float)
                self.assertAlmostEqual(row["score"], float(entry["expected_score"]))
                self.assertEqual(row["extracted_answer"], entry["expected_extracted_answer"])
                expected_status = "correct" if float(entry["expected_score"]) >= 1.0 else "wrong"
                self.assertEqual(row["answer_status"], expected_status)
                self.assertEqual(row["is_wrong_answer"], expected_status == "wrong")
                self.assertIn("primary_metric", row)
                self.assertIn("scorer_name", row)
                self.assertIn("metrics", row)
                if entry["case_type"] == "positive":
                    positive_families.add(entry["task_name"])

        self.assertEqual(positive_families, set(replay.SUPPORTED_TASKS))

    def test_wrapper_matches_direct_harness_task_object_replay(self) -> None:
        direct_runner = replay.HarnessTaskReplayRunner()
        for entry in self.entries:
            if entry["expected_skip_reason"]:
                continue

            row = self.by_case[entry["case_id"]]
            with self.subTest(case_id=entry["case_id"]):
                doc = direct_runner.normalized_doc(entry["task_name"], entry)
                harness_task = direct_runner.resolve_harness_task(entry["task_name"], entry, doc)
                task = direct_runner.load_task(harness_task)
                filter_name = direct_runner.select_filter_name(task)
                filtered = direct_runner.apply_task_filter(task, entry["raw_generation"], doc, filter_name)
                direct_metrics = replay.json_safe_value(task.process_results(doc, [filtered]))
                self.assertEqual(row["metrics"], direct_metrics)
                if filter_name in replay.DISCRETE_FILTER_NAMES:
                    self.assertEqual(row["extracted_answer"], str(filtered))
                self.assertEqual(row["details"]["harness_task"], harness_task)

    def test_avgn_fixture_aggregation(self) -> None:
        aggregation = self.evaluator.aggregate(self.scored)
        avgn_row = next(row for row in aggregation["per_doc"] if row["doc_id"] == "fixture-avgn-1")
        expected = next(entry for entry in self.entries if entry.get("aggregation_fixture_group") == "fixture-avgn-mmlu-redux")

        self.assertEqual(avgn_row["repeat_count"], 3)
        self.assertEqual(avgn_row["supported_count"], 3)
        self.assertAlmostEqual(avgn_row["primary_avg"], expected["expected_primary_avg"])
        self.assertAlmostEqual(avgn_row["majority"], expected["expected_majority"])
        self.assertAlmostEqual(avgn_row["pass_at_k"], expected["expected_pass_at_k"])
        self.assertTrue(avgn_row["not_lm_eval_default_repeats"])
        self.assertEqual(avgn_row["aggregation_primary"], "avg")
        self.assertEqual(avgn_row["aggregation_secondary"], ["majority", "pass@k"])

    def test_report_summary_contains_scored_skipped_and_warning_levels(self) -> None:
        warnings = replay.warning_rows(self.scored)
        jobs = replay.build_jobs(self.scored)
        results = {
            "scoring_backend": replay.SCORING_BACKEND,
            "harness_commit": replay.harness_commit(),
            "tasks": self.scored,
            "jobs": jobs,
            "supported_matrix": replay.support_matrix(self.scored),
            "warnings": warnings,
            "summary": replay.build_run_summary(self.scored, jobs, warnings),
            "protocol_manifest": replay.build_protocol_manifest(
                self.scored,
                harness_commit_value=replay.harness_commit(),
                join_strategies=replay.load_join_strategies(),
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "report.md"
            replay.write_report(path, results)
            report = path.read_text(encoding="utf-8")

        summary = results["summary"]
        self.assertEqual(summary["entry_count"], len(self.entries))
        self.assertGreater(summary["scored_count"], 0)
        self.assertGreater(summary["skipped_count"], 0)
        self.assertGreater(summary["wrong_answer_count"], 0)
        self.assertEqual(summary["parser_error_count"], 0)
        self.assertEqual(summary["missing_lm_eval_dependency_count"], 0)
        self.assertIn("scored", summary["evaluation_status_histogram"])
        self.assertIn("wrong", summary["answer_status_histogram"])
        self.assertIn("gpqa_gated_dataset_skipped", summary["skip_reason_histogram"])
        self.assertIn("warning", summary["warning_level_counts"])
        self.assertIn("mmlu_pro", results["supported_matrix"])
        self.assertIn("scored_count", report)
        self.assertIn("wrong_answer_count", report)
        self.assertIn("## Outcome Status", report)
        self.assertIn("## Parser Families", report)
        self.assertIn("## Skip Reasons", report)
        self.assertIn("## Support Matrix", report)
        self.assertIn("## Wrong Answer Samples", report)


if __name__ == "__main__":
    unittest.main()
