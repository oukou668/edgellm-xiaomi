#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "replay_harness_evaluator.py"

spec = importlib.util.spec_from_file_location("replay_harness_evaluator", SCRIPT)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
sys.modules["replay_harness_evaluator"] = replay
spec.loader.exec_module(replay)


class FakeFilterEnsemble:
    def __init__(self, name, components):
        self.name = name
        self.components = components

    def apply(self, instances):
        for inst in instances:
            values = inst.resps
            for function, kwargs in self.components:
                kwargs = kwargs or {}
                if function == "regex":
                    pattern = re.compile(kwargs["regex_pattern"])
                    filtered = []
                    for value in values:
                        matches = pattern.findall(value)
                        if not matches:
                            filtered.append("[invalid]")
                            continue
                        match = matches[kwargs.get("group_select", 0)]
                        if isinstance(match, tuple):
                            match = next((item for item in match if item), "[invalid]")
                        filtered.append(str(match).strip())
                    values = filtered
                elif function == "multi_choice_regex":
                    pattern = re.compile(kwargs["regex_pattern"])
                    filtered = []
                    for value in values:
                        matches = pattern.findall(value)
                        filtered.append(str(matches[kwargs.get("group_select", 0)]).strip() if matches else "[invalid]")
                    values = filtered
                elif function == "take_first":
                    values = values[0]
            inst.filtered_resps[self.name] = values


class FakeInstance:
    def __init__(self, request_type, doc, arguments, idx, resps):
        self.request_type = request_type
        self.doc = doc
        self.arguments = arguments
        self.idx = idx
        self.resps = resps
        self.filtered_resps = {}


class FakeTask:
    def __init__(self, harness_task):
        self.harness_task = harness_task
        self.OUTPUT_TYPE = "generate_until"
        self.config = types.SimpleNamespace(doc_to_choice=True)
        if harness_task.startswith("mmlu_pro_"):
            self._filters = [
                FakeFilterEnsemble(
                    "custom-extract",
                    [("regex", {"regex_pattern": r"answer is \(?([ABCDEFGHIJ])\)?"}), ("take_first", None)],
                )
            ]
        elif harness_task.startswith("mmlu_redux_"):
            self._filters = [FakeFilterEnsemble("default", [("regex", {"regex_pattern": r"([ABCD])"}), ("take_first", None)])]
        else:
            self._filters = [FakeFilterEnsemble("none", [("take_first", None)])]

    def doc_to_choice(self, doc):
        return doc.get("choices") or doc.get("options") or []

    def doc_to_target(self, doc):
        return doc.get("answer", doc.get("target", ""))

    def process_results(self, doc, results):
        prediction = str(results[0])
        target = self.doc_to_target(doc)
        if isinstance(target, int):
            target = "ABCD"[target]
        if self.harness_task == "ifeval":
            ok = "latency" in prediction
            return {"prompt_level_strict_acc": ok}
        return {"exact_match": 1.0 if prediction == str(target) else 0.0}


class FakeTaskManager:
    def load(self, task_names):
        return {"tasks": {task_name: FakeTask(task_name) for task_name in task_names}}


class ReplayHarnessEvaluatorTests(unittest.TestCase):
    def tearDown(self) -> None:
        for name in list(sys.modules):
            if name.startswith("lm_eval") or name == "datasets":
                sys.modules.pop(name, None)

    def install_fake_harness(self) -> None:
        lm_eval = types.ModuleType("lm_eval")
        tasks = types.ModuleType("lm_eval.tasks")
        tasks.TaskManager = FakeTaskManager
        filters = types.ModuleType("lm_eval.filters")
        filters.build_filter_ensemble = lambda name, components: FakeFilterEnsemble(name, components)
        instance = types.ModuleType("lm_eval.api.instance")
        instance.Instance = FakeInstance
        metrics = types.ModuleType("lm_eval.api.metrics")

        def exact_match_hf_evaluate(predictions, references, ignore_case=False, ignore_punctuation=False, **_):
            pred = predictions[0]
            ref = references[0]
            if ignore_case:
                pred = pred.lower()
                ref = ref.lower()
            if ignore_punctuation:
                pred = re.sub(r"[^\w\s]", "", pred)
                ref = re.sub(r"[^\w\s]", "", ref)
            return {"exact_match": 1.0 if pred == ref else 0.0}

        api = types.ModuleType("lm_eval.api")
        metrics.exact_match_hf_evaluate = exact_match_hf_evaluate
        sys.modules["lm_eval"] = lm_eval
        sys.modules["lm_eval.tasks"] = tasks
        sys.modules["lm_eval.filters"] = filters
        sys.modules["lm_eval.api"] = api
        sys.modules["lm_eval.api.instance"] = instance
        sys.modules["lm_eval.api.metrics"] = metrics

    def test_dispatch_skip_and_error_capture(self) -> None:
        evaluator = replay.ReplayEvaluator(
            task_parsers={
                "ok": lambda raw, entry: {
                    "extracted_answer": raw,
                    "gold": " raw ",
                    "primary_metric": "exact_match",
                    "metric_config": {"ignore_case": False, "ignore_punctuation": False},
                    "parser_name": "ok_parser",
                },
                "boom": lambda raw, entry: (_ for _ in ()).throw(RuntimeError("bad parser")),
            },
            aggregation_policy={"ok": "avg"},
        )
        rows = evaluator.evaluate(
            [
                {"task_name": "ok", "raw_generation": " raw ", "prompt_text": "p"},
                {"task_name": "missing", "raw_generation": "x", "prompt_text": "p"},
                {"task_name": "boom", "raw_generation": "x", "prompt_text": "p"},
            ]
        )

        self.assertTrue(rows[0]["supported_by_harness"])
        self.assertEqual(rows[0]["extracted_answer"], " raw ")
        self.assertEqual(rows[0]["evaluation_status"], "scored")
        self.assertEqual(rows[0]["answer_status"], "correct")
        self.assertFalse(rows[0]["is_wrong_answer"])
        self.assertEqual(rows[1]["skipped_reason"], "unsupported_task")
        self.assertEqual(rows[1]["evaluation_status"], "skipped")
        self.assertEqual(rows[2]["skipped_reason"], "parser_error")
        self.assertEqual(rows[2]["evaluation_status"], "error")
        self.assertTrue(rows[2]["is_error"])

    def test_wrapper_does_not_pre_strip_raw_generation(self) -> None:
        seen = {}

        def parser(raw, _):
            seen["raw"] = raw
            return {"metrics": {"prompt_level_strict_acc": False}, "primary_metric": "prompt_level_strict_acc", "parser_name": "raw_parser"}

        evaluator = replay.ReplayEvaluator({"ifeval": parser}, {"ifeval": "avg"})
        evaluator.evaluate([{"task_name": "ifeval", "raw_generation": "\n  keep spaces  \n", "prompt_text": ""}])
        self.assertEqual(seen["raw"], "\n  keep spaces  \n")

    def test_protocol_officialness_requires_all_hashes(self) -> None:
        evaluator = replay.ReplayEvaluator({"ok": lambda raw, entry: {"metrics": {"exact_match": 1}, "primary_metric": "exact_match"}}, {})
        row = evaluator.evaluate([{"task_name": "ok", "raw_generation": "", "prompt_text": "prompt"}])[0]
        self.assertFalse(row["official_benchmark"])
        self.assertTrue(row["not_official_same_protocol"])
        self.assertIn("official_protocol_unavailable", row["protocol_mismatches"])

    def test_mmlu_pro_uses_harness_filter_pipeline(self) -> None:
        self.install_fake_harness()
        result = replay.HarnessTaskReplayRunner().run(
            "mmlu_pro",
            "The answer is (B).",
            {"doc": {"answer": "B", "source_subtask": "math"}, "gold": "B"},
        )
        score, metrics, primary_metric, scorer_name = replay.score_parser_output("mmlu_pro", result)
        self.assertEqual(result["extracted_answer"], "B")
        self.assertEqual(metrics["exact_match"], 1.0)
        self.assertEqual(score, 1.0)
        self.assertEqual(primary_metric, "exact_match")
        self.assertEqual(scorer_name, "lm_eval_task_process_results")
        self.assertEqual(result["details"]["harness_task"], "mmlu_pro_math")

    def test_ifeval_task_process_results_is_called_without_cleaning(self) -> None:
        self.install_fake_harness()
        doc = {"key": 1, "prompt": "p", "instruction_id_list": ["x"], "kwargs": [{}]}
        result = replay.HarnessTaskReplayRunner().run("ifeval", "\n latency \n", {"doc": doc})
        score, metrics, primary_metric, _ = replay.score_parser_output("ifeval", result)
        self.assertEqual(score, 1.0)
        self.assertEqual(metrics["prompt_level_strict_acc"], True)
        self.assertEqual(primary_metric, "prompt_level_strict_acc")
        self.assertEqual(result["details"]["filtered_response"], "\n latency \n")

    def test_missing_dependency_returns_skip_not_crash(self) -> None:
        evaluator = replay.ReplayEvaluator(replay.default_task_parsers(), {"ifeval": "avg"})
        row = evaluator.evaluate(
            [
                {
                    "task_name": "ifeval",
                    "raw_generation": "answer",
                    "prompt_text": "p",
                    "doc": {"key": 1, "prompt": "p", "instruction_id_list": ["x"], "kwargs": [{}]},
                }
            ]
        )[0]
        self.assertFalse(row["supported_by_harness"])
        self.assertEqual(row["skipped_reason"], "missing_lm_eval_dependency")
        self.assertEqual(row["details"]["missing_module"], "lm_eval.tasks")

    def test_aggregation_avg_majority_pass_at_k(self) -> None:
        evaluator = replay.ReplayEvaluator({}, {})
        rows = [
            {
                "model_id": "m",
                "dataset_name": "AIME-2025",
                "task_name": "aime25",
                "doc_id": "1",
                "supported_by_harness": True,
                "evaluation_status": "scored",
                "answer_status": "wrong",
                "is_wrong_answer": True,
                "is_error": False,
                "score": 0.0,
                "extracted_answer": "41",
                "gold": "42",
            },
            {
                "model_id": "m",
                "dataset_name": "AIME-2025",
                "task_name": "aime25",
                "doc_id": "1",
                "supported_by_harness": True,
                "evaluation_status": "scored",
                "answer_status": "correct",
                "is_wrong_answer": False,
                "is_error": False,
                "score": 1.0,
                "extracted_answer": "42",
                "gold": "42",
            },
        ]
        aggregated = evaluator.aggregate(rows)["per_doc"][0]
        self.assertEqual(aggregated["primary_avg"], 0.5)
        self.assertEqual(aggregated["pass_at_k"], 1.0)
        self.assertEqual(aggregated["aggregation_primary"], "avg")
        self.assertTrue(aggregated["not_lm_eval_default_repeats"])

    def test_join_strategy_config_covers_supported_and_known_skipped_tasks(self) -> None:
        strategies = replay.load_join_strategies()
        for task_name in replay.SUPPORTED_TASKS:
            self.assertIn(task_name, strategies)
            self.assertIn("replayability_status", strategies[task_name])
            self.assertIn("required_doc_fields", strategies[task_name])
        for task_name in replay.UNSUPPORTED_TASKS:
            self.assertIn(task_name, strategies)

    def test_enrichment_failure_taxonomy_does_not_emit_generic_join_reason(self) -> None:
        strategies = replay.load_join_strategies()

        cases = []
        enricher = replay.OfficialDocEnricher(strategies)
        enricher.indexes["mmlu_pro"] = {"by_question": {}, "by_question_choices": {}}
        cases.append(("prompt_not_joinable", enricher, {"task_name": "mmlu_pro", "doc": {"question": "no match", "options": ["a"]}}))

        enricher = replay.OfficialDocEnricher(strategies)
        enricher.indexes["mmlu_pro"] = {"by_question": {replay.question_key("q"): {"question": "q", "answer": ""}}, "by_question_choices": {}}
        cases.append(("missing_gold", enricher, {"task_name": "mmlu_pro", "doc": {"question": "q"}}))

        enricher = replay.OfficialDocEnricher(strategies)
        enricher.indexes["ifeval"] = {"prompt": {"prompt": "prompt", "key": 1}}
        cases.append(("missing_instruction_ids", enricher, {"task_name": "ifeval", "doc": {"prompt": "prompt"}}))

        enricher = replay.OfficialDocEnricher(strategies)
        enricher.indexes["math500"] = {replay.question_key("p"): {"problem": "p", "answer": "42"}}
        cases.append(("missing_solution", enricher, {"task_name": "math500", "doc": {"problem": "p"}}))

        enricher = replay.OfficialDocEnricher(strategies)
        cases.append(("missing_bbh_subtask", enricher, {"task_name": "bbh", "doc": {"input": "q"}}))

        enricher = replay.OfficialDocEnricher(strategies)
        enricher.indexes["aime25"] = {}
        cases.append(("missing_stable_doc_id", enricher, {"task_name": "aime25", "doc": {}}))

        for expected_reason, enricher, entry in cases:
            with self.subTest(expected_reason=expected_reason):
                row = enricher.enrich(entry)
                self.assertEqual(row["pre_skip_reason"], expected_reason)
                self.assertEqual(row["official_doc_join_failure_reason"], expected_reason)
                self.assertNotEqual(row["pre_skip_reason"], "missing_official_doc_join")
                self.assertEqual(row["official_doc_join_details"]["parent_reason"], "missing_official_doc_join")

    def test_gpqa_is_gated_skip_not_parser_error(self) -> None:
        evaluator = replay.ReplayEvaluator(replay.default_task_parsers(), {})
        row = evaluator.evaluate([{"task_name": "gpqa_diamond", "raw_generation": "The answer is (C).", "prompt_text": "p"}])[0]
        self.assertEqual(row["skipped_reason"], "gpqa_gated_dataset_skipped")
        self.assertEqual(row["evaluation_status"], "skipped")
        self.assertFalse(row["is_error"])

    def test_dataset_load_failure_taxonomy(self) -> None:
        datasets = types.ModuleType("datasets")

        def unknown_split(*_, **__):
            raise ValueError("Unknown split test")

        datasets.load_dataset = unknown_split
        sys.modules["datasets"] = datasets
        with self.assertRaises(replay.ReplaySkip) as split_error:
            replay.load_dataset_rows("x", split="test")
        self.assertEqual(split_error.exception.reason, "missing_dataset_split")

        def generic_failure(*_, **__):
            raise RuntimeError("network unavailable")

        datasets.load_dataset = generic_failure
        with self.assertRaises(replay.ReplaySkip) as load_error:
            replay.load_dataset_rows("x", split="test")
        self.assertEqual(load_error.exception.reason, "official_dataset_load_failed")

    def test_join_summary_and_protocol_manifest_counts(self) -> None:
        rows = [
            {
                "task_name": "mmlu_pro",
                "supported_by_harness": True,
                "evaluation_status": "scored",
                "answer_status": "correct",
                "is_wrong_answer": False,
                "is_error": False,
                "score": 1.0,
                "official_doc_join_attempted": True,
                "official_doc_join_success": True,
                "official_benchmark": False,
                "protocol_mismatches": ["official_protocol_unavailable"],
                "prompt_text": "p",
                "prompt_sha256": replay.sha256_text("p"),
            },
            {
                "task_name": "mmlu_pro",
                "supported_by_harness": False,
                "evaluation_status": "skipped",
                "answer_status": "unscored",
                "is_wrong_answer": False,
                "is_error": False,
                "score": "",
                "skipped_reason": "prompt_not_joinable",
                "official_doc_join_attempted": True,
                "official_doc_join_success": False,
                "official_doc_join_failure_reason": "prompt_not_joinable",
                "official_benchmark": False,
                "protocol_mismatches": ["official_protocol_unavailable"],
                "prompt_text": "q",
            },
            {
                "task_name": "ifeval",
                "supported_by_harness": False,
                "evaluation_status": "skipped",
                "answer_status": "unscored",
                "is_wrong_answer": False,
                "is_error": False,
                "score": "",
                "skipped_reason": "not_in_phase1_harness_supported_tasks",
                "official_doc_join_attempted": False,
                "official_doc_join_success": False,
                "official_benchmark": False,
                "protocol_mismatches": ["official_protocol_unavailable"],
                "prompt_text": "r",
            },
        ]
        warnings = replay.warning_rows(rows)
        summary = replay.build_run_summary(rows, replay.build_jobs(rows), warnings)
        self.assertEqual(summary["official_doc_join_attempted_count"], 2)
        self.assertEqual(summary["official_doc_join_success_count"], 1)
        self.assertEqual(summary["official_doc_join_failed_count"], 1)
        self.assertEqual(summary["official_doc_join_failure_histogram"], {"prompt_not_joinable": 1})
        self.assertEqual(summary["wrong_answer_count"], 0)
        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["evaluation_status_histogram"], {"scored": 1, "skipped": 2})

        manifest = replay.build_protocol_manifest(
            rows,
            harness_commit_value="commit",
            join_strategies=replay.load_join_strategies(),
        )
        self.assertEqual(manifest["tasks"]["mmlu_pro"]["official_compatible_count"], 0)
        self.assertEqual(manifest["tasks"]["mmlu_pro"]["official_incompatible_count"], 2)
        self.assertEqual(manifest["tasks"]["mmlu_pro"]["fields"]["prompt"]["unavailable_count"], 2)

    def test_wrong_answer_is_not_skip_or_error(self) -> None:
        self.install_fake_harness()
        evaluator = replay.ReplayEvaluator(replay.default_task_parsers(), {"mmlu_pro": "avg"})
        row = evaluator.evaluate(
            [
                {
                    "task_name": "mmlu_pro",
                    "raw_generation": "The answer is (C).",
                    "prompt_text": "p",
                    "gold": "B",
                    "doc": {"question": "q", "answer": "B", "source_subtask": "math", "options": ["a", "b", "c"]},
                }
            ]
        )[0]

        self.assertTrue(row["supported_by_harness"])
        self.assertEqual(row["score"], 0.0)
        self.assertEqual(row["evaluation_status"], "scored")
        self.assertEqual(row["answer_status"], "wrong")
        self.assertTrue(row["is_wrong_answer"])
        self.assertFalse(row["is_skipped"])
        self.assertFalse(row["is_error"])
        self.assertEqual(row["skipped_reason"], "")

    def test_evaluator_manifest_is_machine_readable(self) -> None:
        manifest = replay.build_evaluator_manifest(
            harness_commit_value="commit",
            join_strategies=replay.load_join_strategies(),
            harness_capabilities={"ok": True},
        )

        self.assertEqual(manifest["raw_generation_source"], "iphone_export_tasks_jsonl")
        self.assertTrue(manifest["parser_scorer_separated"])
        self.assertFalse(manifest["model_calls"])
        self.assertTrue(manifest["lm_eval_task_object_replay"])
        self.assertFalse(manifest["legacy_quick20_scorer"])
        self.assertIn("mmlu_pro", manifest["tasks"])
        self.assertEqual(manifest["tasks"]["mmlu_pro"]["parser"], "harness_task_filter_process_results")
        self.assertEqual(manifest["tasks"]["mmlu_pro"]["scorer"], "lm_eval_task_process_results")
        self.assertIn("bfclv4", manifest["unsupported_tasks"])


if __name__ == "__main__":
    unittest.main()
