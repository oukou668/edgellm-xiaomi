package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkItemResult {
    final BenchmarkItem item;
    final String backendId;
    final String modelId;
    final int repeatIndex;
    final boolean warmup;
    final String output;
    final boolean passed;
    final String error;
    final long firstTokenLatencyMs;
    final long promptEvalLatencyMs;
    final long decodeLatencyMs;
    final long totalLatencyMs;
    final int promptTokens;
    final int estimatedOutputTokens;
    final double decodeTokensPerSecond;
    final String finishReason;
    final GenerationParams generationParams;
    final RuntimeDiagnostics runtimeDiagnostics;
    final List<HardwareSample> hardwareSamples;

    BenchmarkItemResult(
            BenchmarkItem item,
            String backendId,
            String modelId,
            int repeatIndex,
            boolean warmup,
            String output,
            boolean passed,
            String error,
            long firstTokenLatencyMs,
            long promptEvalLatencyMs,
            long decodeLatencyMs,
            long totalLatencyMs,
            int promptTokens,
            int estimatedOutputTokens,
            double decodeTokensPerSecond,
            String finishReason,
            GenerationParams generationParams,
            RuntimeDiagnostics runtimeDiagnostics,
            List<HardwareSample> hardwareSamples) {
        this.item = item;
        this.backendId = backendId == null ? "" : backendId;
        this.modelId = modelId == null ? "" : modelId;
        this.repeatIndex = repeatIndex;
        this.warmup = warmup;
        this.output = output;
        this.passed = passed;
        this.error = error;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.promptEvalLatencyMs = promptEvalLatencyMs;
        this.decodeLatencyMs = decodeLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.promptTokens = promptTokens;
        this.estimatedOutputTokens = estimatedOutputTokens;
        this.decodeTokensPerSecond = decodeTokensPerSecond;
        this.finishReason = finishReason == null ? "unknown" : finishReason;
        this.generationParams = generationParams == null ? GenerationParams.fromJson(null) : generationParams;
        this.runtimeDiagnostics = runtimeDiagnostics == null ? RuntimeDiagnostics.unknown() : runtimeDiagnostics;
        this.hardwareSamples =
                hardwareSamples == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(hardwareSamples));
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("id", item.id);
        json.put("task_id", item.id);
        json.put("backend_id", backendId);
        json.put("model_id", modelId);
        json.put("repeat_index", repeatIndex);
        json.put("warmup", warmup);
        json.put("language", item.language);
        json.put("category", item.category);
        json.put("prompt_class", item.promptClass);
        json.put("prompt", item.displayPrompt());
        json.put("messages", item.messagesToJson());
        json.put("difficulty", item.difficulty);
        json.put("tags", new JSONArray(item.tags));
        json.put("expected_answer", item.expectedAnswer);
        json.put("judge_rule", item.judgeRule);
        json.put("formal_metadata", item.metadataToJson());
        json.put("output", output);
        json.put("passed", passed);
        json.put("error", error);
        json.put("first_token_latency_ms", firstTokenLatencyMs);
        json.put("prompt_eval_latency_ms", promptEvalLatencyMs);
        json.put("decode_latency_ms", decodeLatencyMs);
        json.put("total_latency_ms", totalLatencyMs);
        json.put("prompt_tokens", promptTokens);
        json.put("estimated_output_tokens", estimatedOutputTokens);
        json.put("generated_tokens", estimatedOutputTokens);
        json.put("decode_tokens_per_second", decodeTokensPerSecond);
        json.put("finish_reason", finishReason);
        json.put("hit_max_tokens", "length".equals(finishReason));
        json.put("generation_params", generationParams.toJson());
        json.put("runtime", runtimeDiagnostics.toJson());
        json.put("hardware", new HardwareSummary(hardwareSamples).toJson(hardwareSamples));
        return json;
    }
}
