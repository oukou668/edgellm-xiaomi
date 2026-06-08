package com.xiaomi.llmbenchmark;

import android.content.Context;
import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONObject;

final class LlamaCppInferenceEngine implements InferenceEngine {
    private static final String LIB_NAME = "llmbenchmark-llama";
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
        String prompt = renderPrompt(model, item, params);
        String rawJson;
        int contextWindow = params.contextWindowSize > 0 ? params.contextWindowSize : model.contextWindow;
        String kvCacheType = contextWindow > 32768 ? "q4_0" : "f16";
        synchronized (lock) {
            rawJson =
                    nativeGenerate(
                            prompt,
                            contextWindow,
                            kvCacheType,
                            params.maxTokens,
                            params.temperature,
                            params.topP,
                            params.topK,
                            params.seed);
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
                diagnostics);
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

    private static String renderPrompt(ModelConfig model, BenchmarkItem item, GenerationParams params) {
        String prompt = item.displayPrompt();
        if ("minicpm".equals(model.promptTemplate)) {
            String thinkingSwitch = params.thinkingEnabled ? "\n/think" : "\n/no_think";
            return "<|im_start|>user\n"
                    + prompt
                    + thinkingSwitch
                    + "<|im_end|>\n<|im_start|>assistant\n";
        }
        if ("gemma3".equals(model.promptTemplate)) {
            return "<start_of_turn>user\n" + prompt + "<end_of_turn>\n<start_of_turn>model\n";
        }
        if ("qwen3".equals(model.promptTemplate)) {
            String thinkingSwitch = params.thinkingEnabled ? "\n/think" : "\n/no_think";
            return "<|im_start|>user\n" + prompt + thinkingSwitch + "<|im_end|>\n<|im_start|>assistant\n";
        }
        if ("qwen3.5".equals(model.promptTemplate)) {
            return "<|im_start|>user\n" + prompt + "<|im_end|>\n<|im_start|>assistant\n";
        }
        if ("lfm2.5".equals(model.promptTemplate)) {
            return "<|start_header_id|>user<|end_header_id|>\n\n"
                    + prompt
                    + "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n";
        }
        return prompt;
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
            long seed);

    private static native String nativeSystemInfo();

    private static native String nativeLastError();

    private static native void nativeUnload();
}
