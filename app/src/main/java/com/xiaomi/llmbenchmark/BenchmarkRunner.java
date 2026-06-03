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
        HardwareMonitor monitor = new HardwareMonitor(context, benchmark.hardwareSampleIntervalMs, progress);
        monitor.start();
        DeviceInfo deviceInfo = DeviceInfo.collect(context.getFilesDir());
        progress.onProgress("Device: " + deviceInfo.summary());

        File modelDir = downloader.ensureModel(model, progress);
        InferenceEngine engine = EngineFactory.create();
        long loadStartNs = System.nanoTime();
        monitor.setPhase("model_load", "");
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
            monitor.setPhase("model_load_failed", "");
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
                                0.0,
                                new ArrayList<>()));
            }
            monitor.close();
            return new BenchmarkRunReport(
                    UUID.randomUUID().toString(),
                    startedAt,
                    System.currentTimeMillis(),
                    deviceInfo,
                    model,
                    benchmark,
                    loadMs,
                    results,
                    monitor.snapshot());
        }

        try {
            for (int i = 0; i < benchmark.items.size(); i++) {
                BenchmarkItem item = benchmark.items.get(i);
                progress.onProgress("Running " + (i + 1) + "/" + benchmark.items.size() + ": " + item.id);
                progress.onItemStarted(i + 1, benchmark.items.size(), item);
                monitor.setPhase("inference", item.id);
                int sampleStart = monitor.snapshot().size();
                try {
                    GenerationResult generation = engine.generate(item, model.defaultParams, progress);
                    monitor.setPhase("post_inference", item.id);
                    List<HardwareSample> itemSamples = samplesSince(monitor, sampleStart);
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
                                    tps,
                                    itemSamples));
                } catch (Exception itemError) {
                    monitor.setPhase("inference_error", item.id);
                    results.add(
                            new BenchmarkItemResult(
                                    item,
                                    "",
                                    false,
                                    itemError.getClass().getSimpleName() + ": " + itemError.getMessage(),
                                    -1L,
                                    -1L,
                                    0,
                                    0.0,
                                    samplesSince(monitor, sampleStart)));
                }
            }
        } finally {
            monitor.setPhase("unload", "");
            engine.unload();
            monitor.close();
        }

        return new BenchmarkRunReport(
                UUID.randomUUID().toString(),
                startedAt,
                System.currentTimeMillis(),
                deviceInfo,
                model,
                benchmark,
                loadMs,
                results,
                monitor.snapshot());
    }

    private static List<HardwareSample> samplesSince(HardwareMonitor monitor, int start) {
        List<HardwareSample> all = monitor.snapshot();
        if (start < 0 || start >= all.size()) {
            return all;
        }
        return new ArrayList<>(all.subList(start, all.size()));
    }
}
