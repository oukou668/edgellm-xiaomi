#!/usr/bin/env python3
"""Run official-native scorer adapters over Android table-reproduction evidence.

The adapters in this file are host-side only. They never invoke the Android app
or the model; they consume raw evidence exported by the app and produce
leaderboard-safe rows that can be merged by aggregate_official_evaluation.py.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict
from typing import Any

import replay_harness_evaluator as replay


ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "configs" / "table_reproduction_v1.json"
SCORER_CONFIG_PATH = ROOT / "configs" / "official_scorers_v1.json"
DATASET_ARTIFACTS = ROOT / "artifacts" / "table_reproduction" / "datasets"


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def normalize_letter(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"\(?\b([A-J])\b\)?", text)
    return match.group(1) if match else text[:1]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def task_id_base(entry: dict[str, Any]) -> str:
    doc_id = str(entry.get("doc_id") or entry.get("sample_id") or "")
    if doc_id:
        return doc_id
    task_id = str(entry.get("task_id") or entry.get("id") or "")
    dataset_id = str(entry.get("dataset_id") or entry.get("task_name") or "")
    prefix = f"{dataset_id}__"
    if task_id.startswith(prefix):
        return task_id[len(prefix) :]
    return task_id


def sample_id_for(entry: dict[str, Any]) -> str:
    value = task_id_base(entry)
    return re.sub(r"__sample\d+$", "", value)


def load_dataset_samples(artifact_root: pathlib.Path, dataset_id: str) -> dict[str, dict[str, Any]]:
    path = artifact_root / dataset_id / "samples.jsonl"
    if not path.is_file():
        return {}
    rows = read_jsonl(path)
    return {str(row.get("sample_id") or row.get("id") or index): row for index, row in enumerate(rows)}


def merged_doc(entry: dict[str, Any], sample: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if sample:
        doc = sample.get("harness_replay_doc")
        if isinstance(doc, dict):
            merged.update(doc)
        official = sample.get("official_eval_metadata")
        if isinstance(official, dict):
            merged.update({f"official_{key}": value for key, value in official.items()})
            merged.update({key: value for key, value in official.items() if key not in merged})
    entry_official = entry.get("official_eval_metadata")
    if isinstance(entry_official, dict):
        merged.update({f"official_{key}": value for key, value in entry_official.items()})
        merged.update({key: value for key, value in entry_official.items() if key not in merged})
    entry_doc = entry.get("doc")
    if isinstance(entry_doc, dict):
        merged.update(entry_doc)
    return merged


def required_missing(values: dict[str, Any], required_fields: list[str]) -> list[str]:
    missing = []
    for field in required_fields:
        value = values.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    return missing


def official_row(
    entry: dict[str, Any],
    scorer: dict[str, Any],
    *,
    score: float | str,
    parse_status: str,
    score_status: str,
    blocked_reason: str = "",
    details: dict[str, Any] | None = None,
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    dataset_id = scorer["dataset_id"]
    task_name = replay.normalize_task_name(str(entry.get("task_name") or dataset_id))
    blocker = {}
    if score_status == "blocked":
        blocker = {
            "task_name": task_name,
            "dataset_id": dataset_id,
            "dataset_name": str(entry.get("dataset_name") or dataset_id),
            "blocker_type": blocked_reason or "official_scorer_blocked",
            "reason": blocked_reason or "official_scorer_blocked",
            "message": blocked_reason or "Official scorer could not score this row.",
            "remediation": "Inspect scorer_details and rerun with the required official fields/configuration.",
            "preferred_scorer_backend": scorer.get("scorer_backend", ""),
            "details": details or {},
        }
    return {
        "task_name": task_name,
        "dataset_id": dataset_id,
        "dataset_name": str(entry.get("dataset_name") or dataset_id),
        "task_id": str(entry.get("task_id") or entry.get("doc_id") or ""),
        "sample_id": sample_id_for(entry),
        "repeat_index": int(entry.get("repeat_index") or 0),
        "model_id": str(entry.get("model_id") or ""),
        "scorer_backend": scorer.get("scorer_backend", ""),
        "scorer_adapter_id": scorer.get("adapter_id", ""),
        "scorer_repo_url": scorer.get("repo_url", ""),
        "scorer_repo_commit": scorer.get("repo_commit", ""),
        "scorer_entrypoint": scorer.get("entrypoint", ""),
        "official_benchmark": False,
        "evaluation_tier": "blocker" if score_status == "blocked" else "official_partial",
        "coverage_status": "blocked" if score_status == "blocked" else "partial",
        "average_eligible": False,
        "score": score,
        "parse_status": parse_status,
        "score_status": score_status,
        "blocked_reason": blocked_reason,
        "missing_required_fields": missing_fields or [],
        "scorer_details": details or {},
        "blocker": blocker,
        "supported_by_harness": scorer.get("scorer_backend") == "harness_native",
        "skipped_reason": blocked_reason if score_status == "blocked" else "",
    }


def blocker_row(dataset_id: str, scorer: dict[str, Any], reason: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return official_row(
        {
            "task_name": dataset_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset_id,
            "doc_id": "",
            "raw_generation": "",
        },
        scorer,
        score="",
        parse_status="blocked",
        score_status="blocked",
        blocked_reason=reason,
        details=details or {},
        missing_fields=[],
    )


# SuperGPQA official-style option extraction.
def extract_option_labels(text: Any, options: str = "ABCDEFGHIJ") -> str | None:
    if not isinstance(text, str):
        return "error"
    option_str = "".join(chr(65 + i) for i in range(len(options))) if options else "ABCDEFGHIJ"
    patterns = [
        rf"[Tt]he\s+(?:\w+\s+)?(?:answer|option)(?:\w+\s+)?\s+is?:?\s*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*([{option_str}])(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
        rf"(?i:Answer)[\*\s]*:\s*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*([{option_str}])(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
        rf"^[^\w\r\n]*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*([{option_str}])(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
    ]
    stripped = text.rstrip()
    last_line = stripped.split("\n")[-1]
    for source in [last_line, stripped]:
        for pattern in patterns:
            match = re.search(pattern, source, re.IGNORECASE)
            if match:
                return match.group(1).upper()
    return None


def extract_option_content(text: Any, options_content: list[str]) -> str | None:
    if not isinstance(text, str) or not isinstance(options_content, list):
        return "error"
    escaped = [re.escape(str(option)) for option in options_content]
    if not escaped:
        return None
    joined = "|".join(escaped)
    patterns = [
        rf"[Tt]he\s+(?:\w+\s+)?(?:answer|option)(?:\w+\s+)?\s+is:?\s*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*({joined})(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
        rf"(?i:Answer)\s*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*({joined})(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
        rf"^[^\w\r\n]*(?:[\*\$\{{\(\[\\]*(?:(?:\\boxed|\\mathbf|\\mathrm|\\text)\{{)?)*\s*({joined})(?:\\?\}}?\$?\)?\]?\}}?)*(?:[\s:\.\*)]|$)",
    ]
    stripped = text.rstrip()
    last_line = stripped.split("\n")[-1]
    for source in [last_line, stripped]:
        for pattern in patterns:
            match = re.search(pattern, source)
            if match:
                matched = match.group(1)
                for option in options_content:
                    if matched == str(option):
                        return str(option)
                return matched
    return None


def score_mc_official(entry: dict[str, Any], sample: dict[str, Any] | None, scorer: dict[str, Any]) -> dict[str, Any]:
    doc = merged_doc(entry, sample)
    raw = str(entry.get("raw_generation") or "")
    options = doc.get("options") or doc.get("choices") or (sample or {}).get("options") or []
    if not isinstance(options, list):
        options = []
    gold = normalize_letter((sample or {}).get("answer") or doc.get("answer") or entry.get("gold"))
    protocol = entry.get("protocol") if isinstance(entry.get("protocol"), dict) else {}
    choice_id = str(entry.get("choice_order_id") or protocol.get("choice_order_sha256") or "")
    if scorer["dataset_id"] == "supergpqa":
        missing = required_missing(
            {
                "raw_generation": raw,
                "options": options,
                "answer_letter": gold,
                "discipline": (sample or {}).get("discipline") or doc.get("discipline") or "",
                "field": (sample or {}).get("field") or doc.get("field") or "",
                "subfield": (sample or {}).get("subfield") or doc.get("subfield") or "",
                "difficulty": (sample or {}).get("difficulty") or doc.get("difficulty") or "",
            },
            scorer["required_input_fields"],
        )
    else:
        missing = required_missing(
            {
                "raw_generation": raw,
                "doc": doc,
                "choice_order_id": choice_id,
                "sample_id": sample_id_for(entry),
            },
            scorer["required_input_fields"],
        )
    if scorer["dataset_id"] == "gpqa_diamond":
        expected_choice_id = replay.sha256_text(stable_json(options)) if options else ""
        if not choice_id:
            return official_row(entry, scorer, score="", parse_status="blocked", score_status="blocked", blocked_reason="missing_choice_order_id", details={"missing": missing})
        if expected_choice_id and choice_id != expected_choice_id:
            return official_row(
                entry,
                scorer,
                score="",
                parse_status="blocked",
                score_status="blocked",
                blocked_reason="choice_order_mismatch",
                details={"choice_order_id": choice_id, "expected_choice_order_id": expected_choice_id},
            )
    predicted = extract_option_labels(raw, "ABCDEFGHIJ")
    parse_status = "parsed"
    if predicted is None:
        content = extract_option_content(raw, [str(option) for option in options])
        if content and content in options:
            predicted = chr(ord("A") + options.index(content))
        else:
            parse_status = "miss"
            predicted = ""
    if predicted == "error":
        parse_status = "error"
        predicted = ""
    score = 1.0 if predicted and predicted == gold else 0.0
    details = {
        "predicted_answer": predicted,
        "gold_answer": gold,
        "options": options,
        "official_field_warnings": missing,
        "discipline": (sample or {}).get("discipline") or doc.get("discipline") or "",
        "field": (sample or {}).get("field") or doc.get("field") or "",
        "subfield": (sample or {}).get("subfield") or doc.get("subfield") or "",
        "difficulty": (sample or {}).get("difficulty") or doc.get("difficulty") or "",
    }
    return official_row(entry, scorer, score=score, parse_status=parse_status, score_status="scored", details=details, missing_fields=missing)


# Multi-IF official-style instruction checks for host replay. Unknown official
# instructions are explicit blockers instead of silent false negatives.
def normalize_instruction_ids(value: Any) -> list[str]:
    parsed = parse_json_value(value)
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    if parsed:
        return [str(parsed)]
    return []


def normalize_kwargs(value: Any) -> list[dict[str, Any]]:
    parsed = parse_json_value(value)
    if isinstance(parsed, list):
        output = []
        for item in parsed:
            item = parse_json_value(item)
            output.append(item if isinstance(item, dict) else {})
        return output
    return []


def multi_if_turn_payload(doc: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], str]:
    for index in [3, 2, 1]:
        ids = normalize_instruction_ids(doc.get(f"turn_{index}_instruction_id_list") or doc.get(f"official_turn_{index}_instruction_id_list"))
        kwargs = normalize_kwargs(doc.get(f"turn_{index}_kwargs") or doc.get(f"official_turn_{index}_kwargs"))
        if ids:
            return ids, kwargs, f"turn_{index}"
    ids = normalize_instruction_ids(doc.get("instruction_id_list") or doc.get("official_instruction_id_list"))
    kwargs = normalize_kwargs(doc.get("kwargs") or doc.get("official_kwargs"))
    return ids, kwargs, "single_turn"


def word_count(text: str) -> int:
    return len(re.findall(r"\b\S+\b", text))


def check_multi_if_instruction(response: str, instruction_id: str, kwargs: dict[str, Any]) -> tuple[bool, str]:
    if instruction_id == "change_case:english_lowercase":
        letters = [char for char in response if char.isalpha()]
        return all(char == char.lower() for char in letters), "lowercase"
    if instruction_id == "change_case:english_uppercase":
        letters = [char for char in response if char.isalpha()]
        return all(char == char.upper() for char in letters), "uppercase"
    if instruction_id == "startend:end_checker":
        end_phrase = str(kwargs.get("end_phrase") or "")
        return bool(end_phrase) and response.rstrip().endswith(end_phrase), "end_checker"
    if instruction_id == "startend:start_checker":
        start_phrase = str(kwargs.get("start_phrase") or "")
        return bool(start_phrase) and response.lstrip().startswith(start_phrase), "start_checker"
    if instruction_id == "length_constraints:number_words":
        relation = str(kwargs.get("relation") or "").lower()
        expected = int(kwargs.get("num_words") or 0)
        count = word_count(response)
        if relation == "at least":
            return count >= expected, "number_words_at_least"
        if relation == "at most":
            return count <= expected, "number_words_at_most"
        if relation in {"equal to", "exactly"}:
            return count == expected, "number_words_exactly"
        return False, "number_words_unknown_relation"
    if instruction_id == "length_constraints:number_sentences":
        relation = str(kwargs.get("relation") or "").lower()
        expected = int(kwargs.get("num_sentences") or 0)
        sentences = [part for part in re.split(r"[.!?。！？]+", response.strip()) if part.strip()]
        count = len(sentences)
        if relation == "at least":
            return count >= expected, "number_sentences_at_least"
        if relation == "at most":
            return count <= expected, "number_sentences_at_most"
        if relation in {"equal to", "exactly"}:
            return count == expected, "number_sentences_exactly"
        return False, "number_sentences_unknown_relation"
    if instruction_id == "punctuation:no_comma":
        return "," not in response and "，" not in response, "no_comma"
    if instruction_id == "keywords:forbidden_words":
        forbidden = kwargs.get("forbidden_words") or []
        if not isinstance(forbidden, list):
            forbidden = [forbidden]
        return not any(str(word) and str(word) in response for word in forbidden), "forbidden_words"
    return False, f"unsupported_instruction:{instruction_id}"


def multi_if_variants(response: str) -> list[str]:
    lines = response.split("\n")
    candidates = [
        response,
        response.replace("*", ""),
        "\n".join(lines[1:]).strip(),
        "\n".join(lines[:-1]).strip(),
        "\n".join(lines[1:-1]).strip(),
    ]
    candidates.extend(candidate.replace("*", "") for candidate in list(candidates))
    return [candidate for candidate in candidates if candidate is not None]


def score_multi_if(entry: dict[str, Any], sample: dict[str, Any] | None, scorer: dict[str, Any]) -> dict[str, Any]:
    doc = merged_doc(entry, sample)
    raw = str(entry.get("raw_generation") or "")
    instruction_ids, kwargs_list, turn_id = multi_if_turn_payload(doc)
    values = {
        "raw_generation": raw,
        "key": (sample or {}).get("sample_id") or doc.get("key") or doc.get("official_key"),
        "language": (sample or {}).get("language") or doc.get("language") or doc.get("official_language"),
        "turn_prompts": [doc.get(f"turn_{index}_prompt") or doc.get(f"official_turn_{index}_prompt") for index in [1, 2, 3]],
        "instruction_id_list": instruction_ids,
        "kwargs": kwargs_list,
    }
    missing = required_missing(values, scorer["required_input_fields"])
    if not instruction_ids:
        return official_row(entry, scorer, score="", parse_status="blocked", score_status="blocked", blocked_reason="missing_multi_if_instruction_ids", details={"missing": missing})
    while len(kwargs_list) < len(instruction_ids):
        kwargs_list.append({})
    strict_results = []
    loose_results = []
    unsupported = []
    for instruction_id, kwargs in zip(instruction_ids, kwargs_list):
        ok, label = check_multi_if_instruction(raw, instruction_id, kwargs)
        strict_results.append(ok)
        if label.startswith("unsupported_instruction"):
            unsupported.append(instruction_id)
        loose_ok = any(check_multi_if_instruction(candidate, instruction_id, kwargs)[0] for candidate in multi_if_variants(raw))
        loose_results.append(loose_ok)
    if unsupported:
        return official_row(
            entry,
            scorer,
            score="",
            parse_status="blocked",
            score_status="blocked",
            blocked_reason="unsupported_multi_if_instruction",
            details={"unsupported_instruction_ids": unsupported, "turn_id": turn_id},
            missing_fields=missing,
        )
    details = {
        "turn_id": turn_id,
        "instruction_id_list": instruction_ids,
        "strict_follow_instruction_list": strict_results,
        "loose_follow_instruction_list": loose_results,
        "prompt_level_strict_acc": all(strict_results),
        "instruction_level_strict_acc": sum(strict_results) / len(strict_results),
        "prompt_level_loose_acc": all(loose_results),
        "instruction_level_loose_acc": sum(loose_results) / len(loose_results),
        "official_field_warnings": missing,
        "transcript_semantics_preserved": bool(doc.get("turns") and doc.get("responses")),
    }
    return official_row(entry, scorer, score=1.0 if all(strict_results) else 0.0, parse_status="parsed", score_status="scored", details=details, missing_fields=missing)


JUDGE_PROMPT = """You are tasked with evaluating a model response to see if it meets a specific criteria.
The criteria will always be YES/NO evaluation.

The model response is as follows:
<MODEL_RESPONSE>
{}
</MODEL_RESPONSE>

The criteria that the model response must meet is as follows. Be VERY STRICT!:
<CRITERIA>
{}
</CRITERIA>

Print your reasoning followed by your verdict, either "YES" or "NO"."""


def load_judge_config(path: str) -> dict[str, Any]:
    if not path:
        return {}
    return read_json(pathlib.Path(path))


def score_multichallenge(
    entry: dict[str, Any],
    sample: dict[str, Any] | None,
    scorer: dict[str, Any],
    judge_config: dict[str, Any],
    allow_mock_judge: bool,
) -> dict[str, Any]:
    doc = merged_doc(entry, sample)
    raw = str(entry.get("raw_generation") or "")
    question_id = str(doc.get("QUESTION_ID") or doc.get("question_id") or sample_id_for(entry))
    pass_criteria = str(doc.get("PASS_CRITERIA") or doc.get("pass_criteria") or "").upper()
    target_question = str(doc.get("TARGET_QUESTION") or doc.get("target_question") or "")
    axis = str(doc.get("AXIS") or doc.get("axis") or "")
    values = {
        "raw_generation": raw,
        "QUESTION_ID": question_id,
        "AXIS": axis,
        "CONVERSATION": doc.get("CONVERSATION") or doc.get("conversation"),
        "TARGET_QUESTION": target_question,
        "PASS_CRITERIA": pass_criteria,
    }
    missing = required_missing(values, scorer["required_input_fields"])
    locked = bool(judge_config.get("judge_config_id") and judge_config.get("judge_model") and judge_config.get("judge_prompt_sha256"))
    mock_verdicts = judge_config.get("mock_verdicts") if isinstance(judge_config.get("mock_verdicts"), dict) else {}
    if not locked:
        return official_row(
            entry,
            scorer,
            score="",
            parse_status="blocked",
            score_status="blocked",
            blocked_reason="multichallenge_judge_config_not_locked",
            details={"missing": missing, "policy": scorer.get("judge_policy", "table_priority")},
        )
    if mock_verdicts and allow_mock_judge:
        verdict_row = mock_verdicts.get(question_id) or mock_verdicts.get(sample_id_for(entry)) or {}
        verdict = str(verdict_row.get("verdict") or "NO").upper()
        reasoning = str(verdict_row.get("reasoning") or "mock judge verdict")
        score = 1.0 if verdict == pass_criteria else 0.0
        details = {
            "question_id": question_id,
            "axis": axis,
            "judge_config_id": judge_config.get("judge_config_id"),
            "judge_model": judge_config.get("judge_model"),
            "judge_prompt_sha256": judge_config.get("judge_prompt_sha256"),
            "judge_prompt": JUDGE_PROMPT,
            "judge_reasoning": reasoning,
            "judge_verdict": verdict,
            "pass_criteria": pass_criteria,
            "mock_judge": True,
            "official_field_warnings": missing,
        }
        return official_row(entry, scorer, score=score, parse_status="parsed", score_status="scored", details=details, missing_fields=missing)
    return official_row(
        entry,
        scorer,
        score="",
        parse_status="blocked",
        score_status="blocked",
        blocked_reason="multichallenge_judge_execution_not_configured",
        details={"judge_config_id": judge_config.get("judge_config_id"), "question_id": question_id},
        missing_fields=missing,
    )


def extract_boxed_answer(text: str) -> str | None:
    start = text.rfind("\\boxed{")
    if start >= 0:
        index = start + len("\\boxed{")
        depth = 1
        chars = []
        while index < len(text):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return "".join(chars).strip()
            chars.append(char)
            index += 1
    answer_match = re.search(r"(?:the\s+)?(?:final\s+)?answer\s+is\s*:?\s*(.+?)(?:\.\s*$|\n|$)", text, re.IGNORECASE | re.DOTALL)
    if answer_match:
        return answer_match.group(1).strip()
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    return matches[-1] if matches else None


def normalize_math_answer(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\\boxed\{(.+)\}$", r"\1", text)
    text = text.strip("$ ")
    text = text.replace("\\left", "").replace("\\right", "")
    text = re.sub(r"\s+", "", text)
    text = text.replace("\\dfrac", "\\frac")
    return text.lower()


def math_answers_match(predicted: str | None, gold: str) -> bool:
    if predicted is None:
        return False
    pred_norm = normalize_math_answer(predicted)
    gold_norm = normalize_math_answer(gold)
    if pred_norm == gold_norm:
        return True
    pred_float = safe_float(pred_norm)
    gold_float = safe_float(gold_norm)
    return pred_float is not None and gold_float is not None and pred_float == gold_float


def score_matharena(entry: dict[str, Any], sample: dict[str, Any] | None, scorer: dict[str, Any]) -> dict[str, Any]:
    doc = merged_doc(entry, sample)
    raw = str(entry.get("raw_generation") or "")
    gold = str((sample or {}).get("answer") or doc.get("answer") or entry.get("gold") or "")
    output_tokens = entry.get("output_tokens") or entry.get("generated_tokens") or entry.get("estimated_output_tokens") or len(raw.split())
    values = {
        "raw_generation": raw,
        "problem_idx": sample_id_for(entry),
        "answer": gold,
        "output_tokens": output_tokens,
    }
    missing = required_missing(values, scorer["required_input_fields"])
    predicted = extract_boxed_answer(raw)
    score = 1.0 if math_answers_match(predicted, gold) else 0.0
    details = {
        "predicted_answer": predicted,
        "gold_answer": gold,
        "output_tokens": output_tokens,
        "adapter_mode": "matharena_final_answer_compat",
        "official_field_warnings": missing,
    }
    parse_status = "parsed" if predicted is not None else "miss"
    return official_row(entry, scorer, score=score, parse_status=parse_status, score_status="scored", details=details, missing_fields=missing)


# BBEH official evaluator logic from google-deepmind/bbeh bbeh/evaluate.py.
def bbeh_strip_latex(response: str) -> str:
    if response.startswith("$") and response.endswith("$"):
        response = response[1:-1]
    if "boxed{" in response and response.endswith("}"):
        response = response[0:-1].split("boxed{")[1]
    if "text{" in response and response.endswith("}"):
        response = response[0:-1].split("text{")[1]
    if "texttt{" in response and response.endswith("}"):
        response = response[0:-1].split("texttt{")[1]
    return response


def bbeh_extract_answer(sample: str) -> str:
    answer_prefixes = ["The answer is:", "The final answer is ", "The final answer is: ", "The answer is "]
    answer = sample
    for prefix in answer_prefixes:
        if prefix in answer:
            answer = answer.split(prefix)[-1].strip()
    if answer.endswith("."):
        answer = answer[:-1]
    return bbeh_strip_latex(answer)


def bbeh_fuzzy_match(prediction: str, reference: str) -> bool:
    if prediction == reference:
        return True
    if len(prediction) == 3 and prediction[0] == "(" and prediction[-1] == ")":
        return prediction[1] == reference
    if len(reference) == 3 and reference[0] == "(" and reference[-1] == ")":
        return reference[1] == prediction
    try:
        if float(prediction) == float(reference):
            return True
    except ValueError:
        pass
    if prediction.replace("'", "") == reference.replace("'", ""):
        return True
    if f"[{reference}]" == prediction or f"[{prediction}]" == reference:
        return True
    if prediction.endswith("?") and prediction[:-1] == reference:
        return True
    return False


def bbeh_preprocess_sample(sample: str) -> str:
    prediction = bbeh_extract_answer(sample.strip()).lower()
    prediction = prediction.replace(", ", ",").replace("**", "")
    prediction = prediction.split("\n")[0]
    return prediction[0:-1] if prediction.endswith(".") else prediction


def bbeh_preprocess_reference(reference: str) -> str:
    return reference.strip().lower().replace(", ", ",")


def bbeh_evaluate_correctness(sample: str, reference: str) -> bool:
    return bbeh_fuzzy_match(bbeh_preprocess_sample(sample), bbeh_preprocess_reference(reference))


def score_bbeh(entry: dict[str, Any], sample: dict[str, Any] | None, scorer: dict[str, Any]) -> dict[str, Any]:
    doc = merged_doc(entry, sample)
    raw = str(entry.get("raw_generation") or "")
    gold = str((sample or {}).get("answer") or doc.get("target") or entry.get("gold") or "")
    values = {"raw_generation": raw, "reference_answer": gold, "sample_id": sample_id_for(entry)}
    missing = required_missing(values, scorer["required_input_fields"])
    correct = bbeh_evaluate_correctness(raw, gold)
    details = {
        "predicted_answer": bbeh_preprocess_sample(raw),
        "gold_answer": bbeh_preprocess_reference(gold),
        "official_field_warnings": missing,
    }
    return official_row(entry, scorer, score=1.0 if correct else 0.0, parse_status="parsed", score_status="scored", details=details, missing_fields=missing)


def score_entry(
    entry: dict[str, Any],
    sample: dict[str, Any] | None,
    scorer: dict[str, Any],
    judge_config: dict[str, Any],
    allow_mock_judge: bool,
) -> dict[str, Any]:
    adapter_id = scorer["adapter_id"]
    if adapter_id == "gpqa_harness_official_v1":
        return score_mc_official(entry, sample, scorer)
    if adapter_id == "supergpqa_official_v1":
        return score_mc_official(entry, sample, scorer)
    if adapter_id == "multi_if_official_v1":
        return score_multi_if(entry, sample, scorer)
    if adapter_id == "multichallenge_judge_v1":
        return score_multichallenge(entry, sample, scorer, judge_config, allow_mock_judge)
    if adapter_id == "matharena_final_answer_v1":
        return score_matharena(entry, sample, scorer)
    if adapter_id == "bbeh_official_v1":
        return score_bbeh(entry, sample, scorer)
    return official_row(entry, scorer, score="", parse_status="blocked", score_status="blocked", blocked_reason="unknown_official_scorer_adapter")


def repeat_gate_passes(rows: list[dict[str, Any]], scorer: dict[str, Any]) -> bool:
    if any(row.get("score_status") != "scored" or row.get("missing_required_fields") for row in rows):
        return False
    expected = int(scorer.get("expected_sample_count") or 0)
    if expected and len(rows) != expected:
        return False
    policy = scorer.get("repeat_policy") if isinstance(scorer.get("repeat_policy"), dict) else {}
    policy_type = policy.get("type")
    grouped: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        grouped[str(row.get("sample_id") or "")].add(int(row.get("repeat_index") or 0))
    if policy_type == "avg16":
        problems = int(policy.get("problems") or 0)
        samples_per_problem = int(policy.get("samples_per_problem") or 16)
        return len(grouped) == problems and all(len(repeats) == samples_per_problem for repeats in grouped.values())
    return len(grouped) == expected


def finalize_dataset_rows(rows: list[dict[str, Any]], scorer: dict[str, Any]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    if any(row.get("evaluation_tier") == "blocker" for row in rows):
        return rows
    if not repeat_gate_passes(rows, scorer):
        for row in rows:
            row["official_benchmark"] = False
            row["evaluation_tier"] = "official_partial"
            row["coverage_status"] = "partial"
            row["average_eligible"] = False
        return rows
    for row in rows:
        row["official_benchmark"] = True
        row["evaluation_tier"] = "official_benchmark"
        row["coverage_status"] = "covered"
        row["average_eligible"] = True
    return rows


def dataset_summary(rows: list[dict[str, Any]], scorer: dict[str, Any]) -> dict[str, Any]:
    scored = [row for row in rows if row.get("score_status") == "scored"]
    scores = [float(row["score"]) for row in scored if row.get("score") != ""]
    axis_scores: dict[str, float] = {}
    if scorer["dataset_id"] == "multichallenge":
        by_axis: dict[str, list[float]] = defaultdict(list)
        for row in scored:
            axis = str((row.get("scorer_details") or {}).get("axis") or "")
            if axis:
                by_axis[axis].append(float(row["score"]))
        axis_scores = {axis: statistics.mean(values) for axis, values in by_axis.items() if values}
    return {
        "dataset_id": scorer["dataset_id"],
        "adapter_id": scorer["adapter_id"],
        "row_count": len(rows),
        "scored_count": len(scored),
        "blocker_count": sum(1 for row in rows if row.get("evaluation_tier") == "blocker"),
        "official_benchmark_count": sum(1 for row in rows if row.get("official_benchmark")),
        "average_eligible_count": sum(1 for row in rows if row.get("average_eligible")),
        "score_mean": statistics.mean(scores) if scores else None,
        "axis_scores": axis_scores,
        "tier_histogram": dict(Counter(str(row.get("evaluation_tier") or "") for row in rows)),
        "coverage_histogram": dict(Counter(str(row.get("coverage_status") or "") for row in rows)),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    report_dir = pathlib.Path(args.report_dir).resolve()
    output_dir = pathlib.Path(args.out).resolve() if args.out else report_dir / "official_scorers"
    output_dir.mkdir(parents=True, exist_ok=True)
    scorer_config = read_json(pathlib.Path(args.scorer_config))
    suite = read_json(SUITE_PATH)
    dataset_names = replay.parse_dataset_filter(args.datasets)
    scorers = {
        scorer["dataset_id"]: scorer
        for scorer in scorer_config["scorers"]
        if dataset_names is None or scorer["dataset_id"] in dataset_names
    }
    entries = replay.load_android_report_entries(report_dir, set(scorers) if scorers else dataset_names)
    entries_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        dataset_id = str(entry.get("dataset_id") or entry.get("task_name") or "")
        if dataset_id in scorers:
            entries_by_dataset[dataset_id].append(entry)
    artifact_root = pathlib.Path(args.dataset_artifacts_dir)
    judge_config = load_judge_config(args.judge_config)

    all_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for dataset_id, scorer in sorted(scorers.items()):
        samples = load_dataset_samples(artifact_root, dataset_id)
        rows: list[dict[str, Any]] = []
        if not entries_by_dataset.get(dataset_id):
            rows.append(blocker_row(dataset_id, scorer, "missing_inference_rows", {"report_dir": str(report_dir)}))
        for entry in entries_by_dataset.get(dataset_id, []):
            sample = samples.get(sample_id_for(entry)) or samples.get(task_id_base(entry))
            rows.append(score_entry(entry, sample, scorer, judge_config, args.allow_mock_judge))
        rows = finalize_dataset_rows(rows, scorer)
        all_rows.extend(rows)
        summaries[dataset_id] = dataset_summary(rows, scorer)

    result = {
        "schema_version": 1,
        "report_dir": str(report_dir),
        "suite_id": suite.get("suite_id", ""),
        "scorer_config": str(pathlib.Path(args.scorer_config).resolve()),
        "official_scorer_result_count": len(all_rows),
        "datasets": summaries,
        "tasks": all_rows,
    }
    write_jsonl(output_dir / "official_scorer_rows.jsonl", all_rows)
    (output_dir / "official_scorer_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(output_dir / "official_scorer_blockers.jsonl", [row["blocker"] for row in all_rows if row.get("blocker")])
    (output_dir / "official_scorer_summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run official scorer adapters over Android raw evidence.")
    parser.add_argument("report_dir", help="Android report directory containing raw_evidence.jsonl or harness_replay_entries.jsonl.")
    parser.add_argument("--datasets", action="append", help="Dataset id or comma-separated ids. Defaults to all official scorer datasets.")
    parser.add_argument("--out", default="", help="Output directory. Defaults to report_dir/official_scorers.")
    parser.add_argument("--dataset-artifacts-dir", default=str(DATASET_ARTIFACTS))
    parser.add_argument("--scorer-config", default=str(SCORER_CONFIG_PATH))
    parser.add_argument("--judge-config", default="", help="Locked MultiChallenge judge config JSON.")
    parser.add_argument("--allow-mock-judge", action="store_true", help="Allow mock_verdicts in --judge-config for tests only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run(args)
    print(
        "Official scorers complete: "
        f"{result['official_scorer_result_count']} rows, "
        f"{sum(row['official_benchmark_count'] for row in result['datasets'].values())} official-benchmark rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
