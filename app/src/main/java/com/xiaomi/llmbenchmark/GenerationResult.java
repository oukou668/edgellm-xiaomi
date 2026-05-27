package com.xiaomi.llmbenchmark;

final class GenerationResult {
    final String text;
    final long firstTokenLatencyMs;
    final long totalLatencyMs;
    final int estimatedOutputTokens;

    GenerationResult(String text, long firstTokenLatencyMs, long totalLatencyMs, int estimatedOutputTokens) {
        this.text = text;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.estimatedOutputTokens = estimatedOutputTokens;
    }
}

