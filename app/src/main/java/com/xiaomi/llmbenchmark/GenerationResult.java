package com.xiaomi.llmbenchmark;

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
        this.text = text;
        this.firstTokenLatencyMs = firstTokenLatencyMs;
        this.promptEvalLatencyMs = promptEvalLatencyMs;
        this.decodeLatencyMs = decodeLatencyMs;
        this.totalLatencyMs = totalLatencyMs;
        this.promptTokens = promptTokens;
        this.estimatedOutputTokens = estimatedOutputTokens;
        this.finishReason = finishReason == null ? "unknown" : finishReason;
        this.diagnostics = diagnostics == null ? RuntimeDiagnostics.unknown() : diagnostics;
    }
}
