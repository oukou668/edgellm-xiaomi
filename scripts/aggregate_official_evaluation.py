#!/usr/bin/env python3
"""Aggregate replay and official-native scorer outputs into leaderboard-safe reports."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

import replay_harness_evaluator as replay


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_rows(path: pathlib.Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return read_jsonl(path)
    data = read_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("tasks"), list):
            return data["tasks"]
        if isinstance(data.get("results"), list):
            return data["results"]
    raise SystemExit(f"Unsupported official scorer output shape: {path}")


def default_replay_results_path(report_dir: pathlib.Path) -> pathlib.Path | None:
    candidates = [
        report_dir / "harness_replay_android" / "harness_replay_results.json",
        report_dir / "analysis" / "harness_replay_results.json",
        report_dir / "harness_replay_results.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def normalize_official_row(row: dict[str, Any]) -> dict[str, Any]:
    task_name = replay.normalize_task_name(str(row.get("task_name") or row.get("dataset_id") or row.get("dataset_name") or ""))
    official = bool(row.get("official_benchmark"))
    coverage_status = str(row.get("coverage_status") or ("covered" if official else "partial"))
    normalized = {
        **row,
        "task_name": task_name,
        "dataset_id": str(row.get("dataset_id") or task_name),
        "dataset_name": str(row.get("dataset_name") or task_name),
        "evaluation_tier": str(row.get("evaluation_tier") or ("official_benchmark" if official else "official_partial")),
        "coverage_status": coverage_status,
        "average_eligible": bool(row.get("average_eligible", official and coverage_status == "covered")),
        "supported_by_harness": bool(row.get("supported_by_harness", False)),
        "skipped_reason": str(row.get("skipped_reason") or ""),
        "score": row.get("score", ""),
        "blocker": row.get("blocker") if isinstance(row.get("blocker"), dict) else {},
    }
    normalized["official_benchmark"] = bool(normalized["evaluation_tier"] == "official_benchmark" and normalized["coverage_status"] == "covered")
    normalized["average_eligible"] = bool(normalized["official_benchmark"] and normalized["coverage_status"] == "covered")
    return normalized


def write_leaderboard_report(path: pathlib.Path, results: dict[str, Any]) -> None:
    coverage = results["coverage_report"]
    summary = coverage["summary"]
    lines = [
        "# Leaderboard-Safe Evaluation Report",
        "",
        f"- official_average_status: `{summary['official_average_status']}`",
        f"- official_average: `{summary.get('official_average')}`",
        f"- average_eligible_dataset_count: `{summary['average_eligible_dataset_count']}`",
        f"- blocked_dataset_count: `{summary['blocked_dataset_count']}`",
        "",
        "## Dataset Coverage",
        "",
        "| Dataset | Scorer Backend | Required Coverage | Expected | Actual | Avg Eligible | Status |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for task_name, row in sorted(coverage["datasets"].items()):
        lines.append(
            f"| {task_name} | {row.get('scorer_backend', '')} | {row.get('required_coverage', '')} | "
            f"{row.get('expected_sample_count', 0)} | {row.get('actual_sample_count', 0)} | "
            f"{row.get('average_eligible_count', 0)} | {row.get('coverage_status', '')} |"
        )
    lines += ["", "## Blockers", ""]
    blockers = coverage.get("blockers") or []
    if not blockers:
        lines.append("No blockers.")
    for blocker in blockers:
        lines.append(
            f"- `{blocker.get('task_name', '')}`: {blocker.get('blocker_type', '')} - "
            f"{blocker.get('message', blocker.get('reason', ''))}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate(args: argparse.Namespace) -> dict[str, Any]:
    report_dir = pathlib.Path(args.report_dir).resolve()
    replay_results_path = pathlib.Path(args.replay_results).resolve() if args.replay_results else default_replay_results_path(report_dir)
    if replay_results_path is None and not args.allow_missing_replay:
        raise SystemExit(f"Could not find harness_replay_results.json under {report_dir}")
    output_dir = pathlib.Path(args.output_dir).resolve() if args.output_dir else report_dir / "official_aggregation"
    output_dir.mkdir(parents=True, exist_ok=True)

    replay_results = read_json(replay_results_path) if replay_results_path is not None else {"tasks": []}
    tasks = [dict(row) for row in replay_results.get("tasks", [])]
    official_rows: list[dict[str, Any]] = []
    for value in args.official_scorer_results or []:
        official_rows.extend(normalize_official_row(row) for row in read_rows(pathlib.Path(value).resolve()))
    official_task_names = {str(row.get("task_name") or "") for row in official_rows if row.get("task_name")}
    if official_task_names:
        tasks = [
            row
            for row in tasks
            if not (
                str(row.get("task_name") or "") in official_task_names
                and row.get("evaluation_tier") == "blocker"
                and str(row.get("skipped_reason") or "").startswith(("harness_task_not_supported", "gpqa_gated_dataset_skipped"))
            )
        ]
    merged_tasks = tasks + official_rows
    coverage_report = replay.build_coverage_report(merged_tasks)
    results = {
        "schema_version": 1,
        "report_dir": str(report_dir),
        "replay_results": str(replay_results_path) if replay_results_path is not None else "",
        "missing_replay_allowed": bool(replay_results_path is None),
        "official_scorer_result_count": len(official_rows),
        "tasks": merged_tasks,
        "coverage_report": coverage_report,
        "official_average_status": coverage_report["summary"]["official_average_status"],
        "official_average": coverage_report["summary"]["official_average"],
    }
    (output_dir / "official_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "coverage_report.json").write_text(json.dumps(coverage_report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "blockers.jsonl").open("w", encoding="utf-8") as handle:
        for blocker in coverage_report.get("blockers", []):
            handle.write(json.dumps(blocker, ensure_ascii=False) + "\n")
    write_leaderboard_report(output_dir / "leaderboard_report.md", results)
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build leaderboard-safe coverage and blocker reports from Android replay evidence.")
    parser.add_argument("report_dir", help="Android report directory containing harness replay results.")
    parser.add_argument("--replay-results", default="", help="Explicit harness_replay_results.json path.")
    parser.add_argument("--allow-missing-replay", action="store_true", help="Aggregate official scorer rows even when no harness replay results exist.")
    parser.add_argument("--official-scorer-results", action="append", help="Optional official-native scorer JSON/JSONL outputs to merge.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to report_dir/official_aggregation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    results = aggregate(args)
    print(
        "Official aggregation complete: "
        f"{len(results['tasks'])} task rows, "
        f"{results['coverage_report']['summary']['average_eligible_dataset_count']} average-eligible datasets, "
        f"{results['official_average_status']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
