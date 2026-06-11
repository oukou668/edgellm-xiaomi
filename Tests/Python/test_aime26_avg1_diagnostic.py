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
SUMMARY_SCRIPT = ROOT / "scripts" / "summarize_aime26_avg1_batch_matrix.py"
spec = importlib.util.spec_from_file_location("summarize_aime26_avg1_batch_matrix", SUMMARY_SCRIPT)
assert spec and spec.loader
summary = importlib.util.module_from_spec(spec)
sys.modules["summarize_aime26_avg1_batch_matrix"] = summary
spec.loader.exec_module(summary)


def read_asset_rows() -> list[dict]:
    path = ROOT / "app" / "src" / "main" / "assets" / "benchmarks" / "aime_2026.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Aime26Avg1DiagnosticTests(unittest.TestCase):
    def test_aime_2026_asset_has_30_real_rows(self) -> None:
        rows = read_asset_rows()
        self.assertEqual(len(rows), 30)
        self.assertFalse(any("PLACEHOLDER" in json.dumps(row, ensure_ascii=False) for row in rows))
        self.assertEqual(rows[0]["expected_answer"], "277")
        self.assertEqual(rows[-1]["expected_answer"], "393")
        for row in rows:
            self.assertEqual(row["generation_profile_id"], "avg1_diagnostic")
            self.assertFalse(row["metadata"]["official_benchmark"])
            self.assertFalse(row["metadata"]["average_eligible"])

    def test_avg1_bundle_uses_30_rows_without_avg16_expansion(self) -> None:
        rows = read_asset_rows()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            dataset_dir = root / "datasets" / "aime26"
            dataset_dir.mkdir(parents=True)
            with (dataset_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            (dataset_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "dataset_id": "aime26",
                        "source_repo": "MathArena/aime_2026",
                        "source_revision": "d2de22f3c656b4f56cf8981212186377d1e23bc3",
                        "canonical_sample_count": 30,
                        "fetched_sample_count": 30,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            out_root = root / "bundles"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "prepare_table_reproduction_bundle.py"),
                    "--suite",
                    "avg1_diagnostic",
                    "--model-id",
                    "minicpm5-1b-thinking-q4",
                    "--datasets",
                    "aime26",
                    "--dataset-artifacts-dir",
                    str(root / "datasets"),
                    "--out-root",
                    str(out_root),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            bundle_dir = next(path for path in out_root.iterdir() if path.is_dir())
            manifest = json.loads((bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8"))
            bundle_rows = [
                json.loads(line)
                for line in (bundle_dir / "benchmark.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(manifest["selected_datasets"], ["aime26"])
            self.assertEqual(manifest["task_count"], 30)
            self.assertEqual(manifest["repeat_policy"], "avg1_diagnostic")
            self.assertEqual(manifest["samples_per_problem"], 1)
            self.assertFalse(manifest["official_loop"])
            self.assertFalse(manifest["average_eligible"])
            self.assertEqual(len(bundle_rows), 30)
            self.assertTrue(all("__sample" not in row["task_id"] for row in bundle_rows))
            self.assertTrue(all(row["generation_profile_id"] == "avg1_diagnostic" for row in bundle_rows))
            self.assertTrue(all(row["metadata"]["samples_per_problem"] == 1 for row in bundle_rows))

    def test_batch_matrix_summary_scores_avg1_and_speedup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            report_dirs = []
            for batch_size, decode_ms, generated in [(1, 2000, 30), (2, 2000, 60)]:
                report_dir = root / f"report_b{batch_size}"
                report_dir.mkdir()
                rows = [
                    {
                        "task_id": "aime26__1",
                        "expected_answer": "277",
                        "output": "The final answer is \\boxed{277}.",
                        "prompt_tokens": 100,
                        "generated_tokens": generated // 2,
                        "decode_latency_ms": decode_ms // 2,
                        "total_latency_ms": decode_ms // 2,
                        "finish_reason": "stop",
                        "hit_max_tokens": False,
                        "error": "",
                        "decode_speed_buckets": [
                            {"start": 0, "end": 4096, "tokens": generated // 2, "total_ms": decode_ms // 2}
                        ],
                    },
                    {
                        "task_id": "aime26__2",
                        "expected_answer": "62",
                        "output": "The final answer is \\boxed{0}.",
                        "prompt_tokens": 100,
                        "generated_tokens": generated // 2,
                        "decode_latency_ms": decode_ms // 2,
                        "total_latency_ms": decode_ms // 2,
                        "finish_reason": "stop",
                        "hit_max_tokens": False,
                        "error": "",
                        "decode_speed_buckets": [
                            {"start": 0, "end": 4096, "tokens": generated // 2, "total_ms": decode_ms // 2}
                        ],
                    },
                ]
                (report_dir / "task_results.jsonl").write_text(
                    "\n".join(json.dumps(row) for row in rows) + "\n",
                    encoding="utf-8",
                )
                report = {
                    "run_id": f"run-b{batch_size}",
                    "duration_ms": decode_ms,
                    "model": {"backend_id": "llama_cpp", "model_id": "minicpm5-1b-thinking-q4"},
                    "options": {"batch_size": batch_size},
                    "hardware": {"peak_app_pss_bytes": 1024 * 1024, "peak_thermal_temperature_c": 40.0},
                    "runtime": {"native_library_sha256": "native"},
                    "device": {"fingerprint": "fingerprint"},
                    "decode_speed_profile": [
                        {"start": 0, "end": 4096, "tokens": generated, "total_ms": decode_ms}
                    ],
                    "batch_metrics": [
                        {
                            "batch_size": batch_size,
                            "aggregate_decode_latency_ms": decode_ms,
                            "total_generated_tokens": generated,
                            "aggregate_tokens_per_second": generated * 1000.0 / decode_ms,
                        }
                    ]
                    if batch_size > 1
                    else [],
                }
                (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
                report_dirs.append(report_dir)

            runs = [summary.summarize_report(path) for path in report_dirs]
            summary.add_speedups(runs)
            by_batch = {run["batch_size"]: run for run in runs}
            self.assertEqual(by_batch[1]["avg1_correct"], 1)
            self.assertEqual(by_batch[1]["row_count"], 2)
            self.assertEqual(by_batch[2]["evaluation_tier"], "official_partial")
            self.assertFalse(by_batch[2]["official_benchmark"])
            self.assertAlmostEqual(by_batch[2]["speedup_vs_batch1"], 2.0)
            self.assertEqual(len(by_batch[2]["decode_speed_buckets"]), 16)


if __name__ == "__main__":
    unittest.main()
