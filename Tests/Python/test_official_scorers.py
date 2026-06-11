#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "run_official_scorers.py"
spec = importlib.util.spec_from_file_location("run_official_scorers", SCRIPT)
assert spec and spec.loader
official = importlib.util.module_from_spec(spec)
sys.modules["run_official_scorers"] = official
spec.loader.exec_module(official)

AGG_SCRIPT = SCRIPTS / "aggregate_official_evaluation.py"
agg_spec = importlib.util.spec_from_file_location("aggregate_official_evaluation", AGG_SCRIPT)
assert agg_spec and agg_spec.loader
aggregate = importlib.util.module_from_spec(agg_spec)
sys.modules["aggregate_official_evaluation"] = aggregate
agg_spec.loader.exec_module(aggregate)


SCORERS = {row["dataset_id"]: row for row in json.loads((ROOT / "configs/official_scorers_v1.json").read_text())["scorers"]}


def choice_id(choices):
    return official.replay.sha256_text(official.stable_json(choices))


class OfficialScorerTests(unittest.TestCase):
    def test_manifest_has_exactly_seven_blocker_scorers(self) -> None:
        self.assertEqual(
            set(SCORERS),
            {"gpqa_diamond", "supergpqa", "multi_if", "multichallenge", "aime26", "hmmt_feb_2026", "bbeh"},
        )
        for row in SCORERS.values():
            self.assertTrue(row["repo_url"])
            self.assertTrue(row["repo_commit"])
            self.assertTrue(row["entrypoint"])
            self.assertIsInstance(row["required_input_fields"], list)
            self.assertGreater(row["expected_sample_count"], 0)

    def test_gpqa_choice_order_gate_and_scoring(self) -> None:
        choices = ["red", "blue", "green", "yellow"]
        entry = {
            "task_name": "gpqa_diamond",
            "dataset_id": "gpqa_diamond",
            "doc_id": "gpqa1",
            "choice_order_id": choice_id(choices),
            "raw_generation": "The answer is (B).",
            "doc": {"choices": choices, "answer": "(B)"},
        }
        row = official.score_entry(entry, None, SCORERS["gpqa_diamond"], {}, False)
        self.assertEqual(row["score_status"], "scored")
        self.assertEqual(row["score"], 1.0)

        bad_entry = dict(entry)
        bad_entry["choice_order_id"] = "bad"
        blocked = official.score_entry(bad_entry, None, SCORERS["gpqa_diamond"], {}, False)
        self.assertEqual(blocked["evaluation_tier"], "blocker")
        self.assertEqual(blocked["blocked_reason"], "choice_order_mismatch")

    def test_prepare_full_gpqa_bundle_filters_to_198_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_root = pathlib.Path(tmp)
            artifact_root = out_root / "datasets"
            gpqa_dir = artifact_root / "gpqa_diamond"
            gpqa_dir.mkdir(parents=True)
            choices = ["alpha", "beta", "gamma", "delta"]
            with (gpqa_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
                for index in range(198):
                    row = {
                        "sample_id": f"gpqa_{index}",
                        "prompt": "Question?\n\nChoices:\nA. alpha\nB. beta\nC. gamma\nD. delta\n\nAnswer with the option letter only.",
                        "answer": "B",
                        "harness_replay_doc": {
                            "question": "Question?",
                            "choices": choices,
                            "options": choices,
                            "answer": "(B)",
                        },
                        "official_eval_metadata": {
                            "options": choices,
                            "answer_letter": "B",
                            "choice_order_id": choice_id(choices),
                        },
                    }
                    handle.write(json.dumps(row) + "\n")
            (gpqa_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "dataset_id": "gpqa_diamond",
                        "source_repo": "Idavidrein/gpqa",
                        "source_revision": "633f5ee89ab8ad4522a9f850766b73f62147ffdd",
                        "canonical_sample_count": 198,
                        "fetched_sample_count": 198,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prepare_table_reproduction_bundle.py"),
                    "--suite",
                    "full",
                    "--model-id",
                    "qwen3-0.6b-thinking-q4",
                    "--datasets",
                    "gpqa_diamond",
                    "--out-root",
                    str(out_root),
                    "--dataset-artifacts-dir",
                    str(artifact_root),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            bundle_dirs = [
                path
                for path in out_root.iterdir()
                if path.is_dir() and path.name.startswith("table_reproduction_")
            ]
            self.assertEqual(len(bundle_dirs), 1)
            bundle_dir = bundle_dirs[0]
            manifest = json.loads((bundle_dir / "bundle_manifest.json").read_text())
            with (bundle_dir / "benchmark.jsonl").open(encoding="utf-8") as handle:
                rows = [line for line in handle if line.strip()]
            self.assertEqual(manifest["selected_datasets"], ["gpqa_diamond"])
            self.assertEqual(manifest["datasets"], ["gpqa_diamond"])
            self.assertTrue(manifest["official_loop"])
            self.assertEqual(manifest["task_count"], 198)
            self.assertEqual(len(rows), 198)
            self.assertEqual(len(official.read_jsonl(bundle_dir / "benchmark.jsonl")), 198)

    def test_full_gpqa_official_rows_become_average_eligible_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report_dir = root / "report"
            report_dir.mkdir()
            choices = ["a", "b", "c", "d"]
            with (report_dir / "harness_replay_entries.jsonl").open("w", encoding="utf-8") as handle:
                for index in range(198):
                    entry = {
                        "task_name": "gpqa_diamond",
                        "dataset_id": "gpqa_diamond",
                        "dataset_name": "GPQA-Diamond",
                        "doc_id": f"gpqa_{index}",
                        "task_id": f"gpqa_diamond__gpqa_{index}",
                        "model_id": "model",
                        "prompt_text": "p",
                        "raw_generation": "The answer is (B).",
                        "gold": "B",
                        "choice_order_id": choice_id(choices),
                        "doc": {"choices": choices, "options": choices, "answer": "(B)"},
                    }
                    handle.write(json.dumps(entry) + "\n")
            scorer_out = report_dir / "official"
            run_args = official.build_arg_parser().parse_args(
                [
                    str(report_dir),
                    "--datasets",
                    "gpqa_diamond",
                    "--dataset-artifacts-dir",
                    str(root / "missing-datasets"),
                    "--out",
                    str(scorer_out),
                ]
            )
            result = official.run(run_args)
            self.assertEqual(result["datasets"]["gpqa_diamond"]["official_benchmark_count"], 198)
            rows = [json.loads(line) for line in (scorer_out / "official_scorer_rows.jsonl").read_text().splitlines()]
            self.assertTrue(all(row["official_benchmark"] and row["average_eligible"] for row in rows))

            agg_out = report_dir / "agg"
            agg_args = aggregate.build_arg_parser().parse_args(
                [
                    str(report_dir),
                    "--allow-missing-replay",
                    "--official-scorer-results",
                    str(scorer_out / "official_scorer_rows.jsonl"),
                    "--output-dir",
                    str(agg_out),
                ]
            )
            merged = aggregate.aggregate(agg_args)
            gpqa = merged["coverage_report"]["datasets"]["gpqa_diamond"]
            self.assertEqual(gpqa["coverage_status"], "covered")
            self.assertEqual(gpqa["average_eligible_count"], 198)
            self.assertEqual(merged["official_average_status"], "available")

    def test_supergpqa_option_content_fallback(self) -> None:
        entry = {
            "task_name": "supergpqa",
            "dataset_id": "supergpqa",
            "doc_id": "s1",
            "raw_generation": "After checking, the answer is beta.",
            "doc": {"options": ["alpha", "beta", "gamma"], "answer": "B"},
        }
        sample = {
            "sample_id": "s1",
            "answer": "B",
            "difficulty": "hard",
            "official_eval_metadata": {
                "options": ["alpha", "beta", "gamma"],
                "answer_letter": "B",
                "discipline": "science",
                "field": "physics",
                "subfield": "mechanics",
                "difficulty": "hard",
            },
        }
        row = official.score_entry(entry, sample, SCORERS["supergpqa"], {}, False)
        self.assertEqual(row["score_status"], "scored")
        self.assertEqual(row["score"], 1.0)
        self.assertEqual(row["scorer_details"]["subfield"], "mechanics")

    def test_multi_if_strict_loose_metrics(self) -> None:
        entry = {
            "task_name": "multi_if",
            "dataset_id": "multi_if",
            "doc_id": "m1",
            "raw_generation": "hello there what are they doing?",
            "doc": {
                "key": "m1",
                "language": "English",
                "turn_2_instruction_id_list": '["change_case:english_lowercase", "startend:end_checker"]',
                "turn_2_kwargs": '["{}", "{\\"end_phrase\\": \\"what are they doing?\\"}"]',
                "turn_1_prompt": '{"role":"user","content":"say hello"}',
                "turn_2_prompt": '{"role":"user","content":"end correctly"}',
            },
        }
        row = official.score_entry(entry, None, SCORERS["multi_if"], {}, False)
        self.assertEqual(row["score_status"], "scored")
        self.assertEqual(row["score"], 1.0)
        self.assertTrue(row["scorer_details"]["prompt_level_strict_acc"])

        negative = dict(entry)
        negative["raw_generation"] = "HELLO THERE"
        row = official.score_entry(negative, None, SCORERS["multi_if"], {}, False)
        self.assertEqual(row["score"], 0.0)
        self.assertFalse(row["scorer_details"]["prompt_level_strict_acc"])

    def test_multichallenge_requires_locked_judge_and_supports_mock_for_tests(self) -> None:
        entry = {
            "task_name": "multichallenge",
            "dataset_id": "multichallenge",
            "doc_id": "q1",
            "raw_generation": "I followed the instruction.",
            "doc": {
                "question_id": "q1",
                "axis": "COHERENCE",
                "conversation": [{"role": "user", "content": "hello"}],
                "target_question": "Does it follow the instruction?",
                "pass_criteria": "YES",
            },
        }
        blocked = official.score_entry(entry, None, SCORERS["multichallenge"], {}, False)
        self.assertEqual(blocked["evaluation_tier"], "blocker")
        self.assertEqual(blocked["blocked_reason"], "multichallenge_judge_config_not_locked")

        judge = {
            "judge_config_id": "fixture-judge",
            "judge_model": "fixture",
            "judge_prompt_sha256": "abc",
            "mock_verdicts": {"q1": {"verdict": "YES", "reasoning": "passes"}},
        }
        row = official.score_entry(entry, None, SCORERS["multichallenge"], judge, True)
        self.assertEqual(row["score_status"], "scored")
        self.assertEqual(row["score"], 1.0)
        self.assertEqual(row["scorer_details"]["axis"], "COHERENCE")

    def test_matharena_and_bbeh_scoring(self) -> None:
        aime = official.score_entry(
            {
                "task_name": "aime26",
                "dataset_id": "aime26",
                "doc_id": "1",
                "repeat_index": 0,
                "raw_generation": "The final answer is \\boxed{277}.",
                "doc": {"answer": "277"},
                "output_tokens": 10,
            },
            None,
            SCORERS["aime26"],
            {},
            False,
        )
        self.assertEqual(aime["score"], 1.0)

        hmmt = official.score_entry(
            {
                "task_name": "hmmt_feb_2026",
                "dataset_id": "hmmt_feb_2026",
                "doc_id": "1",
                "raw_generation": "Thus the answer is -\\frac{1}{21}.",
                "doc": {"answer": "-\\frac{1}{21}"},
                "output_tokens": 12,
            },
            None,
            SCORERS["hmmt_feb_2026"],
            {},
            False,
        )
        self.assertEqual(hmmt["score"], 1.0)
        self.assertEqual(hmmt["parse_status"], "parsed")

        bbeh = official.score_entry(
            {
                "task_name": "bbeh",
                "dataset_id": "bbeh",
                "doc_id": "b1",
                "raw_generation": "Ok The answer is: (A)",
                "doc": {"target": "a"},
            },
            None,
            SCORERS["bbeh"],
            {},
            False,
        )
        self.assertEqual(bbeh["score"], 1.0)

    def test_cli_and_aggregation_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report_dir = root / "report"
            report_dir.mkdir()
            artifact_dir = root / "datasets"
            (artifact_dir / "bbeh").mkdir(parents=True)
            (artifact_dir / "bbeh" / "samples.jsonl").write_text(
                json.dumps({"sample_id": "b1", "answer": "4", "harness_replay_doc": {"target": "4"}}) + "\n",
                encoding="utf-8",
            )
            entry = {
                "task_name": "bbeh",
                "dataset_id": "bbeh",
                "dataset_name": "BBEH",
                "doc_id": "b1",
                "task_id": "bbeh__b1",
                "model_id": "model",
                "prompt_text": "p",
                "raw_generation": "The final answer is: \\boxed{4}.",
                "gold": "4",
                "doc": {"target": "4"},
            }
            (report_dir / "harness_replay_entries.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
            out_dir = report_dir / "official"
            args = official.build_arg_parser().parse_args(
                [
                    str(report_dir),
                    "--datasets",
                    "bbeh",
                    "--dataset-artifacts-dir",
                    str(artifact_dir),
                    "--out",
                    str(out_dir),
                ]
            )
            result = official.run(args)
            self.assertEqual(result["official_scorer_result_count"], 1)
            self.assertTrue((out_dir / "official_scorer_rows.jsonl").is_file())

            replay_results = report_dir / "harness_replay_results.json"
            replay_results.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "task_name": "bbeh",
                                "dataset_id": "bbeh",
                                "evaluation_tier": "blocker",
                                "coverage_status": "unsupported",
                                "skipped_reason": "harness_task_not_supported",
                                "blocker": {"task_name": "bbeh", "blocker_type": "official_native_required"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            agg_out = report_dir / "agg"
            agg_args = aggregate.build_arg_parser().parse_args(
                [
                    str(report_dir),
                    "--replay-results",
                    str(replay_results),
                    "--official-scorer-results",
                    str(out_dir / "official_scorer_rows.jsonl"),
                    "--output-dir",
                    str(agg_out),
                ]
            )
            merged = aggregate.aggregate(agg_args)
            self.assertEqual(merged["official_average_status"], "no official average yet")
            self.assertEqual(merged["coverage_report"]["datasets"]["bbeh"]["coverage_status"], "partial")
            self.assertTrue((agg_out / "leaderboard_report.md").is_file())


if __name__ == "__main__":
    unittest.main()
