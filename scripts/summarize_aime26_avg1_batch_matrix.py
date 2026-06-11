#!/usr/bin/env python3
"""Summarize MiniCPM5 AIME2026 Avg@1 batch/KV-cache diagnostic runs."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import time
from collections import defaultdict
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "table_reproduction" / "aime26_avg1_batch_summary"
BUCKET_WIDTH = 4096
BUCKET_MAX = 65536


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def extract_boxed_integer(text: str) -> str:
    boxed = re.findall(r"\\boxed\{([^{}]+)\}", text or "")
    if boxed:
        match = re.search(r"-?\d+", boxed[-1])
        return match.group(0) if match else ""
    matches = re.findall(r"(?<!\d)-?\d{1,3}(?!\d)", text or "")
    return matches[-1] if matches else ""


def correct_avg1(row: dict[str, Any]) -> bool:
    expected = str(row.get("expected_answer") or "").strip()
    if not expected:
        return False
    return extract_boxed_integer(str(row.get("output") or "")) == expected


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def aggregate_buckets(report_json: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_start: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for bucket in report_json.get("decode_speed_profile") or []:
        start = int(bucket.get("start") or 0)
        by_start[start][0] += float(bucket.get("tokens") or 0)
        by_start[start][1] += float(bucket.get("total_ms") or 0)
    if not by_start:
        for row in rows:
            for bucket in row.get("decode_speed_buckets") or []:
                start = int(bucket.get("start") or 0)
                by_start[start][0] += float(bucket.get("tokens") or 0)
                by_start[start][1] += float(bucket.get("total_ms") or 0)
    out = []
    for start in range(0, BUCKET_MAX, BUCKET_WIDTH):
        tokens, total_ms = by_start.get(start, [0.0, 0.0])
        out.append(
            {
                "start": start,
                "end": start + BUCKET_WIDTH,
                "tokens": int(tokens),
                "total_ms": int(total_ms),
                "tokens_per_second": tokens * 1000.0 / total_ms if total_ms > 0 else 0.0,
            }
        )
    return out


def summarize_report(report_dir: pathlib.Path) -> dict[str, Any]:
    report_json = read_json(report_dir / "report.json")
    rows = read_jsonl(report_dir / "task_results.jsonl")
    model = report_json.get("model") or {}
    options = report_json.get("options") or {}
    runtime_details = ((report_json.get("runtime") or {}).get("details") or {})
    hardware = report_json.get("hardware") or {}
    batch_metrics = report_json.get("batch_metrics") or []
    generated_tokens = [int(row.get("generated_tokens") or row.get("estimated_output_tokens") or 0) for row in rows]
    decode_ms = [int(row.get("decode_latency_ms") or 0) for row in rows]
    total_generated = sum(generated_tokens)
    if batch_metrics:
        batch_decode_ms = sum(max(0, int(metric.get("aggregate_decode_latency_ms") or 0)) for metric in batch_metrics)
        aggregate_tps = total_generated * 1000.0 / batch_decode_ms if batch_decode_ms > 0 else 0.0
    else:
        decode_total_ms = sum(max(0, value) for value in decode_ms)
        aggregate_tps = total_generated * 1000.0 / decode_total_ms if decode_total_ms > 0 else 0.0
    correct = sum(1 for row in rows if correct_avg1(row))
    bucket_profile = aggregate_buckets(report_json, rows)
    return {
        "report_dir": str(report_dir),
        "run_id": report_json.get("run_id", ""),
        "backend_id": str(model.get("backend_id") or options.get("backend_id") or ""),
        "accelerator_requested": str(
            runtime_details.get("accelerator_requested") or options.get("llama_accelerator") or ""
        ),
        "accelerator_active": str(runtime_details.get("accelerator_active") or ""),
        "gpu_layers_requested": str(runtime_details.get("gpu_layers_requested") or options.get("llama_gpu_layers") or ""),
        "gpu_layers_offloaded": str(runtime_details.get("gpu_layers_offloaded") or ""),
        "gpu_offload_active": str(runtime_details.get("gpu_offload_active") or ""),
        "model_id": str(model.get("model_id") or ""),
        "dataset_id": "aime26",
        "evaluation_tier": "official_partial",
        "diagnostic_label": "avg1_diagnostic",
        "official_benchmark": False,
        "average_eligible": False,
        "batch_size": int(options.get("batch_size") or 1),
        "row_count": len(rows),
        "expected_row_count": 30,
        "avg1_correct": correct,
        "avg1_score": correct / len(rows) if rows else 0.0,
        "error_count": sum(1 for row in rows if row.get("error")),
        "hit_max_tokens_count": sum(1 for row in rows if row.get("hit_max_tokens")),
        "parse_failure_count": sum(1 for row in rows if not extract_boxed_integer(str(row.get("output") or ""))),
        "generated_tokens_total": total_generated,
        "prompt_tokens_total": sum(int(row.get("prompt_tokens") or 0) for row in rows),
        "aggregate_tokens_per_second": aggregate_tps,
        "wall_time_ms": int(report_json.get("duration_ms") or 0),
        "median_total_latency_ms": statistics.median([int(row.get("total_latency_ms") or 0) for row in rows]) if rows else None,
        "p90_total_latency_ms": percentile([float(row.get("total_latency_ms") or 0) for row in rows], 0.90),
        "peak_app_pss_bytes": hardware.get("peak_app_pss_bytes"),
        "peak_thermal_temperature_c": hardware.get("peak_thermal_temperature_c"),
        "native_lib_hash": (report_json.get("runtime") or {}).get("native_library_sha256", ""),
        "vulkan_lib_hash": runtime_details.get("ggml_vulkan_library_sha256", ""),
        "model_hash": model.get("artifact_sha256", ""),
        "device_fingerprint": (report_json.get("device") or {}).get("fingerprint", ""),
        "batch_metrics": batch_metrics,
        "decode_speed_buckets": bucket_profile,
    }


def add_speedups(runs: list[dict[str, Any]]) -> None:
    baseline: dict[tuple[str, str], float] = {}
    for run in runs:
        if run["batch_size"] == 1:
            baseline[(run["backend_id"], run["accelerator_requested"])] = float(run["aggregate_tokens_per_second"] or 0.0)
    for run in runs:
        base = baseline.get((run["backend_id"], run["accelerator_requested"]), 0.0)
        run["speedup_vs_batch1"] = (
            float(run["aggregate_tokens_per_second"]) / base if base > 0.0 else None
        )


def write_markdown(path: pathlib.Path, runs: list[dict[str, Any]]) -> None:
    lines = [
        "# MiniCPM5-1B AIME2026 Avg@1 Batch/KV Diagnostic",
        "",
        "All rows are `official_benchmark=false`, `average_eligible=false`, and `evaluation_tier=official_partial`.",
        "MLC KV buckets are approximate because they use estimated cumulative token position.",
        "",
        "## Batch Summary",
        "",
        "| Backend | Accelerator | Active | Batch | Rows | Avg@1 | Errors | Hit max | Agg tok/s | Speedup | Peak PSS MiB | Peak thermal C |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda r: (r["backend_id"], r["accelerator_requested"], r["batch_size"])):
        peak_pss = run.get("peak_app_pss_bytes") or 0
        peak_thermal = run.get("peak_thermal_temperature_c")
        speedup = run.get("speedup_vs_batch1")
        lines.append(
            "| {backend} | {accel} | {active} | {batch} | {rows} | {score:.4f} | {errors} | {hit} | {tps:.2f} | {speedup} | {pss:.1f} | {thermal} |".format(
                backend=run["backend_id"],
                accel=run["accelerator_requested"] or "n/a",
                active=run["accelerator_active"] or "n/a",
                batch=run["batch_size"],
                rows=run["row_count"],
                score=run["avg1_score"],
                errors=run["error_count"],
                hit=run["hit_max_tokens_count"],
                tps=run["aggregate_tokens_per_second"],
                speedup="n/a" if speedup is None else f"{speedup:.2f}x",
                pss=peak_pss / 1024.0 / 1024.0 if peak_pss else 0.0,
                thermal="n/a" if peak_thermal in (None, "") else f"{float(peak_thermal):.1f}",
            )
        )
    lines += ["", "## Decode Speed By KV-Cache Length", ""]
    for run in sorted(runs, key=lambda r: (r["backend_id"], r["accelerator_requested"], r["batch_size"])):
        lines += [
            f"### {run['backend_id']} accelerator={run['accelerator_requested'] or 'n/a'} active={run['accelerator_active'] or 'n/a'} batch={run['batch_size']}",
            "",
            "| KV window | tokens | decode ms | tok/s |",
            "|---|---:|---:|---:|",
        ]
        for bucket in run["decode_speed_buckets"]:
            lines.append(
                f"| {bucket['start']}-{bucket['end']} | {bucket['tokens']} | {bucket['total_ms']} | {bucket['tokens_per_second']:.2f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize AIME2026 Avg@1 batch/KV diagnostic reports.")
    parser.add_argument("report_dirs", nargs="+", help="Android report directories.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    runs = [summarize_report(pathlib.Path(value).resolve()) for value in args.report_dirs]
    add_speedups(runs)
    output_dir = pathlib.Path(args.out_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1,
        "created_at_ms": int(time.time() * 1000),
        "matrix": {
            "dataset_id": "aime26",
            "model_family": "MiniCPM5-1B",
            "avg_policy": "Avg@1",
            "batch_sizes": sorted({run["batch_size"] for run in runs}),
            "backends": sorted({run["backend_id"] for run in runs}),
            "accelerators": sorted({run["accelerator_requested"] for run in runs}),
        },
        "runs": runs,
    }
    (output_dir / "aime26_avg1_batch_matrix_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(output_dir / "aime26_avg1_batch_matrix_summary.md", runs)
    print(f"summary written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
