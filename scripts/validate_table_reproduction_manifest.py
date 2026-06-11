#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS_PATH = ROOT / "app/src/main/assets/models.json"
SUITE_PATH = ROOT / "configs/table_reproduction_v1.json"
OFFICIAL_SCORERS_PATH = ROOT / "configs/official_scorers_v1.json"
TARGET_MODELS = {
    "minicpm5-1b-thinking-q4",
    "qwen3-0.6b-thinking-q4",
    "qwen3.5-0.8b-thinking-q4",
    "lfm2.5-1.2b-thinking-q4",
}
TARGET_DATASETS = {
    "mmlu_pro",
    "mmlu_redux",
    "gpqa_diamond",
    "supergpqa",
    "ifeval",
    "multi_if",
    "multichallenge",
    "math500",
    "aime25",
    "aime26",
    "hmmt_feb_2026",
    "bbh",
    "bbeh",
}
SCORER_BACKENDS = {"harness_native", "official_native", "judge_native"}
REQUIRED_COVERAGE = {"full_dataset", "full_group", "avg16"}
OFFICIAL_SCORER_DATASETS = {
    "gpqa_diamond",
    "supergpqa",
    "multi_if",
    "multichallenge",
    "aime26",
    "hmmt_feb_2026",
    "bbeh",
}


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


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def require(value, message, errors):
    if not value:
        errors.append(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-artifacts", action="store_true")
    parser.add_argument(
        "--dataset-artifacts-dir",
        default=str(ROOT / "artifacts/table_reproduction/datasets"),
    )
    parser.add_argument("--datasets", action="append", help="Dataset id or comma-separated ids for strict artifact checks.")
    args = parser.parse_args()
    selected_datasets = parse_dataset_filter(args.datasets)

    models_root = json.loads(MODELS_PATH.read_text())
    suite = json.loads(SUITE_PATH.read_text())
    official_scorers = json.loads(OFFICIAL_SCORERS_PATH.read_text()) if OFFICIAL_SCORERS_PATH.is_file() else {"scorers": []}
    errors = []

    models = [m for m in models_root["models"] if m.get("reproduction_role") == "table_reproduction_v1"]
    model_ids = {m.get("model_id") for m in models}
    if model_ids != TARGET_MODELS:
        errors.append(f"formal model set mismatch: expected {sorted(TARGET_MODELS)} actual {sorted(model_ids)}")
    if set(suite.get("models", [])) != TARGET_MODELS:
        errors.append("suite model ids do not match required four-model set")

    for model in models:
        prefix = f"model {model.get('model_id')}: "
        require(model.get("backend_id") == "llama_cpp", prefix + "backend_id must be llama_cpp", errors)
        for field in [
            "base_model_id",
            "hf_repo",
            "hf_revision",
            "artifact_filename",
            "artifact_sha256",
            "artifact_size_bytes",
            "artifact_license",
            "artifact_source",
            "quantization",
            "prompt_template",
        ]:
            require(model.get(field), prefix + f"missing {field}", errors)
        require(model.get("quantization", "").startswith("Q4"), prefix + "quantization must be Q4", errors)
        require(model.get("context_window") == 81920, prefix + "context_window must be 81920 for M2", errors)
        params = model.get("default_params") or {}
        require(params.get("temperature") == 0.9, prefix + "temperature must be 0.9", errors)
        require(params.get("top_p") == 0.95, prefix + "top_p must be 0.95", errors)
        require(params.get("thinking_enabled") is True, prefix + "thinking_enabled must be true", errors)

    datasets = suite.get("datasets", [])
    dataset_ids = {d.get("dataset_id") for d in datasets}
    if dataset_ids != TARGET_DATASETS:
        errors.append(f"dataset set mismatch: expected {sorted(TARGET_DATASETS)} actual {sorted(dataset_ids)}")
    if len(datasets) != 13:
        errors.append(f"expected 13 formal datasets, found {len(datasets)}")

    profiles = suite.get("generation_profiles") or {}
    require((profiles.get("M2") or {}).get("context_window_size") == 81920, "M2 context must be 81920", errors)
    require((profiles.get("M2") or {}).get("max_tokens") == 65536, "M2 max_tokens must be 65536", errors)
    require((profiles.get("M2") or {}).get("samples_per_problem") == 16, "M2 must use @Avg16", errors)

    for dataset in datasets:
        prefix = f"dataset {dataset.get('dataset_id')}: "
        for field in [
            "display_name",
            "profile_group_id",
            "source_repo",
            "source_revision",
            "source_url",
            "license",
            "canonical_sample_count",
            "prompt_builder_id",
            "parser_id",
            "scorer_id",
            "preferred_scorer_backend",
            "required_coverage",
            "official_table_scores",
        ]:
            require(dataset.get(field), prefix + f"missing {field}", errors)
        require(dataset.get("preferred_scorer_backend") in SCORER_BACKENDS, prefix + "invalid preferred_scorer_backend", errors)
        require(dataset.get("required_coverage") in REQUIRED_COVERAGE, prefix + "invalid required_coverage", errors)
        require(dataset.get("main_leaderboard_eligible") is False, prefix + "main_leaderboard_eligible must default false", errors)
        require(dataset.get("profile_group_id") in profiles, prefix + "unknown profile group", errors)
        scores = dataset.get("official_table_scores") or {}
        require(set(scores) == TARGET_MODELS, prefix + "official_table_scores must cover all four models", errors)

    scorer_entries = official_scorers.get("scorers") or []
    scorer_dataset_ids = {entry.get("dataset_id") for entry in scorer_entries}
    if scorer_dataset_ids != OFFICIAL_SCORER_DATASETS:
        errors.append(f"official scorer dataset set mismatch: expected {sorted(OFFICIAL_SCORER_DATASETS)} actual {sorted(scorer_dataset_ids)}")
    for entry in scorer_entries:
        prefix = f"official scorer {entry.get('dataset_id')}: "
        for field in [
            "adapter_id",
            "scorer_backend",
            "repo_url",
            "repo_commit",
            "entrypoint",
            "required_input_fields",
            "expected_sample_count",
            "repeat_policy",
            "official_benchmark_gate",
        ]:
            require(entry.get(field), prefix + f"missing {field}", errors)
        require(entry.get("scorer_backend") in SCORER_BACKENDS, prefix + "invalid scorer_backend", errors)
        require(isinstance(entry.get("required_input_fields"), list), prefix + "required_input_fields must be a list", errors)
        require(isinstance(entry.get("expected_sample_count"), int), prefix + "expected_sample_count must be int", errors)
        require(isinstance(entry.get("official_benchmark_gate"), list), prefix + "official_benchmark_gate must be a list", errors)

    if args.strict_artifacts:
        artifact_root = pathlib.Path(args.dataset_artifacts_dir)
        strict_dataset_ids = selected_datasets or TARGET_DATASETS
        unknown = sorted(strict_dataset_ids - TARGET_DATASETS)
        require(not unknown, f"unknown strict artifact dataset id(s): {', '.join(unknown)}", errors)
        for dataset_id in strict_dataset_ids:
            dataset_dir = artifact_root / dataset_id
            for name in ["manifest.json", "samples.jsonl"]:
                require((dataset_dir / name).is_file(), f"missing dataset artifact {dataset_id}/{name}", errors)

    if errors:
        for error in errors:
            print("ERROR:", error, file=sys.stderr)
        return 1
    print("table reproduction manifest validation passed")
    print(f"- models: {len(models)}")
    print(f"- datasets: {len(datasets)}")
    print(f"- strict_artifacts: {args.strict_artifacts}")
    if selected_datasets:
        print(f"- strict_artifact_datasets: {sorted(selected_datasets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
