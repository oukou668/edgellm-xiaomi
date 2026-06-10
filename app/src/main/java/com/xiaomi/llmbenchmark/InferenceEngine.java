package com.xiaomi.llmbenchmark;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

interface InferenceEngine {
    void load(ModelConfig model, File modelDir) throws Exception;

    GenerationResult generate(BenchmarkItem item, GenerationParams params) throws Exception;

    RuntimeDiagnostics diagnostics();

    void unload();

    /**
     * Decode a batch of sequences. The default implementation runs them sequentially so any engine
     * that does not override still works; engines with real parallel batching (llama.cpp, MLC
     * server mode) override this. The list sizes must match (one {@link GenerationParams} per item).
     */
    default BatchGenerationResult generateBatch(List<BenchmarkItem> items, List<GenerationParams> params)
            throws Exception {
        List<GenerationResult> results = new ArrayList<>();
        int totalTokens = 0;
        long startNs = System.nanoTime();
        for (int i = 0; i < items.size(); i++) {
            GenerationResult result = generate(items.get(i), params.get(i));
            results.add(result);
            totalTokens += result.estimatedOutputTokens;
        }
        long wallMs = (System.nanoTime() - startNs) / 1_000_000L;
        double tps = wallMs > 0L ? totalTokens * 1000.0 / wallMs : 0.0;
        return new BatchGenerationResult(results, wallMs, 0L, totalTokens, items.size(), tps, diagnostics());
    }
}
