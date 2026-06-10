package com.xiaomi.llmbenchmark;

import java.util.Collections;
import java.util.List;

final class GenerationResult {
    final String text;
    final long firstTokenLatencyMs;
    final long promptEvalLatencyMs;
    final long decodeLatencyMs;
    final long totalLatencyMs;
    final int promptTokens;
    final int estimatedOutputTokens;
    final String finishReason;
    final RuntimeDiagnostics diagnostics;
    final List<DecodeSpeedBucket> decodeSpeedBuckets;

    GenerationResult(String text, long firstTokenLatencyMs, long totalLatencyMs, int estimatedOutputTokens) {
        this(text, firstTokenLatencyMs, -1L, -1L, totalLatencyMs, 0, estimatedOutputTokens, "unknown",
                RuntimeDiagnostics.unknown());
    }

    GenerationResult(
            String text,
            long firstTokenLatencyMs,
            long promptEvalLatencyMs,
            long decodeLatencyMs,
            long totalLatencyMs,
            int promptTokens,
            int estimatedOutputTokens,
            String finishReason,
            RuntimeDiagnostics diagnostics) {
        this(text, firstTokenLatencyMs, promptEvalLatencyMs, decodeLatencyMs, totalLatencyMs, promptTokens,
                estimatedOutputTokens, finishReason, diagnostics, Collections.emptyList());
    }

    GenerationResult(
            String text,
            long firstTokenLatencyMs,
            long promptEvalLatencyMs,
            long decodeLatencyMs,
            long totalLatencyMs,
            int promptTokens,
            int estimatedOutputTokens,
            String finishReason,
            RuntimeDiagnostics diagnostics,
            List<DecodeSpeedBucket> decodeSpeedBuckets) {
        this.text = text;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.promptEvalLatencyMs = promptEvalLatencyMs;
        this.decodeLatencyMs = decodeLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.promptTokens = promptTokens;
        this.estimatedOutputTokens = estimatedOutputTokens;
        this.finishReason = finishReason == null ? "unknown" : finishReason;
        this.diagnostics = diagnostics == null ? RuntimeDiagnostics.unknown() : diagnostics;
        this.decodeSpeedBuckets =
                decodeSpeedBuckets == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new java.util.ArrayList<>(decodeSpeedBuckets));
    }
}
