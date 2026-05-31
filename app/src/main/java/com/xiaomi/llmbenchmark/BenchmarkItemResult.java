package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

final class BenchmarkItemResult {
    final BenchmarkItem item;
    final String output;
    final boolean passed;
    final String error;
    final long firstTokenLatencyMs;
    final long totalLatencyMs;
    final int estimatedOutputTokens;
    final double decodeTokensPerSecond;
    final List<HardwareSample> hardwareSamples;

    BenchmarkItemResult(
            BenchmarkItem item,
            String output,
            boolean passed,
            String error,
            long firstTokenLatencyMs,
            long totalLatencyMs,
            int estimatedOutputTokens,
            double decodeTokensPerSecond,
            List<HardwareSample> hardwareSamples) {
        this.item = item;
        this.output = output;
        this.passed = passed;
        this.error = error;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.estimatedOutputTokens = estimatedOutputTokens;
        this.decodeTokensPerSecond = decodeTokensPerSecond;
        this.hardwareSamples =
                hardwareSamples == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(hardwareSamples));
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("id", item.id);
        json.put("language", item.language);
        json.put("category", item.category);
        json.put("prompt", item.displayPrompt());
        json.put("messages", item.messagesToJson());
        json.put("difficulty", item.difficulty);
        json.put("tags", new JSONArray(item.tags));
        json.put("expected_answer", item.expectedAnswer);
        json.put("judge_rule", item.judgeRule);
        json.put("output", output);
        json.put("passed", passed);
        json.put("error", error);
        json.put("first_token_latency_ms", firstTokenLatencyMs);
        json.put("total_latency_ms", totalLatencyMs);
        json.put("estimated_output_tokens", estimatedOutputTokens);
        json.put("decode_tokens_per_second", decodeTokensPerSecond);
        json.put("hardware", new HardwareSummary(hardwareSamples).toJson(hardwareSamples));
        return json;
    }
}
