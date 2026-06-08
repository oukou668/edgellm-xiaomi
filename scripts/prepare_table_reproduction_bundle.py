#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import re
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "configs/table_reproduction_v1.json"
DEFAULT_ARTIFACTS = ROOT / "artifacts/table_reproduction/datasets"
DEFAULT_OUT = ROOT / "artifacts/table_reproduction/run_bundles"
PARSER_SMOKE_MAX_TOKENS = 32


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path):
    rows = []
    with path.open() as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            row["_line_no"] = line_no
            rows.append(row)
    return rows


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def parse_dataset_filter(values):
    if not values:
        return None
    parsed = set()
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                parsed.add(part)
    return parsed or None


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_harness_suffix(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def letter_index(value):
    text = str(value or "").strip().upper()
    if len(text) == 1 and "A" <= text <= "Z":
        return ord(text) - ord("A")
    return value


def prompt_text_for(row, prompt, messages):
    if prompt:
        return str(prompt)
    if isinstance(messages, list) and messages:
        parts = []
        for message in messages:
            if isinstance(message, dict):
                parts.append(f"{message.get('role', 'user')}: {message.get('content', '')}")
            else:
                parts.append(str(message))
        return "\n".join(parts)
    return ""


def choices_from_prompt(prompt):
    choices = []
    for line in str(prompt or "").splitlines():
        match = re.match(r"^\s*([A-J])\.\s*(.+?)\s*$", line)
        if match:
            choices.append(match.group(2))
    return choices


def replay_doc_from_row(dataset_id, row, prompt, answer):
    doc = row.get("harness_replay_doc")
    if isinstance(doc, dict):
        copied = dict(doc)
        if dataset_id == "mmlu_redux":
            copied["answer"] = letter_index(copied.get("answer"))
        return copied

    choices = choices_from_prompt(prompt)
    if dataset_id in {"mmlu_pro", "mmlu_redux", "supergpqa", "gpqa_diamond"}:
        question = str(prompt or "").split("\n\nChoices:", 1)[0]
        source_subtask = row.get("source_subtask") or row.get("category") or row.get("subject")
        doc = {
            "question": question,
            "choices": choices,
            "options": choices,
            "answer": answer,
        }
        if source_subtask:
            doc["source_subtask"] = source_subtask
            doc["category"] = source_subtask
            doc["dataset_name"] = source_subtask
        if dataset_id == "mmlu_redux":
            doc["dataset_name"] = row.get("source_config") or doc.get("dataset_name") or ""
            doc["answer"] = letter_index(answer)
        if dataset_id == "gpqa_diamond":
            for index, choice in enumerate(choices[:4], 1):
                doc[f"choice{index}"] = choice
            doc["answer"] = f"({answer})" if len(str(answer)) == 1 else answer
        return doc

    if dataset_id == "ifeval":
        meta = row.get("official_eval_metadata") if isinstance(row.get("official_eval_metadata"), dict) else {}
        return {
            "key": row.get("sample_id") or row.get("key"),
            "prompt": prompt,
            "instruction_id_list": row.get("instruction_id_list") or meta.get("instruction_id_list"),
            "kwargs": row.get("kwargs") or meta.get("kwargs"),
        }

    if dataset_id in {"math500", "aime25", "aime26", "hmmt_feb_2026"}:
        problem = str(prompt or "")
        marker = "\n\n"
        if marker in problem:
            problem = problem.split(marker, 1)[1]
        doc = {"problem": problem, "answer": answer}
        if row.get("solution"):
            doc["solution"] = row["solution"]
        return doc

    if dataset_id in {"bbh", "bbeh"}:
        return {
            "input": prompt,
            "target": answer,
            "source_subtask": row.get("source_config") or row.get("source_subtask") or row.get("dataset_name") or "",
            "dataset_name": row.get("source_config") or row.get("dataset_name") or "",
        }

    return dict(row)


def harness_task_for(dataset_id, row, doc):
    if dataset_id == "mmlu_pro":
        subtask = normalize_harness_suffix(doc.get("source_subtask") or doc.get("category") or row.get("source_subtask"))
        return f"mmlu_pro_{subtask}" if subtask else "mmlu_pro"
    if dataset_id == "mmlu_redux":
        subject = normalize_harness_suffix(doc.get("dataset_name") or row.get("source_config") or row.get("subject"))
        return f"mmlu_redux_{subject}_generative" if subject else "mmlu_redux_generative"
    if dataset_id == "ifeval":
        return "ifeval"
    if dataset_id == "aime25":
        return "aime25"
    if dataset_id == "math500":
        return "minerva_math500"
    if dataset_id == "bbh":
        subtask = normalize_harness_suffix(doc.get("source_subtask") or row.get("source_config"))
        return f"bbh_zeroshot_{subtask}" if subtask else "bbh"
    return dataset_id


def question_from_doc(doc, prompt):
    for key in ("question", "problem", "input", "prompt"):
        value = doc.get(key)
        if value:
            return str(value)
    return str(prompt or "")


def harness_replay_entry(row, dataset, profile, model_id, artifact_hash, prompt, messages, answer, sample_id, generation_params):
    dataset_id = dataset["dataset_id"]
    prompt_text = prompt_text_for(row, prompt, messages)
    doc = replay_doc_from_row(dataset_id, row, prompt_text, str(answer))
    choices = doc.get("choices") or doc.get("options") or []
    protocol = {
        "observed_repeats": row.get("_avg_sample_count", 1),
        "expected_repeats": row.get("_avg_sample_count", 1),
        "generation_kwargs_sha256": sha256_text(stable_json(generation_params)),
        "stop_sequences_sha256": sha256_text(stable_json([])),
    }
    if choices:
        protocol["choice_order_sha256"] = sha256_text(stable_json(choices))
    choice_order_id = protocol.get("choice_order_sha256", "")

    return {
        "task_name": dataset_id,
        "dataset_id": dataset_id,
        "dataset_name": dataset["display_name"],
        "harness_task": harness_task_for(dataset_id, row, doc),
        "doc_id": sample_id,
        "question": question_from_doc(doc, prompt_text),
        "prompt_text": prompt_text,
        "prompt_sha256": sha256_text(prompt_text),
        "raw_generation": "",
        "rawGeneration": "",
        "repeat_index": row.get("_avg_sample_index", 0),
        "model_id": model_id,
        "summary_id": "",
        "gold": str(answer),
        "doc": doc,
        "protocol": protocol,
        "choice_order_id": choice_order_id,
        "sample_denominator": dataset["canonical_sample_count"],
        "prompt_profile_id": dataset["prompt_builder_id"],
        "judge_config_id": "unlocked" if dataset.get("requires_llm_judge") else "",
        "official_eval_metadata": row.get("official_eval_metadata") if isinstance(row.get("official_eval_metadata"), dict) else {},
        "official_source_row": row.get("harness_replay_doc") if isinstance(row.get("harness_replay_doc"), dict) else {},
        "dataset_artifact_hash": artifact_hash,
        "source_repo": dataset["source_repo"],
        "source_revision": dataset["source_revision"],
        "dataset_revision": dataset["source_revision"],
        "prompt_builder_id": dataset["prompt_builder_id"],
        "parser_id": dataset["parser_id"],
        "scorer_id": dataset["scorer_id"],
        "preferred_scorer_backend": dataset.get("preferred_scorer_backend", ""),
        "required_coverage": dataset.get("required_coverage", ""),
        "main_leaderboard_eligible": bool(dataset.get("main_leaderboard_eligible", False)),
        "official_table_score": dataset["official_table_scores"].get(model_id),
        "context_window_size": profile["context_window_size"],
        "formal_max_tokens": profile["max_tokens"],
    }


def select_rows(rows, suite_kind, dataset_id, profile):
    if suite_kind == "full":
        selected = rows
    elif suite_kind == "parser_smoke":
        selected = [min(rows, key=prompt_length)]
    else:
        selected = rows[:1]
    if not selected:
        raise SystemExit(f"dataset {dataset_id} has no samples")

    repeats = 1
    if suite_kind in {"protocol_smoke", "full"} and profile.get("samples_per_problem") == 16:
        repeats = 16
    if suite_kind == "parser_smoke" and profile.get("samples_per_problem") == 16:
        repeats = 1
    expanded = []
    for row in selected:
        for sample_index in range(repeats):
            copy = dict(row)
            copy["_avg_sample_index"] = sample_index
            copy["_avg_sample_count"] = repeats
            expanded.append(copy)
    return expanded


def prompt_length(row):
    prompt = row.get("prompt") or row.get("question") or row.get("input") or ""
    messages = row.get("messages")
    if isinstance(messages, list) and messages:
        prompt = "\n".join(str(message.get("content", message)) for message in messages)
    return len(str(prompt))


def row_to_benchmark_item(row, dataset, profile, model_id, artifact_hash, suite_kind):
    sample_id = str(row.get("sample_id") or row.get("id") or row["_line_no"])
    suffix = ""
    if row.get("_avg_sample_count", 1) > 1:
        suffix = f"__sample{row['_avg_sample_index']:02d}"
    prompt = row.get("prompt") or row.get("question") or row.get("input")
    messages = row.get("messages")
    require(prompt or messages, f"{dataset['dataset_id']} sample {sample_id} missing prompt/messages")
    answer = row.get("answer") or row.get("target") or row.get("gold") or row.get("expected_answer", "")
    max_tokens = profile["max_tokens"]
    if suite_kind == "parser_smoke":
        max_tokens = min(max_tokens, PARSER_SMOKE_MAX_TOKENS)
    generation_params = {
        "temperature": 0.9,
        "top_p": 0.95,
        "top_k": 0,
        "seed": int(row.get("_avg_sample_index", 0)),
        "max_tokens": max_tokens,
        "context_window_size": profile["context_window_size"],
        "thinking_enabled": True,
    }
    item = {
        "task_id": f"{dataset['dataset_id']}__{sample_id}{suffix}",
        "dataset_id": dataset["dataset_id"],
        "sample_id": sample_id,
        "language": row.get("language", "en"),
        "category": dataset["dataset_id"],
        "prompt_class": "formal",
        "difficulty": row.get("difficulty", "formal"),
        "tags": ["table_reproduction_v1", dataset["profile_group_id"], dataset["scorer_id"]],
        "expected_answer": str(answer),
        "judge_rule": "external_scorer",
        "scorer_id": dataset["scorer_id"],
        "parser_id": dataset["parser_id"],
        "profile_group_id": dataset["profile_group_id"],
        "generation_profile_id": f"{dataset['profile_group_id']}_{profile['context_window_size']}_{profile['max_tokens']}",
        "dataset_artifact_hash": artifact_hash,
        "official_table_score": dataset["official_table_scores"].get(model_id),
        "max_new_tokens": max_tokens,
        "generation_params": generation_params,
        "metadata": {
            "source_repo": dataset["source_repo"],
            "source_revision": dataset["source_revision"],
            "prompt_builder_id": dataset["prompt_builder_id"],
            "formal_max_tokens": profile["max_tokens"],
            "avg_sample_index": row.get("_avg_sample_index", 0),
            "avg_sample_count": row.get("_avg_sample_count", 1),
            "official_eval_metadata": row.get("official_eval_metadata") if isinstance(row.get("official_eval_metadata"), dict) else {},
            "harness_replay": harness_replay_entry(
                row,
                dataset,
                profile,
                model_id,
                artifact_hash,
                prompt,
                messages,
                answer,
                sample_id,
                generation_params,
            ),
        },
    }
    if messages:
        item["messages"] = messages
    else:
        item["prompt"] = prompt
    return item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        choices=["parser_smoke", "protocol_smoke", "full"],
        default="parser_smoke",
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--dataset-artifacts-dir", default=str(DEFAULT_ARTIFACTS))
    parser.add_argument("--out-root", default=str(DEFAULT_OUT))
    parser.add_argument("--allow-missing-datasets", action="store_true")
    parser.add_argument("--datasets", action="append", help="Dataset id or comma-separated ids. Defaults to the full formal suite.")
    args = parser.parse_args()

    suite = json.loads(SUITE_PATH.read_text())
    require(args.model_id in suite["models"], f"model is not in formal suite: {args.model_id}")
    selected_datasets = parse_dataset_filter(args.datasets)
    suite_datasets = suite["datasets"]
    if selected_datasets:
        known = {dataset["dataset_id"] for dataset in suite_datasets}
        unknown = sorted(selected_datasets - known)
        require(not unknown, f"unknown formal dataset id(s): {', '.join(unknown)}")
        suite_datasets = [dataset for dataset in suite_datasets if dataset["dataset_id"] in selected_datasets]
        require(suite_datasets, "dataset filter selected no datasets")
    artifact_root = pathlib.Path(args.dataset_artifacts_dir)
    out_root = pathlib.Path(args.out_root)
    dataset_slug = ""
    if selected_datasets:
        dataset_slug = "_" + "_".join(dataset["dataset_id"] for dataset in suite_datasets)
    bundle_id = f"table_reproduction_{args.suite}{dataset_slug}_{args.model_id}_{int(time.time())}"
    bundle_dir = out_root / bundle_id
    bundle_dir.mkdir(parents=True, exist_ok=False)

    benchmark_rows = []
    blockers = []
    for dataset in suite_datasets:
        dataset_id = dataset["dataset_id"]
        dataset_dir = artifact_root / dataset_id
        samples_path = dataset_dir / "samples.jsonl"
        manifest_path = dataset_dir / "manifest.json"
        if not samples_path.is_file() or not manifest_path.is_file():
            blockers.append({"dataset_id": dataset_id, "reason": "missing official dataset artifact"})
            continue
        artifact_hash = sha256_file(samples_path)
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("source_revision") != dataset["source_revision"]:
            blockers.append({"dataset_id": dataset_id, "reason": "source_revision mismatch"})
            continue
        rows = read_jsonl(samples_path)
        profile = suite["generation_profiles"][dataset["profile_group_id"]]
        for row in select_rows(rows, args.suite, dataset_id, profile):
            benchmark_rows.append(row_to_benchmark_item(row, dataset, profile, args.model_id, artifact_hash, args.suite))

    if blockers and not args.allow_missing_datasets:
        (bundle_dir / "blockers.json").write_text(json.dumps(blockers, indent=2) + "\n")
        raise SystemExit(f"bundle blocked; see {bundle_dir / 'blockers.json'}")
    if blockers:
        (bundle_dir / "blockers.json").write_text(json.dumps(blockers, indent=2) + "\n")

    benchmark_path = bundle_dir / "benchmark.jsonl"
    with benchmark_path.open("w") as handle:
        for row in benchmark_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    manifest = {
        "bundle_id": bundle_id,
        "suite_id": suite["suite_id"],
        "suite_kind": args.suite,
        "model_id": args.model_id,
        "created_at_ms": int(time.time() * 1000),
        "task_count": len(benchmark_rows),
        "datasets": [d["dataset_id"] for d in suite_datasets],
        "selected_datasets": [d["dataset_id"] for d in suite_datasets],
        "official_loop": bool(args.suite == "full" and selected_datasets),
        "blockers": blockers,
        "expected_generation_log_rows_for_repeat_1": len(benchmark_rows),
    }
    (bundle_dir / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"bundle ready: {bundle_dir}")
    print(f"bundle_id={bundle_id}")
    print(f"task_count={len(benchmark_rows)}")


if __name__ == "__main__":
    main()
