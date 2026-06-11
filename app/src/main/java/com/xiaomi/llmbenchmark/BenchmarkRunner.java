package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

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
                        + options.repeatCount
                        + ", batch_size="
                        + options.batchSize
                        + ", unload_after_run="
                        + options.unloadAfterRun);

        LiveStatus.get()
                .startJob(
                        options.backendId,
                        model.modelId,
                        model.displayName,
                        benchmark.benchmarkId,
                        benchmark.displayName,
                        options.batchSize,
                        benchmark.items.size(),
                        options.repeatCount);

        List<JSONObject> batchMetrics = new ArrayList<>();
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
            if (options.isBatched() && engine instanceof MlcInferenceEngine) {
                ((MlcInferenceEngine) engine).setServingMode(true);
                progress.onProgress("MLC serving mode enabled for batched run.");
            }
        }
        long loadStartNs = System.nanoTime();
        monitor.setPhase("model_load", "");
        LiveStatus.get().setPhase("model_load");
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
            LiveStatus.get().setPhase("model_load_failed");
            LiveStatus.get().finishJob();
            for (BenchmarkItem item : benchmark.items) {
                results.add(
                        failedResult(
                                model, item, 0, false, model.backendId, message, new ArrayList<>(), engine.diagnostics()));
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
                    sourceIdentity,
                    batchMetrics);
        }

        try {
            int batchIndex = 0;
            for (int warmup = 0; warmup < options.warmupCount; warmup++) {
                if (options.isBatched()) {
                    for (int start = 0; start < benchmark.items.size(); start += options.batchSize) {
                        List<BenchmarkItem> chunk = chunkOf(benchmark.items, start, options.batchSize);
                        progress.onProgress(
                                "Warmup " + (warmup + 1) + "/" + options.warmupCount + " batch@" + start);
                        warmupResults.addAll(
                                runChunk(engine, model, chunk, warmup, true, monitor, options, batchIndex++).results);
                    }
                } else {
                    for (int i = 0; i < benchmark.items.size(); i++) {
                        BenchmarkItem item = benchmark.items.get(i);
                        progress.onProgress(
                                "Warmup " + (warmup + 1) + "/" + options.warmupCount + " " + (i + 1) + "/"
                                        + benchmark.items.size() + ": " + item.id);
                        warmupResults.add(runItem(engine, model, item, warmup, true, monitor, options));
                    }
                }
            }
            batchIndex = 0;
            for (int repeat = 0; repeat < options.repeatCount; repeat++) {
                if (options.isBatched()) {
                    for (int start = 0; start < benchmark.items.size(); start += options.batchSize) {
                        List<BenchmarkItem> chunk = chunkOf(benchmark.items, start, options.batchSize);
                        if (!chunk.isEmpty()) {
                            BenchmarkItem head = chunk.get(0);
                            LiveStatus.get()
                                    .startItem(
                                            start + 1, benchmark.items.size(), repeat + 1, head.id,
                                            head.displayPrompt(), head.expectedAnswer);
                        }
                        progress.onProgress(
                                "Repeat " + (repeat + 1) + "/" + options.repeatCount + " batch@" + start
                                        + " size=" + chunk.size());
                        ChunkOutcome outcome =
                                runChunk(engine, model, chunk, repeat, false, monitor, options, batchIndex++);
                        results.addAll(outcome.results);
                        if (outcome.metric != null) {
                            batchMetrics.add(outcome.metric);
                        }
                    }
                } else {
                    for (int i = 0; i < benchmark.items.size(); i++) {
                        BenchmarkItem item = benchmark.items.get(i);
                        LiveStatus.get()
                                .startItem(
                                        i + 1, benchmark.items.size(), repeat + 1, item.id,
                                        item.displayPrompt(), item.expectedAnswer);
                        progress.onProgress(
                                "Running repeat " + (repeat + 1) + "/" + options.repeatCount + " " + (i + 1) + "/"
                                        + benchmark.items.size() + ": " + item.id);
                        results.add(runItem(engine, model, item, repeat, false, monitor, options));
                    }
                }
            }
        } finally {
            if (options.unloadAfterRun) {
                monitor.setPhase("unload", "");
                engine.unload();
            } else {
                monitor.setPhase("model_retained", "");
                progress.onProgress("Model retained in process; unload_after_run=false.");
            }
            monitor.close();
            LiveStatus.get().finishJob();
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
                sourceIdentity,
                batchMetrics);
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
        String backendId = options.isDummy() ? "dummy" : model.backendId;
        GenerationParams generationParams = item.resolvedParams(model.defaultParams);
        try {
            GenerationResult generation = engine.generate(item, generationParams);
            monitor.setPhase(warmup ? "warmup_post_inference" : "post_inference", item.id);
            return buildResult(
                    model, item, generation, generationParams, repeatIndex, warmup, options, backendId,
                    samplesSince(monitor, sampleStart));
        } catch (Exception itemError) {
            monitor.setPhase(warmup ? "warmup_inference_error" : "inference_error", item.id);
            return failedResult(
                    model,
                    item,
                    repeatIndex,
                    warmup,
                    backendId,
                    itemError.getClass().getSimpleName() + ": " + itemError.getMessage(),
                    samplesSince(monitor, sampleStart),
                    engine.diagnostics());
        }
    }

    private ChunkOutcome runChunk(
            InferenceEngine engine,
            ModelConfig model,
            List<BenchmarkItem> chunk,
            int repeatIndex,
            boolean warmup,
            HardwareMonitor monitor,
            BenchmarkRunOptions options,
            int batchIndex) {
        String label = chunk.isEmpty() ? "batch" : chunk.get(0).id;
        monitor.setPhase(warmup ? "warmup_inference" : "inference", label);
        int sampleStart = monitor.snapshot().size();
        String backendId = options.isDummy() ? "dummy" : model.backendId;
        List<GenerationParams> params = new ArrayList<>();
        for (BenchmarkItem item : chunk) {
            params.add(item.resolvedParams(model.defaultParams));
        }
        List<BenchmarkItemResult> out = new ArrayList<>();
        try {
            BatchGenerationResult batch = engine.generateBatch(chunk, params);
            monitor.setPhase(warmup ? "warmup_post_inference" : "post_inference", label);
            List<HardwareSample> samples = samplesSince(monitor, sampleStart);
            for (int i = 0; i < chunk.size(); i++) {
                GenerationResult generation =
                        i < batch.perSequence.size() ? batch.perSequence.get(i) : null;
                if (generation == null) {
                    out.add(
                            failedResult(
                                    model, chunk.get(i), repeatIndex, warmup, backendId,
                                    "missing batch sequence", samples, engine.diagnostics()));
                } else {
                    out.add(
                            buildResult(
                                    model, chunk.get(i), generation, params.get(i), repeatIndex, warmup,
                                    options, backendId, samples));
                }
            }
            JSONObject metric = null;
            if (!warmup) {
                try {
                    metric = batch.toJson();
                    metric.put("batch_index", batchIndex);
                } catch (Exception ignored) {
                    metric = null;
                }
            }
            return new ChunkOutcome(out, metric);
        } catch (Exception batchError) {
            monitor.setPhase(warmup ? "warmup_inference_error" : "inference_error", label);
            List<HardwareSample> samples = samplesSince(monitor, sampleStart);
            String message = batchError.getClass().getSimpleName() + ": " + batchError.getMessage();
            for (BenchmarkItem item : chunk) {
                out.add(failedResult(model, item, repeatIndex, warmup, backendId, message, samples, engine.diagnostics()));
            }
            return new ChunkOutcome(out, null);
        }
    }

    private BenchmarkItemResult buildResult(
            ModelConfig model,
            BenchmarkItem item,
            GenerationResult generation,
            GenerationParams generationParams,
            int repeatIndex,
            boolean warmup,
            BenchmarkRunOptions options,
            String backendId,
            List<HardwareSample> samples) {
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
                backendId,
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
                samples,
                generation.decodeSpeedBuckets);
    }

    private BenchmarkItemResult failedResult(
            ModelConfig model,
            BenchmarkItem item,
            int repeatIndex,
            boolean warmup,
            String backendId,
            String message,
            List<HardwareSample> samples,
            RuntimeDiagnostics diagnostics) {
        return new BenchmarkItemResult(
                item,
                backendId,
                model.modelId,
                repeatIndex,
                warmup,
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
                diagnostics,
                samples);
    }

    private static List<BenchmarkItem> chunkOf(List<BenchmarkItem> items, int start, int batchSize) {
        int end = Math.min(start + batchSize, items.size());
        return new ArrayList<>(items.subList(start, end));
    }

    private static List<HardwareSample> samplesSince(HardwareMonitor monitor, int start) {
        List<HardwareSample> all = monitor.snapshot();
        if (start < 0 || start >= all.size()) {
            return all;
        }
        return new ArrayList<>(all.subList(start, all.size()));
    }

    private static final class ChunkOutcome {
        final List<BenchmarkItemResult> results;
        final JSONObject metric;

        ChunkOutcome(List<BenchmarkItemResult> results, JSONObject metric) {
            this.results = results;
            this.metric = metric;
        }
    }
}
