package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

final class LlamaCppInferenceEngine implements InferenceEngine {
    private static final String LIB_NAME = "llmbenchmark-llama";
    // Per-sample inference timeout: 120 minutes. The native decode loop stops at this deadline and
    // reports finish_reason="timeout" (it does NOT throw, so the decode-speed profile is preserved).
    private static final long PER_SAMPLE_TIMEOUT_MS = 120L * 60L * 1000L;
    private static boolean libraryLoaded;

    private final Context context;
    private final Object lock = new Object();
    private ModelConfig model;
    private RuntimeDiagnostics diagnostics = RuntimeDiagnostics.unknown();
    private boolean nativeReady;

    LlamaCppInferenceEngine(Context context) {
        this.context = context.getApplicationContext();
        loadLibraryOnce();
        nativeInit(this.context.getApplicationInfo().nativeLibraryDir);
        nativeReady = true;
    }

    @Override
    public void load(ModelConfig model, File modelDir) throws Exception {
        if (!model.isLlamaCpp()) {
            throw new IllegalArgumentException("Not a llama.cpp model: " + model.modelId);
        }
        ModelPreflight.verify(model, modelDir);
        File gguf = new File(modelDir, model.artifactFilename);
        int threads = Math.max(2, Math.min(4, Runtime.getRuntime().availableProcessors() - 2));
        Map<String, String> details = new LinkedHashMap<>();
        details.put("model_path", gguf.getAbsolutePath());
        details.put("model_id", model.modelId);
        details.put("hf_repo", model.hfRepo);
        details.put("hf_revision", model.hfRevision);
        details.put("artifact_sha256", model.artifactSha256);
        details.put("artifact_size_bytes", String.valueOf(model.artifactSizeBytes));
        details.put("actual_size_bytes", String.valueOf(gguf.length()));
        details.put("threads", String.valueOf(threads));
        details.put("max_context_window", String.valueOf(model.contextWindow));
        details.put("default_temperature", String.valueOf(model.defaultParams.temperature));
        details.put("default_top_p", String.valueOf(model.defaultParams.topP));
        details.put("default_thinking_enabled", String.valueOf(model.defaultParams.thinkingEnabled));
        details.put("chat_template", "official_gguf_template");
        diagnostics =
                new RuntimeDiagnostics(
                        model.backendId,
                        "llama.cpp",
                        "",
                        NativeLibraryInfo.path(context, System.mapLibraryName(LIB_NAME)),
                        NativeLibraryInfo.sha256(context, System.mapLibraryName(LIB_NAME)),
                        BuildConfig.LLAMA_CPP_GIT_COMMIT,
                        details);
        synchronized (lock) {
            nativeUnload();
            int result =
                    nativeLoad(
                            gguf.getAbsolutePath(),
                            threads,
                            model.defaultParams.temperature,
                            model.defaultParams.topP,
                            model.defaultParams.topK,
                            model.defaultParams.seed);
            if (result != 0) {
                details.put("native_load_result", String.valueOf(result));
                details.put("native_last_error", nativeLastError());
                throw new IllegalStateException(
                        "llama.cpp native load failed: " + result + " " + nativeLastError());
            }
            this.model = model;
            details.put("system_info", nativeSystemInfo());
            diagnostics =
                    new RuntimeDiagnostics(
                            model.backendId,
                            "llama.cpp",
                            "",
                            NativeLibraryInfo.path(context, System.mapLibraryName(LIB_NAME)),
                            NativeLibraryInfo.sha256(context, System.mapLibraryName(LIB_NAME)),
                            BuildConfig.LLAMA_CPP_GIT_COMMIT,
                            details);
        }
    }

    @Override
    public GenerationResult generate(BenchmarkItem item, GenerationParams params) throws Exception {
        if (model == null) {
            throw new IllegalStateException("llama.cpp engine is not loaded.");
        }
        int contextWindow = params.contextWindowSize > 0 ? params.contextWindowSize : model.contextWindow;
        String kvCacheType = contextWindow > 32768 ? "q4_0" : "f16";
        String rawJson;
        synchronized (lock) {
            rawJson =
                    nativeGenerate(
                            item.displayPrompt(),
                            contextWindow,
                            kvCacheType,
                            params.maxTokens,
                            params.temperature,
                            params.topP,
                            params.topK,
                            params.seed,
                            params.thinkingEnabled,
                            PER_SAMPLE_TIMEOUT_MS,
                            item.id);
        }
        JSONObject json = new JSONObject(rawJson);
        return new GenerationResult(
                json.optString("text", ""),
                json.optLong("first_token_latency_ms", -1L),
                json.optLong("prompt_eval_latency_ms", -1L),
                json.optLong("decode_latency_ms", -1L),
                json.optLong("total_latency_ms", -1L),
                json.optInt("prompt_tokens", 0),
                json.optInt("generated_tokens", 0),
                json.optString("finish_reason", "unknown"),
                diagnostics,
                DecodeSpeedBucket.listFromJson(json.optJSONArray("decode_speed_buckets")));
    }

    @Override
    public BatchGenerationResult generateBatch(List<BenchmarkItem> items, List<GenerationParams> params)
            throws Exception {
        if (model == null) {
            throw new IllegalStateException("llama.cpp engine is not loaded.");
        }
        // Hyperparameters are held constant across a batch (only batch size varies), so the first
        // sequence's context/kv/sampling drive the native call.
        GenerationParams head = params.get(0);
        int contextWindow = head.contextWindowSize > 0 ? head.contextWindowSize : model.contextWindow;
        String kvCacheType = contextWindow > 32768 ? "q4_0" : "f16";
        String[] prompts = new String[items.size()];
        String[] itemIds = new String[items.size()];
        for (int i = 0; i < items.size(); i++) {
            prompts[i] = items.get(i).displayPrompt();
            itemIds[i] = items.get(i).id;
        }
        String rawJson;
        synchronized (lock) {
            rawJson =
                    nativeGenerateBatch(
                            prompts,
                            contextWindow,
                            kvCacheType,
                            head.maxTokens,
                            head.temperature,
                            head.topP,
                            head.topK,
                            head.seed,
                            head.thinkingEnabled,
                            PER_SAMPLE_TIMEOUT_MS,
                            itemIds);
        }
        JSONObject json = new JSONObject(rawJson);
        long decodeWall = json.optLong("aggregate_decode_latency_ms", -1L);
        long prefillWall = json.optLong("aggregate_prefill_latency_ms", -1L);
        int totalGenerated = json.optInt("total_generated_tokens", 0);
        double aggregateTps = json.optDouble("aggregate_tokens_per_second", 0.0);
        JSONArray sequences = json.optJSONArray("sequences");
        List<GenerationResult> results = new ArrayList<>();
        int count = sequences == null ? 0 : sequences.length();
        for (int i = 0; i < count; i++) {
            JSONObject seq = sequences.optJSONObject(i);
            results.add(
                    new GenerationResult(
                            seq.optString("text", ""),
                            seq.optLong("first_token_latency_ms", -1L),
                            -1L,
                            seq.optLong("decode_latency_ms", decodeWall),
                            -1L,
                            seq.optInt("prompt_tokens", 0),
                            seq.optInt("generated_tokens", 0),
                            seq.optString("finish_reason", "unknown"),
                            diagnostics,
                            DecodeSpeedBucket.listFromJson(seq.optJSONArray("decode_speed_buckets"))));
        }
        if (results.isEmpty()) {
            throw new IllegalStateException(
                    "llama.cpp batch failed: " + json.optString("error", "no sequences returned"));
        }
        return new BatchGenerationResult(
                results, decodeWall, prefillWall, totalGenerated, items.size(), aggregateTps, diagnostics);
    }

    @Override
    public RuntimeDiagnostics diagnostics() {
        return diagnostics;
    }

    @Override
    public void unload() {
        synchronized (lock) {
            if (nativeReady) {
                nativeUnload();
            }
            model = null;
        }
    }

    private static synchronized void loadLibraryOnce() {
        if (!libraryLoaded) {
            System.loadLibrary(LIB_NAME);
            libraryLoaded = true;
        }
    }

    private static native void nativeInit(String nativeLibDir);

    private static native int nativeLoad(
            String modelPath,
            int threads,
            double temperature,
            double topP,
            int topK,
            long seed);

    private static native String nativeGenerate(
            String prompt,
            int contextWindow,
            String kvCacheType,
            int maxTokens,
            double temperature,
            double topP,
            int topK,
            long seed,
            boolean thinking,
            long timeoutMs,
            String itemId);

    private static native String nativeGenerateBatch(
            String[] prompts,
            int perSeqContext,
            String kvCacheType,
            int maxTokens,
            double temperature,
            double topP,
            int topK,
            long seed,
            boolean thinking,
            long timeoutMs,
            String[] itemIds);

    private static native String nativeSystemInfo();

    private static native String nativeLastError();

    private static native void nativeUnload();
}
