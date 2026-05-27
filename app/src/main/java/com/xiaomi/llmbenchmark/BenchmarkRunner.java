package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

final class BenchmarkRunner {
    private final Context context;
    private final ModelDownloader downloader;

    BenchmarkRunner(Context context) {
        this.context = context.getApplicationContext();
        this.downloader = new ModelDownloader(context);
    }

    BenchmarkRunReport run(ModelConfig model, BenchmarkConfig benchmark, ProgressSink progress) throws Exception {
        long startedAt = System.currentTimeMillis();
        DeviceInfo deviceInfo = DeviceInfo.collect(context.getFilesDir());
        progress.onProgress("Device: " + deviceInfo.summary());

        File modelDir = downloader.ensureModel(model, progress);
        InferenceEngine engine = EngineFactory.create();
        long loadStartNs = System.nanoTime();
        progress.onProgress("Loading MLC engine: " + model.modelId);
        List<BenchmarkItemResult> results = new ArrayList<>();
        long loadMs;
        try {
            engine.load(model, modelDir);
            loadMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - loadStartNs);
            progress.onProgress("Model loaded in " + loadMs + " ms");
        } catch (Exception loadError) {
            loadMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - loadStartNs);
            String message = loadError.getClass().getSimpleName() + ": " + loadError.getMessage();
            progress.onProgress("Model load failed: " + message);
            for (BenchmarkItem item : benchmark.items) {
                results.add(
                        new BenchmarkItemResult(
                                item,
                                "",
                                false,
                                message,
                                -1L,
                                -1L,
                                0,
                                0.0));
            }
            return new BenchmarkRunReport(
                    UUID.randomUUID().toString(),
                    startedAt,
                    System.currentTimeMillis(),
                    deviceInfo,
                    model,
                    benchmark,
                    loadMs,
                    results);
        }

        try {
            for (int i = 0; i < benchmark.items.size(); i++) {
                BenchmarkItem item = benchmark.items.get(i);
                progress.onProgress("Running " + (i + 1) + "/" + benchmark.items.size() + ": " + item.id);
                try {
                    GenerationResult generation =
                            engine.generate(item.prompt, model.defaultParams, item.maxNewTokens);
                    boolean passed = Judge.score(item, generation.text);
                    double tps =
                            generation.totalLatencyMs <= 0
                                    ? 0.0
                                    : generation.estimatedOutputTokens * 1000.0 / generation.totalLatencyMs;
                    results.add(
                            new BenchmarkItemResult(
                                    item,
                                    generation.text,
                                    passed,
                                    "",
                                    generation.firstTokenLatencyMs,
                                    generation.totalLatencyMs,
                                    generation.estimatedOutputTokens,
                                    tps));
                } catch (Exception itemError) {
                    results.add(
                            new BenchmarkItemResult(
                                    item,
                                    "",
                                    false,
                                    itemError.getClass().getSimpleName() + ": " + itemError.getMessage(),
                                    -1L,
                                    -1L,
                                    0,
                                    0.0));
                }
            }
        } finally {
            engine.unload();
        }

        return new BenchmarkRunReport(
                UUID.randomUUID().toString(),
                startedAt,
                System.currentTimeMillis(),
                deviceInfo,
                model,
                benchmark,
                loadMs,
                results);
    }
}
