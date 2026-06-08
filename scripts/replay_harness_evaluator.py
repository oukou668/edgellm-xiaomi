#!/usr/bin/env python3
"""Lightweight replay evaluator that reuses lm-evaluation-harness parsers.

This script never calls a model and never invokes ``lm_eval.simple_evaluate``.
It treats exported iPhone ``rawGeneration`` values as stored generate-until
responses, dispatches them to task-specific parser wrappers, and records clear
skip reasons when the installed harness or required official doc fields are not
available.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.metadata
import json
import numbers
import pathlib
import re
import string
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable


ROOT = pathlib.Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "LLMBenchmarkApp" / "Resources"
CONFIGS = ROOT / "Configs"
JOIN_STRATEGIES_PATH = CONFIGS / "harness_replay_join_strategies.json"
TABLE_REPRODUCTION_SUITE_PATH = ROOT / "configs" / "table_reproduction_v1.json"

HARNESS_COMMIT = "95d580638385578c1c07fa554cf16ad7f5b5f460"
SCORING_BACKEND = "lm_eval_harness_task_object_replay"
DEFAULT_AGGREGATION = "avg"

EVALUATION_TIERS = {"pipeline_test", "reference_replay", "official_partial", "official_benchmark", "blocker"}
COVERAGE_STATUSES = {"covered", "partial", "blocked", "unsupported"}
FULL_GROUP_TASKS = {"mmlu_pro", "mmlu_redux", "bbh"}
AVG16_TASKS = {"aime25", "aime26", "hmmt_feb_2026"}
REFERENCE_REPLAY_TASKS = {"ifeval", "math500", "aime25"}

BLOCKER_CATALOG: dict[str, dict[str, str]] = {
    "gpqa_diamond": {
        "blocker_type": "missing_gated_processed_doc",
        "message": "GPQA-Diamond replay requires the gated processed document and saved choice order.",
        "remediation": "Export lm-eval processed GPQA doc fields and choice order from the prompt builder before scoring.",
    },
    "supergpqa": {
        "blocker_type": "official_native_required",
        "message": "SuperGPQA should use the official native scorer over the full discipline set.",
        "remediation": "Integrate the official SuperGPQA evaluator and verify all required official fields.",
    },
    "multi_if": {
        "blocker_type": "official_native_required",
        "message": "Multi-IF requires official multi-turn and multilingual transcript scoring.",
        "remediation": "Integrate the official Multi-IF scorer and preserve full turn-level transcripts.",
    },
    "multichallenge": {
        "blocker_type": "judge_native_required",
        "message": "MultiChallenge requires a locked judge model, version, and prompt.",
        "remediation": "Add judge-native scoring only after judge config is fixed and recorded.",
    },
    "aime26": {
        "blocker_type": "matharena_official_native_required",
        "message": "AIME26 is not available as a native task in the pinned harness.",
        "remediation": "Use MathArena official-native exact integer scoring with @Avg16 aggregation.",
    },
    "hmmt_feb_2026": {
        "blocker_type": "matharena_official_native_required",
        "message": "HMMT Feb 2026 is not available as a native task in the pinned harness.",
        "remediation": "Use MathArena official-native math-expression normalization with @Avg16 aggregation.",
    },
    "bbeh": {
        "blocker_type": "official_native_required",
        "message": "BBEH should use the official bbeh/evaluate.py full-set evaluator.",
        "remediation": "Integrate official bbeh/evaluate.py over the full 4520 examples.",
    },
}

REQUIRED_HARNESS_MODULES = [
    "lm_eval.tasks",
    "lm_eval.api.instance",
    "lm_eval.filters",
    "lm_eval.api.metrics",
    "lm_eval.tasks.ifeval.utils",
    "lm_eval.tasks.aime.utils",
    "lm_eval.tasks.minerva_math.utils",
    "lm_eval.tasks.hendrycks_math.utils",
]

SUPPORTED_TASKS: dict[str, dict[str, str]] = {
    "mmlu_pro": {
        "dataset_name": "MMLU-Pro",
        "harness_source": "lm_eval/tasks/mmlu_pro",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "exact_match",
        "metric_type": "accuracy",
    },
    "mmlu_redux": {
        "dataset_name": "MMLU-Redux",
        "harness_source": "lm_eval/tasks/mmlu-redux/generative",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "exact_match",
        "metric_type": "accuracy",
    },
    "ifeval": {
        "dataset_name": "IFEval",
        "harness_source": "lm_eval/tasks/ifeval/ifeval.yaml",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "prompt_level_strict_acc",
        "metric_type": "pass_rate",
    },
    "aime25": {
        "dataset_name": "AIME-2025",
        "harness_source": "lm_eval/tasks/aime/aime25.yaml",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "exact_match",
        "metric_type": "accuracy",
    },
    "math500": {
        "dataset_name": "MATH-500",
        "harness_source": "lm_eval/tasks/minerva_math/minerva_math500.yaml",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "math_verify",
        "metric_type": "accuracy",
    },
    "bbh": {
        "dataset_name": "BBH",
        "harness_source": "lm_eval/tasks/bbh/*",
        "parser": "harness_task_filter_process_results",
        "scorer": "lm_eval_task_process_results",
        "primary_metric": "exact_match",
        "metric_type": "accuracy",
    },
}

UNSUPPORTED_TASKS = {
    "gpqa_diamond": "gpqa_gated_dataset_skipped",
    "supergpqa": "harness_task_not_supported",
    "lcb_pro_2502_easy": "harness_task_not_supported",
    "ojbench": "harness_task_not_supported",
    "lcb_v6_avg3": "harness_task_not_supported",
    "ifbench": "harness_task_not_supported",
    "multi_if": "harness_task_not_supported",
    "multichallenge": "harness_task_not_supported",
    "aime26": "harness_task_not_supported",
    "hmmt_feb_2026": "harness_task_not_supported",
    "bbeh": "harness_task_not_supported",
    "bfclv4": "harness_task_not_supported",
    "tau2_bench_telecom_aa": "harness_task_not_supported",
    "ceval": "not_in_phase1_harness_supported_tasks",
    "squad": "not_in_phase1_harness_supported_tasks",
}

DATASET_ID_TO_TASK = {
    "mmlu_pro_quick_20": "mmlu_pro",
    "mmlu_pro": "mmlu_pro",
    "mmlu-redux": "mmlu_redux",
    "mmlu_redux": "mmlu_redux",
    "gpqa_diamond": "gpqa_diamond",
    "gpqa-diamond": "gpqa_diamond",
    "ifeval": "ifeval",
    "ifeval_lite_quick_20": "ifeval",
    "aime25": "aime25",
    "aime_2025": "aime25",
    "math500_quick_20": "math500",
    "math_500": "math500",
    "math500": "math500",
    "bbh_quick_20": "bbh",
    "bbh": "bbh",
    "ceval_quick_20": "ceval",
    "squad_v1_quick_20": "squad",
}

PLANNED_DATASET_ALIASES = {
    "MMLU-Pro": "mmlu_pro",
    "MMLU-Redux": "mmlu_redux",
    "GPQA-Diamond": "gpqa_diamond",
    "IFEval": "ifeval",
    "AIME-2025": "aime25",
    "MATH-500": "math500",
    "BBH": "bbh",
    "SuperGPQA": "supergpqa",
    "LCB-Pro 2502(Easy)": "lcb_pro_2502_easy",
    "OJBench": "ojbench",
    "LCB-v6(@Avg3)": "lcb_v6_avg3",
    "IFBench": "ifbench",
    "Multi-IF": "multi_if",
    "MultiChallenge": "multichallenge",
    "AIME-2026": "aime26",
    "HMMT Feb 2026": "hmmt_feb_2026",
    "BBEH": "bbeh",
    "BFCLv4": "bfclv4",
    "τ²-Bench Telecom-AA": "tau2_bench_telecom_aa",
}


class ReplaySkip(Exception):
    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def short_hash(value: Any) -> str:
    return sha256_text(str(value or ""))[:16]


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_join_strategies() -> dict[str, dict[str, Any]]:
    if not JOIN_STRATEGIES_PATH.exists():
        return {}
    return read_json(JOIN_STRATEGIES_PATH)


def load_table_reproduction_suite() -> dict[str, Any]:
    if not TABLE_REPRODUCTION_SUITE_PATH.exists():
        return {"datasets": []}
    return read_json(TABLE_REPRODUCTION_SUITE_PATH)


def table_dataset_policies() -> dict[str, dict[str, Any]]:
    suite = load_table_reproduction_suite()
    return {str(row.get("dataset_id")): row for row in suite.get("datasets", []) if row.get("dataset_id")}


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def import_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - import failures become explicit skip reasons.
        raise ReplaySkip("missing_lm_eval_dependency", {"missing_module": name, "error": str(exc)}) from exc


def check_harness_capabilities() -> dict[str, Any]:
    imports: dict[str, dict[str, Any]] = {}
    ok = True
    for module in REQUIRED_HARNESS_MODULES:
        try:
            importlib.import_module(module)
            imports[module] = {"available": True, "error": ""}
        except Exception as exc:  # noqa: BLE001 - this is diagnostic output.
            ok = False
            imports[module] = {"available": False, "error": str(exc)}
    return {
        "ok": ok,
        "harness_commit": harness_commit(),
        "harness_version": harness_version(),
        "required_imports": imports,
    }


def normalize_task_name(value: str) -> str:
    stripped = value.strip()
    if stripped in PLANNED_DATASET_ALIASES:
        return PLANNED_DATASET_ALIASES[stripped]
    lowered = stripped.lower().replace("-", "_").replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")
    return DATASET_ID_TO_TASK.get(stripped, DATASET_ID_TO_TASK.get(lowered, lowered))


def metric_value(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, numbers.Number):
        return float(value)
    if hasattr(value, "item"):
        return metric_value(value.item())
    if isinstance(value, list):
        return sum(metric_value(item) for item in value) / len(value) if value else 0.0
    return 0.0


def json_safe_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    if isinstance(value, numbers.Number):
        return float(value)
    if hasattr(value, "item"):
        return json_safe_value(value.item())
    if isinstance(value, list):
        return [json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    return str(value)


def exact_match_score(prediction: str, gold: str, *, ignore_case: bool, ignore_punctuation: bool) -> float:
    try:
        metrics = importlib.import_module("lm_eval.api.metrics")
        result = metrics.exact_match_hf_evaluate(
            predictions=[prediction],
            references=[gold],
            ignore_case=ignore_case,
            ignore_punctuation=ignore_punctuation,
        )
        return float(result["exact_match"])
    except Exception:
        pred = prediction
        ref = gold
        if ignore_case:
            pred = pred.lower()
            ref = ref.lower()
        if ignore_punctuation:
            table = str.maketrans("", "", string.punctuation)
            pred = pred.translate(table)
            ref = ref.translate(table)
        return 1.0 if pred == ref else 0.0


def default_primary_metric(task_name: str) -> str:
    return SUPPORTED_TASKS.get(task_name, {}).get("primary_metric", "")


def default_scorer_name(task_name: str) -> str:
    return SUPPORTED_TASKS.get(task_name, {}).get("scorer", "")


def answer_status(score: Any) -> str:
    if score == "" or score is None:
        return "unscored"
    value = float(score)
    if value >= 1.0:
        return "correct"
    if value <= 0.0:
        return "wrong"
    return "partial"


def evaluation_status_for_skip(reason: str) -> str:
    if reason in ERROR_SKIP_REASONS or any(reason.startswith(prefix) for prefix in ERROR_SKIP_PREFIXES):
        return "error"
    return "skipped"


def dataset_version_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    doc = entry.get("doc") if isinstance(entry.get("doc"), dict) else {}
    if isinstance(doc, dict) and isinstance(doc.get("_harness_replay_dataset_version"), dict):
        return dict(doc["_harness_replay_dataset_version"])
    details = entry.get("official_doc_join_details") if isinstance(entry.get("official_doc_join_details"), dict) else {}
    strategy = entry.get("official_doc_join_strategy") or entry.get("task_name") or ""
    return {
        "dataset_path": details.get("dataset_path", ""),
        "dataset_name": details.get("dataset_name", ""),
        "split": details.get("split", ""),
        "revision": details.get("revision", ""),
        "fingerprint": details.get("fingerprint", ""),
        "source": strategy,
    }


def score_parser_output(task_name: str, parsed: dict[str, Any]) -> tuple[float, dict[str, Any], str, str]:
    primary_metric = str(parsed.get("primary_metric") or default_primary_metric(task_name))
    scorer_name = str(parsed.get("scorer_name") or default_scorer_name(task_name))
    metrics = json_safe_value(dict(parsed.get("metrics") or {}))

    if primary_metric == "exact_match" and "exact_match" not in metrics:
        prediction = str(parsed.get("extracted_answer") or "")
        gold = str(parsed.get("gold") or "")
        metric_config = parsed.get("metric_config") if isinstance(parsed.get("metric_config"), dict) else {}
        score = exact_match_score(
            prediction,
            gold,
            ignore_case=bool(metric_config.get("ignore_case", True)),
            ignore_punctuation=bool(metric_config.get("ignore_punctuation", True)),
        )
        metrics["exact_match"] = score
        scorer_name = scorer_name or "exact_match_hf_evaluate"
        return score, metrics, primary_metric, scorer_name

    if primary_metric and primary_metric in metrics:
        scorer_name = scorer_name or "metric_value"
        return metric_value(metrics.get(primary_metric)), metrics, primary_metric, scorer_name

    scorer_name = scorer_name or "metric_value"
    return 0.0, metrics, primary_metric, scorer_name


HARNESS_FILTER_PRIORITY = ("custom-extract", "default", "flexible-extract", "get-answer", "none")
DISCRETE_FILTER_NAMES = {"custom-extract", "default", "flexible-extract", "get-answer", "strict-match"}


def normalize_harness_suffix(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def letter_answer_to_index(value: Any) -> Any:
    text = str(value or "").strip().upper()
    if len(text) == 1 and "A" <= text <= "Z":
        return ord(text) - ord("A")
    return value


def require_fields(doc: dict[str, Any], fields: list[str], reason_prefix: str) -> None:
    missing = [field for field in fields if field not in doc]
    if missing:
        raise ReplaySkip(reason_prefix, {"missing_fields": missing})


def protocol_mismatches(entry: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    prompt_text = str(entry.get("prompt_text") or entry.get("prompt") or "")
    prompt_sha = str(entry.get("prompt_sha256") or sha256_text(prompt_text))
    official_prompt_sha = entry.get("official_harness_prompt_sha256")
    if official_prompt_sha is None:
        mismatches.append("official_protocol_unavailable")
    elif prompt_sha != official_prompt_sha:
        mismatches.append("prompt_sha256")

    protocol = entry.get("protocol") or {}
    comparisons = [
        ("fewshot_examples_sha256", "official_harness_fewshot_examples_sha256"),
        ("choice_order_sha256", "official_harness_choice_order_sha256"),
        ("generation_kwargs_sha256", "official_harness_generation_kwargs_sha256"),
        ("stop_sequences_sha256", "official_harness_stop_sequences_sha256"),
    ]
    for actual_key, official_key in comparisons:
        actual = protocol.get(actual_key) or entry.get(actual_key)
        expected = protocol.get(official_key) or entry.get(official_key)
        if expected is None:
            if "official_protocol_unavailable" not in mismatches:
                mismatches.append("official_protocol_unavailable")
        elif actual != expected:
            mismatches.append(actual_key)

    expected_commit = entry.get("official_harness_commit")
    if expected_commit is not None and expected_commit != entry.get("harness_commit", HARNESS_COMMIT):
        mismatches.append("harness_commit")

    expected_repeats = protocol.get("expected_repeats") or entry.get("expected_repeats")
    if expected_repeats is not None:
        observed = protocol.get("observed_repeats") or entry.get("observed_repeats")
        if observed != expected_repeats:
            mismatches.append("repeat_count")
    return sorted(set(mismatches))


def official_gate_failures(row: dict[str, Any]) -> list[str]:
    failures = list(row.get("protocol_mismatches") or [])
    required_actual_fields = {
        "prompt_sha256": row.get("prompt_sha256"),
        "generation_kwargs_sha256": (row.get("protocol") or {}).get("generation_kwargs_sha256") or row.get("generation_kwargs_sha256"),
        "dataset_revision": row.get("dataset_revision") or row.get("source_revision"),
        "parser_name": row.get("parser_name"),
        "scorer_name": row.get("scorer_name"),
        "aggregation_policy": row.get("aggregation_policy"),
        "sample_denominator": row.get("sample_denominator"),
    }
    for field, value in required_actual_fields.items():
        if value in (None, ""):
            failures.append(f"missing_{field}")

    protocol = row.get("protocol") if isinstance(row.get("protocol"), dict) else {}
    official_fields = [
        "official_harness_prompt_sha256",
        "official_harness_generation_kwargs_sha256",
        "official_harness_stop_sequences_sha256",
        "official_dataset_revision",
        "official_parser_id",
        "official_scorer_id",
        "official_aggregation",
        "official_sample_count",
    ]
    for field in official_fields:
        if row.get(field) is None and protocol.get(field) is None:
            failures.append(f"missing_{field}")
    return sorted(set(str(item) for item in failures if item))


def blocker_for(row: dict[str, Any], reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    task_name = str(row.get("task_name") or "")
    catalog = BLOCKER_CATALOG.get(task_name, {})
    policy = table_dataset_policies().get(task_name, {})
    preferred = str(row.get("preferred_scorer_backend") or policy.get("preferred_scorer_backend") or catalog.get("preferred_scorer_backend") or "")
    return {
        "task_name": task_name,
        "dataset_id": str(row.get("dataset_id") or task_name),
        "dataset_name": str(row.get("dataset_name") or task_name),
        "reason": reason,
        "blocker_type": catalog.get("blocker_type", reason),
        "message": catalog.get("message", reason),
        "remediation": catalog.get("remediation", "Add an official scorer or complete the missing replay evidence before leaderboard scoring."),
        "preferred_scorer_backend": preferred,
        "details": details or {},
    }


def is_full_group_replay(row: dict[str, Any]) -> bool:
    protocol = row.get("protocol") if isinstance(row.get("protocol"), dict) else {}
    return bool(row.get("full_group_coverage") or row.get("official_full_group") or protocol.get("full_group_coverage"))


def has_avg16_coverage(row: dict[str, Any]) -> bool:
    protocol = row.get("protocol") if isinstance(row.get("protocol"), dict) else {}
    expected = protocol.get("expected_repeats") or row.get("expected_repeats")
    observed = protocol.get("observed_repeats") or row.get("observed_repeats")
    try:
        return int(expected) == 16 and int(observed) == 16
    except Exception:
        return False


def apply_evaluation_policy(row: dict[str, Any]) -> dict[str, Any]:
    task_name = str(row.get("task_name") or "")
    reason = str(row.get("skipped_reason") or "")
    official_failures = official_gate_failures(row)
    result = {**row, "official_gate_failures": official_failures}

    if reason:
        result["evaluation_tier"] = "blocker"
        result["coverage_status"] = "blocked" if task_name == "gpqa_diamond" else "unsupported"
        result["average_eligible"] = False
        result["official_benchmark"] = False
        result["blocker"] = blocker_for(result, reason, result.get("details") if isinstance(result.get("details"), dict) else {})
        return result

    if task_name in FULL_GROUP_TASKS and not is_full_group_replay(result):
        result["evaluation_tier"] = "pipeline_test"
        result["coverage_status"] = "partial"
        result["average_eligible"] = False
        result["official_benchmark"] = False
        result["blocker"] = {}
        return result

    if task_name in AVG16_TASKS and not has_avg16_coverage(result):
        result["evaluation_tier"] = "reference_replay" if result.get("supported_by_harness") else "blocker"
        result["coverage_status"] = "partial"
        result["average_eligible"] = False
        result["official_benchmark"] = False
        result["blocker"] = {}
        return result

    if not official_failures and result.get("supported_by_harness"):
        result["evaluation_tier"] = "official_benchmark"
        result["coverage_status"] = "covered"
        result["average_eligible"] = True
        result["official_benchmark"] = True
        result["blocker"] = {}
        return result

    if result.get("official_partial"):
        result["evaluation_tier"] = "official_partial"
    else:
        result["evaluation_tier"] = "reference_replay" if task_name in REFERENCE_REPLAY_TASKS or result.get("supported_by_harness") else "blocker"
    result["coverage_status"] = "partial"
    result["average_eligible"] = False
    result["official_benchmark"] = False
    result["blocker"] = {}
    return result


class HarnessTaskReplayRunner:
    """Replay stored generations through real lm-eval task filters and metrics."""

    def __init__(self) -> None:
        self._task_manager: Any | None = None
        self._loaded_tasks: dict[str, Any] = {}

    def parser_for(self, task_name: str) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
        def parser(raw_generation: str, entry: dict[str, Any]) -> dict[str, Any]:
            return self.run(task_name, raw_generation, entry)

        return parser

    def task_manager(self) -> Any:
        if self._task_manager is None:
            tasks_module = import_module("lm_eval.tasks")
            try:
                self._task_manager = tasks_module.TaskManager()
            except Exception as exc:  # noqa: BLE001 - environment/config errors become explicit skips.
                raise ReplaySkip("missing_lm_eval_dependency", {"missing_module": "lm_eval.tasks.TaskManager", "error": str(exc)}) from exc
        return self._task_manager

    def load_task(self, harness_task: str) -> Any:
        if harness_task in self._loaded_tasks:
            return self._loaded_tasks[harness_task]
        manager = self.task_manager()
        try:
            loaded = manager.load([harness_task])
            task = loaded["tasks"][harness_task]
        except KeyError as exc:
            raise ReplaySkip("missing_harness_task", {"harness_task": harness_task}) from exc
        except Exception as exc:  # noqa: BLE001 - task load is part of replay diagnostics.
            raise ReplaySkip("harness_task_load_failed", {"harness_task": harness_task, "error": str(exc)}) from exc
        self._loaded_tasks[harness_task] = task
        return task

    def resolve_harness_task(self, task_name: str, entry: dict[str, Any], doc: dict[str, Any]) -> str:
        explicit = str(entry.get("harness_task") or "")
        if task_name == "mmlu_pro":
            if explicit.startswith("mmlu_pro_"):
                return explicit
            subtask = normalize_harness_suffix(
                doc.get("source_subtask") or doc.get("category") or entry.get("source_subtask") or entry.get("category")
            )
            if not subtask:
                raise ReplaySkip("missing_harness_task", {"task_name": task_name, "missing": "mmlu_pro_source_subtask"})
            return f"mmlu_pro_{subtask}"
        if task_name == "mmlu_redux":
            if explicit.startswith("mmlu_redux_") and explicit.endswith("_generative") and explicit != "mmlu_redux_generative":
                return explicit
            subject = normalize_harness_suffix(
                doc.get("dataset_name")
                or doc.get("subject")
                or entry.get("mmlu_redux_subject")
                or entry.get("subject")
                or entry.get("source_subtask")
            )
            if not subject:
                raise ReplaySkip("missing_harness_task", {"task_name": task_name, "missing": "mmlu_redux_subject"})
            return f"mmlu_redux_{subject}_generative"
        if task_name == "ifeval":
            return "ifeval"
        if task_name == "aime25":
            return "aime25"
        if task_name == "math500":
            return "minerva_math500"
        if task_name == "bbh":
            if explicit.startswith("bbh_"):
                return explicit
            subtask = normalize_harness_suffix(
                entry.get("bbh_subtask") or doc.get("source_subtask") or doc.get("dataset_name") or entry.get("source_subtask")
            )
            if not subtask:
                task_id = str(entry.get("doc_id") or entry.get("taskID") or "")
                match = re.match(r"bbh-([a-z0-9_]+)-\d+", task_id)
                subtask = normalize_harness_suffix(match.group(1)) if match else ""
            if not subtask:
                raise ReplaySkip("missing_bbh_subtask")
            variant = normalize_harness_suffix(entry.get("bbh_variant") or "zeroshot") or "zeroshot"
            return f"bbh_{variant}_{subtask}"
        raise ReplaySkip("unsupported_task", {"task_name": task_name})

    def normalized_doc(self, task_name: str, entry: dict[str, Any]) -> dict[str, Any]:
        doc = entry.get("doc") if isinstance(entry.get("doc"), dict) else {}
        doc = dict(doc)
        if task_name == "aime25":
            if "problem" not in doc and "Problem" in doc:
                doc["problem"] = doc["Problem"]
            if "answer" not in doc and "Answer" in doc:
                doc["answer"] = doc["Answer"]
        if task_name == "mmlu_pro":
            require_fields(doc, ["answer"], "missing_gold")
        elif task_name == "mmlu_redux":
            doc["answer"] = letter_answer_to_index(doc.get("answer"))
            require_fields(doc, ["answer"], "missing_gold")
        elif task_name == "ifeval":
            require_fields(doc, ["key", "prompt", "instruction_id_list", "kwargs"], "missing_instruction_ids")
        elif task_name == "aime25":
            require_fields(doc, ["problem"], "prompt_not_joinable")
            require_fields(doc, ["answer"], "missing_gold")
        elif task_name == "math500":
            require_fields(doc, ["problem"], "prompt_not_joinable")
            require_fields(doc, ["solution"], "missing_solution")
            require_fields(doc, ["answer"], "missing_gold")
        elif task_name == "bbh":
            require_fields(doc, ["target"], "missing_gold")
        return doc

    def select_filter_name(self, task: Any) -> str:
        filters = list(getattr(task, "_filters", []) or [])
        names = [str(getattr(filter_ensemble, "name", "")) for filter_ensemble in filters]
        for preferred in HARNESS_FILTER_PRIORITY:
            if preferred in names:
                return preferred
        if names:
            return names[0]
        raise ReplaySkip("missing_harness_filter", {"available_filters": names})

    def apply_task_filter(self, task: Any, raw_generation: str, doc: dict[str, Any], filter_name: str) -> Any:
        instance_module = import_module("lm_eval.api.instance")
        try:
            instance = instance_module.Instance(
                request_type="generate_until",
                doc=doc,
                arguments=(),
                idx=0,
                resps=[raw_generation],
            )
        except Exception as exc:  # noqa: BLE001
            raise ReplaySkip("harness_filter_failed:instance", {"error": str(exc)}) from exc

        for filter_ensemble in list(getattr(task, "_filters", []) or []):
            if str(getattr(filter_ensemble, "name", "")) != filter_name:
                continue
            try:
                filter_ensemble.apply([instance])
            except Exception as exc:  # noqa: BLE001
                raise ReplaySkip(f"harness_filter_failed:{filter_name}", {"error": str(exc)}) from exc
            filtered = instance.filtered_resps.get(filter_name)
            if isinstance(filtered, list) and len(filtered) == 1:
                return filtered[0]
            return filtered
        raise ReplaySkip("missing_harness_filter", {"filter_name": filter_name})

    def gold_from_task(self, task: Any, doc: dict[str, Any], fallback: Any) -> Any:
        try:
            target = task.doc_to_target(doc)
            choices = task.doc_to_choice(doc) if getattr(getattr(task, "config", None), "doc_to_choice", None) is not None else None
            if isinstance(choices, list) and isinstance(target, numbers.Integral) and 0 <= int(target) < len(choices):
                return choices[int(target)]
            return target
        except Exception:
            return fallback

    def run(self, task_name: str, raw_generation: str, entry: dict[str, Any]) -> dict[str, Any]:
        doc = self.normalized_doc(task_name, entry)
        harness_task = self.resolve_harness_task(task_name, entry, doc)
        task = self.load_task(harness_task)
        filter_name = self.select_filter_name(task)
        filtered = self.apply_task_filter(task, raw_generation, doc, filter_name)
        try:
            metrics = task.process_results(doc, [filtered])
        except Exception as exc:  # noqa: BLE001
            raise ReplaySkip("harness_process_results_failed", {"harness_task": harness_task, "filter_name": filter_name, "error": str(exc)}) from exc

        fallback_gold = entry.get("gold") or doc.get("answer") or doc.get("target") or ""
        gold = self.gold_from_task(task, doc, fallback_gold)
        filter_names = [str(getattr(filter_ensemble, "name", "")) for filter_ensemble in list(getattr(task, "_filters", []) or [])]
        primary_metric = default_primary_metric(task_name)
        if primary_metric not in metrics and metrics:
            primary_metric = next(iter(metrics.keys()))
        extracted = str(filtered) if filter_name in DISCRETE_FILTER_NAMES else ""
        return {
            "metrics": metrics,
            "extracted_answer": extracted,
            "gold": str(gold if gold is not None else ""),
            "primary_metric": primary_metric,
            "scorer_name": "lm_eval_task_process_results",
            "parser_name": "harness_task_filter_process_results",
            "harness_evaluator_variant": harness_task,
            "details": {
                "harness_task": harness_task,
                "filter_name": filter_name,
                "filter_names": filter_names,
                "output_type": str(getattr(task, "OUTPUT_TYPE", "") or getattr(task, "output_type", "")),
                "filtered_response": json_safe_value(filtered),
                "task_object_replay": True,
                "model_calls": False,
            },
        }


def default_task_parsers() -> dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]]:
    runner = HarnessTaskReplayRunner()
    return {task_name: runner.parser_for(task_name) for task_name in SUPPORTED_TASKS}


@dataclass
class ReplayEvaluator:
    task_parsers: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]]
    aggregation_policy: dict[str, str]
    harness_commit: str = HARNESS_COMMIT

    def evaluate(self, raw_log_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for entry in raw_log_entries:
            task_name = normalize_task_name(str(entry.get("task_name") or entry.get("datasetID") or entry.get("dataset_name") or ""))
            raw_generation = str(entry.get("raw_generation") if "raw_generation" in entry else entry.get("rawGeneration", ""))
            base = {**entry, "task_name": task_name, "harness_commit": self.harness_commit}
            mismatches = protocol_mismatches(base)
            base["official_benchmark"] = not mismatches
            base["not_official_same_protocol"] = bool(mismatches)
            base["not_official_same_prompt"] = "prompt_sha256" in mismatches or "official_protocol_unavailable" in mismatches
            base["protocol_mismatches"] = mismatches
            base["aggregation_policy"] = self.aggregation_policy.get(task_name, DEFAULT_AGGREGATION)

            if base.get("pre_skip_reason"):
                results.append(self._skipped(base, str(base["pre_skip_reason"]), base.get("pre_skip_details") or {}))
                continue

            parser = self.task_parsers.get(task_name)
            if parser is None:
                reason = UNSUPPORTED_TASKS.get(task_name, "unsupported_task")
                results.append(self._skipped(base, reason))
                continue
            try:
                parsed = parser(raw_generation, base)
                meta = SUPPORTED_TASKS.get(task_name, {})
                score, metrics, primary_metric, scorer_name = score_parser_output(task_name, parsed)
                status = answer_status(score)
                parsed_details = parsed.get("details") if isinstance(parsed.get("details"), dict) else {}
                actual_harness_task = str(parsed_details.get("harness_task") or parsed.get("harness_evaluator_variant") or base.get("harness_task") or task_name)
                row = {
                    **base,
                    "supported_by_harness": True,
                    "skipped_reason": "",
                    "score": score,
                    "metrics": metrics,
                    "primary_metric": primary_metric,
                    "metric_name": primary_metric,
                    "metric_higher_is_better": True,
                    "scorer_name": scorer_name,
                    "extracted_answer": parsed.get("extracted_answer", ""),
                    "gold": parsed.get("gold", base.get("gold", "")),
                    "parser_name": parsed.get("parser_name", meta.get("parser", "")),
                    "harness_task": actual_harness_task,
                    "harness_source": meta.get("harness_source", ""),
                    "harness_evaluator_variant": parsed.get("harness_evaluator_variant", ""),
                    "dataset_version": dataset_version_from_entry(base),
                    "evaluation_status": "scored",
                    "answer_status": status,
                    "is_wrong_answer": status == "wrong",
                    "is_skipped": False,
                    "is_error": False,
                    "details": parsed_details,
                    "error": "",
                }
                results.append(apply_evaluation_policy(row))
            except ReplaySkip as exc:
                results.append(self._skipped(base, exc.reason, exc.details))
            except Exception as exc:  # noqa: BLE001 - per-entry errors are report data.
                results.append(self._skipped(base, "parser_error", {"error": str(exc)}))
        return results

    def _skipped(self, entry: dict[str, Any], reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        task_name = str(entry.get("task_name", ""))
        meta = SUPPORTED_TASKS.get(task_name, {})
        evaluation_status = evaluation_status_for_skip(reason)
        row = {
            **entry,
            "supported_by_harness": False,
            "skipped_reason": reason,
            "score": "",
            "metrics": {},
            "primary_metric": meta.get("primary_metric", ""),
            "metric_name": meta.get("primary_metric", ""),
            "metric_higher_is_better": True,
            "scorer_name": meta.get("scorer", ""),
            "extracted_answer": "",
            "gold": entry.get("gold", ""),
            "parser_name": meta.get("parser", ""),
            "harness_task": entry.get("harness_task") or task_name,
            "harness_source": meta.get("harness_source", ""),
            "harness_evaluator_variant": "",
            "dataset_version": dataset_version_from_entry(entry),
            "evaluation_status": evaluation_status,
            "answer_status": "unscored",
            "is_wrong_answer": False,
            "is_skipped": evaluation_status == "skipped",
            "is_error": evaluation_status == "error",
            "details": details or {},
            "error": (details or {}).get("error", ""),
        }
        return apply_evaluation_policy(row)

    def aggregate(self, scored_entries: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in scored_entries:
            model_id = str(row.get("model_id") or "")
            dataset_name = str(row.get("dataset_name") or row.get("task_name") or "")
            doc_id = str(row.get("doc_id") or row.get("taskID") or row.get("id") or "")
            grouped[(model_id, dataset_name, doc_id)].append(row)

        per_doc: list[dict[str, Any]] = []
        for (model_id, dataset_name, doc_id), rows in grouped.items():
            supported = [row for row in rows if row.get("supported_by_harness") and row.get("score") != ""]
            scores = [float(row["score"]) for row in supported]
            extracted = [str(row.get("extracted_answer") or "") for row in supported if row.get("extracted_answer")]
            gold = str(supported[0].get("gold") if supported else rows[0].get("gold", ""))
            majority_answer = Counter(extracted).most_common(1)[0][0] if extracted else ""
            majority_score = exact_match_score(majority_answer, gold, ignore_case=True, ignore_punctuation=True) if majority_answer and gold else ""
            per_doc.append(
                {
                    "model_id": model_id,
                    "dataset_name": dataset_name,
                    "task_name": rows[0].get("task_name", ""),
                    "doc_id": doc_id,
                    "repeat_count": len(rows),
                    "supported_count": len(supported),
                    "skipped_count": len(rows) - len(supported),
                    "average_eligible_count": sum(1 for row in rows if row.get("average_eligible")),
                    "evaluation_tiers": sorted({str(row.get("evaluation_tier") or "") for row in rows if row.get("evaluation_tier")}),
                    "coverage_statuses": sorted({str(row.get("coverage_status") or "") for row in rows if row.get("coverage_status")}),
                    "primary_avg": sum(scores) / len(scores) if scores else "",
                    "majority": majority_score,
                    "pass_at_k": 1.0 if any(score > 0 for score in scores) else ("" if not scores else 0.0),
                    "aggregation_primary": "avg",
                    "aggregation_secondary": ["majority", "pass@k"],
                    "not_lm_eval_default_repeats": len(rows) > 1,
                }
            )

        return {
            "per_doc": per_doc,
            "datasets": aggregate_rows(per_doc, "dataset_name"),
            "models": aggregate_rows(per_doc, "model_id"),
        }


def aggregate_rows(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(key, ""))].append(row)
    result: dict[str, dict[str, Any]] = {}
    for name, items in sorted(buckets.items()):
        values = [float(item["primary_avg"]) for item in items if item.get("primary_avg") != ""]
        result[name] = {
            "doc_count": len(items),
            "scored_doc_count": len(values),
            "primary_avg": sum(values) / len(values) if values else "",
            "skipped_doc_count": len(items) - len(values),
        }
    return result


def load_catalog_resources() -> dict[str, dict[str, dict[str, Any]]]:
    catalog_path = RESOURCES / "benchmark_datasets.json"
    if not catalog_path.exists():
        return {}
    catalog = read_json(catalog_path)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for dataset in catalog.get("datasets", []):
        dataset_id = dataset.get("id")
        task_file = dataset.get("task_file") or dataset_id
        path = RESOURCES / f"{task_file}.json"
        if not dataset_id or not path.exists():
            continue
        result[dataset_id] = {str(row.get("id")): row for row in read_json(path)}
    return result


def quick20_doc(dataset_id: str, resource_task: dict[str, Any] | None) -> dict[str, Any]:
    if not resource_task:
        return {}
    if dataset_id == "mmlu_pro_quick_20":
        return {
            "question": resource_task.get("question", ""),
            "options": [choice.get("text", "") for choice in resource_task.get("choices", [])],
            "answer": resource_task.get("answer", ""),
            "source_subtask": resource_task.get("source_subtask", ""),
            "category": resource_task.get("source_subtask", ""),
        }
    if dataset_id == "bbh_quick_20":
        return {
            "input": resource_task.get("question", ""),
            "target": resource_task.get("answer", ""),
            "source_subtask": resource_task.get("source_subtask", ""),
        }
    if dataset_id == "math500_quick_20":
        return {
            "problem": resource_task.get("question", ""),
            "answer": resource_task.get("answer", ""),
        }
    if dataset_id == "ifeval_lite_quick_20":
        return {
            "prompt": resource_task.get("question", ""),
            "validators": resource_task.get("validators", []),
        }
    return resource_task


def normalized_join_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s]+", "", text)
    return text.strip()


def doc_choice_texts(doc: dict[str, Any]) -> list[str]:
    choices = doc.get("choices")
    if choices is None:
        choices = doc.get("options")
    if not isinstance(choices, list):
        return []
    result: list[str] = []
    for choice in choices:
        if isinstance(choice, dict):
            result.append(str(choice.get("text") or choice.get("value") or ""))
        else:
            result.append(str(choice))
    return result


def question_key(question: Any) -> str:
    return normalized_join_text(question)


def question_choices_key(question: Any, choices: list[str]) -> str:
    choice_part = "||".join(normalized_join_text(choice) for choice in choices)
    return f"{question_key(question)}##{choice_part}"


def plain_doc(doc: Any) -> dict[str, Any]:
    return json.loads(json.dumps(dict(doc), ensure_ascii=False, default=str))


def dataset_load_failure_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if "split" in text and any(marker in text for marker in ["unknown", "not found", "not available", "invalid"]):
        return "missing_dataset_split"
    return "official_dataset_load_failed"


def load_dataset_rows(path: str, *, name: str | None = None, split: str = "test", trust_remote_code: bool = False) -> list[dict[str, Any]]:
    try:
        datasets = importlib.import_module("datasets")
    except Exception as exc:  # noqa: BLE001
        raise ReplaySkip("missing_lm_eval_dependency", {"missing_module": "datasets", "error": str(exc)}) from exc
    kwargs: dict[str, Any] = {"split": split}
    if trust_remote_code:
        kwargs["trust_remote_code"] = True
    try:
        dataset = datasets.load_dataset(path, name, **kwargs) if name is not None else datasets.load_dataset(path, **kwargs)
    except Exception as exc:  # noqa: BLE001 - surfaced as enrichment miss, not crash.
        raise ReplaySkip(dataset_load_failure_reason(exc), {"dataset_path": path, "dataset_name": name or "", "split": split, "error": str(exc)}) from exc
    version = {
        "dataset_path": path,
        "dataset_name": name or "",
        "split": split,
        "revision": "",
        "fingerprint": str(getattr(dataset, "_fingerprint", "") or ""),
        "builder_name": str(getattr(getattr(dataset, "info", None), "builder_name", "") or ""),
        "config_name": str(getattr(getattr(dataset, "info", None), "config_name", "") or name or ""),
        "version": str(getattr(getattr(dataset, "info", None), "version", "") or ""),
    }
    rows: list[dict[str, Any]] = []
    for row in dataset:
        doc = plain_doc(row)
        doc["_harness_replay_dataset_version"] = version
        rows.append(doc)
    return rows


def with_join_telemetry(
    entry: dict[str, Any],
    *,
    attempted: bool,
    success: bool,
    strategy: str = "",
    key: str = "",
    failure_reason: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **entry,
        "official_doc_join_attempted": attempted,
        "official_doc_join_success": success,
        "official_doc_join_strategy": strategy,
        "official_doc_join_key": key,
        "official_doc_join_failure_reason": failure_reason,
        "official_doc_join_details": details or {},
    }


def join_failure_details(
    *,
    dataset_path: str,
    strategy: dict[str, Any] | None,
    attempted_keys: list[str],
    reason: str = "",
    **extra: Any,
) -> dict[str, Any]:
    details = {
        "parent_reason": "missing_official_doc_join",
        "dataset_path": dataset_path,
        "attempted_join_keys": attempted_keys,
        "primary_join_keys": (strategy or {}).get("primary_join_keys", []),
        "fallback_join_keys": (strategy or {}).get("fallback_join_keys", []),
        "replayability_status": (strategy or {}).get("replayability_status", ""),
    }
    if reason:
        details["reason"] = reason
    details.update({key: value for key, value in extra.items() if value not in (None, "")})
    return details


class OfficialDocEnricher:
    def __init__(self, join_strategies: dict[str, dict[str, Any]] | None = None) -> None:
        self.indexes: dict[str, Any] = {}
        self.join_strategies = join_strategies or load_join_strategies()

    def enrich_all(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.enrich(entry) for entry in entries]

    def enrich(self, entry: dict[str, Any]) -> dict[str, Any]:
        task_name = str(entry.get("task_name") or "")
        if task_name not in SUPPORTED_TASKS:
            return with_join_telemetry(entry, attempted=False, success=False)
        strategy = self.join_strategies.get(task_name, {})
        try:
            if task_name == "mmlu_pro":
                enriched = self.enrich_mmlu_pro(entry)
            if task_name == "mmlu_redux":
                enriched = self.enrich_mmlu_redux(entry)
            if task_name == "gpqa_diamond":
                enriched = self.enrich_gpqa_diamond(entry)
            if task_name == "ifeval":
                enriched = self.enrich_ifeval(entry)
            if task_name == "aime25":
                enriched = self.enrich_aime25(entry)
            if task_name == "math500":
                enriched = self.enrich_math500(entry)
            if task_name == "bbh":
                enriched = self.enrich_bbh(entry)
            return enriched
        except ReplaySkip as exc:
            details = {**join_failure_details(dataset_path=str(strategy.get("dataset_path") or ""), strategy=strategy, attempted_keys=[]), **exc.details}
            enriched = with_join_telemetry(
                entry,
                attempted=True,
                success=False,
                strategy=task_name,
                key=str(exc.details.get("join_key") or ""),
                failure_reason=exc.reason,
                details=details,
            )
            enriched["pre_skip_reason"] = exc.reason
            enriched["pre_skip_details"] = details
            return enriched
        return with_join_telemetry(entry, attempted=True, success=False, strategy=task_name, failure_reason="prompt_not_joinable")

    def enrich_mmlu_pro(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("mmlu_pro", {})
        dataset_path = "TIGER-Lab/MMLU-Pro"
        indexes = self.indexes.get("mmlu_pro")
        if indexes is None:
            by_question: dict[str, dict[str, Any]] = {}
            by_question_choices: dict[str, dict[str, Any]] = {}
            for split in ["test", "validation"]:
                for doc in load_dataset_rows(dataset_path, split=split):
                    question = doc.get("question")
                    choices = doc_choice_texts(doc)
                    by_question[question_key(question)] = doc
                    if choices:
                        by_question_choices[question_choices_key(question, choices)] = doc
            indexes = {"by_question": by_question, "by_question_choices": by_question_choices}
            self.indexes["mmlu_pro"] = indexes
        doc = entry.get("doc") or {}
        question = doc.get("question") or entry.get("question") or entry.get("prompt_text")
        choices = doc_choice_texts(doc)
        if not question_key(question):
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        attempted = []
        match = None
        join_key = ""
        if choices:
            key = question_choices_key(question, choices)
            attempted.append(f"question_choices:{short_hash(key)}")
            match = indexes["by_question_choices"].get(key)
            join_key = attempted[-1] if match else ""
        if not match:
            key = question_key(question)
            attempted.append(f"question:{short_hash(key)}")
            match = indexes["by_question"].get(key)
            join_key = attempted[-1] if match else ""
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=attempted))
        gold = str(match.get("answer") or "")
        if not gold:
            raise ReplaySkip("missing_gold", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=attempted, join_key=join_key))
        subtask = normalize_harness_suffix(match.get("source_subtask") or match.get("category") or doc.get("source_subtask"))
        harness_task = entry.get("harness_task") if str(entry.get("harness_task") or "").startswith("mmlu_pro_") else ""
        if not harness_task and subtask:
            harness_task = f"mmlu_pro_{subtask}"
        return with_join_telemetry(
            {**entry, "doc": match, "gold": gold, "harness_task": harness_task or "mmlu_pro"},
            attempted=True,
            success=True,
            strategy="mmlu_pro",
            key=join_key,
            details={"dataset_path": dataset_path, "matched_by": join_key},
        )

    def enrich_mmlu_redux(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("mmlu_redux", {})
        dataset_path = "fxmarty/mmlu-redux-2.0-ok"
        indexes = self.indexes.get("mmlu_redux")
        if indexes is None:
            by_question: dict[str, dict[str, Any]] = {}
            by_question_choices: dict[str, dict[str, Any]] = {}
            for doc in load_dataset_rows(dataset_path, split="test", trust_remote_code=True):
                question = doc.get("question")
                choices = doc_choice_texts(doc)
                by_question[question_key(question)] = doc
                if choices:
                    by_question_choices[question_choices_key(question, choices)] = doc
            indexes = {"by_question": by_question, "by_question_choices": by_question_choices}
            self.indexes["mmlu_redux"] = indexes
        doc = entry.get("doc") or {}
        question = doc.get("question") or entry.get("question") or entry.get("prompt_text")
        choices = doc_choice_texts(doc)
        if not question_key(question):
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        attempted = []
        match = None
        join_key = ""
        if choices:
            key = question_choices_key(question, choices)
            attempted.append(f"question_choices:{short_hash(key)}")
            match = indexes["by_question_choices"].get(key)
            join_key = attempted[-1] if match else ""
        if not match:
            key = question_key(question)
            attempted.append(f"question:{short_hash(key)}")
            match = indexes["by_question"].get(key)
            join_key = attempted[-1] if match else ""
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=attempted))
        gold = str(match.get("answer", ""))
        if gold == "":
            raise ReplaySkip("missing_gold", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=attempted, join_key=join_key))
        subject = normalize_harness_suffix(match.get("dataset_name") or match.get("subject") or match.get("category") or doc.get("dataset_name"))
        harness_task = entry.get("harness_task") if str(entry.get("harness_task") or "").startswith("mmlu_redux_") else ""
        if not harness_task and subject:
            harness_task = f"mmlu_redux_{subject}_generative"
        return with_join_telemetry(
            {**entry, "doc": match, "gold": gold, "harness_task": harness_task or "mmlu_redux_generative"},
            attempted=True,
            success=True,
            strategy="mmlu_redux",
            key=join_key,
            details={"dataset_path": dataset_path, "matched_by": join_key},
        )

    def enrich_gpqa_diamond(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("gpqa_diamond", {})
        dataset_path = "lm_eval.tasks.gpqa.generative"
        doc = entry.get("doc") or {}
        required = ["Question", "choice1", "choice2", "choice3", "choice4", "choices", "answer"]
        missing = [field for field in required if field not in doc]
        if missing:
            raise ReplaySkip(
                "missing_choice_order",
                join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=["saved_processed_choice_order"], missing_fields=missing),
            )
        return with_join_telemetry(
            entry,
            attempted=True,
            success=True,
            strategy="gpqa_diamond_saved_choice_order",
            key=f"choice_order:{short_hash(json.dumps(doc_choice_texts(doc), ensure_ascii=False))}",
            details={"dataset_path": dataset_path, "matched_by": "saved_processed_choice_order"},
        )

    def enrich_ifeval(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("ifeval", {})
        dataset_path = "google/IFEval"
        index = self.indexes.get("ifeval")
        if index is None:
            index = {str(doc.get("prompt") or ""): doc for doc in load_dataset_rows(dataset_path, split="train")}
            self.indexes["ifeval"] = index
        prompt = str((entry.get("doc") or {}).get("prompt") or entry.get("prompt_text") or "")
        if not prompt:
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        join_key = f"prompt:{short_hash(prompt)}"
        match = index.get(prompt)
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        if not match.get("instruction_id_list") or "kwargs" not in match:
            raise ReplaySkip("missing_instruction_ids", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        return with_join_telemetry(
            {**entry, "doc": match, "harness_task": "ifeval"},
            attempted=True,
            success=True,
            strategy="ifeval_prompt",
            key=join_key,
            details={"dataset_path": dataset_path, "matched_by": "prompt"},
        )

    def enrich_aime25(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("aime25", {})
        dataset_path = "math-ai/aime25"
        index = self.indexes.get("aime25")
        if index is None:
            index = {question_key(doc.get("problem")): doc for doc in load_dataset_rows(dataset_path, split="test")}
            self.indexes["aime25"] = index
        problem = (entry.get("doc") or {}).get("problem") or entry.get("question") or entry.get("prompt_text")
        key = question_key(problem)
        if not key:
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        join_key = f"problem:{short_hash(key)}"
        match = index.get(key)
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        if "answer" not in match:
            raise ReplaySkip("missing_gold", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        return with_join_telemetry(
            {**entry, "doc": match, "gold": str(match["answer"]), "harness_task": "aime25"},
            attempted=True,
            success=True,
            strategy="aime25_problem",
            key=join_key,
            details={"dataset_path": dataset_path, "matched_by": "problem"},
        )

    def enrich_math500(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("math500", {})
        dataset_path = "HuggingFaceH4/MATH-500"
        index = self.indexes.get("math500")
        if index is None:
            index = {question_key(doc.get("problem")): self.process_math500_doc(doc) for doc in load_dataset_rows(dataset_path, split="test")}
            self.indexes["math500"] = index
        problem = (entry.get("doc") or {}).get("problem") or entry.get("question") or entry.get("prompt_text")
        key = question_key(problem)
        if not key:
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        join_key = f"problem:{short_hash(key)}"
        match = index.get(key)
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        if "solution" not in match:
            raise ReplaySkip("missing_solution", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        if "answer" not in match:
            raise ReplaySkip("missing_gold", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key))
        return with_join_telemetry(
            {**entry, "doc": match, "gold": str(match["answer"]), "harness_task": "minerva_math500"},
            attempted=True,
            success=True,
            strategy="math500_problem",
            key=join_key,
            details={"dataset_path": dataset_path, "matched_by": "problem"},
        )

    def process_math500_doc(self, doc: dict[str, Any]) -> dict[str, Any]:
        if doc.get("answer"):
            return doc
        solution = str(doc.get("solution") or "")
        if not solution:
            return doc
        try:
            utils = import_module("lm_eval.tasks.minerva_math.utils")
            boxed = utils.last_boxed_only_string(solution)
            answer = utils.normalize_final_answer(utils.remove_boxed(boxed)) if boxed else ""
            if answer:
                return {**doc, "answer": answer}
        except ReplaySkip:
            raise
        except Exception:
            return doc
        return doc

    def enrich_bbh(self, entry: dict[str, Any]) -> dict[str, Any]:
        strategy = self.join_strategies.get("bbh", {})
        dataset_path = "SaylorTwift/bbh"
        local_doc = entry.get("doc") or {}
        subtask = str(entry.get("bbh_subtask") or local_doc.get("source_subtask") or local_doc.get("dataset_name") or "")
        if not subtask:
            task_id = str(entry.get("doc_id") or "")
            match = re.match(r"bbh-([a-z0-9_]+)-\d+", task_id)
            subtask = match.group(1) if match else ""
        if not subtask:
            raise ReplaySkip("missing_bbh_subtask", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[]))
        indexes = self.indexes.get("bbh", {})
        index = indexes.get(subtask)
        if index is None:
            index = {question_key(doc.get("input")): doc for doc in load_dataset_rows(dataset_path, name=subtask, split="test")}
            indexes[subtask] = index
            self.indexes["bbh"] = indexes
        question = local_doc.get("input") or entry.get("question") or entry.get("prompt_text")
        key = question_key(question)
        if not key:
            raise ReplaySkip("missing_stable_doc_id", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[], dataset_name=subtask))
        join_key = f"{subtask}:input:{short_hash(key)}"
        match = index.get(key)
        if not match:
            raise ReplaySkip("prompt_not_joinable", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key, dataset_name=subtask))
        if "target" not in match:
            raise ReplaySkip("missing_gold", join_failure_details(dataset_path=dataset_path, strategy=strategy, attempted_keys=[join_key], join_key=join_key, dataset_name=subtask))
        return with_join_telemetry(
            {**entry, "doc": {**match, "source_subtask": subtask}, "gold": str(match["target"]), "harness_task": f"bbh_zeroshot_{subtask}"},
            attempted=True,
            success=True,
            strategy="bbh_subtask_input",
            key=join_key,
            details={"dataset_path": dataset_path, "dataset_name": subtask, "matched_by": "input"},
        )


def find_run_dirs(raw_dir: pathlib.Path) -> list[pathlib.Path]:
    return sorted(path.parent for path in raw_dir.glob("*/tasks.jsonl"))


def load_export_entries(
    export_dir: pathlib.Path,
    raw_dir: pathlib.Path,
    datasets: set[str] | None,
    *,
    allow_math_fallback: bool,
    bbh_variant: str,
) -> list[dict[str, Any]]:
    resources = load_catalog_resources()
    entries: list[dict[str, Any]] = []
    for run_dir in find_run_dirs(raw_dir):
        summary_path = run_dir / "summary.json"
        summary = read_json(summary_path) if summary_path.exists() else {}
        summary_dataset_id = str(summary.get("datasetID") or "")
        model_id = str(summary.get("environment", {}).get("modelID") or summary.get("profile", {}).get("modelID") or "")
        for repeat_index, row in enumerate(read_jsonl(run_dir / "tasks.jsonl")):
            dataset_id = str(row.get("datasetID") or summary_dataset_id)
            task_name = normalize_task_name(dataset_id)
            if datasets and task_name not in datasets and dataset_id not in datasets:
                continue
            task_id = str(row.get("taskID") or row.get("id") or "")
            resource_task = resources.get(dataset_id, {}).get(task_id)
            doc = row.get("doc") or quick20_doc(dataset_id, resource_task)
            golds = row.get("goldAnswers") or ([] if resource_task is None else resource_task.get("answers", []))
            entries.append(
                {
                    "task_name": task_name,
                    "dataset_id": dataset_id,
                    "dataset_name": SUPPORTED_TASKS.get(task_name, {}).get("dataset_name", dataset_id),
                    "harness_task": row.get("harness_task") or task_name,
                    "doc_id": task_id,
                    "question": str(row.get("question") or ""),
                    "prompt_text": str(row.get("prompt") or ""),
                    "prompt_sha256": sha256_text(str(row.get("prompt") or "")),
                    "raw_generation": str(row.get("rawGeneration") or ""),
                    "repeat_index": repeat_index,
                    "model_id": model_id,
                    "summary_id": run_dir.name,
                    "gold": str(golds[0]) if golds else str(row.get("answer") or ""),
                    "doc": doc,
                    "protocol": row.get("protocol") or {},
                    "metric": row.get("metric") or {},
                    "source_export_dir": str(export_dir),
                    "allow_math_fallback": allow_math_fallback,
                    "bbh_variant": bbh_variant,
                }
            )
    return entries


def matches_dataset_filter(task_name: str, dataset_id: str, datasets: set[str] | None) -> bool:
    return not datasets or task_name in datasets or dataset_id in datasets


def messages_to_prompt_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    lines = []
    for message in messages:
        if isinstance(message, dict):
            lines.append(f"{message.get('role', 'user')}: {message.get('content', '')}")
        else:
            lines.append(str(message))
    return "\n".join(lines)


def android_entry_from_raw_evidence(row: dict[str, Any]) -> dict[str, Any]:
    task_result = row.get("task_result") if isinstance(row.get("task_result"), dict) else {}
    run = row.get("run") if isinstance(row.get("run"), dict) else {}
    metadata = task_result.get("formal_metadata") if isinstance(task_result.get("formal_metadata"), dict) else {}
    replay = row.get("harness_replay_entry") if isinstance(row.get("harness_replay_entry"), dict) else {}
    if not replay:
        replay = metadata.get("harness_replay") if isinstance(metadata.get("harness_replay"), dict) else {}
    entry = dict(replay)

    dataset_id = str(
        entry.get("dataset_id")
        or metadata.get("dataset_id")
        or task_result.get("dataset_id")
        or task_result.get("category")
        or ""
    )
    task_name = normalize_task_name(str(entry.get("task_name") or dataset_id or task_result.get("category") or ""))
    prompt_text = str(
        entry.get("prompt_text")
        or row.get("resolved_prompt")
        or task_result.get("prompt")
        or messages_to_prompt_text(row.get("resolved_messages") or task_result.get("messages"))
        or ""
    )
    raw_generation = str(
        row.get("raw_generation")
        if "raw_generation" in row
        else entry.get("raw_generation")
        if "raw_generation" in entry
        else task_result.get("output", "")
    )

    entry.update(
        {
            "task_name": task_name,
            "dataset_id": dataset_id or task_name,
            "dataset_name": str(entry.get("dataset_name") or task_result.get("category") or dataset_id or task_name),
            "task_id": str(entry.get("task_id") or task_result.get("task_id") or task_result.get("id") or ""),
            "doc_id": str(entry.get("doc_id") or metadata.get("sample_id") or task_result.get("task_id") or task_result.get("id") or ""),
            "prompt_text": prompt_text,
            "prompt_sha256": str(entry.get("prompt_sha256") or sha256_text(prompt_text)),
            "raw_generation": raw_generation,
            "rawGeneration": raw_generation,
            "repeat_index": entry.get("repeat_index", task_result.get("repeat_index", 0)),
            "model_id": str(entry.get("model_id") or task_result.get("model_id") or run.get("model", {}).get("model_id") or ""),
            "summary_id": str(entry.get("summary_id") or run.get("run_id") or ""),
            "gold": str(entry.get("gold") or task_result.get("expected_answer") or ""),
            "protocol": entry.get("protocol") if isinstance(entry.get("protocol"), dict) else {},
            "generated_tokens": task_result.get("generated_tokens") or task_result.get("estimated_output_tokens") or entry.get("generated_tokens") or "",
            "output_tokens": task_result.get("generated_tokens") or task_result.get("estimated_output_tokens") or entry.get("output_tokens") or "",
            "generation_params": metadata.get("generation_params") if isinstance(metadata.get("generation_params"), dict) else entry.get("generation_params", {}),
            "official_eval_metadata": metadata.get("official_eval_metadata") if isinstance(metadata.get("official_eval_metadata"), dict) else entry.get("official_eval_metadata", {}),
            "source_export_dir": str(row.get("source_export_dir") or ""),
            "android_report_format": str(entry.get("android_report_format") or "xiaomi_llmbenchmark_raw_evidence_v1"),
        }
    )
    if "doc" not in entry or not isinstance(entry.get("doc"), dict):
        entry["doc"] = {}
    if "harness_task" not in entry or not entry.get("harness_task"):
        entry["harness_task"] = task_name
    return entry


def load_android_report_entries(report_dir: pathlib.Path, datasets: set[str] | None) -> list[dict[str, Any]]:
    entries_path = report_dir / "harness_replay_entries.jsonl"
    evidence_path = report_dir / "raw_evidence.jsonl"
    entries: list[dict[str, Any]] = []
    if entries_path.exists():
        for row in read_jsonl(entries_path):
            entry = dict(row)
            dataset_id = str(entry.get("dataset_id") or entry.get("dataset_name") or "")
            task_name = normalize_task_name(str(entry.get("task_name") or dataset_id))
            if not matches_dataset_filter(task_name, dataset_id, datasets):
                continue
            prompt_text = str(entry.get("prompt_text") or "")
            entry["task_name"] = task_name
            entry["dataset_id"] = dataset_id or task_name
            entry["raw_generation"] = str(entry.get("raw_generation") if "raw_generation" in entry else entry.get("rawGeneration", ""))
            entry["rawGeneration"] = entry["raw_generation"]
            entry["prompt_sha256"] = str(entry.get("prompt_sha256") or sha256_text(prompt_text))
            entry["source_export_dir"] = str(report_dir)
            entries.append(entry)
        return entries

    if evidence_path.exists():
        for row in read_jsonl(evidence_path):
            entry = android_entry_from_raw_evidence(row)
            dataset_id = str(entry.get("dataset_id") or "")
            task_name = normalize_task_name(str(entry.get("task_name") or dataset_id))
            if not matches_dataset_filter(task_name, dataset_id, datasets):
                continue
            entry["source_export_dir"] = str(report_dir)
            entries.append(entry)
    return entries


def parse_dataset_filter(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    parsed: set[str] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                parsed.add(normalize_task_name(part))
    return parsed or None


def support_matrix(scored_entries: list[dict[str, Any]], join_strategies: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    join_strategies = join_strategies or load_join_strategies()
    policies = table_dataset_policies()
    matrix: dict[str, Any] = {}
    seen_tasks = {str(row.get("task_name", "")) for row in scored_entries}
    for task_name, meta in SUPPORTED_TASKS.items():
        rows = [row for row in scored_entries if row.get("task_name") == task_name]
        strategy = join_strategies.get(task_name, {})
        policy = policies.get(task_name, {})
        matrix[task_name] = {
            **meta,
            "preferred_scorer_backend": policy.get("preferred_scorer_backend", ""),
            "required_coverage": policy.get("required_coverage", ""),
            "configured_supported_by_harness": True,
            "primary_metric": meta.get("primary_metric", ""),
            "scorer": meta.get("scorer", ""),
            "metric_type": meta.get("metric_type", ""),
            "aggregation_primary": DEFAULT_AGGREGATION,
            "aggregation_secondary": ["majority", "pass@k"],
            "replayability_status": strategy.get("replayability_status", ""),
            "legacy_export_limitations": strategy.get("legacy_export_limitations", []),
            "seen_in_input": task_name in seen_tasks,
            "scored_entries": sum(1 for row in rows if row.get("supported_by_harness")),
            "skipped_entries": sum(1 for row in rows if not row.get("supported_by_harness")),
            "skipped_reasons": sorted({str(row.get("skipped_reason")) for row in rows if row.get("skipped_reason")}),
        }
    for task_name, reason in UNSUPPORTED_TASKS.items():
        rows = [row for row in scored_entries if row.get("task_name") == task_name]
        strategy = join_strategies.get(task_name, {})
        policy = policies.get(task_name, {})
        matrix[task_name] = {
            "dataset_name": task_name,
            "preferred_scorer_backend": policy.get("preferred_scorer_backend", ""),
            "required_coverage": policy.get("required_coverage", ""),
            "configured_supported_by_harness": False,
            "replayability_status": strategy.get("replayability_status", "not_in_phase1_parser_replay"),
            "legacy_export_limitations": strategy.get("legacy_export_limitations", []),
            "seen_in_input": task_name in seen_tasks,
            "scored_entries": 0,
            "skipped_entries": len(rows),
            "skipped_reasons": sorted({str(row.get("skipped_reason") or reason) for row in rows}) or [reason],
        }
    return matrix


def expected_sample_count(policy: dict[str, Any]) -> int:
    base = int(policy.get("canonical_sample_count") or 0)
    if policy.get("required_coverage") == "avg16":
        return base * 16
    return base


def build_coverage_report(scored_entries: list[dict[str, Any]], policies: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    policies = policies or table_dataset_policies()
    task_names = sorted(set(policies) | {str(row.get("task_name") or "") for row in scored_entries if row.get("task_name")})
    datasets: dict[str, Any] = {}
    blockers: list[dict[str, Any]] = []
    official_scores: list[float] = []

    for task_name in task_names:
        rows = [row for row in scored_entries if str(row.get("task_name") or "") == task_name]
        policy = policies.get(task_name, {})
        eligible_rows = [row for row in rows if row.get("average_eligible") and row.get("score") != ""]
        if eligible_rows:
            official_scores.append(sum(float(row["score"]) for row in eligible_rows) / len(eligible_rows))
        row_blockers = [row.get("blocker") for row in rows if isinstance(row.get("blocker"), dict) and row.get("blocker")]
        blockers.extend(row_blockers)
        expected = expected_sample_count(policy)
        if eligible_rows and expected and len(eligible_rows) >= expected:
            dataset_status = "covered"
        elif row_blockers:
            dataset_status = "blocked" if any(b.get("blocker_type") == "missing_gated_processed_doc" for b in row_blockers) else "unsupported"
        elif rows:
            dataset_status = "partial"
        else:
            dataset_status = "blocked"
            blockers.append(
                {
                    "task_name": task_name,
                    "dataset_id": task_name,
                    "dataset_name": policy.get("display_name", task_name),
                    "reason": "missing_inference_rows",
                    "blocker_type": "missing_inference_rows",
                    "message": "No Android raw evidence rows were present for this dataset.",
                    "remediation": "Run and export this dataset before official aggregation.",
                    "preferred_scorer_backend": policy.get("preferred_scorer_backend", ""),
                    "details": {},
                }
            )
        datasets[task_name] = {
            "dataset_id": task_name,
            "dataset_name": policy.get("display_name", task_name),
            "scorer_backend": policy.get("preferred_scorer_backend", rows[0].get("preferred_scorer_backend", "") if rows else ""),
            "required_coverage": policy.get("required_coverage", rows[0].get("required_coverage", "") if rows else ""),
            "expected_sample_count": expected,
            "actual_sample_count": len(rows),
            "covered_count": sum(1 for row in rows if row.get("coverage_status") == "covered"),
            "partial_count": sum(1 for row in rows if row.get("coverage_status") == "partial"),
            "blocked_count": sum(1 for row in rows if row.get("evaluation_tier") == "blocker"),
            "average_eligible_count": len(eligible_rows),
            "evaluation_tier_histogram": dict(Counter(str(row.get("evaluation_tier") or "unknown") for row in rows)),
            "coverage_status_histogram": dict(Counter(str(row.get("coverage_status") or "unknown") for row in rows)),
            "coverage_status": dataset_status,
            "main_leaderboard_eligible": bool(policy.get("main_leaderboard_eligible", False)) and dataset_status == "covered",
            "blocker_count": len(row_blockers) + (0 if rows else 1),
        }

    return {
        "schema_version": 1,
        "datasets": datasets,
        "blockers": blockers,
        "summary": {
            "dataset_count": len(datasets),
            "covered_dataset_count": sum(1 for row in datasets.values() if row["coverage_status"] == "covered"),
            "partial_dataset_count": sum(1 for row in datasets.values() if row["coverage_status"] == "partial"),
            "blocked_dataset_count": sum(1 for row in datasets.values() if row["coverage_status"] in {"blocked", "unsupported"}),
            "average_eligible_dataset_count": sum(1 for row in datasets.values() if row["average_eligible_count"] > 0),
            "official_average": sum(official_scores) / len(official_scores) if official_scores else None,
            "official_average_status": "available" if official_scores else "no official average yet",
        },
    }


ERROR_SKIP_REASONS = {
    "parser_error",
    "missing_lm_eval_dependency",
    "harness_task_load_failed",
    "harness_process_results_failed",
    "missing_harness_filter",
}
ERROR_SKIP_PREFIXES = ("harness_filter_failed:", "missing_harness_filter:")
WARNING_SKIP_REASONS = {
    "prompt_not_joinable",
    "missing_stable_doc_id",
    "missing_dataset_split",
    "missing_gold",
    "missing_solution",
    "missing_choice_order",
    "missing_instruction_ids",
    "missing_bbh_task_yaml",
    "missing_bbh_subtask_filter",
    "missing_bbh_subtask",
    "missing_harness_task",
    "official_dataset_load_failed",
}


def warning_level_for_row(row: dict[str, Any]) -> str:
    reason = str(row.get("skipped_reason") or "")
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    if reason in ERROR_SKIP_REASONS or any(reason.startswith(prefix) for prefix in ERROR_SKIP_PREFIXES):
        return "error"
    if reason in WARNING_SKIP_REASONS:
        return "warning"
    if details and (details.get("choice_echo_detected") or details.get("option_echo_warning")):
        return "warning"
    if reason or row.get("protocol_mismatches"):
        return "info"
    return "info"


def skip_reason_histogram(scored_entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("skipped_reason") or "") for row in scored_entries if row.get("skipped_reason"))
    return dict(counts.most_common())


def official_doc_join_failure_histogram(scored_entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str(row.get("official_doc_join_failure_reason") or row.get("skipped_reason") or "")
        for row in scored_entries
        if row.get("official_doc_join_attempted") and not row.get("official_doc_join_success")
    )
    counts.pop("", None)
    return dict(counts.most_common())


def build_run_summary(
    scored_entries: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    scored_count = sum(1 for row in scored_entries if row.get("supported_by_harness") and row.get("score") != "")
    skipped_count = len(scored_entries) - scored_count
    skip_hist = skip_reason_histogram(scored_entries)
    join_attempted_count = sum(1 for row in scored_entries if row.get("official_doc_join_attempted"))
    join_success_count = sum(1 for row in scored_entries if row.get("official_doc_join_success"))
    join_failed_count = sum(1 for row in scored_entries if row.get("official_doc_join_attempted") and not row.get("official_doc_join_success"))
    join_failure_hist = official_doc_join_failure_histogram(scored_entries)
    warning_levels = Counter(str(row.get("warning_level") or "info") for row in warnings)
    evaluation_status_counts = Counter(str(row.get("evaluation_status") or "unknown") for row in scored_entries)
    answer_status_counts = Counter(str(row.get("answer_status") or "unknown") for row in scored_entries)
    tier_counts = Counter(str(row.get("evaluation_tier") or "unknown") for row in scored_entries)
    coverage_counts = Counter(str(row.get("coverage_status") or "unknown") for row in scored_entries)
    wrong_answer_count = sum(1 for row in scored_entries if row.get("is_wrong_answer"))
    error_count = sum(1 for row in scored_entries if row.get("is_error"))

    family_summary: dict[str, Any] = {}
    task_names = sorted({str(row.get("task_name") or "") for row in scored_entries})
    for task_name in task_names:
        rows = [row for row in scored_entries if str(row.get("task_name") or "") == task_name]
        family_warnings = [row for row in warnings if str(row.get("task_name") or "") == task_name]
        family_skip_hist = skip_reason_histogram(rows)
        family_join_attempted_count = sum(1 for row in rows if row.get("official_doc_join_attempted"))
        family_join_success_count = sum(1 for row in rows if row.get("official_doc_join_success"))
        family_join_failed_count = sum(1 for row in rows if row.get("official_doc_join_attempted") and not row.get("official_doc_join_success"))
        family_answer_status_counts = Counter(str(row.get("answer_status") or "unknown") for row in rows)
        family_evaluation_status_counts = Counter(str(row.get("evaluation_status") or "unknown") for row in rows)
        family_tier_counts = Counter(str(row.get("evaluation_tier") or "unknown") for row in rows)
        family_coverage_counts = Counter(str(row.get("coverage_status") or "unknown") for row in rows)
        family_summary[task_name] = {
            "entry_count": len(rows),
            "scored_count": sum(1 for row in rows if row.get("supported_by_harness") and row.get("score") != ""),
            "skipped_count": sum(1 for row in rows if not row.get("supported_by_harness") or row.get("score") == ""),
            "average_eligible_count": sum(1 for row in rows if row.get("average_eligible")),
            "wrong_answer_count": sum(1 for row in rows if row.get("is_wrong_answer")),
            "error_count": sum(1 for row in rows if row.get("is_error")),
            "evaluation_status_histogram": dict(family_evaluation_status_counts),
            "answer_status_histogram": dict(family_answer_status_counts),
            "evaluation_tier_histogram": dict(family_tier_counts),
            "coverage_status_histogram": dict(family_coverage_counts),
            "skip_reason_histogram": family_skip_hist,
            "official_doc_join_attempted_count": family_join_attempted_count,
            "official_doc_join_success_count": family_join_success_count,
            "official_doc_join_failed_count": family_join_failed_count,
            "official_doc_join_failure_histogram": official_doc_join_failure_histogram(rows),
            "parser_error_count": family_skip_hist.get("parser_error", 0),
            "missing_lm_eval_dependency_count": family_skip_hist.get("missing_lm_eval_dependency", 0),
            "warning_level_counts": dict(Counter(str(row.get("warning_level") or "info") for row in family_warnings)),
        }

    return {
        "entry_count": len(scored_entries),
        "job_count": len(jobs),
        "scored_count": scored_count,
        "skipped_count": skipped_count,
        "wrong_answer_count": wrong_answer_count,
        "error_count": error_count,
        "evaluation_status_histogram": dict(evaluation_status_counts),
        "answer_status_histogram": dict(answer_status_counts),
        "evaluation_tier_histogram": dict(tier_counts),
        "coverage_status_histogram": dict(coverage_counts),
        "average_eligible_count": sum(1 for row in scored_entries if row.get("average_eligible")),
        "skip_reason_histogram": skip_hist,
        "official_doc_join_attempted_count": join_attempted_count,
        "official_doc_join_success_count": join_success_count,
        "official_doc_join_failed_count": join_failed_count,
        "official_doc_join_failure_histogram": join_failure_hist,
        "parser_error_count": skip_hist.get("parser_error", 0),
        "missing_lm_eval_dependency_count": skip_hist.get("missing_lm_eval_dependency", 0),
        "warning_count": len(warnings),
        "warning_level_counts": dict(warning_levels),
        "parser_family_summary": family_summary,
    }


def warning_rows(scored_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for row in scored_entries:
        reason = str(row.get("skipped_reason") or "")
        details = row.get("details") or {}
        diagnostics = details if isinstance(details, dict) else {}
        should_warn = bool(reason) or bool(row.get("protocol_mismatches"))
        should_warn = should_warn or bool(diagnostics.get("choice_echo_detected")) or bool(diagnostics.get("option_echo_warning"))
        if not should_warn:
            continue
        warnings.append(
            {
                "summary_id": row.get("summary_id", ""),
                "model_id": row.get("model_id", ""),
                "dataset_name": row.get("dataset_name", ""),
                "task_name": row.get("task_name", ""),
                "doc_id": row.get("doc_id", ""),
                "warning_level": warning_level_for_row(row),
                "skipped_reason": reason,
                "official_doc_join_failure_reason": row.get("official_doc_join_failure_reason", ""),
                "protocol_mismatches": row.get("protocol_mismatches", []),
                "official_doc_join_details": row.get("official_doc_join_details", {}),
                "details": diagnostics,
            }
        )
    return warnings


def flatten_task_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary_id": row.get("summary_id", ""),
        "model_id": row.get("model_id", ""),
        "dataset_id": row.get("dataset_id", ""),
        "dataset_name": row.get("dataset_name", ""),
        "task_name": row.get("task_name", ""),
        "doc_id": row.get("doc_id", ""),
        "repeat_index": row.get("repeat_index", ""),
        "supported_by_harness": row.get("supported_by_harness", ""),
        "evaluation_tier": row.get("evaluation_tier", ""),
        "coverage_status": row.get("coverage_status", ""),
        "average_eligible": row.get("average_eligible", ""),
        "evaluation_status": row.get("evaluation_status", ""),
        "answer_status": row.get("answer_status", ""),
        "is_wrong_answer": row.get("is_wrong_answer", ""),
        "is_skipped": row.get("is_skipped", ""),
        "is_error": row.get("is_error", ""),
        "skipped_reason": row.get("skipped_reason", ""),
        "score": row.get("score", ""),
        "primary_metric": row.get("primary_metric", ""),
        "metric_name": row.get("metric_name", ""),
        "scorer_name": row.get("scorer_name", ""),
        "metrics": json.dumps(row.get("metrics", {}), ensure_ascii=False, sort_keys=True),
        "extracted_answer": row.get("extracted_answer", ""),
        "gold": row.get("gold", ""),
        "parser_name": row.get("parser_name", ""),
        "harness_task": row.get("harness_task", ""),
        "harness_evaluator_variant": row.get("harness_evaluator_variant", ""),
        "official_benchmark": row.get("official_benchmark", ""),
        "official_gate_failures": json.dumps(row.get("official_gate_failures", []), ensure_ascii=False),
        "not_official_same_protocol": row.get("not_official_same_protocol", ""),
        "not_official_same_prompt": row.get("not_official_same_prompt", ""),
        "protocol_mismatches": json.dumps(row.get("protocol_mismatches", []), ensure_ascii=False),
        "aggregation_policy": row.get("aggregation_policy", ""),
        "official_doc_join_attempted": row.get("official_doc_join_attempted", ""),
        "official_doc_join_success": row.get("official_doc_join_success", ""),
        "official_doc_join_strategy": row.get("official_doc_join_strategy", ""),
        "official_doc_join_key": row.get("official_doc_join_key", ""),
        "official_doc_join_failure_reason": row.get("official_doc_join_failure_reason", ""),
        "official_doc_join_details": json.dumps(row.get("official_doc_join_details", {}), ensure_ascii=False, sort_keys=True),
        "dataset_version": json.dumps(row.get("dataset_version", {}), ensure_ascii=False, sort_keys=True),
        "details": json.dumps(row.get("details", {}), ensure_ascii=False, sort_keys=True),
        "blocker": json.dumps(row.get("blocker", {}), ensure_ascii=False, sort_keys=True),
        "error": row.get("error", ""),
        "raw_generation": row.get("raw_generation", ""),
    }


def build_jobs(scored_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in scored_entries:
        buckets[(str(row.get("summary_id", "")), str(row.get("model_id", "")), str(row.get("dataset_name", "")))].append(row)
    jobs: list[dict[str, Any]] = []
    for (summary_id, model_id, dataset_name), rows in sorted(buckets.items()):
        scores = [float(row["score"]) for row in rows if row.get("supported_by_harness") and row.get("score") != ""]
        jobs.append(
            {
                "summary_id": summary_id,
                "model_id": model_id,
                "dataset_name": dataset_name,
                "task_name": rows[0].get("task_name", ""),
                "entry_count": len(rows),
                "scored_count": len(scores),
                "skipped_count": len(rows) - len(scores),
                "average_eligible_count": sum(1 for row in rows if row.get("average_eligible")),
                "evaluation_tiers": ",".join(sorted({str(row.get("evaluation_tier")) for row in rows if row.get("evaluation_tier")})),
                "coverage_statuses": ",".join(sorted({str(row.get("coverage_status")) for row in rows if row.get("coverage_status")})),
                "wrong_answer_count": sum(1 for row in rows if row.get("is_wrong_answer")),
                "error_count": sum(1 for row in rows if row.get("is_error")),
                "primary_avg": sum(scores) / len(scores) if scores else "",
                "supported_by_harness": bool(scores),
                "skipped_reasons": ",".join(sorted({str(row.get("skipped_reason")) for row in rows if row.get("skipped_reason")})),
                "official_benchmark": all(row.get("official_benchmark") for row in rows) if rows else False,
                "average_eligible": all(row.get("average_eligible") for row in rows) if rows else False,
                "aggregation_primary": "avg",
                "aggregation_secondary": "majority,pass@k",
                "not_lm_eval_default_repeats": any(int(row.get("repeat_index") or 0) > 0 for row in rows),
            }
        )
    return jobs


PROTOCOL_FIELDS = [
    ("prompt", "prompt_sha256", "official_harness_prompt_sha256"),
    ("fewshot", "fewshot_examples_sha256", "official_harness_fewshot_examples_sha256"),
    ("choice_order", "choice_order_sha256", "official_harness_choice_order_sha256"),
    ("generation_kwargs", "generation_kwargs_sha256", "official_harness_generation_kwargs_sha256"),
    ("stop_sequences", "stop_sequences_sha256", "official_harness_stop_sequences_sha256"),
]


def protocol_field_values(row: dict[str, Any], actual_key: str, official_key: str) -> tuple[Any, Any]:
    protocol = row.get("protocol") or {}
    if actual_key == "prompt_sha256":
        prompt_text = str(row.get("prompt_text") or row.get("prompt") or "")
        actual = row.get("prompt_sha256") or (sha256_text(prompt_text) if prompt_text else None)
    else:
        actual = protocol.get(actual_key) or row.get(actual_key)
    expected = protocol.get(official_key) or row.get(official_key)
    return actual, expected


def build_protocol_manifest(
    scored_entries: list[dict[str, Any]],
    *,
    harness_commit_value: str,
    join_strategies: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    for task_name in sorted({str(row.get("task_name") or "") for row in scored_entries}):
        rows = [row for row in scored_entries if str(row.get("task_name") or "") == task_name]
        strategy = join_strategies.get(task_name, {})
        field_counts: dict[str, Any] = {}
        for field_name, actual_key, official_key in PROTOCOL_FIELDS:
            available = matched = mismatched = unavailable = 0
            for row in rows:
                actual, expected = protocol_field_values(row, actual_key, official_key)
                if actual is None or expected is None:
                    unavailable += 1
                else:
                    available += 1
                    if actual == expected:
                        matched += 1
                    else:
                        mismatched += 1
            field_counts[field_name] = {
                "available_count": available,
                "match_count": matched,
                "mismatch_count": mismatched,
                "unavailable_count": unavailable,
            }

        mismatch_counter = Counter(mismatch for row in rows for mismatch in row.get("protocol_mismatches", []))
        dataset_versions = [
            row.get("dataset_version")
            for row in rows
            if isinstance(row.get("dataset_version"), dict) and any((row.get("dataset_version") or {}).values())
        ]
        unique_dataset_versions = []
        seen_versions = set()
        for version in dataset_versions:
            key = json.dumps(version, ensure_ascii=False, sort_keys=True)
            if key not in seen_versions:
                seen_versions.add(key)
                unique_dataset_versions.append(version)
        tasks[task_name] = {
            "entry_count": len(rows),
            "scored_count": sum(1 for row in rows if row.get("supported_by_harness") and row.get("score") != ""),
            "official_compatible_count": sum(1 for row in rows if row.get("official_benchmark")),
            "official_incompatible_count": sum(1 for row in rows if not row.get("official_benchmark")),
            "parser": SUPPORTED_TASKS.get(task_name, {}).get("parser", ""),
            "scorer": SUPPORTED_TASKS.get(task_name, {}).get("scorer", ""),
            "primary_metric": SUPPORTED_TASKS.get(task_name, {}).get("primary_metric", ""),
            "aggregation_primary": DEFAULT_AGGREGATION,
            "aggregation_secondary": ["majority", "pass@k"],
            "blocking_protocol_mismatches": dict(mismatch_counter.most_common()),
            "fields": field_counts,
            "dataset_versions": unique_dataset_versions,
            "judge": {
                "judge_backend": "none",
                "judge_version": "",
                "judge_calls": False,
            },
            "official_doc_join": {
                "attempted_count": sum(1 for row in rows if row.get("official_doc_join_attempted")),
                "success_count": sum(1 for row in rows if row.get("official_doc_join_success")),
                "failed_count": sum(1 for row in rows if row.get("official_doc_join_attempted") and not row.get("official_doc_join_success")),
                "failure_histogram": official_doc_join_failure_histogram(rows),
            },
            "replayability_status": strategy.get("replayability_status", ""),
            "legacy_export_limitations": strategy.get("legacy_export_limitations", []),
        }

    return {
        "harness_commit": harness_commit_value,
        "harness_version": harness_version(),
        "scoring_backend": SCORING_BACKEND,
        "official_benchmark": False,
        "model_calls": False,
        "lm_eval_simple_evaluate": False,
        "judge_calls": False,
        "tasks": tasks,
    }


def write_report(path: pathlib.Path, results: dict[str, Any]) -> None:
    summary = results.get("summary", {})
    lines = [
        "# Harness Function Replay Report",
        "",
        f"- scoring_backend: `{SCORING_BACKEND}`",
        f"- harness_commit: `{results['harness_commit']}`",
        "- execution: `parser_metric_replay_only`",
        "- model_calls: `false`",
        "- lm_eval_simple_evaluate: `false`",
        "- official_benchmark: `false unless protocol fields fully match`",
        "- aggregation_primary: `avg`",
        "- aggregation_secondary: `[majority, pass@k]`",
        f"- Entries: `{summary.get('entry_count', len(results['tasks']))}`",
        f"- Jobs: `{summary.get('job_count', len(results['jobs']))}`",
        f"- scored_count: `{summary.get('scored_count', 0)}`",
        f"- skipped_count: `{summary.get('skipped_count', 0)}`",
        f"- average_eligible_count: `{summary.get('average_eligible_count', 0)}`",
        f"- wrong_answer_count: `{summary.get('wrong_answer_count', 0)}`",
        f"- error_count: `{summary.get('error_count', 0)}`",
        f"- official_doc_join_attempted_count: `{summary.get('official_doc_join_attempted_count', 0)}`",
        f"- official_doc_join_success_count: `{summary.get('official_doc_join_success_count', 0)}`",
        f"- official_doc_join_failed_count: `{summary.get('official_doc_join_failed_count', 0)}`",
        f"- parser_error_count: `{summary.get('parser_error_count', 0)}`",
        f"- missing_lm_eval_dependency_count: `{summary.get('missing_lm_eval_dependency_count', 0)}`",
        "",
        "## Outcome Status",
        "",
        f"- evaluation_status_histogram: `{json.dumps(summary.get('evaluation_status_histogram', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- answer_status_histogram: `{json.dumps(summary.get('answer_status_histogram', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- evaluation_tier_histogram: `{json.dumps(summary.get('evaluation_tier_histogram', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- coverage_status_histogram: `{json.dumps(summary.get('coverage_status_histogram', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Skip Reasons",
        "",
    ]
    skip_hist = summary.get("skip_reason_histogram") or {}
    if not skip_hist:
        lines.append("No skipped entries.")
    else:
        for reason, count in skip_hist.items():
            lines.append(f"- `{reason}`: {count}")

    join_hist = summary.get("official_doc_join_failure_histogram") or {}
    lines += ["", "## Official Doc Join", ""]
    if not join_hist:
        lines.append("No official doc join failures.")
    else:
        for reason, count in join_hist.items():
            lines.append(f"- `{reason}`: {count}")

    level_counts = summary.get("warning_level_counts") or {}
    lines += ["", "## Warning Levels", ""]
    if not level_counts:
        lines.append("No warnings.")
    else:
        for level, count in sorted(level_counts.items()):
            lines.append(f"- `{level}`: {count}")

    lines += [
        "",
        "## Parser Families",
        "",
        "| Task | Entries | Scored | Avg Eligible | Tiers | Coverage | Wrong | Skipped | Errors | Top Reasons |",
        "|---|---:|---:|---:|---|---|---:|---:|---:|---|",
    ]
    for task_name, row in sorted((summary.get("parser_family_summary") or {}).items()):
        reasons = ", ".join(f"{reason}:{count}" for reason, count in (row.get("skip_reason_histogram") or {}).items())
        tiers = ",".join(sorted((row.get("evaluation_tier_histogram") or {}).keys()))
        coverage = ",".join(sorted((row.get("coverage_status_histogram") or {}).keys()))
        lines.append(
            f"| {task_name} | {row.get('entry_count', 0)} | {row.get('scored_count', 0)} | "
            f"{row.get('average_eligible_count', 0)} | {tiers} | {coverage} | "
            f"{row.get('wrong_answer_count', 0)} | {row.get('skipped_count', 0)} | "
            f"{row.get('error_count', 0)} | {reasons} |"
        )

    lines += [
        "",
        "## Jobs",
        "",
        "| Model | Dataset | Entries | Scored | Avg Eligible | Tier | Coverage | Primary Avg | Reasons |",
        "|---|---|---:|---:|---:|---|---|---:|---|",
    ]
    for job in results["jobs"]:
        avg = job["primary_avg"]
        avg_text = f"{avg:.4f}" if isinstance(avg, float) else ""
        lines.append(
            f"| {job['model_id']} | {job['dataset_name']} | {job['entry_count']} | "
            f"{job['scored_count']} | {job.get('average_eligible_count', 0)} | {job.get('evaluation_tiers', '')} | "
            f"{job.get('coverage_statuses', '')} | {avg_text} | {job['skipped_reasons']} |"
        )

    coverage_report = results.get("coverage_report") or {}
    coverage_summary = coverage_report.get("summary") or {}
    lines += [
        "",
        "## Coverage Report",
        "",
        f"- official_average_status: `{coverage_summary.get('official_average_status', 'no official average yet')}`",
        f"- average_eligible_dataset_count: `{coverage_summary.get('average_eligible_dataset_count', 0)}`",
        f"- blocked_dataset_count: `{coverage_summary.get('blocked_dataset_count', 0)}`",
        "",
        "| Dataset | Scorer Backend | Required Coverage | Expected | Actual | Avg Eligible | Status |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for task_name, row in sorted((coverage_report.get("datasets") or {}).items()):
        lines.append(
            f"| {task_name} | {row.get('scorer_backend', '')} | {row.get('required_coverage', '')} | "
            f"{row.get('expected_sample_count', 0)} | {row.get('actual_sample_count', 0)} | "
            f"{row.get('average_eligible_count', 0)} | {row.get('coverage_status', '')} |"
        )

    lines += [
        "",
        "## Support Matrix",
        "",
        "| Task | Scorer Backend | Required Coverage | Harness Source | Replayability | Seen | Scored | Skipped | Reasons |",
        "|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for task_name, row in sorted(results["supported_matrix"].items()):
        lines.append(
            f"| {task_name} | {row.get('preferred_scorer_backend', '')} | {row.get('required_coverage', '')} | "
            f"{row.get('harness_source', '')} | {row.get('replayability_status', '')} | {row['seen_in_input']} | "
            f"{row['scored_entries']} | {row['skipped_entries']} | {', '.join(row['skipped_reasons'])} |"
        )

    protocol_manifest = results.get("protocol_manifest") or {}
    lines += ["", "## Protocol Manifest Summary", ""]
    if not protocol_manifest.get("tasks"):
        lines.append("No protocol manifest data.")
    else:
        lines += [
            "| Task | Entries | Official Compatible | Official Incompatible | Blocking Mismatches |",
            "|---|---:|---:|---:|---|",
        ]
        for task_name, row in sorted(protocol_manifest["tasks"].items()):
            mismatches = ", ".join(f"{name}:{count}" for name, count in (row.get("blocking_protocol_mismatches") or {}).items())
            lines.append(
                f"| {task_name} | {row.get('entry_count', 0)} | {row.get('official_compatible_count', 0)} | "
                f"{row.get('official_incompatible_count', 0)} | {mismatches} |"
            )

    lines += ["", "## Warning Summary", ""]
    warnings = results["warnings"]
    if not warnings:
        lines.append("No warnings.")
    else:
        counts = Counter(
            f"{row.get('warning_level', 'info')}:{row.get('skipped_reason') or ','.join(row.get('protocol_mismatches', [])) or 'diagnostic'}"
            for row in warnings
        )
        for reason, count in counts.most_common():
            lines.append(f"- `{reason}`: {count}")

    failures = [row for row in results["tasks"] if row.get("skipped_reason") or row.get("score") == 0.0][:10]
    lines += ["", "## Top Failure Samples", ""]
    if not failures:
        lines.append("No failure samples.")
    for row in failures:
        raw = str(row.get("raw_generation", "")).replace("\n", "\\n")[:500]
        lines += [
            f"### {row.get('dataset_name', '')} / {row.get('doc_id', '')}",
            "",
            f"- skipped_reason: `{row.get('skipped_reason', '')}`",
            f"- extracted_answer: `{row.get('extracted_answer', '')}`",
            f"- gold: `{row.get('gold', '')}`",
            f"- parser: `{row.get('parser_name', '')}`",
            f"- raw_generation: `{raw}`",
            "",
        ]
    wrongs = [row for row in results["tasks"] if row.get("is_wrong_answer")][:10]
    lines += ["", "## Wrong Answer Samples", ""]
    if not wrongs:
        lines.append("No wrong answer samples.")
    for row in wrongs:
        raw = str(row.get("raw_generation", "")).replace("\n", "\\n")[:500]
        lines += [
            f"### {row.get('dataset_name', '')} / {row.get('doc_id', '')}",
            "",
            f"- score: `{row.get('score', '')}`",
            f"- extracted_answer: `{row.get('extracted_answer', '')}`",
            f"- gold: `{row.get('gold', '')}`",
            f"- primary_metric: `{row.get('primary_metric', '')}`",
            f"- parser: `{row.get('parser_name', '')}`",
            f"- scorer: `{row.get('scorer_name', '')}`",
            f"- raw_generation: `{raw}`",
            "",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def harness_commit() -> str:
    try:
        distribution = importlib.metadata.distribution("lm-eval")
        direct_url = distribution.read_text("direct_url.json")
        if direct_url:
            parsed = json.loads(direct_url)
            commit = (parsed.get("vcs_info") or {}).get("commit_id")
            if commit:
                return str(commit)
    except Exception:
        pass
    try:
        module = importlib.import_module("lm_eval")
        module_path = pathlib.Path(module.__file__).resolve()
        if ".venv-lm-eval-replay" in module_path.parts:
            return HARNESS_COMMIT
        repo = module_path.parents[1]
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return HARNESS_COMMIT


def harness_version() -> str:
    try:
        return importlib.metadata.version("lm-eval")
    except Exception:
        return ""


def build_evaluator_manifest(
    *,
    harness_commit_value: str,
    join_strategies: dict[str, dict[str, Any]],
    harness_capabilities: dict[str, Any],
) -> dict[str, Any]:
    tasks: dict[str, Any] = {}
    for task_name, meta in sorted(SUPPORTED_TASKS.items()):
        strategy = join_strategies.get(task_name, {})
        tasks[task_name] = {
            "dataset_name": meta.get("dataset_name", ""),
            "harness_source": meta.get("harness_source", ""),
            "harness_task": task_name,
            "parser": meta.get("parser", ""),
            "scorer": meta.get("scorer", ""),
            "primary_metric": meta.get("primary_metric", ""),
            "metric_type": meta.get("metric_type", ""),
            "aggregation_primary": DEFAULT_AGGREGATION,
            "aggregation_secondary": ["majority", "pass@k"],
            "dataset_path": strategy.get("dataset_path", ""),
            "splits": strategy.get("splits", []),
            "required_doc_fields": strategy.get("required_doc_fields", []),
            "required_protocol_fields": strategy.get("required_protocol_fields", []),
            "replayability_status": strategy.get("replayability_status", ""),
            "legacy_export_limitations": strategy.get("legacy_export_limitations", []),
        }
    unsupported = {
        task_name: {
            "skipped_reason": reason,
            "replayability_status": (join_strategies.get(task_name) or {}).get("replayability_status", "not_in_phase1_parser_replay"),
            "legacy_export_limitations": (join_strategies.get(task_name) or {}).get("legacy_export_limitations", []),
        }
        for task_name, reason in sorted(UNSUPPORTED_TASKS.items())
    }
    return {
        "scoring_backend": SCORING_BACKEND,
        "execution": "lm_eval_task_object_filter_process_results_replay",
        "model_calls": False,
        "lm_eval_simple_evaluate": False,
        "lm_eval_task_object_replay": True,
        "legacy_quick20_scorer": False,
        "judge_calls": False,
        "harness_commit": harness_commit_value,
        "harness_version": harness_version(),
        "harness_capabilities": harness_capabilities,
        "raw_generation_source": "iphone_export_tasks_jsonl",
        "parser_scorer_separated": True,
        "task_filter_source": "lm_eval_configurable_task_filters",
        "metric_source": "lm_eval_configurable_task_process_results",
        "status_fields": ["evaluation_status", "answer_status", "is_wrong_answer", "is_skipped", "is_error"],
        "tasks": tasks,
        "unsupported_tasks": unsupported,
    }


def score_export(args: argparse.Namespace) -> dict[str, Any]:
    export_dir = pathlib.Path(args.export_dir).resolve()
    raw_dir = pathlib.Path(args.raw_dir).resolve() if args.raw_dir else export_dir / "latest_batch_raw"
    output_dir = pathlib.Path(args.output_dir).resolve() if args.output_dir else export_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = parse_dataset_filter(args.datasets)
    commit = harness_commit()
    join_strategies = load_join_strategies()
    evaluator = ReplayEvaluator(
        task_parsers=default_task_parsers(),
        aggregation_policy=defaultdict(lambda: DEFAULT_AGGREGATION, {"aime25": "avg", "math500": "avg"}),
        harness_commit=commit,
    )
    entries_jsonl = pathlib.Path(args.entries_jsonl).resolve() if args.entries_jsonl else None
    if entries_jsonl:
        entries = []
        for row in read_jsonl(entries_jsonl):
            task_name = normalize_task_name(str(row.get("task_name") or row.get("dataset_id") or row.get("dataset_name") or ""))
            dataset_id = str(row.get("dataset_id") or "")
            if matches_dataset_filter(task_name, dataset_id, datasets):
                entries.append({**row, "task_name": task_name, "source_export_dir": str(entries_jsonl.parent)})
    elif (export_dir / "harness_replay_entries.jsonl").exists() or (export_dir / "raw_evidence.jsonl").exists():
        entries = load_android_report_entries(export_dir, datasets)
    else:
        entries = load_export_entries(
            export_dir,
            raw_dir,
            datasets,
            allow_math_fallback=args.allow_math_fallback,
            bbh_variant=args.bbh_variant,
        )
    if args.enrich_official_docs:
        entries = OfficialDocEnricher(join_strategies).enrich_all(entries)
    scored = evaluator.evaluate(entries)
    aggregated = evaluator.aggregate(scored)
    warnings = warning_rows(scored)
    jobs = build_jobs(scored)
    matrix = support_matrix(scored, join_strategies)
    coverage_report = build_coverage_report(scored)
    summary = build_run_summary(scored, jobs, warnings)
    protocol_manifest = build_protocol_manifest(scored, harness_commit_value=commit, join_strategies=join_strategies)
    harness_capabilities = check_harness_capabilities()
    evaluator_manifest = build_evaluator_manifest(
        harness_commit_value=commit,
        join_strategies=join_strategies,
        harness_capabilities=harness_capabilities,
    )
    results = {
        "scoring_backend": SCORING_BACKEND,
        "harness_commit": commit,
        "harness_version": harness_version(),
        "model_calls": False,
        "lm_eval_simple_evaluate": False,
        "judge_calls": False,
        "enrich_official_docs": bool(args.enrich_official_docs),
        "harness_capabilities": harness_capabilities,
        "official_benchmark": False,
        "aggregation_primary": "avg",
        "aggregation_secondary": ["majority", "pass@k"],
        "tasks": scored,
        "jobs": jobs,
        "aggregation": aggregated,
        "supported_matrix": matrix,
        "coverage_report": coverage_report,
        "warnings": warnings,
        "summary": summary,
        "join_strategies": join_strategies,
        "protocol_manifest": protocol_manifest,
        "evaluator_manifest": evaluator_manifest,
    }

    prefix = "harness_replay_enriched" if args.enrich_official_docs else "harness_replay"
    (output_dir / f"{prefix}_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(output_dir / f"{prefix}_tasks.csv", [flatten_task_row(row) for row in scored])
    write_csv(output_dir / f"{prefix}_jobs.csv", jobs)
    (output_dir / f"{prefix}_supported_matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / f"{prefix}_coverage_report.json").write_text(json.dumps(coverage_report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / f"{prefix}_evaluator_manifest.json").write_text(json.dumps(evaluator_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "harness_replay_protocol_manifest.json").write_text(json.dumps(protocol_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / f"{prefix}_blockers.jsonl").open("w", encoding="utf-8") as file:
        for blocker in coverage_report.get("blockers", []):
            file.write(json.dumps(blocker, ensure_ascii=False) + "\n")
    with (output_dir / f"{prefix}_warnings.jsonl").open("w", encoding="utf-8") as file:
        for warning in warnings:
            file.write(json.dumps(warning, ensure_ascii=False) + "\n")
    write_report(output_dir / f"{prefix}_report.md", results)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay exported raw generations through lm-eval harness parser functions.")
    parser.add_argument("export_dir", nargs="?", default=".", help="Export/report directory, e.g. an Android report dir or iPhone export dir.")
    parser.add_argument("--raw-dir", default="", help="Raw log directory. Defaults to export_dir/latest_batch_raw.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to export_dir/analysis.")
    parser.add_argument("--entries-jsonl", default="", help="Direct harness_replay_entries.jsonl input. Overrides export-dir auto-detection.")
    parser.add_argument("--datasets", nargs="*", help="Comma-separated or repeated dataset/task filters.")
    parser.add_argument("--allow-math-fallback", action="store_true", help="Allow MATH-500 fallback to hendrycks_math when minerva math deps are missing.")
    parser.add_argument("--bbh-variant", default="zeroshot", help="BBH YAML variant to read, e.g. zeroshot, cot_zeroshot, cot_fewshot.")
    parser.add_argument("--enrich-official-docs", action="store_true", help="Join exported entries with official datasets before replay scoring.")
    parser.add_argument("--check-harness", action="store_true", help="Only validate required lm-eval harness imports.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check_harness:
        capabilities = check_harness_capabilities()
        print(json.dumps(capabilities, ensure_ascii=False, indent=2))
        return 0 if capabilities["ok"] else 1
    results = score_export(args)
    summary = results.get("summary", {})
    print(
        "Harness replay complete: "
        f"{len(results['jobs'])} jobs, {len(results['tasks'])} entries, "
        f"{summary.get('scored_count', 0)} scored, "
        f"{summary.get('skipped_count', 0)} skipped, "
        f"{len(results['warnings'])} warnings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
