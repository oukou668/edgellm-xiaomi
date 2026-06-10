package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import org.json.JSONObject;

final class ReportWriter {
    private final Context context;

    ReportWriter(Context context) {
        this.context = context.getApplicationContext();
    }

    File write(BenchmarkRunReport report) throws Exception {
        String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date(report.startedAtMs));
        File dir = new File(context.getFilesDir(), "reports/" + stamp + "_" + report.benchmark.benchmarkId);
        if (!dir.exists() && !dir.mkdirs()) {
            throw new IllegalStateException("Could not create report directory: " + dir);
        }
        writeText(new File(dir, "report.json"), report.toJson().toString(2));
        writeText(new File(dir, "report.csv"), toCsv(report));
        writeText(new File(dir, "report.md"), toMarkdown(report));
        writeText(new File(dir, "run_manifest.json"), toRunManifest(report).toString(2));
        writeText(new File(dir, "task_results.jsonl"), toJsonl(report.results));
        writeText(new File(dir, "generation_log.jsonl"), toGenerationJsonl(report.results));
        writeText(new File(dir, "warmup_generation_log.jsonl"), toGenerationJsonl(report.warmupResults));
        writeText(new File(dir, "raw_evidence.jsonl"), toEvidenceJsonl(report, report.results));
        writeText(new File(dir, "harness_replay_entries.jsonl"), toHarnessReplayJsonl(report, report.results));
        return dir;
    }

    private static String toCsv(BenchmarkRunReport report) {
        StringBuilder builder = new StringBuilder();
        builder.append(
                "backend_id,model_id,repeat_index,warmup,id,language,category,prompt_class,difficulty,tags,passed,error,first_token_latency_ms,prompt_eval_latency_ms,decode_latency_ms,total_latency_ms,prompt_tokens,generated_tokens,decode_tokens_per_second,finish_reason,peak_app_pss_bytes,peak_system_memory_used_ratio,peak_battery_temperature_c,peak_thermal_temperature_c,prompt,expected_answer,output\n");
        for (BenchmarkItemResult result : report.results) {
            HardwareSummary hardware = new HardwareSummary(result.hardwareSamples);
            builder.append(csv(result.backendId)).append(',');
            builder.append(csv(result.modelId)).append(',');
            builder.append(result.repeatIndex).append(',');
            builder.append(result.warmup).append(',');
            builder.append(csv(result.item.id)).append(',');
            builder.append(csv(result.item.language)).append(',');
            builder.append(csv(result.item.category)).append(',');
            builder.append(csv(result.item.promptClass)).append(',');
            builder.append(csv(result.item.difficulty)).append(',');
            builder.append(csv(String.join(";", result.item.tags))).append(',');
            builder.append(result.passed).append(',');
            builder.append(csv(result.error)).append(',');
            builder.append(result.firstTokenLatencyMs).append(',');
            builder.append(result.promptEvalLatencyMs).append(',');
            builder.append(result.decodeLatencyMs).append(',');
            builder.append(result.totalLatencyMs).append(',');
            builder.append(result.promptTokens).append(',');
            builder.append(result.estimatedOutputTokens).append(',');
            builder.append(String.format(Locale.US, "%.3f", result.decodeTokensPerSecond)).append(',');
            builder.append(csv(result.finishReason)).append(',');
            builder.append(hardware.peakAppPssBytes).append(',');
            builder.append(String.format(Locale.US, "%.4f", hardware.peakSystemMemoryUsedRatio)).append(',');
            builder.append(formatDouble(hardware.peakBatteryTempC)).append(',');
            builder.append(formatDouble(hardware.peakThermalTempC)).append(',');
            builder.append(csv(result.item.displayPrompt())).append(',');
            builder.append(csv(result.item.expectedAnswer)).append(',');
            builder.append(csv(result.output)).append('\n');
        }
        return builder.toString();
    }

    private static String toMarkdown(BenchmarkRunReport report) {
        StringBuilder builder = new StringBuilder();
        builder.append("# LLM Benchmark Report\n\n");
        builder.append("- Run ID: `").append(report.runId).append("`\n");
        builder.append("- Device: ").append(report.deviceInfo.summary()).append('\n');
        builder.append("- Backend: ").append(report.options.backendId).append(" (`").append(report.options.smokeType).append("`)\n");
        builder.append("- Model: ").append(report.model.displayName).append(" (`").append(report.model.modelId).append("`)\n");
        builder.append("- Artifact: ").append(report.model.artifactDisplayName()).append('\n');
        builder.append("- Benchmark: ").append(report.benchmark.displayName).append(" (`").append(report.benchmark.benchmarkId).append("`)\n");
        builder.append("- Warmup/repeat: ").append(report.options.warmupCount).append('/').append(report.options.repeatCount).append('\n');
        builder.append("- Model load: ").append(report.modelLoadMs).append(" ms\n");
        builder.append("- Passed: ").append(report.passedCount()).append('/').append(report.results.size()).append('\n');
        builder.append("- Failed items: ").append(report.failureCount()).append('\n');
        builder.append("- Avg decode tokens/s: ")
                .append(String.format(Locale.US, "%.2f", report.averageTokensPerSecond()))
                .append('\n');
        HardwareSummary runHardware = new HardwareSummary(report.hardwareSamples);
        builder.append("- Hardware samples: ").append(runHardware.sampleCount).append('\n');
        builder.append("- Peak app PSS: ").append(formatBytes(runHardware.peakAppPssBytes)).append('\n');
        builder.append("- Peak system memory used: ")
                .append(String.format(Locale.US, "%.1f%%", runHardware.peakSystemMemoryUsedRatio * 100.0))
                .append('\n');
        builder.append("- Peak battery temp: ").append(formatTemperature(runHardware.peakBatteryTempC)).append('\n');
        builder.append("- Peak thermal temp: ")
                .append(formatTemperature(runHardware.peakThermalTempC))
                .append(runHardware.peakThermalZone.isEmpty() ? "" : " (`" + escapeMd(runHardware.peakThermalZone) + "`)")
                .append("\n\n");
        builder.append("| ID | Pass | Difficulty | First token ms | Total ms | tok/s | Peak PSS | Peak temp | Output |\n");
        builder.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |\n");
        for (BenchmarkItemResult result : report.results) {
            HardwareSummary hardware = new HardwareSummary(result.hardwareSamples);
            builder.append("| ")
                    .append(escapeMd(result.item.id))
                    .append(" | ")
                    .append(result.passed ? "yes" : "no")
                    .append(" | ")
                    .append(escapeMd(result.item.difficulty))
                    .append(" | ")
                    .append(result.firstTokenLatencyMs)
                    .append(" | ")
                    .append(result.totalLatencyMs)
                    .append(" | ")
                    .append(String.format(Locale.US, "%.2f", result.decodeTokensPerSecond))
                    .append(" | ")
                    .append(formatBytes(hardware.peakAppPssBytes))
                    .append(" | ")
                    .append(formatTemperature(hardware.peakThermalTempC))
                    .append(" | ")
                    .append(escapeMd(shorten(result.output.isEmpty() ? result.error : result.output, 120)))
                    .append(" |\n");
        }
        appendDecodeSpeedProfile(builder, report);
        appendBatchThroughput(builder, report);
        return builder.toString();
    }

    private static void appendDecodeSpeedProfile(StringBuilder builder, BenchmarkRunReport report) {
        java.util.TreeMap<Integer, long[]> byStart = new java.util.TreeMap<>();
        for (BenchmarkItemResult result : report.results) {
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
        if (byStart.isEmpty()) {
            return;
        }
        builder.append("\n## Decode speed by KV-cache length\n\n");
        builder.append("| KV window (tokens) | tokens | decode ms | tok/s |\n");
        builder.append("| --- | ---: | ---: | ---: |\n");
        for (java.util.Map.Entry<Integer, long[]> entry : byStart.entrySet()) {
            int start = entry.getKey();
            long tokens = entry.getValue()[0];
            long totalMs = entry.getValue()[1];
            double tps = totalMs > 0L ? tokens * 1000.0 / totalMs : 0.0;
            builder.append("| ")
                    .append(start)
                    .append("-")
                    .append(start + DecodeSpeedBucket.WIDTH)
                    .append(" | ")
                    .append(tokens)
                    .append(" | ")
                    .append(totalMs)
                    .append(" | ")
                    .append(String.format(Locale.US, "%.2f", tps))
                    .append(" |\n");
        }
    }

    private static void appendBatchThroughput(StringBuilder builder, BenchmarkRunReport report) {
        if (report.batchMetrics.isEmpty()) {
            return;
        }
        builder.append("\n## Batch throughput\n\n");
        builder.append("- Configured batch size: ").append(report.options.batchSize).append('\n');
        builder.append("\n| Batch # | Batch size | Decode ms | Total tokens | Aggregate tok/s |\n");
        builder.append("| ---: | ---: | ---: | ---: | ---: |\n");
        for (JSONObject metric : report.batchMetrics) {
            builder.append("| ")
                    .append(metric.optInt("batch_index", 0))
                    .append(" | ")
                    .append(metric.optInt("batch_size", report.options.batchSize))
                    .append(" | ")
                    .append(metric.optLong("aggregate_decode_latency_ms", -1L))
                    .append(" | ")
                    .append(metric.optInt("total_generated_tokens", 0))
                    .append(" | ")
                    .append(String.format(Locale.US, "%.2f", metric.optDouble("aggregate_tokens_per_second", 0.0)))
                    .append(" |\n");
        }
    }

    private static JSONObject toRunManifest(BenchmarkRunReport report) throws Exception {
        JSONObject json = new JSONObject();
        json.put("run_id", report.runId);
        json.put("started_at_ms", report.startedAtMs);
        json.put("finished_at_ms", report.finishedAtMs);
        json.put("backend_id", report.options.backendId);
        json.put("smoke_type", report.options.smokeType);
        json.put("warmup_count", report.options.warmupCount);
        json.put("repeat_count", report.options.repeatCount);
        json.put("task_count", report.benchmark.items.size());
        json.put("expected_generation_log_rows", report.benchmark.items.size() * report.options.repeatCount);
        json.put("actual_generation_log_rows", report.results.size());
        json.put("actual_warmup_generation_log_rows", report.warmupResults.size());
        json.put("model_id", report.model.modelId);
        json.put("artifact_filename", report.model.artifactFilename);
        json.put("artifact_sha256", report.model.artifactSha256);
        json.put("runtime", report.runtimeDiagnostics.toJson());
        json.put("source_identity", report.sourceIdentity);
        return json;
    }

    private static String toJsonl(Iterable<BenchmarkItemResult> results) throws Exception {
        StringBuilder builder = new StringBuilder();
        for (BenchmarkItemResult result : results) {
            builder.append(result.toJson().toString()).append('\n');
        }
        return builder.toString();
    }

    private static String toGenerationJsonl(Iterable<BenchmarkItemResult> results) throws Exception {
        StringBuilder builder = new StringBuilder();
        for (BenchmarkItemResult result : results) {
            JSONObject json = new JSONObject();
            json.put("task_id", result.item.id);
            json.put("backend_id", result.backendId);
            json.put("model_id", result.modelId);
            json.put("repeat_index", result.repeatIndex);
            json.put("warmup", result.warmup);
            json.put("prompt", result.item.displayPrompt());
            json.put("output", result.output);
            json.put("prompt_tokens", result.promptTokens);
            json.put("generated_tokens", result.estimatedOutputTokens);
            json.put("first_token_latency_ms", result.firstTokenLatencyMs);
            json.put("prompt_eval_latency_ms", result.promptEvalLatencyMs);
            json.put("decode_latency_ms", result.decodeLatencyMs);
            json.put("total_latency_ms", result.totalLatencyMs);
            json.put("finish_reason", result.finishReason);
            json.put("hit_max_tokens", "length".equals(result.finishReason));
            json.put("generation_params", result.generationParams.toJson());
            json.put("formal_metadata", result.item.metadataToJson());
            json.put("passed", result.passed);
            json.put("error", result.error);
            builder.append(json.toString()).append('\n');
        }
        return builder.toString();
    }

    private static String toEvidenceJsonl(BenchmarkRunReport report, Iterable<BenchmarkItemResult> results)
            throws Exception {
        StringBuilder builder = new StringBuilder();
        JSONObject reportJson = report.toJson();
        JSONObject run = new JSONObject();
        run.put("run_id", report.runId);
        run.put("benchmark_id", report.benchmark.benchmarkId);
        run.put("backend_id", report.options.backendId);
        run.put("smoke_type", report.options.smokeType);
        run.put("model", reportJson.getJSONObject("model"));
        run.put("runtime", report.runtimeDiagnostics.toJson());
        run.put("source_identity", report.sourceIdentity);
        run.put("device", report.deviceInfo.toJson());
        for (BenchmarkItemResult result : results) {
            JSONObject json = new JSONObject();
            json.put("run", run);
            json.put("task_result", result.toJson());
            json.put("resolved_prompt", result.item.displayPrompt());
            json.put("resolved_messages", result.item.messagesToJson());
            json.put("raw_generation", result.output);
            json.put("harness_replay_entry", harnessReplayEntry(report, result));
            json.put("generation_acceptance", generationAcceptance(result));
            builder.append(json.toString()).append('\n');
        }
        return builder.toString();
    }

    private static String toHarnessReplayJsonl(BenchmarkRunReport report, Iterable<BenchmarkItemResult> results)
            throws Exception {
        StringBuilder builder = new StringBuilder();
        for (BenchmarkItemResult result : results) {
            builder.append(harnessReplayEntry(report, result).toString()).append('\n');
        }
        return builder.toString();
    }

    private static JSONObject harnessReplayEntry(BenchmarkRunReport report, BenchmarkItemResult result)
            throws Exception {
        JSONObject metadata = result.item.metadataToJson();
        JSONObject replay = metadata.optJSONObject("harness_replay");
        JSONObject json = replay == null ? new JSONObject() : new JSONObject(replay.toString());
        putIfMissing(json, "task_name", result.item.datasetId.isEmpty() ? result.item.category : result.item.datasetId);
        putIfMissing(json, "dataset_id", result.item.datasetId.isEmpty() ? result.item.category : result.item.datasetId);
        putIfMissing(json, "dataset_name", result.item.category);
        putIfMissing(json, "doc_id", result.item.sampleId.isEmpty() ? result.item.id : result.item.sampleId);
        putIfMissing(json, "prompt_text", result.item.displayPrompt());
        putIfMissing(json, "prompt_sha256", Hashing.sha256(result.item.displayPrompt()));
        putIfMissing(json, "gold", result.item.expectedAnswer);
        putIfMissing(json, "harness_task", json.optString("task_name", result.item.datasetId));
        json.put("raw_generation", result.output);
        json.put("rawGeneration", result.output);
        json.put("repeat_index", result.repeatIndex);
        json.put("model_id", result.modelId);
        json.put("backend_id", result.backendId);
        json.put("summary_id", report.runId);
        json.put("run_id", report.runId);
        json.put("android_report_benchmark_id", report.benchmark.benchmarkId);
        json.put("android_task_id", result.item.id);
        json.put("android_report_format", "xiaomi_llmbenchmark_harness_replay_v1");
        json.put("generation_params", result.generationParams.toJson());
        json.put("runtime", result.runtimeDiagnostics.toJson());
        json.put("device", report.deviceInfo.toJson());
        json.put("android_task_result", result.toJson());
        return json;
    }

    private static void putIfMissing(JSONObject json, String key, Object value) throws Exception {
        if (!json.has(key) || json.isNull(key) || json.optString(key).isEmpty()) {
            json.put(key, value);
        }
    }

    private static JSONObject generationAcceptance(BenchmarkItemResult result) throws Exception {
        JSONObject json = new JSONObject();
        boolean rawNonEmpty = result.output != null && !result.output.trim().isEmpty();
        boolean tokensPresent = result.promptTokens > 0 && result.estimatedOutputTokens > 0;
        boolean hitMaxTokens = "length".equals(result.finishReason);
        json.put("raw_generation_non_empty", rawNonEmpty);
        json.put("prompt_tokens_gt_zero", result.promptTokens > 0);
        json.put("generated_tokens_gt_zero", result.estimatedOutputTokens > 0);
        json.put("hit_max_tokens", hitMaxTokens);
        json.put("accepted", rawNonEmpty && tokensPresent && !hitMaxTokens && result.error.isEmpty());
        return json;
    }

    private static void writeText(File file, String text) throws Exception {
        try (FileOutputStream output = new FileOutputStream(file)) {
            output.write(text.getBytes(StandardCharsets.UTF_8));
        }
    }

    private static String csv(String value) {
        String clean = value == null ? "" : value;
        return "\"" + clean.replace("\"", "\"\"") + "\"";
    }

    private static String escapeMd(String value) {
        return (value == null ? "" : value).replace("|", "\\|").replace("\n", " ");
    }

    private static String shorten(String value, int max) {
        if (value == null || value.length() <= max) {
            return value == null ? "" : value;
        }
        return value.substring(0, max - 3) + "...";
    }

    private static String formatBytes(long bytes) {
        if (bytes <= 0L) {
            return "n/a";
        }
        return String.format(Locale.US, "%.1f MiB", bytes / 1024.0 / 1024.0);
    }

    private static String formatTemperature(double temperatureC) {
        if (Double.isNaN(temperatureC)) {
            return "n/a";
        }
        return String.format(Locale.US, "%.1f C", temperatureC);
    }

    private static String formatDouble(double value) {
        return Double.isNaN(value) ? "" : String.format(Locale.US, "%.3f", value);
    }
}
