package com.xiaomi.llmbenchmark;

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

    BenchmarkItemResult(
            BenchmarkItem item,
            String output,
            boolean passed,
            String error,
            long firstTokenLatencyMs,
            long totalLatencyMs,
            int estimatedOutputTokens,
            double decodeTokensPerSecond) {
        this.item = item;
        this.output = output;
        this.passed = passed;
        this.error = error;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.estimatedOutputTokens = estimatedOutputTokens;
        this.decodeTokensPerSecond = decodeTokensPerSecond;
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("id", item.id);
        json.put("language", item.language);
        json.put("category", item.category);
        json.put("prompt", item.prompt);
        json.put("expected_answer", item.expectedAnswer);
        json.put("judge_rule", item.judgeRule);
        json.put("output", output);
        json.put("passed", passed);
        json.put("error", error);
        json.put("first_token_latency_ms", firstTokenLatencyMs);
        json.put("total_latency_ms", totalLatencyMs);
        json.put("estimated_output_tokens", estimatedOutputTokens);
        json.put("decode_tokens_per_second", decodeTokensPerSecond);
        return json;
    }
}

