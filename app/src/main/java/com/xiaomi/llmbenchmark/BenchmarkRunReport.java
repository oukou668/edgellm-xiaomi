package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkRunReport {
    final String runId;
    final long startedAtMs;
    final long finishedAtMs;
    final DeviceInfo deviceInfo;
    final ModelConfig model;
    final BenchmarkConfig benchmark;
    final long modelLoadMs;
    final List<BenchmarkItemResult> results;
    final List<HardwareSample> hardwareSamples;

    BenchmarkRunReport(
            String runId,
            long startedAtMs,
            long finishedAtMs,
            DeviceInfo deviceInfo,
            ModelConfig model,
            BenchmarkConfig benchmark,
            long modelLoadMs,
            List<BenchmarkItemResult> results,
            List<HardwareSample> hardwareSamples) {
        this.runId = runId;
        this.startedAtMs = startedAtMs;
        this.finishedAtMs = finishedAtMs;
        this.deviceInfo = deviceInfo;
        this.model = model;
        this.benchmark = benchmark;
        this.modelLoadMs = modelLoadMs;
        this.results = Collections.unmodifiableList(results);
        this.hardwareSamples =
                hardwareSamples == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(hardwareSamples));
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
        JSONObject modelJson = new JSONObject();
        modelJson.put("model_id", model.modelId);
        modelJson.put("display_name", model.displayName);
        modelJson.put("mlc_model_url", model.mlcModelUrl);
        modelJson.put("model_lib", model.modelLib);
        modelJson.put("quantization", model.quantization);
        modelJson.put("context_window", model.contextWindow);
        modelJson.put("estimated_vram_bytes", model.estimatedVramBytes);
        modelJson.put("load_ms", modelLoadMs);
        json.put("model", modelJson);
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
        metrics.put("average_decode_tokens_per_second", averageTokensPerSecond());
        json.put("metrics", metrics);
        json.put("hardware", new HardwareSummary(hardwareSamples).toJson(hardwareSamples));
        JSONArray resultArray = new JSONArray();
        for (BenchmarkItemResult result : results) {
            resultArray.put(result.toJson());
        }
        json.put("results", resultArray);
        return json;
    }
}
