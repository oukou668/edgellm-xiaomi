#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "replay_harness_evaluator.py"
SUITE = ROOT / "configs" / "table_reproduction_v1.json"

spec = importlib.util.spec_from_file_location("replay_harness_evaluator_policy", SCRIPT)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
sys.modules["replay_harness_evaluator_policy"] = replay
spec.loader.exec_module(replay)


def parser_with_score(score=1.0, primary_metric="exact_match", harness_task="task"):
    def parser(raw, entry):
        return {
            "metrics": {primary_metric: score},
            "primary_metric": primary_metric,
            "parser_name": "harness_task_filter_process_results",
            "scorer_name": "lm_eval_task_process_results",
            "gold": entry.get("gold", ""),
            "details": {"harness_task": harness_task},
        }

    return parser


class EvaluationPolicyTests(unittest.TestCase):
    def test_all_formal_datasets_have_scorer_policy(self) -> None:
        suite = json.loads(SUITE.read_text())
        self.assertEqual(len(suite["datasets"]), 13)
        for dataset in suite["datasets"]:
            self.assertIn(dataset["preferred_scorer_backend"], {"harness_native", "official_native", "judge_native"})
            self.assertIn(dataset["required_coverage"], {"full_dataset", "full_group", "avg16"})
            self.assertFalse(dataset["main_leaderboard_eligible"])

    def test_full_group_subtask_replay_is_pipeline_test(self) -> None:
        evaluator = replay.ReplayEvaluator(
            {"mmlu_pro": parser_with_score(harness_task="mmlu_pro_math")},
            {"mmlu_pro": "avg"},
        )
        row = evaluator.evaluate(
            [
                {
                    "task_name": "mmlu_pro",
                    "raw_generation": "answer is B",
                    "prompt_text": "p",
                    "gold": "B",
                    "doc": {"answer": "B", "source_subtask": "math"},
                }
            ]
        )[0]
        self.assertEqual(row["evaluation_tier"], "pipeline_test")
        self.assertEqual(row["coverage_status"], "partial")
        self.assertFalse(row["average_eligible"])
        self.assertFalse(row["official_benchmark"])

    def test_reference_replay_is_not_average_eligible(self) -> None:
        evaluator = replay.ReplayEvaluator(
            {"ifeval": parser_with_score(primary_metric="prompt_level_strict_acc", harness_task="ifeval")},
            {"ifeval": "avg"},
        )
        row = evaluator.evaluate(
            [
                {
                    "task_name": "ifeval",
                    "raw_generation": "answer",
                    "prompt_text": "p",
                    "doc": {"key": 1, "prompt": "p", "instruction_id_list": ["x"], "kwargs": [{}]},
                    "sample_denominator": 541,
                }
            ]
        )[0]
        self.assertEqual(row["evaluation_tier"], "reference_replay")
        self.assertEqual(row["coverage_status"], "partial")
        self.assertFalse(row["average_eligible"])

    def test_official_benchmark_requires_complete_gate(self) -> None:
        prompt = "p"
        protocol = {
            "fewshot_examples_sha256": "few",
            "official_harness_fewshot_examples_sha256": "few",
            "choice_order_sha256": "choices",
            "official_harness_choice_order_sha256": "choices",
            "generation_kwargs_sha256": "gen",
            "official_harness_generation_kwargs_sha256": "gen",
            "stop_sequences_sha256": "stop",
            "official_harness_stop_sequences_sha256": "stop",
            "observed_repeats": 1,
            "expected_repeats": 1,
        }
        evaluator = replay.ReplayEvaluator(
            {"ifeval": parser_with_score(primary_metric="prompt_level_strict_acc", harness_task="ifeval")},
            {"ifeval": "avg"},
        )
        row = evaluator.evaluate(
            [
                {
                    "task_name": "ifeval",
                    "raw_generation": "answer",
                    "prompt_text": prompt,
                    "prompt_sha256": replay.sha256_text(prompt),
                    "official_harness_prompt_sha256": replay.sha256_text(prompt),
                    "protocol": protocol,
                    "doc": {"key": 1, "prompt": prompt, "instruction_id_list": ["x"], "kwargs": [{}]},
                    "sample_denominator": 541,
                    "dataset_revision": "rev",
                    "official_dataset_revision": "rev",
                    "official_parser_id": "ifeval_instruction_parser_v1",
                    "official_scorer_id": "ifeval_official_v1",
                    "official_aggregation": "avg",
                    "official_sample_count": 541,
                }
            ]
        )[0]
        self.assertEqual(row["evaluation_tier"], "official_benchmark")
        self.assertEqual(row["coverage_status"], "covered")
        self.assertTrue(row["average_eligible"])
        self.assertTrue(row["official_benchmark"])

    def test_skipped_rows_emit_structured_blocker(self) -> None:
        evaluator = replay.ReplayEvaluator({}, {})
        row = evaluator.evaluate([{"task_name": "supergpqa", "raw_generation": "A", "prompt_text": "p"}])[0]
        self.assertEqual(row["evaluation_tier"], "blocker")
        self.assertEqual(row["coverage_status"], "unsupported")
        self.assertFalse(row["average_eligible"])
        self.assertEqual(row["blocker"]["blocker_type"], "official_native_required")

    def test_coverage_report_excludes_non_official_rows_from_average(self) -> None:
        rows = [
            {
                "task_name": "mmlu_pro",
                "dataset_id": "mmlu_pro",
                "evaluation_tier": "pipeline_test",
                "coverage_status": "partial",
                "average_eligible": False,
                "score": 1.0,
            },
            {
                "task_name": "supergpqa",
                "dataset_id": "supergpqa",
                "evaluation_tier": "blocker",
                "coverage_status": "unsupported",
                "average_eligible": False,
                "skipped_reason": "harness_task_not_supported",
                "blocker": {"task_name": "supergpqa", "blocker_type": "official_native_required"},
            },
        ]
        report = replay.build_coverage_report(rows)
        self.assertEqual(report["summary"]["official_average_status"], "no official average yet")
        self.assertEqual(report["datasets"]["mmlu_pro"]["average_eligible_count"], 0)
        self.assertGreaterEqual(report["summary"]["blocked_dataset_count"], 1)


if __name__ == "__main__":
    unittest.main()
