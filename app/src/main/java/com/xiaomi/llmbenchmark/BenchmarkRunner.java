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
        return run(model, benchmark, BenchmarkRunOptions.defaults(model.backendId), progress);
    }

    BenchmarkRunReport run(
            ModelConfig model, BenchmarkConfig benchmark, BenchmarkRunOptions options, ProgressSink progress)
            throws Exception {
        long startedAt = System.currentTimeMillis();
        HardwareMonitor monitor = new HardwareMonitor(context, benchmark.hardwareSampleIntervalMs);
        monitor.start();
        DeviceInfo deviceInfo = DeviceInfo.collect(context.getFilesDir());
        org.json.JSONObject sourceIdentity = SourceIdentity.collect(context);
        progress.onProgress("Device: " + deviceInfo.summary());
        progress.onProgress(
                "Backend: "
                        + options.backendId
                        + ", smoke_type="
                        + options.smokeType
                        + ", warmup="
                        + options.warmupCount
                        + ", repeat="
                        + options.repeatCount);

        File modelDir;
        InferenceEngine engine;
        if (options.isDummy()) {
            modelDir = new File(context.getFilesDir(), "dummy-model");
            if (!modelDir.exists() && !modelDir.mkdirs()) {
                throw new IllegalStateException("Could not create dummy model directory: " + modelDir);
            }
            engine = new DummyInferenceEngine();
            progress.onProgress("Using dummy backend; model download and native load are skipped.");
        } else {
            modelDir = downloader.ensureModel(model, progress);
            ModelPreflight.verify(model, modelDir);
            engine = EngineFactory.create(context, model.backendId);
        }
        long loadStartNs = System.nanoTime();
        monitor.setPhase("model_load", "");
        progress.onProgress("Loading " + model.backendId + " engine: " + model.modelId);
        List<BenchmarkItemResult> results = new ArrayList<>();
        List<BenchmarkItemResult> warmupResults = new ArrayList<>();
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
                                model.backendId,
                                model.modelId,
                                0,
                                false,
                                "",
                                false,
                                message,
                                -1L,
                                -1L,
                                -1L,
                                -1L,
                                0,
                                0,
                                0.0,
                                "error",
                                item.resolvedParams(model.defaultParams),
                                engine.diagnostics(),
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
                    options,
                    loadMs,
                    engine.diagnostics(),
                    warmupResults,
                    results,
                    monitor.snapshot(),
                    sourceIdentity);
        }

        try {
            for (int warmup = 0; warmup < options.warmupCount; warmup++) {
                for (int i = 0; i < benchmark.items.size(); i++) {
                    BenchmarkItem item = benchmark.items.get(i);
                    progress.onProgress(
                            "Warmup "
                                    + (warmup + 1)
                                    + "/"
                                    + options.warmupCount
                                    + " "
                                    + (i + 1)
                                    + "/"
                                    + benchmark.items.size()
                                    + ": "
                                    + item.id);
                    warmupResults.add(runItem(engine, model, item, warmup, true, monitor, options));
                }
            }
            for (int repeat = 0; repeat < options.repeatCount; repeat++) {
                for (int i = 0; i < benchmark.items.size(); i++) {
                    BenchmarkItem item = benchmark.items.get(i);
                    progress.onProgress(
                            "Running repeat "
                                    + (repeat + 1)
                                    + "/"
                                    + options.repeatCount
                                    + " "
                                    + (i + 1)
                                    + "/"
                                    + benchmark.items.size()
                                    + ": "
                                    + item.id);
                    results.add(runItem(engine, model, item, repeat, false, monitor, options));
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
                options,
                loadMs,
                engine.diagnostics(),
                warmupResults,
                results,
                monitor.snapshot(),
                sourceIdentity);
    }

    private BenchmarkItemResult runItem(
            InferenceEngine engine,
            ModelConfig model,
            BenchmarkItem item,
            int repeatIndex,
            boolean warmup,
            HardwareMonitor monitor,
            BenchmarkRunOptions options) {
        monitor.setPhase(warmup ? "warmup_inference" : "inference", item.id);
        int sampleStart = monitor.snapshot().size();
        String resultBackendId = options.isDummy() ? "dummy" : model.backendId;
        try {
            GenerationParams generationParams = item.resolvedParams(model.defaultParams);
            GenerationResult generation = engine.generate(item, generationParams);
            monitor.setPhase(warmup ? "warmup_post_inference" : "post_inference", item.id);
            boolean passed =
                    warmup
                            || ("external_scorer".equals(item.judgeRule)
                                    ? generation.text != null && !generation.text.trim().isEmpty()
                                    : Judge.score(item, generation.text));
            String error = "";
            if (options.isRealSmoke()) {
                if (generation.text == null || generation.text.trim().isEmpty()) {
                    passed = false;
                    error = "real_model_smoke produced empty output";
                } else if (generation.promptTokens <= 0 || generation.estimatedOutputTokens <= 0) {
                    passed = false;
                    error =
                            "real_model_smoke token gate failed: prompt_tokens="
                                    + generation.promptTokens
                                    + ", generated_tokens="
                                    + generation.estimatedOutputTokens;
                }
            }
            double tps =
                    generation.decodeLatencyMs > 0
                            ? generation.estimatedOutputTokens * 1000.0 / generation.decodeLatencyMs
                            : generation.totalLatencyMs <= 0
                                    ? 0.0
                                    : generation.estimatedOutputTokens * 1000.0 / generation.totalLatencyMs;
            return new BenchmarkItemResult(
                    item,
                    resultBackendId,
                    model.modelId,
                    repeatIndex,
                    warmup,
                    generation.text,
                    passed,
                    error,
                    generation.firstTokenLatencyMs,
                    generation.promptEvalLatencyMs,
                    generation.decodeLatencyMs,
                    generation.totalLatencyMs,
                    generation.promptTokens,
                    generation.estimatedOutputTokens,
                    tps,
                    generation.finishReason,
                    generationParams,
                    generation.diagnostics,
                    samplesSince(monitor, sampleStart));
        } catch (Exception itemError) {
            monitor.setPhase(warmup ? "warmup_inference_error" : "inference_error", item.id);
            return new BenchmarkItemResult(
                    item,
                    resultBackendId,
                    model.modelId,
                    repeatIndex,
                    warmup,
                    "",
                    false,
                    itemError.getClass().getSimpleName() + ": " + itemError.getMessage(),
                    -1L,
                    -1L,
                    -1L,
                    -1L,
                    0,
                    0,
                    0.0,
                    "error",
                    item.resolvedParams(model.defaultParams),
                    engine.diagnostics(),
                    samplesSince(monitor, sampleStart));
        }
    }

    private static List<HardwareSample> samplesSince(HardwareMonitor monitor, int start) {
        List<HardwareSample> all = monitor.snapshot();
        if (start < 0 || start >= all.size()) {
            return all;
        }
        return new ArrayList<>(all.subList(start, all.size()));
    }
}
