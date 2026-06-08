#!/usr/bin/env python3
import argparse
import json
import pathlib
import re
import statistics


ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "configs/table_reproduction_v1.json"


UNIMPLEMENTED_OFFICIAL_SCORERS = {
    "ifeval_official_v1",
    "multi_if_official_v1",
    "multichallenge_official_llm_judge_v1",
}


def read_jsonl(path):
    with path.open() as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def parse_mc_letter(text):
    match = re.search(r"\b([A-J])\b", text.upper())
    if match:
        return match.group(1)
    match = re.search(r"(?:answer|答案)\s*[:：]?\s*([A-J])", text, flags=re.I)
    return match.group(1).upper() if match else None


def parse_boxed_answer(text):
    boxed = re.search(r"\\boxed\{([^}]*)\}", text)
    if boxed:
        return boxed.group(1).strip()
    numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
    return numbers[-1] if numbers else None


def normalize(value):
    return re.sub(r"\s+", " ", str(value).strip().lower())


def score_row(row):
    result = row["task_result"]
    metadata = result.get("formal_metadata") or {}
    scorer_id = metadata.get("scorer_id") or result.get("scorer_id") or ""
    parser_id = metadata.get("parser_id") or result.get("parser_id") or ""
    raw = row.get("raw_generation") or result.get("output") or ""
    expected = result.get("expected_answer") or ""
    if not raw.strip():
        return {"parse_status": "failed", "score_status": "failed", "score": 0.0, "reason": "empty_generation"}
    if result.get("finish_reason") == "length" or result.get("hit_max_tokens"):
        return {"parse_status": "blocked", "score_status": "blocked", "score": 0.0, "reason": "hit_max_tokens"}
    if scorer_id in UNIMPLEMENTED_OFFICIAL_SCORERS:
        return {
            "parse_status": "blocked",
            "score_status": "blocked",
            "score": 0.0,
            "reason": f"official scorer not configured: {scorer_id}",
        }

    parsed = raw.strip()
    if parser_id == "mc_letter_v1":
        parsed = parse_mc_letter(raw)
    elif parser_id == "boxed_answer_v1":
        parsed = parse_boxed_answer(raw)
    elif parser_id in {"bbh_answer_parser_v1", "bbeh_answer_parser_v1"}:
        parsed = raw.strip()

    if parsed is None or str(parsed).strip() == "":
        return {"parse_status": "failed", "score_status": "failed", "score": 0.0, "reason": "parser returned empty"}
    if not expected:
        return {"parse_status": "parsed", "score_status": "blocked", "score": 0.0, "reason": "missing expected answer"}

    score = 1.0 if normalize(parsed) == normalize(expected) else 0.0
    return {"parse_status": "parsed", "score_status": "scored", "score": score, "parsed_answer": parsed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report_dir")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report_dir = pathlib.Path(args.report_dir)
    evidence_path = report_dir / "raw_evidence.jsonl"
    if not evidence_path.is_file():
        raise SystemExit(f"raw_evidence.jsonl not found: {evidence_path}")
    suite = json.loads(SUITE_PATH.read_text())
    datasets = {d["dataset_id"]: d for d in suite["datasets"]}
    scored_rows = []
    for row in read_jsonl(evidence_path):
        result = row["task_result"]
        metadata = result.get("formal_metadata") or {}
        dataset_id = metadata.get("dataset_id") or result.get("category")
        scored = score_row(row)
        scored_row = {
            "dataset_id": dataset_id,
            "task_id": result.get("task_id") or result.get("id"),
            "model_id": result.get("model_id"),
            "repeat_index": result.get("repeat_index"),
            "prompt_tokens": result.get("prompt_tokens"),
            "generated_tokens": result.get("generated_tokens") or result.get("estimated_output_tokens"),
            "finish_reason": result.get("finish_reason"),
            **scored,
        }
        scored_rows.append(scored_row)

    by_dataset = {}
    for row in scored_rows:
        by_dataset.setdefault(row["dataset_id"], []).append(row)

    summary = []
    for dataset_id, rows in sorted(by_dataset.items()):
        scored = [r["score"] for r in rows if r["score_status"] == "scored"]
        blocked = [r for r in rows if r["score_status"] == "blocked"]
        failed = [r for r in rows if r["score_status"] == "failed"]
        score = statistics.mean(scored) * 100.0 if scored else None
        model_id = rows[0]["model_id"] if rows else ""
        baseline = (datasets.get(dataset_id, {}).get("official_table_scores") or {}).get(model_id)
        summary.append(
            {
                "dataset_id": dataset_id,
                "model_id": model_id,
                "score": score,
                "official_table_score": baseline,
                "delta": None if score is None or baseline is None else score - baseline,
                "denominator": len(rows),
                "scored": len(scored),
                "blocked": len(blocked),
                "failed": len(failed),
            }
        )

    out_dir = pathlib.Path(args.out) if args.out else report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "table_reproduction_scored_rows.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in scored_rows)
    )
    (out_dir / "table_reproduction_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("table reproduction scoring complete")
    print(f"- rows: {len(scored_rows)}")
    print(f"- datasets: {len(summary)}")
    print(f"- output: {out_dir}")


if __name__ == "__main__":
    main()
