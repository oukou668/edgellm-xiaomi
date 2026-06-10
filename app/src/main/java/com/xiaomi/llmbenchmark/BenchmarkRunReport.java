package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkRunReport {
    final String runId;
    final long startedAtMs;
    final long finishedAtMs;
    final DeviceInfo deviceInfo;
    final ModelConfig model;
    final BenchmarkConfig benchmark;
    final BenchmarkRunOptions options;
    final long modelLoadMs;
    final RuntimeDiagnostics runtimeDiagnostics;
    final List<BenchmarkItemResult> warmupResults;
    final List<BenchmarkItemResult> results;
    final List<HardwareSample> hardwareSamples;
    final JSONObject sourceIdentity;
    final List<JSONObject> batchMetrics;

    BenchmarkRunReport(
            String runId,
            long startedAtMs,
            long finishedAtMs,
            DeviceInfo deviceInfo,
            ModelConfig model,
            BenchmarkConfig benchmark,
            BenchmarkRunOptions options,
            long modelLoadMs,
            RuntimeDiagnostics runtimeDiagnostics,
            List<BenchmarkItemResult> warmupResults,
            List<BenchmarkItemResult> results,
            List<HardwareSample> hardwareSamples,
            JSONObject sourceIdentity,
            List<JSONObject> batchMetrics) {
        this.runId = runId;
        this.startedAtMs = startedAtMs;
        this.finishedAtMs = finishedAtMs;
        this.deviceInfo = deviceInfo;
        this.model = model;
        this.benchmark = benchmark;
        this.options = options;
        this.modelLoadMs = modelLoadMs;
        this.runtimeDiagnostics = runtimeDiagnostics == null ? RuntimeDiagnostics.unknown() : runtimeDiagnostics;
        this.warmupResults =
                warmupResults == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(warmupResults));
        this.results = Collections.unmodifiableList(results);
        this.hardwareSamples =
                hardwareSamples == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(hardwareSamples));
        this.sourceIdentity = sourceIdentity == null ? new JSONObject() : sourceIdentity;
        this.batchMetrics =
                batchMetrics == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(batchMetrics));
    }

    int passedCount() {
        int count = 0;
        for (BenchmarkItemResult result : results) {
            if (result.passed) {
                count++;
            }
        }
        return count;
    }

    int failureCount() {
        int count = 0;
        for (BenchmarkItemResult result : results) {
            if (result.error != null && !result.error.isEmpty()) {
                count++;
            }
        }
        return count;
    }

    double averageTokensPerSecond() {
        double total = 0.0;
        int count = 0;
        for (BenchmarkItemResult result : results) {
            if (result.decodeTokensPerSecond > 0.0) {
                total += result.decodeTokensPerSecond;
                count++;
            }
        }
        return count == 0 ? 0.0 : total / count;
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("run_id", runId);
        json.put("started_at_ms", startedAtMs);
        json.put("finished_at_ms", finishedAtMs);
        json.put("duration_ms", finishedAtMs - startedAtMs);
        json.put("device", deviceInfo.toJson());
        json.put("source_identity", sourceIdentity);
        json.put("options", options.toJson());
        JSONObject modelJson = new JSONObject();
        modelJson.put("backend_id", model.backendId);
        modelJson.put("model_id", model.modelId);
        modelJson.put("display_name", model.displayName);
        modelJson.put("hf_repo", model.hfRepo);
        modelJson.put("hf_revision", model.hfRevision);
        modelJson.put("mlc_model_url", model.mlcModelUrl);
        modelJson.put("model_lib", model.modelLib);
        modelJson.put("artifact_filename", model.artifactFilename);
        modelJson.put("artifact_sha256", model.artifactSha256);
        modelJson.put("artifact_size_bytes", model.artifactSizeBytes);
        modelJson.put("base_model_id", model.baseModelId);
        modelJson.put("artifact_license", model.artifactLicense);
        modelJson.put("artifact_source", model.artifactSource);
        modelJson.put("quantization", model.quantization);
        modelJson.put("context_window", model.contextWindow);
        modelJson.put("prompt_template", model.promptTemplate);
        modelJson.put("reproduction_role", model.reproductionRole);
        modelJson.put("default_params", model.defaultParams.toJson());
        modelJson.put("estimated_memory_bytes", model.estimatedMemoryBytes);
        modelJson.put("load_ms", modelLoadMs);
        json.put("model", modelJson);
        json.put("runtime", runtimeDiagnostics.toJson());
        JSONObject benchJson = new JSONObject();
        benchJson.put("benchmark_id", benchmark.benchmarkId);
        benchJson.put("display_name", benchmark.displayName);
        benchJson.put("version", benchmark.version);
        benchJson.put("item_count", benchmark.items.size());
        json.put("benchmark", benchJson);
        JSONObject metrics = new JSONObject();
        metrics.put("passed", passedCount());
        metrics.put("failed_items", failureCount());
        metrics.put("total_items", results.size());
        metrics.put("warmup_items", warmupResults.size());
        metrics.put("average_decode_tokens_per_second", averageTokensPerSecond());
        json.put("metrics", metrics);
        json.put("hardware", new HardwareSummary(hardwareSamples).toJson(hardwareSamples));
        JSONArray resultArray = new JSONArray();
        for (BenchmarkItemResult result : results) {
            resultArray.put(result.toJson());
        }
        json.put("results", resultArray);
        JSONArray warmupArray = new JSONArray();
        for (BenchmarkItemResult result : warmupResults) {
            warmupArray.put(result.toJson());
        }
        json.put("warmup_results", warmupArray);
        JSONArray batchArray = new JSONArray();
        for (JSONObject metric : batchMetrics) {
            batchArray.put(metric);
        }
        json.put("batch_metrics", batchArray);
        json.put("decode_speed_profile", decodeSpeedProfile());
        return json;
    }

    /** Aggregates per-item KV-length decode buckets across the whole run into one tok/s-vs-KV table. */
    private JSONArray decodeSpeedProfile() throws Exception {
        java.util.TreeMap<Integer, long[]> byStart = new java.util.TreeMap<>();
        for (BenchmarkItemResult result : results) {
            for (DecodeSpeedBucket bucket : result.decodeSpeedBuckets) {
                long[] acc = byStart.get(bucket.startToken);
                if (acc == null) {
                    acc = new long[] {0L, 0L};
                    byStart.put(bucket.startToken, acc);
                }
                acc[0] += bucket.tokens;
                acc[1] += bucket.totalMs;
            }
        }
        JSONArray array = new JSONArray();
        for (Map.Entry<Integer, long[]> entry : byStart.entrySet()) {
            int start = entry.getKey();
            long tokens = entry.getValue()[0];
            long totalMs = entry.getValue()[1];
            JSONObject bucket = new JSONObject();
            bucket.put("start", start);
            bucket.put("end", start + DecodeSpeedBucket.WIDTH);
            bucket.put("tokens", tokens);
            bucket.put("total_ms", totalMs);
            bucket.put("tokens_per_second", totalMs > 0L ? tokens * 1000.0 / totalMs : 0.0);
            array.put(bucket);
        }
        return array;
    }
}
