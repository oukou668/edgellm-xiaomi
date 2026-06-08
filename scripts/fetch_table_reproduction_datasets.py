#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "configs/table_reproduction_v1.json"
OUT_ROOT = ROOT / "artifacts/table_reproduction/datasets"
RAW_SOURCE_ROOT = ROOT / "artifacts/table_reproduction/raw_sources"
PAGE_SIZE = 100


def http_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Xiaomi17TableReproduction/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def dataset_url(path, **params):
    query = urllib.parse.urlencode(params)
    return f"https://datasets-server.huggingface.co/{path}?{query}"


def splits_for(repo):
    return http_json(dataset_url("splits", dataset=repo)).get("splits", [])


def size_for(repo):
    try:
        return http_json(dataset_url("size", dataset=repo)).get("size", {})
    except Exception:
        return {}


def fetch_rows(repo, config, split):
    rows = []
    offset = 0
    while True:
        data = http_json(
            dataset_url(
                "rows",
                dataset=repo,
                config=config,
                split=split,
                offset=offset,
                length=PAGE_SIZE,
            )
        )
        batch = data.get("rows") or []
        if not batch:
            break
        rows.extend(item["row"] for item in batch)
        offset += len(batch)
        if len(batch) < PAGE_SIZE:
            break
    return rows


def selected_splits(dataset, splits):
    dataset_id = dataset["dataset_id"]
    if dataset_id == "mmlu_pro":
        return [s for s in splits if s["split"] == "test"]
    if dataset_id in {"mmlu_redux", "bbh"}:
        return [s for s in splits if s["split"] == "test"]
    if dataset_id == "multichallenge":
        return [s for s in splits if s["split"] == "test"]
    return [splits[0]] if splits else []


def letter(index):
    try:
        return chr(ord("A") + int(index))
    except Exception:
        return ""


def option_lines(options):
    options = to_plain(options)
    if isinstance(options, dict):
        keys = sorted(options)
        return "\n".join(f"{key}. {options[key]}" for key in keys)
    if isinstance(options, list):
        return "\n".join(f"{letter(i)}. {value}" for i, value in enumerate(options))
    return str(options or "")


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def lettered_choices(options):
    options = to_plain(options)
    if isinstance(options, dict):
        return [str(options[key]) for key in sorted(options)]
    if isinstance(options, list):
        return [str(value) for value in options]
    return []


def mc_answer(row):
    for key in ["answer_letter", "answer"]:
        value = row.get(key)
        if isinstance(value, str) and len(value.strip()) == 1 and value.strip().isalpha():
            return value.strip().upper()
    if isinstance(row.get("answer"), int):
        return letter(row.get("answer"))
    if "answer_index" in row:
        return letter(row.get("answer_index"))
    return str(row.get("answer") or "")


def deterministic_gpqa_options(row, sample_id):
    choices = [
        ("correct", row.get("Correct Answer")),
        ("incorrect", row.get("Incorrect Answer 1")),
        ("incorrect", row.get("Incorrect Answer 2")),
        ("incorrect", row.get("Incorrect Answer 3")),
    ]
    ranked = sorted(
        choices,
        key=lambda item: hashlib.sha256(f"{sample_id}|{item[1]}".encode()).hexdigest(),
    )
    options = [answer for _, answer in ranked]
    correct_index = next(index for index, (kind, _) in enumerate(ranked) if kind == "correct")
    return options, letter(correct_index)


def to_plain(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "tolist"):
        return to_plain(value.tolist())
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def parse_json_value(value):
    value = to_plain(value)
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def multi_if_messages(row):
    messages = []
    for index in range(1, 4):
        parsed = parse_json_value(row.get(f"turn_{index}_prompt"))
        if isinstance(parsed, dict):
            content = parsed.get("content")
            if content:
                messages.append({"role": parsed.get("role", "user"), "content": str(content)})
        elif parsed:
            messages.append({"role": "user", "content": str(parsed)})
    return messages


def conversation_text(conversation):
    conversation = to_plain(conversation)
    if isinstance(conversation, dict):
        roles = conversation.get("role") or []
        contents = conversation.get("content") or []
        if isinstance(roles, list) and isinstance(contents, list):
            return "\n".join(f"{role}: {content}" for role, content in zip(roles, contents))
    if isinstance(conversation, list):
        lines = []
        for turn in conversation:
            if isinstance(turn, dict):
                lines.append(f"{turn.get('role', 'user')}: {turn.get('content', '')}")
            else:
                lines.append(str(turn))
        return "\n".join(lines)
    return str(conversation or "")


def normalize_row(dataset, row, config, index):
    row = to_plain(row)
    dataset_id = dataset["dataset_id"]
    sample_id = str(
        row.get("question_id")
        or row.get("uuid")
        or row.get("Record ID")
        or row.get("key")
        or row.get("unique_id")
        or row.get("problem_idx")
        or f"{config}_{index}"
    )
    normalized = {
        "sample_id": sample_id,
        "language": row.get("language", "en"),
        "difficulty": row.get("difficulty", "formal"),
        "source_config": config,
        "source_index": index,
    }
    if dataset_id in {"mmlu_pro", "mmlu_redux", "supergpqa", "gpqa_diamond"}:
        question = row.get("question") or row.get("Question") or row.get("input") or ""
        if dataset_id == "gpqa_diamond" and row.get("Correct Answer"):
            options, normalized["answer"] = deterministic_gpqa_options(row, sample_id)
        else:
            options = row.get("options") or row.get("choices") or []
            normalized["answer"] = mc_answer(row)
        normalized["prompt"] = f"{question}\n\nChoices:\n{option_lines(options)}\n\nAnswer with the option letter only."
        choices = lettered_choices(options)
        source_subtask = row.get("source_subtask") or row.get("category") or row.get("subject") or config
        doc = {
            "question": question,
            "choices": choices,
            "options": choices,
            "answer": normalized["answer"],
            "source_subtask": source_subtask,
            "category": source_subtask,
            "dataset_name": config,
        }
        if dataset_id == "gpqa_diamond":
            doc.update(
                {
                    "Question": question,
                    "choice1": choices[0] if len(choices) > 0 else "",
                    "choice2": choices[1] if len(choices) > 1 else "",
                    "choice3": choices[2] if len(choices) > 2 else "",
                    "choice4": choices[3] if len(choices) > 3 else "",
                    "answer": f"({normalized['answer']})" if len(str(normalized["answer"])) == 1 else normalized["answer"],
                }
            )
        if dataset_id in {"gpqa_diamond", "supergpqa"}:
            normalized["official_eval_metadata"] = {
                **row,
                "options": choices,
                "answer_letter": normalized["answer"],
                "choice_order_id": sha256_text(stable_json(choices)) if choices else "",
                "discipline": row.get("discipline", ""),
                "field": row.get("field", ""),
                "subfield": row.get("subfield", ""),
                "difficulty": row.get("difficulty", normalized.get("difficulty", "")),
            }
        normalized["harness_replay_doc"] = doc
    elif dataset_id == "ifeval":
        normalized["prompt"] = row.get("prompt", "")
        normalized["answer"] = ""
        normalized["official_eval_metadata"] = {
            "instruction_id_list": row.get("instruction_id_list"),
            "kwargs": row.get("kwargs"),
        }
        normalized["harness_replay_doc"] = {
            "key": row.get("key", sample_id),
            "prompt": normalized["prompt"],
            "instruction_id_list": row.get("instruction_id_list"),
            "kwargs": row.get("kwargs"),
        }
    elif dataset_id == "multi_if":
        turns = row.get("turns")
        if isinstance(turns, list) and turns:
            normalized["messages"] = [{"role": "user", "content": str(turn)} for turn in turns]
        elif multi_if_messages(row):
            normalized["messages"] = multi_if_messages(row)
        else:
            prompt = row.get("turn_1_prompt") or row.get("prompt") or ""
            normalized["prompt"] = prompt
        normalized["answer"] = ""
        normalized["official_eval_metadata"] = row
        normalized["harness_replay_doc"] = row
    elif dataset_id == "multichallenge":
        conversation = row.get("conversation")
        target = row.get("target_question") or ""
        normalized["prompt"] = f"Conversation:\n{conversation_text(conversation)}\n\nTarget question:\n{target}"
        normalized["answer"] = ""
        normalized["official_eval_metadata"] = {
            **row,
            "QUESTION_ID": row.get("QUESTION_ID") or row.get("question_id") or sample_id,
            "AXIS": row.get("AXIS") or row.get("axis"),
            "CONVERSATION": row.get("CONVERSATION") or row.get("conversation"),
            "TARGET_QUESTION": row.get("TARGET_QUESTION") or target,
            "PASS_CRITERIA": row.get("PASS_CRITERIA") or row.get("pass_criteria"),
            "pass_criteria": row.get("pass_criteria"),
            "axis": row.get("axis"),
            "num_turns": row.get("num_turns"),
        }
        normalized["harness_replay_doc"] = row
    elif dataset_id in {"math500", "aime25", "aime26", "hmmt_feb_2026"}:
        problem = row.get("problem") or row.get("input") or ""
        normalized["prompt"] = f"Solve the problem. Put the final answer in \\boxed{{}}.\n\n{problem}"
        normalized["answer"] = str(row.get("answer") or row.get("target") or "")
        normalized["official_eval_metadata"] = {
            **row,
            "problem_idx": row.get("problem_idx") or row.get("id") or sample_id,
            "answer": normalized["answer"],
        }
        normalized["harness_replay_doc"] = {
            "problem": problem,
            "answer": normalized["answer"],
            "problem_idx": row.get("problem_idx") or row.get("id") or sample_id,
        }
        if row.get("solution"):
            normalized["harness_replay_doc"]["solution"] = row.get("solution")
    elif dataset_id in {"bbh", "bbeh"}:
        normalized["prompt"] = str(row.get("input") or row.get("question") or "")
        normalized["answer"] = str(row.get("target") or row.get("answer") or "")
        if dataset_id == "bbeh":
            normalized["official_eval_metadata"] = {
                **row,
                "reference_answer": normalized["answer"],
                "sample_id": sample_id,
            }
        normalized["harness_replay_doc"] = {
            "input": normalized["prompt"],
            "target": normalized["answer"],
            "source_subtask": config,
            "dataset_name": config,
        }
    else:
        normalized["prompt"] = str(row.get("prompt") or row.get("question") or row.get("input") or "")
        normalized["answer"] = str(row.get("answer") or row.get("target") or "")
        normalized["harness_replay_doc"] = row
    return normalized


def read_jsonl(path):
    rows = []
    with path.open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_json(path):
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    raise RuntimeError(f"unsupported JSON root in {path}")


def read_table(path):
    import pandas as pd

    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix == ".csv":
        frame = pd.read_csv(path)
    else:
        raise RuntimeError(f"unsupported table file: {path}")
    return [to_plain(row) for row in frame.to_dict(orient="records")]


def read_arrow_stream(path):
    import pyarrow as pa
    import pyarrow.ipc as ipc

    with pa.memory_map(str(path), "r") as source:
        table = ipc.open_stream(source).read_all()
    return [to_plain(row) for row in table.to_pylist()]


def raw_rows_for(dataset, raw_root):
    dataset_id = dataset["dataset_id"]
    dataset_root = raw_root / dataset_id
    if not dataset_root.is_dir():
        raise RuntimeError("raw source directory missing")
    if dataset_id in {"mmlu_pro", "multichallenge", "aime25", "aime26", "hmmt_feb_2026"}:
        files = sorted(dataset_root.glob("*.parquet"))
        if not files:
            raise RuntimeError("no parquet raw source files")
        return [(path.stem.replace("-00000-of-00001", ""), read_table(path)) for path in files]
    if dataset_id == "mmlu_redux":
        files = sorted(dataset_root.glob("*/data-00000-of-00001.arrow"))
        if not files:
            raise RuntimeError("no MMLU-Redux arrow source files")
        return [(path.parent.name, read_arrow_stream(path)) for path in files]
    if dataset_id == "gpqa_diamond":
        path = dataset_root / "gpqa_diamond.csv"
        if not path.is_file():
            raise RuntimeError("gpqa_diamond.csv missing")
        return [("diamond", read_table(path))]
    if dataset_id == "supergpqa":
        path = dataset_root / "SuperGPQA-all.jsonl"
        if not path.is_file():
            raise RuntimeError("SuperGPQA-all.jsonl missing")
        return [("default", read_jsonl(path))]
    if dataset_id == "ifeval":
        path = dataset_root / "ifeval_input_data.jsonl"
        if not path.is_file():
            raise RuntimeError("ifeval_input_data.jsonl missing")
        return [("default", read_jsonl(path))]
    if dataset_id == "multi_if":
        path = dataset_root / "multiIF_20241018.csv"
        if not path.is_file():
            raise RuntimeError("multiIF_20241018.csv missing")
        return [("default", read_table(path))]
    if dataset_id == "math500":
        path = dataset_root / "test.jsonl"
        if not path.is_file():
            raise RuntimeError("test.jsonl missing")
        return [("test", read_jsonl(path))]
    if dataset_id == "bbh":
        files = sorted(dataset_root.glob("*/test-00000-of-00001.parquet"))
        if not files:
            raise RuntimeError("no BBH parquet task files")
        return [(path.parent.name, read_table(path)) for path in files]
    if dataset_id == "bbeh":
        path = dataset_root / "bbeh_data.json"
        if not path.is_file():
            raise RuntimeError("bbeh_data.json missing")
        return [("default", read_json(path))]
    raise RuntimeError("no raw-source parser for dataset")


def write_dataset(dataset, rows_by_config, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_path = out_dir / "samples.jsonl"
    count = 0
    with samples_path.open("w") as handle:
        for config, rows in rows_by_config:
            for index, row in enumerate(rows):
                sample = normalize_row(dataset, row, config, index)
                handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
                count += 1
    manifest = {
        "dataset_id": dataset["dataset_id"],
        "source_repo": dataset["source_repo"],
        "source_revision": dataset["source_revision"],
        "source_url": dataset["source_url"],
        "license": dataset["license"],
        "canonical_sample_count": dataset["canonical_sample_count"],
        "fetched_sample_count": count,
        "fetched_at_ms": int(time.time() * 1000),
        "prompt_builder_id": dataset["prompt_builder_id"],
        "parser_id": dataset["parser_id"],
        "scorer_id": dataset["scorer_id"],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", default=str(OUT_ROOT))
    parser.add_argument("--raw-source-root", default=str(RAW_SOURCE_ROOT))
    parser.add_argument("--from-raw-sources", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    suite = json.loads(SUITE_PATH.read_text())
    out_root = pathlib.Path(args.out_root)
    raw_root = pathlib.Path(args.raw_source_root)
    blockers = []
    fetched = []
    for dataset in suite["datasets"]:
        dataset_id = dataset["dataset_id"]
        repo = dataset["source_repo"]
        print(f"== {dataset_id}: {repo} ==")
        try:
            if args.from_raw_sources:
                rows_by_config = raw_rows_for(dataset, raw_root)
                for config, rows in rows_by_config:
                    print(f"  raw/{config}: {len(rows)} rows")
            else:
                splits = selected_splits(dataset, splits_for(repo))
                if not splits:
                    raise RuntimeError("no selected splits")
                rows_by_config = []
                for split in splits:
                    rows = fetch_rows(repo, split["config"], split["split"])
                    rows_by_config.append((split["config"], rows))
                    print(f"  {split['config']}/{split['split']}: {len(rows)} rows")
            count = write_dataset(dataset, rows_by_config, out_root / dataset_id)
            fetched.append({"dataset_id": dataset_id, "rows": count})
            print(f"  wrote {count} samples")
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            blockers.append({"dataset_id": dataset_id, "reason": reason})
            print(f"  BLOCKED: {reason}")

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "_fetch_summary.json").write_text(
        json.dumps({"fetched": fetched, "blockers": blockers}, indent=2, sort_keys=True) + "\n"
    )
    if blockers and not args.allow_missing:
        raise SystemExit(f"dataset fetch blocked for {len(blockers)} datasets; see {out_root / '_fetch_summary.json'}")
    print(f"fetched datasets: {len(fetched)}")
    print(f"blocked datasets: {len(blockers)}")


if __name__ == "__main__":
    main()
