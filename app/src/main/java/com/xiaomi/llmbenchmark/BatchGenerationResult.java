package com.xiaomi.llmbenchmark;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.json.JSONObject;

/**
 * Result of decoding a batch of sequences concurrently. The headline throughput number is
 * {@link #aggregateTokensPerSecond}: total generated tokens across all sequences divided by the
 * wall-clock of the parallel decode phase (NOT the sum of per-sequence decode times).
 */
final class BatchGenerationResult {
    final List<GenerationResult> perSequence;
    final long aggregateDecodeWallMs;
    final long aggregatePrefillWallMs;
    final int totalGeneratedTokens;
    final int batchSize;
    final double aggregateTokensPerSecond;
    final RuntimeDiagnostics diagnostics;

    BatchGenerationResult(
            List<GenerationResult> perSequence,
            long aggregateDecodeWallMs,
            long aggregatePrefillWallMs,
            int totalGeneratedTokens,
            int batchSize,
            double aggregateTokensPerSecond,
            RuntimeDiagnostics diagnostics) {
        this.perSequence =
                perSequence == null
                        ? Collections.emptyList()
                        : Collections.unmodifiableList(new ArrayList<>(perSequence));
        this.aggregateDecodeWallMs = aggregateDecodeWallMs;
        this.aggregatePrefillWallMs = aggregatePrefillWallMs;
        this.totalGeneratedTokens = totalGeneratedTokens;
        this.batchSize = batchSize;
        this.aggregateTokensPerSecond = aggregateTokensPerSecond;
        this.diagnostics = diagnostics == null ? RuntimeDiagnostics.unknown() : diagnostics;
    }

    JSONObject toJson() throws Exception {
        JSONObject json = new JSONObject();
        json.put("batch_size", batchSize);
        json.put("aggregate_decode_latency_ms", aggregateDecodeWallMs);
        json.put("aggregate_prefill_latency_ms", aggregatePrefillWallMs);
        json.put("total_generated_tokens", totalGeneratedTokens);
        json.put("aggregate_tokens_per_second", aggregateTokensPerSecond);
        return json;
    }
}
