#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "replay_harness_evaluator.py"

spec = importlib.util.spec_from_file_location("replay_harness_evaluator_android", SCRIPT)
assert spec and spec.loader
replay = importlib.util.module_from_spec(spec)
sys.modules["replay_harness_evaluator_android"] = replay
spec.loader.exec_module(replay)


class FakeFilterEnsemble:
    def __init__(self, name, components):
        self.name = name
        self.components = components

    def apply(self, instances):
        for inst in instances:
            values = inst.resps
            for function, kwargs in self.components:
                if function == "regex":
                    pattern = re.compile(kwargs["regex_pattern"])
                    matches = pattern.findall(values[0])
                    values = [str(matches[kwargs.get("group_select", 0)]).strip() if matches else "[invalid]"]
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
    OUTPUT_TYPE = "generate_until"

    def __init__(self, harness_task):
        self.harness_task = harness_task
        self.config = types.SimpleNamespace(doc_to_choice=True)
        self._filters = [FakeFilterEnsemble("default", [("regex", {"regex_pattern": r"([ABCD])"}), ("take_first", {})])]

    def doc_to_choice(self, doc):
        return doc.get("choices") or []

    def doc_to_target(self, doc):
        return doc.get("answer", "")

    def process_results(self, doc, results):
        target = self.doc_to_target(doc)
        if isinstance(target, int):
            target = "ABCD"[target]
        return {"exact_match": 1.0 if str(results[0]) == str(target) else 0.0}


class FakeTaskManager:
    def load(self, task_names):
        return {"tasks": {task_name: FakeTask(task_name) for task_name in task_names}}


class AndroidHarnessReplayExportTests(unittest.TestCase):
    def tearDown(self) -> None:
        for name in list(sys.modules):
            if name.startswith("lm_eval"):
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
        api = types.ModuleType("lm_eval.api")
        sys.modules["lm_eval"] = lm_eval
        sys.modules["lm_eval.tasks"] = tasks
        sys.modules["lm_eval.filters"] = filters
        sys.modules["lm_eval.api"] = api
        sys.modules["lm_eval.api.instance"] = instance
        sys.modules["lm_eval.api.metrics"] = metrics

    def test_loads_android_harness_replay_entries_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = pathlib.Path(tmp)
            entry = {
                "task_name": "mmlu_redux",
                "dataset_id": "mmlu_redux",
                "dataset_name": "MMLU-Redux",
                "harness_task": "mmlu_redux_abstract_algebra_generative",
                "doc_id": "abstract_algebra_0",
                "prompt_text": "p",
                "raw_generation": "C",
                "gold": "C",
                "doc": {"question": "q", "dataset_name": "abstract_algebra", "choices": ["a", "b", "c", "d"], "answer": 2},
            }
            (report_dir / "harness_replay_entries.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

            rows = replay.load_android_report_entries(report_dir, None)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_name"], "mmlu_redux")
            self.assertEqual(rows[0]["raw_generation"], "C")
            self.assertEqual(rows[0]["source_export_dir"], str(report_dir))

    def test_converts_legacy_raw_evidence_to_replay_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = pathlib.Path(tmp)
            raw = {
                "run": {"run_id": "run-1"},
                "resolved_prompt": "p",
                "raw_generation": "B",
                "task_result": {
                    "task_id": "mmlu_redux__abstract_algebra_0",
                    "category": "mmlu_redux",
                    "model_id": "model",
                    "repeat_index": 0,
                    "expected_answer": "B",
                    "formal_metadata": {
                        "dataset_id": "mmlu_redux",
                        "sample_id": "abstract_algebra_0",
                        "harness_replay": {
                            "task_name": "mmlu_redux",
                            "dataset_id": "mmlu_redux",
                            "dataset_name": "MMLU-Redux",
                            "harness_task": "mmlu_redux_abstract_algebra_generative",
                            "doc": {"question": "q", "dataset_name": "abstract_algebra", "choices": ["a", "b", "c", "d"], "answer": 1},
                        },
                    },
                },
            }
            (report_dir / "raw_evidence.jsonl").write_text(json.dumps(raw) + "\n", encoding="utf-8")

            rows = replay.load_android_report_entries(report_dir, {"mmlu_redux"})

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["doc_id"], "abstract_algebra_0")
            self.assertEqual(rows[0]["raw_generation"], "B")
            self.assertEqual(rows[0]["summary_id"], "run-1")

    def test_mmlu_redux_letter_gold_is_normalized_to_choice_index(self) -> None:
        self.assertEqual(replay.letter_answer_to_index("D"), 3)
        self.assertEqual(replay.letter_answer_to_index("B"), 1)
        self.assertEqual(replay.letter_answer_to_index(2), 2)

    def test_score_export_scores_android_report_with_fake_harness(self) -> None:
        self.install_fake_harness()
        with tempfile.TemporaryDirectory() as tmp:
            report_dir = pathlib.Path(tmp)
            output_dir = report_dir / "analysis"
            entry = {
                "task_name": "mmlu_redux",
                "dataset_id": "mmlu_redux",
                "dataset_name": "MMLU-Redux",
                "harness_task": "mmlu_redux_abstract_algebra_generative",
                "doc_id": "abstract_algebra_0",
                "model_id": "model",
                "prompt_text": "p",
                "raw_generation": "C",
                "gold": "C",
                "doc": {"question": "q", "dataset_name": "abstract_algebra", "choices": ["a", "b", "c", "d"], "answer": 2},
            }
            (report_dir / "harness_replay_entries.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")

            args = replay.build_arg_parser().parse_args([str(report_dir), "--output-dir", str(output_dir)])
            results = replay.score_export(args)

            self.assertEqual(results["summary"]["scored_count"], 1)
            self.assertEqual(results["tasks"][0]["score"], 1.0)
            self.assertTrue((output_dir / "harness_replay_results.json").is_file())


if __name__ == "__main__":
    unittest.main()
